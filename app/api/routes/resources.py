"""Router for resource-related endpoints (OCR, etc.)."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.core.security import get_current_active_user, require_feature_flag
from app.schema.ocr import BatchResponse
from app.schema.sql import User
from app.services.audit import log_llm_interaction
from app.services.ocr_service import OcrService

router = APIRouter()

# Define file and form defaults once to avoid inline function calls.
FILES_FIELD = File(...)
MESSAGE_FIELD = Form(None)
# Define service dependency once to satisfy linting guidance.
OCR_SERVICE_DEPENDENCY = Depends(OcrService)


@router.post("/image/extract-text", response_model=BatchResponse, dependencies=[Depends(require_feature_flag("feature.ocr"))])
async def extract_text_from_images(files: list[UploadFile] = FILES_FIELD, message: str | None = MESSAGE_FIELD, current_user: User = Depends(get_current_active_user), service: OcrService = OCR_SERVICE_DEPENDENCY) -> BatchResponse:  # noqa: B008
  """Validate OCR uploads, delegate extraction, and log audit data."""
  # Guard against empty uploads to return a clear client error.
  if not files:
    raise HTTPException(status_code=400, detail="No files provided")

  # Enforce batch size limits for consistent latency.
  if len(files) > 5:
    raise HTTPException(status_code=400, detail="Maximum 5 files allowed.")

  # Prepare audit metadata before extraction begins.
  audit_status = "success"
  audit_summary = f"OCR extract text request; file_count={len(files)}; has_message={bool(message)}"
  try:
    # Delegate extraction so orchestration stays outside the transport layer.
    results = await service.extract_text(files=files, message=message)
  except Exception:
    # Mark audit status as error before re-raising.
    audit_status = "error"
    raise
  finally:
    # Persist the OCR audit event regardless of outcome.
    await log_llm_interaction(user_id=current_user.id, model_name=service.model_name, prompt_summary=audit_summary, status=audit_status)

  # Return the batch response to the client in a consistent structure.
  return BatchResponse(results=results)
