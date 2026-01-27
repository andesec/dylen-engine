import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile

from app.api.routes.resources import extract_text_from_images
from app.schema.ocr import BatchResponse, ExtractionResult
from app.schema.sql import User
from app.services.ocr_service import OcrService


def test_extract_text_validation_no_files() -> None:
  """Ensure empty uploads return a validation error."""

  async def _test() -> None:
    """Exercise the route with no files to confirm validation."""
    # Mock authenticated user for dependency injection.
    mock_user = AsyncMock(spec=User)
    # Mock the service so the dependency can be injected.
    mock_service = AsyncMock(spec=OcrService)
    try:
      # Trigger the route with no files to validate the guard.
      await extract_text_from_images(files=[], current_user=mock_user, service=mock_service)
    except HTTPException as exc:
      # Validate the expected HTTP error response.
      assert exc.status_code == 400
      assert "No files provided" in exc.detail
    else:
      # Fail the test if validation does not raise.
      raise AssertionError("Expected HTTPException(400) but none was raised")

  # Run the async test body.
  asyncio.run(_test())


def test_extract_text_validation_too_many_files() -> None:
  """Ensure oversized batches return a validation error."""

  async def _test() -> None:
    """Exercise the route with too many files to confirm the guard."""
    # Mock authenticated user for dependency injection.
    mock_user = AsyncMock(spec=User)
    # Mock the service so the dependency can be injected.
    mock_service = AsyncMock(spec=OcrService)
    # Build a list of mock uploads to exceed the limit.
    files = [AsyncMock(spec=UploadFile) for _ in range(6)]
    try:
      # Trigger the route with too many files to validate the guard.
      await extract_text_from_images(files=files, current_user=mock_user, service=mock_service)
    except HTTPException as exc:
      # Validate the expected HTTP error response.
      assert exc.status_code == 400
      assert "Maximum 5 files allowed" in exc.detail
    else:
      # Fail the test if validation does not raise.
      raise AssertionError("Expected HTTPException(400) but none was raised")

  # Run the async test body.
  asyncio.run(_test())


def test_extract_text_success() -> None:
  """Ensure OCR extraction returns a populated batch response."""

  async def _test() -> None:
    """Execute a happy-path request and verify results."""
    # Mock authenticated user for dependency injection.
    mock_user = AsyncMock(spec=User)
    # Mock the service to return a fixed result.
    mock_service = AsyncMock(spec=OcrService)
    # Provide a model name so audit logging can use it.
    mock_service.model_name = "gemini-2.0-flash-lite"
    # Stub the extraction result to avoid model calls.
    mock_service.extract_text = AsyncMock(return_value=[ExtractionResult(filename="test.png", content="Extracted Text")])
    # Mock the audit logger to avoid database writes.
    mock_audit = AsyncMock()
    with patch("app.api.routes.resources.log_llm_interaction", mock_audit):
      # Trigger the extraction route to validate the response.
      response = await extract_text_from_images(files=[AsyncMock(spec=UploadFile)], current_user=mock_user, service=mock_service)

    # Confirm the response structure and content.
    assert isinstance(response, BatchResponse)
    assert len(response.results) == 1
    assert response.results[0].content == "Extracted Text"
    assert response.results[0].filename == "test.png"

  # Run the async test body.
  asyncio.run(_test())


def test_extract_text_with_message() -> None:
  """Ensure user instructions are passed to the service."""

  async def _test() -> None:
    """Execute a request with a user message to verify prompt handling."""
    # Mock authenticated user for dependency injection.
    mock_user = AsyncMock(spec=User)
    # Mock the service to return a fixed result.
    mock_service = AsyncMock(spec=OcrService)
    # Provide a model name so audit logging can use it.
    mock_service.model_name = "gemini-2.0-flash-lite"
    # Stub the extraction result to avoid model calls.
    mock_service.extract_text = AsyncMock(return_value=[ExtractionResult(filename="msg_test.png", content="Extracted Text With Msg")])
    # Mock the audit logger to avoid database writes.
    mock_audit = AsyncMock()
    with patch("app.api.routes.resources.log_llm_interaction", mock_audit):
      # Trigger the extraction route with a custom instruction.
      await extract_text_from_images(files=[AsyncMock(spec=UploadFile)], message="Pay attention to dates.", current_user=mock_user, service=mock_service)

    # Confirm the service receives the user message.
    mock_service.extract_text.assert_awaited_once()
    # Capture the call arguments to confirm message forwarding.
    _args, kwargs = mock_service.extract_text.call_args
    assert kwargs["message"] == "Pay attention to dates."

  # Run the async test body.
  asyncio.run(_test())
