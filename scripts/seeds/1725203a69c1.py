"""Seed data for migration 1725203a69c1."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection


async def seed(connection: AsyncConnection) -> None:
  """Apply seed data for this migration (intentionally empty)."""
  # No seed data is required for this revision.
  return
