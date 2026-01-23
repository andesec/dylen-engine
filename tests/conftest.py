"""Test configuration for importing the application package."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "dgs-backend"
if str(APP_DIR) not in sys.path:
  sys.path.insert(0, str(APP_DIR))

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def mock_db_session():
  session = AsyncMock()
  # Mock execute result
  result = MagicMock()
  result.scalar_one_or_none.return_value = None
  result.scalar_one.return_value = None
  session.execute.return_value = result
  return session


@pytest.fixture
def override_get_db(mock_db_session):
  async def _get_db():
    yield mock_db_session

  return _get_db


@pytest.fixture
async def async_client(override_get_db):
  app.dependency_overrides[get_db] = override_get_db
  async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
    yield client
  app.dependency_overrides.clear()


@pytest.fixture
def db_session(mock_db_session):
  return mock_db_session
