"""Service layer for OCR extraction with model orchestration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.ai.providers.base import AIModel
from app.ai.router import ProviderMode, get_model_for_mode
from app.schema.ocr import ExtractionResult

logger = logging.getLogger(__name__)
# Define a shared constant to clarify byte-size calculations.
_ONE_MEGABYTE = 1024 * 1024

# Store the OCR file size limit in one place for clarity.
_ONE_MEGABYTE = 1024 * 1024


class OcrService:
  """Coordinate OCR extraction to keep routes thin and consistent."""

  def __init__(self, provider_mode: ProviderMode = ProviderMode.GEMINI, model_name: str = "gemini-2.0-flash-lite", max_file_size: int = _ONE_MEGABYTE) -> None:
    """Store OCR configuration to keep extraction behavior consistent."""
    # Store provider details so callers do not need to handle model setup.
    self._provider_mode = provider_mode
    # Store model name so extraction stays deterministic.
    self._model_name = model_name
    # Store size limits to prevent oversized uploads.
    self._max_file_size = max_file_size

  def _create_model(self) -> AIModel:
    """Create the model client so file processing can stay isolated."""
    try:
      # Initialize the model client for the configured provider.
      model = get_model_for_mode(self._provider_mode, model=self._model_name)
    except Exception as exc:
      logger.error("Failed to initialize model: %s", exc)
      raise HTTPException(status_code=500, detail="Configuration error: Model unavailable.") from exc

    # Enforce file upload support for OCR workflows.
    if hasattr(model, "supports_files") and not model.supports_files:
      raise HTTPException(status_code=500, detail="Provider does not support file uploads.")

    return model

  def _load_prompt(self, message: str | None) -> str:
    """Load the OCR prompt so requests remain consistent across calls."""
    # Resolve the prompt location relative to the app package.
    prompt_path = Path(__file__).resolve().parents[1] / "ai" / "prompts" / "ocr.md"
    try:
      # Read prompt content from disk for consistent formatting.
      with open(prompt_path, encoding="utf-8") as handle:
        prompt_text = handle.read()
    except Exception as exc:
      logger.error("Failed to load OCR prompt: %s", exc)
      prompt_text = "Extract text from these images."

    # Append user instructions to keep prompts contextual.
    if message:
      prompt_text = f"{prompt_text}\n\nUser Instructions:\n{message}"

    return prompt_text

  async def _process_file(self, model: AIModel, prompt_text: str, file: UploadFile) -> ExtractionResult:
    """Process a single file so batch handling stays predictable."""
    try:
      # Read file content for upload and validation.
      content = await file.read()
      # Enforce size constraints early to protect the provider.
      if len(content) > self._max_file_size:
        return ExtractionResult(filename=file.filename or "", content=f"Error: File exceeds {self._max_file_size} byte limit.")

      # Upload the content for provider-side processing.
      uploaded_ref = await model.upload_file(file_content=content, mime_type=file.content_type or "application/octet-stream", display_name=file.filename)
      # Generate text using the uploaded file reference.
      response = await model.generate_with_files(prompt_text, [uploaded_ref])
      return ExtractionResult(filename=file.filename or "", content=response.content or "No text detected.")
    except Exception as exc:
      logger.exception("Error processing file %s", file.filename)
      return ExtractionResult(filename=file.filename or "", content=f"Error: {str(exc)}")

  async def extract_text(self, files: list[UploadFile], message: str | None) -> list[ExtractionResult]:
    """Extract text in parallel to keep latency low while preserving mapping."""
    # Build the prompt once so the batch stays consistent.
    prompt_text = self._load_prompt(message)
    # Initialize the model once to reuse connections.
    model = self._create_model()
    # Kick off file processing tasks to reduce wall time.
    tasks = [self._process_file(model, prompt_text, file) for file in files]
    # Await completion to return ordered results.
    results = await asyncio.gather(*tasks)
    return list(results)
