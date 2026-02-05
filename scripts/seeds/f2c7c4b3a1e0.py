"""Seed data for migration f2c7c4b3a1e0."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection


async def seed(connection: AsyncConnection) -> None:
  """Record no-op seed for this revision to satisfy migration tracking."""
  # This migration only adds schema, so seeding is intentionally empty.
  return
