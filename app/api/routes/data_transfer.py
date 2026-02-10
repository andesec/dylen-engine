"""Admin APIs for secure export/hydrate runs backed by background jobs."""

from __future__ import annotations

import datetime
import time
import uuid
from typing import Any

import msgspec
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.msgspec_utils import decode_msgspec_request, encode_msgspec_response
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_admin_user, require_role_level
from app.jobs.models import JobRecord
from app.schema.data_transfer import DataTransferRun
from app.schema.sql import RoleLevel, User
from app.services.export_storage_client import build_export_storage_client
from app.services.jobs import trigger_job_processing
from app.storage.postgres_jobs_repo import PostgresJobsRepository
from app.utils.ids import generate_job_id

router = APIRouter()


class ExportCreateRequest(msgspec.Struct):
  """Request payload for creating an export run."""

  include_illustrations: bool
  include_audios: bool
  include_fensters: bool
  separate_zips: bool
  password: str
  idempotency_key: str


class HydrateCreateRequest(msgspec.Struct):
  """Request payload for creating a hydrate run."""

  export_run_id: str
  include_illustrations: bool
  include_audios: bool
  include_fensters: bool
  separate_zips: bool
  password: str
  dry_run: bool
  idempotency_key: str


class DownloadLinksRequest(msgspec.Struct):
  """Request payload for signed download links."""

  ttl_seconds: int


class RunResponse(msgspec.Struct):
  """Response payload for one transfer run."""

  run_id: str
  job_id: str
  run_type: str
  status: str
  source_export_run_id: str | None
  include_illustrations: bool
  include_audios: bool
  include_fensters: bool
  separate_zips: bool
  dry_run: bool
  artifacts: dict[str, Any] | None
  result: dict[str, Any] | None
  error_message: str | None
  created_at: str
  started_at: str | None
  completed_at: str | None


class CreateRunResponse(msgspec.Struct):
  """Response payload for create-run endpoints."""

  run_id: str
  job_id: str
  status: str


class DownloadLinkItem(msgspec.Struct):
  """Descriptor for one signed artifact URL."""

  artifact_kind: str
  object_name: str
  expires_at: str
  signed_url: str


class DownloadLinksResponse(msgspec.Struct):
  """Response payload for signed download links."""

  run_id: str
  items: list[DownloadLinkItem]


def _password_ok(value: str) -> bool:
  """Validate minimum password complexity for export/hydrate requests."""
  if len(value) < 10:
    return False
  has_upper = any(ch.isupper() for ch in value)
  has_lower = any(ch.islower() for ch in value)
  has_digit = any(ch.isdigit() for ch in value)
  has_symbol = any(not ch.isalnum() for ch in value)
  return has_upper and has_lower and has_digit and has_symbol


def _serialize_run(run: DataTransferRun) -> RunResponse:
  """Convert run row to stable API payload."""
  return RunResponse(
    run_id=str(run.id),
    job_id=run.job_id,
    run_type=run.run_type,
    status=run.status,
    source_export_run_id=str(run.source_export_run_id) if run.source_export_run_id else None,
    include_illustrations=bool(run.include_illustrations),
    include_audios=bool(run.include_audios),
    include_fensters=bool(run.include_fensters),
    separate_zips=bool(run.separate_zips),
    dry_run=bool(run.dry_run),
    artifacts=run.artifacts_json,
    result=run.result_json,
    error_message=run.error_message,
    created_at=run.created_at.isoformat(),
    started_at=run.started_at.isoformat() if run.started_at else None,
    completed_at=run.completed_at.isoformat() if run.completed_at else None,
  )


