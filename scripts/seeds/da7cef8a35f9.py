"""Seed data for migration da7cef8a35f9."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection


async def seed(connection: AsyncConnection) -> None:
  """Apply seed data for this migration (intentionally empty)."""
  # No seed data is required for this revision.
  return
