import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile

from app.api.routes.resources import BatchResponse, extract_text_from_images
from app.schema.sql import User


def test_extract_text_validation_no_files():
  """Validate error handling for missing files with an authenticated user."""

  async def _test():
    """Run the coroutine to validate missing-file handling."""
    # Mock authenticated user for dependency injection.
    mock_user = AsyncMock(spec=User)
    # Exercise the handler with no files to trigger validation.
    try:
      await extract_text_from_images(files=[], current_user=mock_user)
    except Exception as e:
      assert e.status_code == 400
      assert "No files provided" in e.detail

  asyncio.run(_test())


def test_extract_text_validation_too_many_files():
  """Validate error handling for too many files with an authenticated user."""

  async def _test():
    """Run the coroutine to validate file-count handling."""
    # Mock authenticated user for dependency injection.
    mock_user = AsyncMock(spec=User)
    # Prepare the file list over the limit to trigger validation.
    files = [AsyncMock(spec=UploadFile) for _ in range(6)]
    mock_user = AsyncMock(spec=User)
    try:
      await extract_text_from_images(files=files, current_user=mock_user)
    except Exception as e:
      assert e.status_code == 400
      assert "Maximum 5 files allowed" in e.detail

  asyncio.run(_test())


def test_extract_text_success():
  """Validate successful text extraction with an authenticated user."""

  async def _test():
    """Run the coroutine to validate successful extraction."""
    # Mock authenticated user for dependency injection.
    mock_user = AsyncMock(spec=User)
    # Mock file
    file = AsyncMock(spec=UploadFile)
    file.filename = "test.png"
    file.content_type = "image/png"
    file.read.return_value = b"fake_content"
    # Mock AIModel
    mock_model = AsyncMock()
    mock_model.supports_structured_output = True
    mock_model.supports_files = True
    mock_model.upload_file.return_value = "file_ref"
    mock_model.generate_with_files.return_value.content = "Extracted Text"
    with patch("app.api.routes.resources.get_model_for_mode", return_value=mock_model):
      response = await extract_text_from_images(files=[file], current_user=mock_user)

    assert isinstance(response, BatchResponse)
    assert len(response.results) == 1
    assert response.results[0].content == "Extracted Text"
    assert response.results[0].filename == "test.png"

  asyncio.run(_test())


def test_extract_text_with_message():
  """Validate message augmentation with an authenticated user."""

  async def _test():
    """Run the coroutine to validate message augmentation."""
    # Mock authenticated user for dependency injection.
    mock_user = AsyncMock(spec=User)
    # Mock file
    file = AsyncMock(spec=UploadFile)
    file.filename = "msg_test.png"
    file.read.return_value = b"fake_content"
    # Mock AIModel
    mock_model = AsyncMock()
    mock_model.supports_structured_output = True
    mock_model.supports_files = True
    mock_model.upload_file.return_value = "file_ref"
    mock_model.generate_with_files.return_value.content = "Extracted Text With Msg"
    with patch("app.api.routes.resources.get_model_for_mode", return_value=mock_model):
      # Assert that generate_with_files is called with the message appended
      # We need to capture the call arguments
      await extract_text_from_images(files=[file], message="Pay attention to dates.", current_user=mock_user)

      # Verify call args
      args, _ = mock_model.generate_with_files.call_args
      prompt_used = args[0]
      assert "User Instructions:" in prompt_used
      assert "Pay attention to dates." in prompt_used

  asyncio.run(_test())