async def _get_run_or_404(*, db_session: AsyncSession, run_id: str, expected_type: str) -> DataTransferRun:
  """Load a transfer run and validate run_type."""
  try:
    parsed_run_id = uuid.UUID(run_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid run id.") from exc
  stmt = select(DataTransferRun).where(DataTransferRun.id == parsed_run_id)
  run = (await db_session.execute(stmt)).scalar_one_or_none()
  if run is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
  if run.run_type != expected_type:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run type mismatch.")
  return run


async def _queue_maintenance_job(*, job_id: str, current_user: User, payload: dict[str, Any], settings: Settings, background_tasks: BackgroundTasks) -> str:
  """Create and enqueue a maintenance job for transfer execution."""
  timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
  record = JobRecord(
    job_id=job_id,
    user_id=str(current_user.id),
    job_kind="maintenance",
    request=payload,
    status="queued",
    target_agent="maintenance",
    phase="queued",
    created_at=timestamp,
    updated_at=timestamp,
    expected_sections=0,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=0,
    logs=["Data transfer job queued by admin."],
    progress=0.0,
    ttl=int(time.time()) + 7200,
    idempotency_key=f"data-transfer:{job_id}",
  )
  repo = PostgresJobsRepository()
  await repo.create_job(record)
  trigger_job_processing(background_tasks, job_id, settings)
  return job_id


@router.post("/data-transfer/exports", dependencies=[Depends(require_role_level(RoleLevel.GLOBAL))])
async def create_export_run(request: Request, background_tasks: BackgroundTasks, db_session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings), current_user: User = Depends(get_current_admin_user)):  # noqa: B008
  """Queue one export run and return run/job identifiers."""
  payload = await decode_msgspec_request(request, ExportCreateRequest)
  if not _password_ok(payload.password):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password does not meet complexity rules.")
  existing_stmt = select(DataTransferRun).where(DataTransferRun.run_type == "export", DataTransferRun.requested_by == current_user.id, DataTransferRun.idempotency_key == payload.idempotency_key)
  existing_run = (await db_session.execute(existing_stmt)).scalar_one_or_none()
  if existing_run is not None:
    return encode_msgspec_response(CreateRunResponse(run_id=str(existing_run.id), job_id=existing_run.job_id, status=existing_run.status))
  gcs_bucket = settings.export_bucket
  if not gcs_bucket:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Export bucket is not configured.")
  run_id = uuid.uuid4()
  job_id = generate_job_id()
  run = DataTransferRun(
    id=run_id,
    job_id=job_id,
    run_type="export",
    status="queued",
    requested_by=current_user.id,
    source_export_run_id=None,
    include_illustrations=bool(payload.include_illustrations),
    include_audios=bool(payload.include_audios),
    include_fensters=bool(payload.include_fensters),
    separate_zips=bool(payload.separate_zips),
    dry_run=False,
    password_plaintext=payload.password,
    gcs_bucket=gcs_bucket,
    artifacts_json=None,
    filters_json={"include_illustrations": bool(payload.include_illustrations), "include_audios": bool(payload.include_audios), "include_fensters": bool(payload.include_fensters), "separate_zips": bool(payload.separate_zips)},
    result_json=None,
    error_message=None,
    idempotency_key=payload.idempotency_key,
  )
  db_session.add(run)
  await db_session.commit()
  try:
    await _queue_maintenance_job(job_id=job_id, current_user=current_user, payload={"action": "data_export", "run_id": str(run_id)}, settings=settings, background_tasks=background_tasks)
  except Exception as exc:  # noqa: BLE001
    run.status = "error"
    run.error_message = f"Failed to queue job: {exc}"
    db_session.add(run)
    await db_session.commit()
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to queue export job.") from exc
  return encode_msgspec_response(CreateRunResponse(run_id=str(run.id), job_id=job_id, status=run.status), status_code=status.HTTP_201_CREATED)


@router.get("/data-transfer/exports/{run_id}", dependencies=[Depends(require_role_level(RoleLevel.GLOBAL))])
async def get_export_run(run_id: str = Path(...), db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)):  # noqa: B008
  """Return one export run status and metadata."""
  _ = current_user
  run = await _get_run_or_404(db_session=db_session, run_id=run_id, expected_type="export")
  return encode_msgspec_response(_serialize_run(run))


@router.post("/data-transfer/exports/{run_id}/download-links", dependencies=[Depends(require_role_level(RoleLevel.GLOBAL))])
async def get_export_download_links(run_id: str, request: Request, db_session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings), current_user: User = Depends(get_current_admin_user)):  # noqa: B008
  """Return signed artifact download URLs for a completed export run."""
  _ = current_user
  payload = await decode_msgspec_request(request, DownloadLinksRequest)
  run = await _get_run_or_404(db_session=db_session, run_id=run_id, expected_type="export")
  if run.status != "done":
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Export run is not complete.")
  entries = list((run.artifacts_json or {}).get("entries", []))
  if not entries:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No artifacts found for run.")
  max_ttl = int(settings.export_signed_url_ttl_seconds)
  ttl_seconds = max(60, min(int(payload.ttl_seconds), max_ttl))
  client = build_export_storage_client(settings)
  expires_at = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=ttl_seconds)).isoformat()
  items: list[DownloadLinkItem] = []
  for entry in entries:
    object_name = str(entry.get("object_name") or "")
    if object_name == "":
      continue
    try:
      signed_url = await client.generate_signed_url(object_name=object_name, ttl_seconds=ttl_seconds)
    except RuntimeError as exc:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    items.append(DownloadLinkItem(artifact_kind=str(entry.get("kind") or "unknown"), object_name=object_name, expires_at=expires_at, signed_url=signed_url))
  return encode_msgspec_response(DownloadLinksResponse(run_id=str(run.id), items=items))


