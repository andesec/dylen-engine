"""Service layer for OCR extraction with model orchestration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from app.ai.providers.base import AIModel
from app.ai.router import ProviderMode, get_model_for_mode
from app.config import Settings
from app.core.database import get_session_factory
from app.schema.ocr import ExtractionResult
from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import QuotaExceededError, commit_quota_reservation, release_quota_reservation, reserve_quota
from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)
# Store the OCR file size limit in one place for clarity.
_ONE_MEGABYTE = 1024 * 1024
_DEFAULT_PROVIDER_MODE = ProviderMode.GEMINI
_DEFAULT_MODEL_NAME = "gemini-2.0-flash-lite"
UserId = uuid.UUID | None
SettingsValue = Settings | None
QuotaLimit = int | None


class OcrService:
  """Coordinate OCR extraction to keep routes thin and consistent."""

  def __init__(self, provider_mode: ProviderMode = _DEFAULT_PROVIDER_MODE, model_name: str = _DEFAULT_MODEL_NAME, max_file_size: int = _ONE_MEGABYTE, *, user_id: UserId = None, settings: SettingsValue = None, quota_limit: QuotaLimit = None) -> None:
    """Store OCR configuration to keep extraction behavior consistent."""
    # Store provider details so callers do not need to handle model setup.
    self._provider_mode = provider_mode
    # Store model name so extraction stays deterministic.
    self._model_name = model_name
    # Store size limits to prevent oversized uploads.
    self._max_file_size = max_file_size
    # Store the user id so quota reservations are scoped correctly.
    self._user_id = user_id
    # Store settings so runtime configuration can be enforced.
    self._settings = settings
    # Store the resolved quota limit for the request context.
    self._quota_limit = quota_limit

  @property
  def model_name(self) -> str:
    """Expose the configured model name for audit logging."""
    # Return the model name so callers can log it consistently.
    return self._model_name

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
    reservation_active = False
    reservation_limit = int(self._quota_limit or 0)
    reservation_job_id = str(uuid.uuid4())
    # Ensure quota reservations have the required context.
    if self._user_id is None:
      raise RuntimeError("OCR missing user_id for quota reservation.")
    if self._settings is None:
      raise RuntimeError("OCR missing settings for quota reservation.")
    # Require a database session factory for quota reservation and logging.
    session_factory = get_session_factory()
    if session_factory is None:
      raise RuntimeError("Database session factory unavailable for quota reservation.")
    if reservation_limit <= 0:
      raise QuotaExceededError("ocr.extract quota disabled")
    try:
      # Reserve monthly OCR quota before processing uploads.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        reserve_metadata = {"request_id": reservation_job_id, "file_count": len(files)}
        await reserve_quota(session, user_id=self._user_id, metric_key="ocr.extract", period=QuotaPeriod.MONTH, quantity=len(files), limit=reservation_limit, job_id=reservation_job_id, metadata=reserve_metadata)
      reservation_active = True
      # Build the prompt once so the batch stays consistent.
      prompt_text = self._load_prompt(message)
      # Initialize the model once to reuse connections.
      model = self._create_model()
      # Kick off file processing tasks to reduce wall time.
      tasks = [self._process_file(model, prompt_text, file) for file in files]
      # Await completion to return ordered results.
      results = await asyncio.gather(*tasks)
      # Commit the reservation once OCR completes successfully.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        commit_metadata = {"request_id": reservation_job_id, "file_count": len(files)}
        await commit_quota_reservation(session, user_id=self._user_id, metric_key="ocr.extract", period=QuotaPeriod.MONTH, quantity=len(files), limit=reservation_limit, job_id=reservation_job_id, metadata=commit_metadata)
      return list(results)
    except Exception:  # noqa: BLE001
      # Release quota reservation when OCR extraction fails.
      logger.error("OCR extraction failed during execution.", exc_info=True)
      if reservation_active:
        try:
          async with session_factory() as session:
            # Build quota metadata for audit logging.
            release_metadata = {"request_id": reservation_job_id, "file_count": len(files), "reason": "ocr_failed"}
            await release_quota_reservation(session, user_id=self._user_id, metric_key="ocr.extract", period=QuotaPeriod.MONTH, quantity=len(files), limit=reservation_limit, job_id=reservation_job_id, metadata=release_metadata)
        except Exception:  # noqa: BLE001
          logger.error("OCR failed to release quota reservation.", exc_info=True)
      raise
