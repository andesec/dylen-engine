"""Router for resource-related endpoints (OCR, etc.)."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.ai.router import ProviderMode, get_model_for_mode

router = APIRouter()
logger = logging.getLogger(__name__)
FILES_PARAM = File(...)
MESSAGE_PARAM = Form(None)


class ExtractionResult(BaseModel):
  filename: str
  content: str


class BatchResponse(BaseModel):
  results: list[ExtractionResult]


@router.post("/image/extract-text", response_model=BatchResponse)
async def extract_text_from_images(files: list[UploadFile] = FILES_PARAM, message: str | None = MESSAGE_PARAM):
  """
  Endpoint to upload multiple photos and extract formatted text
  using Gemini 2.0 Flash Lite.
  """
  # Guard against empty uploads early.
  if not files:
    raise HTTPException(status_code=400, detail="No files provided")

  # Guard against oversized batch sizes to protect compute.
  if len(files) > 5:
    raise HTTPException(status_code=400, detail="Maximum 5 files allowed.")

  # Validate file sizes for each upload.
  max_size = 1 * 1024 * 1024  # 1MB
  # Note: UploadFile size might not be available directly without reading or checking headers.
  # We will check content length if available, or during read.

  # Initialize the model using the abstraction.
  # Hardcoded to Gemini as requested
  try:
    model = get_model_for_mode(ProviderMode.GEMINI, model="gemini-2.0-flash-lite")
  except Exception as e:
    logger.error(f"Failed to initialize model: {e}")
    raise HTTPException(status_code=500, detail="Configuration error: Model unavailable.") from e

  # Check for file support capability if possible, or just try.
  if hasattr(model, "supports_files") and not model.supports_files:
    raise HTTPException(status_code=500, detail="Provider does not support file uploads.")

  # Load defaults prompt content from disk.
  prompt_path = Path(__file__).resolve().parents[2] / "ai" / "prompts" / "ocr.md"
  try:
    prompt_text = prompt_path.read_text()
  except Exception as e:
    logger.error(f"Failed to load OCR prompt: {e}")
    prompt_text = "Extract text from these images."  # Fallback

  # Append user instructions when provided.
  if message:
    prompt_text = f"{prompt_text}\n\nUser Instructions:\n{message}"

  # Process files
  # We can process them in a batch if the model supports multiple files in one request,
  # OR process them individually. The user request sample code processed them individually
  # but mentioned "begins processing them TOGETHER in one call" in the text description?
  # "DGS immediately uploads them to files api, and then begins processing them TOGETHER in one call."
  # AND "The files are uploaded to the DGS and DGS immediately uploads them to files api, and then begins processing them TOGETHER in one call."
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
  # Decision: I will stick to the sample code's logic (multiple requests) because it maps cleaner to `BatchResponse(results=[...])`.
  # If I did one call, I'd have to parse "Image 1 text... Image 2 text..." which is error prone.

  async def process_file(file: UploadFile) -> ExtractionResult:
    # Upload and process a single file to keep results aligned to filenames.
    uploaded_ref = None
    try:
      # Load file content for size check and upload.
      content = await file.read()
      # Enforce the maximum file size per upload.
      if len(content) > max_size:
        return ExtractionResult(filename=file.filename or "", content="Error: File exceeds 1MB limit.")

      # Upload content to the provider.
      uploaded_ref = await model.upload_file(file_content=content, mime_type=file.content_type or "application/octet-stream", display_name=file.filename)

      # Generate output from the uploaded file.
      # We use a fresh model call for each file to ensure clear separation of results.
      response = await model.generate_with_files(prompt_text, [uploaded_ref])

      return ExtractionResult(filename=file.filename or "", content=response.content or "No text detected.")

    except Exception as e:
      logger.exception(f"Error processing file {file.filename}: {e}")
      return ExtractionResult(filename=file.filename or "", content=f"Error: {str(e)}")

  # Run processing tasks in parallel for faster responses.
  tasks = [process_file(file) for file in files]
  results = await asyncio.gather(*tasks)

  return BatchResponse(results=list(results))
