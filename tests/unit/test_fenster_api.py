import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
from app.main import app
from app.core.security import get_current_identity
from app.core.database import get_db
from app.schema.fenster import FensterWidget, FensterWidgetType
from app.schema.sql import UserStatus
import uuid
import base64

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_db():
    return AsyncMock()

def test_fenster_unauthorized(client):
    # No auth header
    response = client.get("/api/v1/fenster/some-id")
    # 401 because HTTPBearer dependency fails (missing token)
    assert response.status_code == 401

def test_fenster_forbidden_free_tier(client, mock_db):
    user = MagicMock()
    user.status = UserStatus.APPROVED
    user.id = uuid.uuid4()
    claims = {"tier": "Free"}

    app.dependency_overrides[get_current_identity] = lambda: (user, claims)
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.get(f"/api/v1/fenster/{uuid.uuid4()}")
        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "UPGRADE_REQUIRED"
    finally:
        del app.dependency_overrides[get_current_identity]
        del app.dependency_overrides[get_db]

@pytest.mark.anyio
async def test_fenster_success_inline(client, mock_db):
    user = MagicMock()
    user.status = UserStatus.APPROVED
    user.id = uuid.uuid4()
    claims = {"tier": "Plus"}

    widget_id = uuid.uuid4()
    content_bytes = b"compressed_content"
    encoded_content = base64.b64encode(content_bytes).decode("utf-8")

    mock_widget = MagicMock()
    mock_widget.fenster_id = widget_id
    mock_widget.type = FensterWidgetType.INLINE_BLOB
    mock_widget.content = content_bytes
    mock_widget.url = None

    # Mock DB execution
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_widget
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_current_identity] = lambda: (user, claims)
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        response = client.get(f"/api/v1/fenster/{widget_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["fenster_id"] == str(widget_id)
        assert data["type"] == "inline_blob"
        assert data["content"] == encoded_content
    finally:
        del app.dependency_overrides[get_current_identity]
        del app.dependency_overrides[get_db]
