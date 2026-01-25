"""Router for resource-related endpoints (OCR, etc.)."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.schema.ocr import BatchResponse
from app.services.ocr_service import OcrService

router = APIRouter()

# Define file and form defaults once to avoid inline function calls.
FILES_FIELD = File(...)
MESSAGE_FIELD = Form(None)
# Define service dependency once to satisfy linting guidance.
OCR_SERVICE_DEPENDENCY = Depends(OcrService)


@router.post("/image/extract-text", response_model=BatchResponse)
async def extract_text_from_images(files: list[UploadFile] = FILES_FIELD, message: str | None = MESSAGE_FIELD, service: OcrService = OCR_SERVICE_DEPENDENCY) -> BatchResponse:
  """Validate OCR uploads and delegate extraction to the service layer."""
  # Guard against empty uploads to return a clear client error.
  if not files:
    raise HTTPException(status_code=400, detail="No files provided")

  # Enforce batch size limits for consistent latency.
  if len(files) > 5:
    raise HTTPException(status_code=400, detail="Maximum 5 files allowed.")

  # Delegate extraction so orchestration stays outside the transport layer.
  results = await service.extract_text(files=files, message=message)
  return BatchResponse(results=results)
