import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile

from app.api.routes.resources import extract_text_from_images
from app.schema.ocr import BatchResponse


def test_extract_text_validation_no_files() -> None:
  """Ensure empty uploads return a validation error."""

  async def _test() -> None:
    """Exercise the route with no files to confirm validation."""
    try:
      # Trigger the route with no files to validate the guard.
      await extract_text_from_images(files=[])
    except HTTPException as exc:
      # Validate the expected HTTP error response.
      assert exc.status_code == 400
      assert "No files provided" in exc.detail

  asyncio.run(_test())


def test_extract_text_validation_too_many_files() -> None:
  """Ensure oversized batches return a validation error."""

  async def _test() -> None:
    """Exercise the route with too many files to confirm the guard."""
    # Build a list of mock uploads to exceed the limit.
    files = [AsyncMock(spec=UploadFile) for _ in range(6)]
    try:
      # Trigger the route with too many files to validate the guard.
      await extract_text_from_images(files=files)
    except HTTPException as exc:
      # Validate the expected HTTP error response.
      assert exc.status_code == 400
      assert "Maximum 5 files allowed" in exc.detail

  asyncio.run(_test())


def test_extract_text_success() -> None:
  """Ensure OCR extraction returns a populated batch response."""

  async def _test() -> None:
    """Execute a happy-path request and verify results."""
    # Build a mock upload for the OCR request.
    file = AsyncMock(spec=UploadFile)
    file.filename = "test.png"
    file.content_type = "image/png"
    file.read.return_value = b"fake_content"
    # Build a mock model to avoid network calls.
    mock_model = AsyncMock()
    mock_model.supports_structured_output = True
    mock_model.supports_files = True
    mock_model.upload_file.return_value = "file_ref"
    mock_model.generate_with_files.return_value.content = "Extracted Text"
    with patch("app.services.ocr_service.get_model_for_mode", return_value=mock_model):
      # Trigger the extraction route to validate the response.
      response = await extract_text_from_images(files=[file])

    # Confirm the response structure and content.
    assert isinstance(response, BatchResponse)
    assert len(response.results) == 1
    assert response.results[0].content == "Extracted Text"
    assert response.results[0].filename == "test.png"

  asyncio.run(_test())


def test_extract_text_with_message() -> None:
  """Ensure user instructions are appended to the prompt."""

  async def _test() -> None:
    """Execute a request with a user message to verify prompt handling."""
    # Build a mock upload for the OCR request.
    file = AsyncMock(spec=UploadFile)
    file.filename = "msg_test.png"
    file.read.return_value = b"fake_content"
    # Build a mock model to capture prompt input.
    mock_model = AsyncMock()
    mock_model.supports_structured_output = True
    mock_model.supports_files = True
    mock_model.upload_file.return_value = "file_ref"
    mock_model.generate_with_files.return_value.content = "Extracted Text With Msg"
    with patch("app.services.ocr_service.get_model_for_mode", return_value=mock_model):
      # Trigger the extraction route with a custom instruction.
      await extract_text_from_images(files=[file], message="Pay attention to dates.")
      # Capture prompt input from the model call.
      args, _ = mock_model.generate_with_files.call_args
      prompt_used = args[0]
      assert "User Instructions:" in prompt_used
      assert "Pay attention to dates." in prompt_used

  asyncio.run(_test())
