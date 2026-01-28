"""Unit tests for usage row creation when tier seed data is missing."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schema.quotas import UserUsageMetrics
from app.services.users import ensure_usage_row


@pytest.mark.anyio
async def test_ensure_usage_row_raises_when_free_missing():
  """Ensure `ensure_usage_row` fails loudly when required tier seed data is missing."""
  # Use a stable user id to ensure insert params are predictable.
  user_id = uuid.uuid4()

  # Mock async session with controlled execute/get behavior.
  session = AsyncMock()
  usage_row = MagicMock(spec=UserUsageMetrics)
  session.get.return_value = usage_row

  tier_missing_result = MagicMock()
  tier_missing_result.scalar_one_or_none.return_value = None
  session.execute.side_effect = [tier_missing_result]

  with pytest.raises(RuntimeError, match="Free"):
    await ensure_usage_row(session, user_id)
