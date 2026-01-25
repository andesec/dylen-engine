"""Router for resource-related endpoints (OCR, etc.)."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.ai.router import ProviderMode, get_model_for_mode
from app.core.security import get_current_active_user
from app.schema.sql import User
from app.services.audit import log_llm_interaction

router = APIRouter()
logger = logging.getLogger(__name__)


class ExtractionResult(BaseModel):
  filename: str
  content: str


class BatchResponse(BaseModel):
  results: list[ExtractionResult]


@router.post("/image/extract-text", response_model=BatchResponse)
async def extract_text_from_images(files: list[UploadFile] = File(...), message: str | None = Form(None), current_user: User = Depends(get_current_active_user)):  # noqa: B008
  """
  Endpoint to upload multiple photos and extract formatted text
  using Gemini 2.0 Flash Lite.
  """
  if not files:
    raise HTTPException(status_code=400, detail="No files provided")

  if len(files) > 5:
    raise HTTPException(status_code=400, detail="Maximum 5 files allowed.")

  # Validate file sizes
  max_size = 1 * 1024 * 1024  # 1MB
  # Note: UploadFile size might not be available directly without reading or checking headers.
  # We will check content length if available, or during read.

  # Initialize the model using the abstraction
  # Hardcoded to Gemini as requested
  try:
    model = get_model_for_mode(ProviderMode.GEMINI, model="gemini-2.0-flash-lite")
  except Exception as e:
    logger.error(f"Failed to initialize model: {e}")
    raise HTTPException(status_code=500, detail="Configuration error: Model unavailable.") from e

  if not model.supports_structured_output:
    # Actually we don't strictly need structured output for Markdown text,
    # but supports_files is not on AIModel base yet if we didn't add the property to base...
    # Wait, I added `supports_files` property to base.
    pass

  # Check for file support capability if possible, or just try.
  if hasattr(model, "supports_files") and not model.supports_files:
    raise HTTPException(status_code=500, detail="Provider does not support file uploads.")

  # Load defaults prompt
  prompt_path = Path(__file__).resolve().parents[2] / "ai" / "prompts" / "ocr.md"
  try:
    with open(prompt_path) as f:
      prompt_text = f.read()
  except Exception as e:
    logger.error(f"Failed to load OCR prompt: {e}")
    prompt_text = "Extract text from these images."  # Fallback

  if message:
    prompt_text = f"{prompt_text}\n\nUser Instructions:\n{message}"

  results = []

  # Process files
  # We can process them in a batch if the model supports multiple files in one request,
  # OR process them individually. The user request sample code processed them individually
  # but mentioned "begins processing them TOGETHER in one call" in the text description?
  # "DGS immediately uploads them to files api, and then begins processing them
  # TOGETHER in one call."
  # AND "The files are uploaded to the DGS and DGS immediately uploads them to files api,
  # and then begins processing them TOGETHER in one call."
  # BUT the sample code had a loop: `upload_tasks` (parallel) then `response = client.models.generate_content...` inside a loop?
  # Wait, the sample code loop `for idx, g_file in enumerate(gemini_files):` implies individual processing per file.
  # However, "processing them TOGETHER" usually means one prompt with multiple images.
  #
  # Re-reading user request: "The flow will be that the API takes the files from the user along with an optional prompt.
  # The files are uploaded to the DGS and DGS immediately uploads them to files api, and then begins processing them TOGETHER in one call."
  # AND "BatchResponse" suggests a batch of results.
  # If we process TOGETHER, we get ONE response text for ALL images (e.g. "Here is text for image 1... Here is text for image 2...").
  # If the user wants `BatchResponse` with `results: List[ExtractionResult]`, individual processing is safer for structured separation,
  # UNLESS we ask the model to output a structured JSON list of results.
  #
  # Given the sample code had a loop and produced a list of results, I will follow that pattern for now as it's more robust for "ExtractionResult" mapping.
  # BUT "processing them TOGETHER in one call" is quite specific.
  # The user might mean "Parallel uploads, then... processing?"
  # Actually, looking at the user's provided code:
  # `results = [] ... for idx, g_file in enumerate(gemini_files): ... generate_content ... results.append`
  # The USER's sample code does individual generation. The TEXT says "processing them TOGETHER".
  #
  # Conflict: Text vs Code.
  # Decision: I will stick to the sample code's logic (multiple requests) because it maps cleaner to `BatchResponse(results=[...])` without complex parsing of a single merged string.
  # If I did one call, I'd have to parse "Image 1 text... Image 2 text..." which is error prone.

  async def process_file(file: UploadFile, idx: int) -> ExtractionResult:
    """Process a single upload to ensure per-file OCR isolation."""
    uploaded_ref = None
    try:
      content = await file.read()
      if len(content) > max_size:
        return ExtractionResult(filename=file.filename or "", content="Error: File exceeds 1MB limit.")

      # Upload
      uploaded_ref = await model.upload_file(file_content=content, mime_type=file.content_type or "application/octet-stream", display_name=file.filename)

      # Generate
      # We use a fresh model call for each file to ensure clear separation of results
      response = await model.generate_with_files(prompt_text, [uploaded_ref])

      return ExtractionResult(filename=file.filename or "", content=response.content or "No text detected.")

    except Exception as e:
      logger.exception(f"Error processing file {file.filename}: {e}")
      return ExtractionResult(filename=file.filename or "", content=f"Error: {str(e)}")

  # Record an audit entry so OCR usage is tracked in the database.
  audit_status = "success"
  audit_summary = f"OCR extract text request; file_count={len(files)}; has_message={bool(message)}"
  try:
    # Run in parallel
    tasks = [process_file(file, i) for i, file in enumerate(files)]
    results = await asyncio.gather(*tasks)

  except Exception:
    audit_status = "error"
    raise

  finally:
    await log_llm_interaction(user_id=current_user.id, model_name=model.name, prompt_summary=audit_summary, status=audit_status)

  return BatchResponse(results=list(results))