@router.post("/data-transfer/hydrates", dependencies=[Depends(require_role_level(RoleLevel.GLOBAL))])
async def create_hydrate_run(request: Request, background_tasks: BackgroundTasks, db_session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings), current_user: User = Depends(get_current_admin_user)):  # noqa: B008
  """Queue one hydrate run from a source export run id."""
  payload = await decode_msgspec_request(request, HydrateCreateRequest)
  if not _password_ok(payload.password):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password does not meet complexity rules.")
  try:
    export_run_uuid = uuid.UUID(payload.export_run_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid export_run_id.") from exc
  source_stmt = select(DataTransferRun).where(DataTransferRun.id == export_run_uuid)
  source_export_run = (await db_session.execute(source_stmt)).scalar_one_or_none()
  if source_export_run is None or source_export_run.run_type != "export":
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source export run not found.")
  if source_export_run.status != "done":
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Source export run is not complete.")
  if source_export_run.password_plaintext != payload.password:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password mismatch.")
  # Enforce the same field filters so hydrate mirrors the exported data shape.
  if (
    bool(source_export_run.include_illustrations) != bool(payload.include_illustrations)
    or bool(source_export_run.include_audios) != bool(payload.include_audios)
    or bool(source_export_run.include_fensters) != bool(payload.include_fensters)
    or bool(source_export_run.separate_zips) != bool(payload.separate_zips)
  ):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Hydrate filters must match the source export run filters.")
  existing_stmt = select(DataTransferRun).where(DataTransferRun.run_type == "hydrate", DataTransferRun.requested_by == current_user.id, DataTransferRun.idempotency_key == payload.idempotency_key)
  existing_run = (await db_session.execute(existing_stmt)).scalar_one_or_none()
  if existing_run is not None:
    return encode_msgspec_response(CreateRunResponse(run_id=str(existing_run.id), job_id=existing_run.job_id, status=existing_run.status))
  gcs_bucket = settings.export_bucket
  if not gcs_bucket:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Export bucket is not configured.")
  run_id = uuid.uuid4()
  job_id = generate_job_id()
  run = DataTransferRun(
    id=run_id,
    job_id=job_id,
    run_type="hydrate",
    status="queued",
    requested_by=current_user.id,
    source_export_run_id=source_export_run.id,
    include_illustrations=bool(payload.include_illustrations),
    include_audios=bool(payload.include_audios),
    include_fensters=bool(payload.include_fensters),
    separate_zips=bool(payload.separate_zips),
    dry_run=bool(payload.dry_run),
    password_plaintext=payload.password,
    gcs_bucket=gcs_bucket,
    artifacts_json=None,
    filters_json={
      "include_illustrations": bool(payload.include_illustrations),
      "include_audios": bool(payload.include_audios),
      "include_fensters": bool(payload.include_fensters),
      "separate_zips": bool(payload.separate_zips),
      "dry_run": bool(payload.dry_run),
    },
    result_json=None,
    error_message=None,
    idempotency_key=payload.idempotency_key,
  )
  db_session.add(run)
  await db_session.commit()
  try:
    await _queue_maintenance_job(job_id=job_id, current_user=current_user, payload={"action": "data_hydrate", "run_id": str(run_id), "export_run_id": str(source_export_run.id)}, settings=settings, background_tasks=background_tasks)
  except Exception as exc:  # noqa: BLE001
    run.status = "error"
    run.error_message = f"Failed to queue job: {exc}"
    db_session.add(run)
    await db_session.commit()
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to queue hydrate job.") from exc
  return encode_msgspec_response(CreateRunResponse(run_id=str(run.id), job_id=job_id, status=run.status), status_code=status.HTTP_201_CREATED)


@router.get("/data-transfer/hydrates/{run_id}", dependencies=[Depends(require_role_level(RoleLevel.GLOBAL))])
async def get_hydrate_run(run_id: str = Path(...), db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)):  # noqa: B008
  """Return one hydrate run status and metadata."""
  _ = current_user
  run = await _get_run_or_404(db_session=db_session, run_id=run_id, expected_type="hydrate")
  return encode_msgspec_response(_serialize_run(run))
