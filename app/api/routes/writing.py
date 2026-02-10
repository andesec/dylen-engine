import time
from collections.abc import Mapping

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps_concurrency import verify_concurrency
from app.api.models import JobCreateResponse, WritingCheckRequest
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user, require_feature_flag
from app.jobs.models import JobRecord
from app.schema.quotas import QuotaPeriod
from app.schema.sql import User
from app.services.audit import log_llm_interaction
from app.services.quota_buckets import get_quota_snapshot
from app.services.request_validation import _validate_writing_request
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.tasks.factory import get_task_enqueuer
from app.services.users import get_user_subscription_tier
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id

router = APIRouter()

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _writing_request_metrics(request: WritingCheckRequest) -> Mapping[str, int]:
  """Compute non-sensitive metrics for writing checks.

  How/Why:
    - Writing text can contain sensitive user content.
    - We avoid storing any user-provided text in audit logs by logging only coarse metrics.
    - A richer writing-quality metric may be added later; this keeps the data model forward-compatible.
  """
  # Log only aggregated metrics so audit trails remain privacy-safe.
  text = request.text or ""
  text_chars = len(text)
  text_words = len([part for part in text.split() if part.strip()])
  metrics = {"text_chars": int(text_chars), "text_words": int(text_words)}
  if request.widget_id is not None:
    metrics["widget_id"] = int(request.widget_id)
  return metrics


def _compute_job_ttl(settings: Settings) -> int | None:
  if settings.jobs_ttl_seconds is None:
    return None
  return int(time.time()) + settings.jobs_ttl_seconds


@router.post("/check", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_feature_flag("feature.writing")), Depends(verify_concurrency("writing"))])
async def create_writing_check(  # noqa: B008
  request: WritingCheckRequest,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
) -> JobCreateResponse:
  """Create a background job to check a writing task response."""

  if current_user.id:
    metrics = _writing_request_metrics(request)
    widget_info = f"widget={metrics.get('widget_id')}" if "widget_id" in metrics else "legacy"
    prompt_summary = f"Writing check queued; chars={metrics['text_chars']} words={metrics['text_words']} {widget_info}"
    await log_llm_interaction(user_id=current_user.id, model_name="writing-check", prompt_summary=prompt_summary, status="queued", session=db_session)

  tier_id, _tier_name = await get_user_subscription_tier(db_session, current_user.id)
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=None)
  writing_checks_per_month = int(runtime_config.get("limits.writing_checks_per_month") or 0)
  # Deny-by-default: missing/invalid config means the capability is treated as unavailable.
  if writing_checks_per_month <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "writing.check"})

  snapshot = await get_quota_snapshot(db_session, user_id=current_user.id, metric_key="writing.check", period=QuotaPeriod.MONTH, limit=writing_checks_per_month)
  if snapshot.remaining <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "writing.check"})

  _validate_writing_request(request)
  if not request.idempotency_key:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="idempotency_key is required.")
  repo = _get_jobs_repo(settings)

  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())

  record = JobRecord(
    job_id=job_id,
    user_id=str(current_user.id),
    job_kind="writing",
    request=request.model_dump(mode="python"),
    status="queued",
    target_agent="writing",
    phase="queued",
    expected_sections=0,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=0,
    retry_sections=None,
    retry_agents=None,
    created_at=timestamp,
    updated_at=timestamp,
    ttl=_compute_job_ttl(settings),
    idempotency_key=request.idempotency_key,
  )
  try:
    await repo.create_job(record)
  except Exception as exc:  # noqa: BLE001
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create writing check job.") from exc

  enqueuer = get_task_enqueuer(settings)
  try:
    await enqueuer.enqueue(job_id, {})
  except Exception as exc:  # noqa: BLE001
    try:
      await repo.update_job(job_id, status="error", phase="error", logs=["Enqueue failed: TASK_ENQUEUE_FAILED"], completed_at=time.strftime(_DATE_FORMAT, time.gmtime()))
    except Exception:  # noqa: BLE001
      pass
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to enqueue writing check job.") from exc

  response = JobCreateResponse(job_id=job_id, expected_sections=0)

  return response
