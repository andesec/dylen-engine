"""Service helpers for running export/hydrate bundles and packaging encrypted zip artifacts."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyzipper
from app.config import Settings
from app.schema.data_transfer import DataTransferRun
from app.services.export_storage_client import build_export_storage_client
from scripts.export_success_graph_sql import _normalize_async_dsn as _normalize_export_dsn
from scripts.export_success_graph_sql import _run_export
from scripts.hydrate_success_graph_sql import _normalize_async_dsn as _normalize_hydrate_dsn
from scripts.hydrate_success_graph_sql import _run_hydrate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ArtifactEntry:
  """Descriptor for one uploaded artifact object."""

  kind: str
  object_name: str
  sha256: str
  size_bytes: int


def _sha256_bytes(payload: bytes) -> str:
  """Return sha256 for byte payloads."""
  hasher = hashlib.sha256()
  hasher.update(payload)
  return hasher.hexdigest()


def _derive_zip_password(*, export_run_id: str, password_plaintext: str) -> str:
  """Build the two-factor password string required for zip encryption."""
  return f"{export_run_id}:{password_plaintext}"


def _zip_encrypted(*, output_path: Path, input_root: Path, relative_paths: list[Path], password: str) -> None:
  """Create an AES-encrypted zip with explicit file list rooted at input_root."""
  with pyzipper.AESZipFile(output_path, mode="w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as archive:
    archive.setpassword(password.encode("utf-8"))
    for rel_path in relative_paths:
      source_path = input_root / rel_path
      if source_path.is_dir():
        continue
      archive.write(source_path, arcname=str(rel_path))


def _extract_encrypted_zip(*, zip_path: Path, output_dir: Path, password: str) -> None:
  """Extract an AES-encrypted zip into output_dir."""
  with pyzipper.AESZipFile(zip_path, mode="r") as archive:
    archive.setpassword(password.encode("utf-8"))
    for member in archive.infolist():
      member_name = member.filename
      if member_name.startswith("/") or ".." in Path(member_name).parts:
        raise RuntimeError(f"Unsafe path in zip member: {member_name}")
      target_path = (output_dir / member_name).resolve()
      if output_dir.resolve() not in target_path.parents and target_path != output_dir.resolve():
        raise RuntimeError(f"Unsafe extraction target for zip member: {member_name}")
      if member.is_dir():
        target_path.mkdir(parents=True, exist_ok=True)
        continue
      target_path.parent.mkdir(parents=True, exist_ok=True)
      with archive.open(member, "r") as source, target_path.open("wb") as destination:
        shutil.copyfileobj(source, destination)


def _collect_relative_files(root: Path) -> list[Path]:
  """Collect file-only relative paths under root in stable order."""
  files: list[Path] = []
  for path in sorted(root.rglob("*")):
    if path.is_file():
      files.append(path.relative_to(root))
  return files


def _object_prefix(*, settings: Settings, run_type: str, run_id: str) -> str:
  """Build deterministic object prefix for transfer artifacts."""
  base_prefix = (settings.export_object_prefix or "data-transfer").strip("/") or "data-transfer"
  return f"{base_prefix}/{run_type}/{run_id}"


async def execute_export_run(*, session: AsyncSession, settings: Settings, run: DataTransferRun) -> dict[str, Any]:
  """Execute one export run and upload encrypted zip artifacts."""
  if not settings.pg_dsn:
    raise RuntimeError("DYLEN_PG_DSN must be configured for export runs.")

  storage_client = build_export_storage_client(settings)
  await storage_client.ensure_bucket()
  run.status = "running"
  run.started_at = datetime.now(UTC)
  session.add(run)
  await session.commit()

  derived_password = _derive_zip_password(export_run_id=str(run.id), password_plaintext=run.password_plaintext)

  with tempfile.TemporaryDirectory(prefix=f"transfer-export-{run.id}-") as tmp_dir_raw:
    tmp_dir = Path(tmp_dir_raw)
    sql_path = tmp_dir / "bundle.sql"
    sidecar_dir = tmp_dir / "sidecar"
    normalized_dsn = _normalize_export_dsn(settings.pg_dsn)
    await _run_export(dsn=normalized_dsn, out_sql=sql_path, sidecar_dir=sidecar_dir, strict=True, max_rows=None, include_illustrations=bool(run.include_illustrations), include_audios=bool(run.include_audios), include_fensters=bool(run.include_fensters))

    artifact_entries: list[ArtifactEntry] = []
    prefix = _object_prefix(settings=settings, run_type="exports", run_id=str(run.id))
    zip_candidates: list[tuple[str, Path]] = []

    if run.separate_zips:
      core_root = tmp_dir / "core"
      core_root.mkdir(parents=True, exist_ok=True)
      shutil.copy2(sql_path, core_root / "bundle.sql")
      manifest_path = sidecar_dir / "manifest.json"
      if manifest_path.exists():
        shutil.copy2(manifest_path, core_root / "manifest.json")
      core_zip_path = tmp_dir / "core.zip"
      _zip_encrypted(output_path=core_zip_path, input_root=core_root, relative_paths=_collect_relative_files(core_root), password=derived_password)
      zip_candidates.append(("core", core_zip_path))

      if run.include_illustrations and (sidecar_dir / "illustrations").exists():
        illustrations_zip_path = tmp_dir / "illustrations.zip"
        illustration_paths = [path.relative_to(sidecar_dir) for path in sorted((sidecar_dir / "illustrations").rglob("*")) if path.is_file()]
        _zip_encrypted(output_path=illustrations_zip_path, input_root=sidecar_dir, relative_paths=illustration_paths, password=derived_password)
        zip_candidates.append(("illustrations", illustrations_zip_path))
      tutor_sidecar_dir = sidecar_dir / "tutors"
      if run.include_audios and tutor_sidecar_dir.exists():
        audios_zip_path = tmp_dir / "audios.zip"
        audio_paths = [path.relative_to(sidecar_dir) for path in sorted(tutor_sidecar_dir.rglob("*")) if path.is_file()]
        _zip_encrypted(output_path=audios_zip_path, input_root=sidecar_dir, relative_paths=audio_paths, password=derived_password)
        zip_candidates.append(("audios", audios_zip_path))
      if run.include_fensters and (sidecar_dir / "fenster_widgets").exists():
        fensters_zip_path = tmp_dir / "fensters.zip"
        fenster_paths = [path.relative_to(sidecar_dir) for path in sorted((sidecar_dir / "fenster_widgets").rglob("*")) if path.is_file()]
        _zip_encrypted(output_path=fensters_zip_path, input_root=sidecar_dir, relative_paths=fenster_paths, password=derived_password)
        zip_candidates.append(("fensters", fensters_zip_path))
    else:
      bundle_root = tmp_dir / "bundle"
      bundle_root.mkdir(parents=True, exist_ok=True)
      shutil.copy2(sql_path, bundle_root / "bundle.sql")
      if (sidecar_dir / "manifest.json").exists():
        shutil.copy2(sidecar_dir / "manifest.json", bundle_root / "manifest.json")
      # Copy only requested sidecars to the encrypted bundle.
      if run.include_illustrations and (sidecar_dir / "illustrations").exists():
        shutil.copytree(sidecar_dir / "illustrations", bundle_root / "illustrations", dirs_exist_ok=True)
      tutor_sidecar_dir = sidecar_dir / "tutors"
      if run.include_audios and tutor_sidecar_dir.exists():
        shutil.copytree(tutor_sidecar_dir, bundle_root / "tutors", dirs_exist_ok=True)
      if run.include_fensters and (sidecar_dir / "fenster_widgets").exists():
        shutil.copytree(sidecar_dir / "fenster_widgets", bundle_root / "fenster_widgets", dirs_exist_ok=True)
      bundle_zip_path = tmp_dir / "bundle.zip"
      _zip_encrypted(output_path=bundle_zip_path, input_root=bundle_root, relative_paths=_collect_relative_files(bundle_root), password=derived_password)
      zip_candidates.append(("bundle", bundle_zip_path))

    for kind, zip_path in zip_candidates:
      payload = zip_path.read_bytes()
      size_bytes = len(payload)
      if settings.export_max_zip_bytes is not None and size_bytes > settings.export_max_zip_bytes:
        raise RuntimeError(f"Artifact zip `{kind}` exceeds configured max bytes.")
      object_name = f"{prefix}/{zip_path.name}"
      await storage_client.upload_bytes(object_name=object_name, payload=payload, content_type="application/zip")
      artifact_entries.append(ArtifactEntry(kind=kind, object_name=object_name, sha256=_sha256_bytes(payload), size_bytes=size_bytes))

    artifacts_json = {"entries": [{"kind": entry.kind, "object_name": entry.object_name, "sha256": entry.sha256, "size_bytes": entry.size_bytes} for entry in artifact_entries]}
    return {"artifacts_json": artifacts_json, "artifact_count": len(artifact_entries)}


async def execute_hydrate_run(*, session: AsyncSession, settings: Settings, run: DataTransferRun) -> dict[str, Any]:
  """Execute one hydrate run from a source export run and encrypted zip artifacts."""
  if not settings.pg_dsn:
    raise RuntimeError("DYLEN_PG_DSN must be configured for hydrate runs.")
  if run.source_export_run_id is None:
    raise RuntimeError("Hydrate run is missing source export run id.")

  source_stmt = select(DataTransferRun).where(DataTransferRun.id == run.source_export_run_id)
  source_export_run = (await session.execute(source_stmt)).scalar_one_or_none()
  if source_export_run is None:
    raise RuntimeError("Source export run was not found.")
  if source_export_run.run_type != "export":
    raise RuntimeError("Source run must be an export run.")
  if source_export_run.status != "done":
    raise RuntimeError("Source export run is not complete.")
  if source_export_run.password_plaintext != run.password_plaintext:
    raise RuntimeError("Provided password does not match source export run password.")
  if (
    bool(source_export_run.include_illustrations) != bool(run.include_illustrations)
    or bool(source_export_run.include_audios) != bool(run.include_audios)
    or bool(source_export_run.include_fensters) != bool(run.include_fensters)
    or bool(source_export_run.separate_zips) != bool(run.separate_zips)
  ):
    raise RuntimeError("Hydrate run filters do not match source export run filters.")

  source_entries = list((source_export_run.artifacts_json or {}).get("entries", []))
  if not source_entries:
    raise RuntimeError("Source export run has no artifacts to hydrate.")

  storage_client = build_export_storage_client(settings)
  run.status = "running"
  run.started_at = datetime.now(UTC)
  session.add(run)
  await session.commit()

  derived_password = _derive_zip_password(export_run_id=str(source_export_run.id), password_plaintext=source_export_run.password_plaintext)

  with tempfile.TemporaryDirectory(prefix=f"transfer-hydrate-{run.id}-") as tmp_dir_raw:
    tmp_dir = Path(tmp_dir_raw)
    downloaded_dir = tmp_dir / "downloaded"
    extracted_dir = tmp_dir / "extracted"
    downloaded_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir.mkdir(parents=True, exist_ok=True)

    for entry in source_entries:
      object_name = str(entry.get("object_name") or "")
      if not object_name:
        continue
      payload, _metadata = await storage_client.download_bytes(object_name=object_name)
      size_bytes = len(payload)
      expected_size = entry.get("size_bytes")
      if expected_size is not None and int(expected_size) != size_bytes:
        raise RuntimeError(f"Artifact size mismatch for object {object_name}.")
      if settings.export_max_zip_bytes is not None and size_bytes > settings.export_max_zip_bytes:
        raise RuntimeError(f"Artifact zip `{object_name}` exceeds configured max bytes.")
      target_zip_path = downloaded_dir / Path(object_name).name
      target_zip_path.write_bytes(payload)
      if entry.get("sha256") and _sha256_bytes(payload) != str(entry.get("sha256")):
        raise RuntimeError(f"Artifact checksum mismatch for object {object_name}.")
      _extract_encrypted_zip(zip_path=target_zip_path, output_dir=extracted_dir, password=derived_password)

    sql_path_candidates = list(extracted_dir.rglob("bundle.sql"))
    if not sql_path_candidates:
      raise RuntimeError("Hydrate extraction failed: bundle.sql not found.")
    sql_path = sql_path_candidates[0]
    sidecar_dir = extracted_dir
    normalized_dsn = _normalize_hydrate_dsn(settings.pg_dsn)
    await _run_hydrate(
      dsn=normalized_dsn,
      in_sql=sql_path,
      sidecar_dir=sidecar_dir,
      strict=True,
      dry_run=bool(run.dry_run),
      advisory_lock_key=819224151,
      verify_rerun=True,
      include_illustrations=bool(run.include_illustrations),
      include_audios=bool(run.include_audios),
      include_fensters=bool(run.include_fensters),
    )

  return {"hydrated_from_export_run_id": str(source_export_run.id), "dry_run": bool(run.dry_run)}
