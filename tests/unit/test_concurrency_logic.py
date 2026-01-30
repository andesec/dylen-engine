from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.deps_concurrency import check_concurrency_limit
from app.schema.sql import User
from fastapi import HTTPException


@pytest.mark.anyio
async def test_check_concurrency_limit_under_limit():
  user = User(id="user1")
  db = AsyncMock()

  with patch("app.api.deps_concurrency.get_user_subscription_tier", return_value=(1, "Free")):
    # Mock override query (return None)
    # Mock tier query (return object with limit)
    # Mock count query (return 0)

    # 1. UserTierOverride (return None)
    # 2. SubscriptionTier (return tier)
    # 3. Count (return 0)

    mock_override_result = MagicMock()
    mock_override_result.scalar_one_or_none.return_value = None

    mock_tier = MagicMock()
    mock_tier.concurrent_lesson_limit = 5
    mock_tier_result = MagicMock()
    mock_tier_result.scalar_one_or_none.return_value = mock_tier

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 0

    # We need to set side_effect for db.execute
    # Note: Depending on implementation, get_user_subscription_tier might use db.execute too?
    # But we patched it.
    db.execute.side_effect = [mock_override_result, mock_tier_result, mock_count_result]

    await check_concurrency_limit("lesson", user, db)
    # Should not raise


@pytest.mark.anyio
async def test_check_concurrency_limit_over_limit():
  user = User(id="user1")
  db = AsyncMock()

  with patch("app.api.deps_concurrency.get_user_subscription_tier", return_value=(1, "Free")):
    # 1. UserTierOverride (return None)
    # 2. SubscriptionTier (return tier limit=1)
    # 3. Count (return 1)

    mock_override_result = MagicMock()
    mock_override_result.scalar_one_or_none.return_value = None

    mock_tier = MagicMock()
    mock_tier.concurrent_lesson_limit = 1
    mock_tier_result = MagicMock()
    mock_tier_result.scalar_one_or_none.return_value = mock_tier

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 1

    db.execute.side_effect = [mock_override_result, mock_tier_result, mock_count_result]

    with pytest.raises(HTTPException) as exc:
      await check_concurrency_limit("lesson", user, db)
    assert exc.value.status_code == 429
    assert "Concurrency limit reached" in exc.value.detail


@pytest.mark.anyio
async def test_check_concurrency_limit_with_override():
  user = User(id="user1")
  db = AsyncMock()

  with patch("app.api.deps_concurrency.get_user_subscription_tier", return_value=(1, "Free")):
    # 1. UserTierOverride (return object with limit=10)
    # 2. Count (return 5) -> Should pass

    mock_override = MagicMock()
    mock_override.concurrent_lesson_limit = 10
    mock_override_result = MagicMock()
    mock_override_result.scalar_one_or_none.return_value = mock_override

    mock_count_result = MagicMock()
    mock_count_result.scalar_one.return_value = 5

    db.execute.side_effect = [mock_override_result, mock_count_result]

    await check_concurrency_limit("lesson", user, db)
    # Should not raise
