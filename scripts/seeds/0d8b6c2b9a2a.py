"""Seed data for migration 0d8b6c2b9a2a."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection


async def seed(connection: AsyncConnection) -> None:
  """Record no-op seed for this revision to satisfy migration tracking."""
  # This migration only adds schema, so seeding is intentionally empty.
  return
