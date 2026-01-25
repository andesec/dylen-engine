import asyncio
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile

from app.api.routes.resources import BatchResponse, extract_text_from_images


def test_extract_text_validation_no_files():
  async def _test():
    try:
      # Attempt extraction with no files to hit the validation guard.
      await extract_text_from_images(files=[])
    except Exception as e:
      # Validate the error response is a 400 with the expected message.
      assert e.status_code == 400
      assert "No files provided" in e.detail

  asyncio.run(_test())


def test_extract_text_validation_too_many_files():
  async def _test():
    # Build a mock batch that exceeds the allowed file count.
    files = [AsyncMock(spec=UploadFile) for _ in range(6)]
    try:
      # Attempt extraction with too many files to hit the validation guard.
      await extract_text_from_images(files=files)
    except Exception as e:
      # Validate the error response is a 400 with the expected message.
      assert e.status_code == 400
      assert "Maximum 5 files allowed" in e.detail

  asyncio.run(_test())


def test_extract_text_success():
  async def _test():
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
      # Execute the handler to verify expected response shape.
      response = await extract_text_from_images(files=[file])

    assert isinstance(response, BatchResponse)
    assert len(response.results) == 1
    assert response.results[0].content == "Extracted Text"
    assert response.results[0].filename == "test.png"

  asyncio.run(_test())


def test_extract_text_with_message():
  async def _test():
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
      # Assert that generate_with_files is called with the message appended.
      # We need to capture the call arguments.
      await extract_text_from_images(files=[file], message="Pay attention to dates.")

      # Verify call args
      args, _ = mock_model.generate_with_files.call_args
      prompt_used = args[0]
      assert "User Instructions:" in prompt_used
      assert "Pay attention to dates." in prompt_used

  asyncio.run(_test())
