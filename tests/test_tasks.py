import os
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.config import get_settings
from app.main import app
from app.services.tasks.factory import get_task_enqueuer
from httpx import ASGITransport, AsyncClient


@pytest.mark.anyio
async def test_local_task_dispatch():
  """Verify that the local enqueuer posts to the correct endpoint."""

  settings = get_settings()
  # Force settings for test
  settings = replace(settings, base_url="http://localhost:8000", task_secret="test-task-secret")

  with patch("app.services.tasks.local.httpx.AsyncClient") as mock_client_cls:
    mock_client = AsyncMock()
    mock_client_cls.return_value.__aenter__.return_value = mock_client
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_client.post.return_value = mock_response

    enqueuer = get_task_enqueuer(settings)  # Should be local-http default

    job_id = "test-job-123"
    await enqueuer.enqueue(job_id, {})

    expected_url = f"{settings.base_url.rstrip('/')}/internal/tasks/process-job"
    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == expected_url
    assert kwargs["json"] == {"job_id": job_id}


@pytest.mark.anyio
async def test_task_handler_endpoint():
  """Verify the handler endpoint calls the job processor."""

  with patch.dict(os.environ, {"DYLEN_TASK_SECRET": "test-task-secret"}):
    get_settings.cache_clear()
    with patch("app.api.routes.tasks.process_job_sync", new_callable=AsyncMock) as mock_process:
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/internal/tasks/process-job", json={"job_id": "job-abc"}, headers={"authorization": "Bearer test-task-secret"})

      assert response.status_code == 200
      assert response.json() == {"status": "ok"}
      mock_process.assert_called_once()
      args, _ = mock_process.call_args
      assert args[0] == "job-abc"
    get_settings.cache_clear()
