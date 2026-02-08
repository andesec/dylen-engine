"""Repository helpers for Web Push subscription persistence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.schema.push_subscriptions import WebPushSubscription


@dataclass(frozen=True)
class PushSubscriptionEntry:
  """Capture a single web push subscription payload for storage."""

  user_id: uuid.UUID
  endpoint: str
  p256dh: str
  auth: str
  user_agent: str | None


class PushSubscriptionRepository:
  """Persist and manage push subscriptions in Postgres."""

  async def upsert(self, entry: PushSubscriptionEntry) -> None:
    """Insert or update a subscription row keyed by endpoint."""
    session_factory = get_session_factory()
    if session_factory is None:
      return

    async with session_factory() as session:
      await self._upsert_with_session(session=session, entry=entry)

  async def _upsert_with_session(self, *, session: AsyncSession, entry: PushSubscriptionEntry) -> None:
    # Upsert by endpoint so a browser refresh rotates keys cleanly.
    stmt = insert(WebPushSubscription).values(user_id=entry.user_id, endpoint=entry.endpoint, p256dh=entry.p256dh, auth=entry.auth, user_agent=entry.user_agent)
    stmt = stmt.on_conflict_do_update(index_elements=["endpoint"], set_={"user_id": entry.user_id, "p256dh": entry.p256dh, "auth": entry.auth, "user_agent": entry.user_agent})
    await session.execute(stmt)
    await session.commit()

  async def delete_for_user_endpoint(self, *, user_id: uuid.UUID, endpoint: str) -> None:
    """Delete a subscription for a specific user and endpoint."""
    session_factory = get_session_factory()
    if session_factory is None:
      return

    async with session_factory() as session:
      await self._delete_for_user_endpoint_with_session(session=session, user_id=user_id, endpoint=endpoint)

  async def _delete_for_user_endpoint_with_session(self, *, session: AsyncSession, user_id: uuid.UUID, endpoint: str) -> None:
    # Constrain delete by user ownership so users cannot remove other devices.
    stmt = delete(WebPushSubscription).where(WebPushSubscription.user_id == user_id, WebPushSubscription.endpoint == endpoint)
    await session.execute(stmt)
    await session.commit()

  async def list_for_user(self, *, user_id: uuid.UUID) -> list[PushSubscriptionEntry]:
    """List all push subscriptions for a user."""
    session_factory = get_session_factory()
    if session_factory is None:
      return []

    async with session_factory() as session:
      return await self._list_for_user_with_session(session=session, user_id=user_id)

  async def _list_for_user_with_session(self, *, session: AsyncSession, user_id: uuid.UUID) -> list[PushSubscriptionEntry]:
    # Fetch all rows so each registered browser can receive the event.
    stmt = select(WebPushSubscription).where(WebPushSubscription.user_id == user_id)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [PushSubscriptionEntry(user_id=row.user_id, endpoint=row.endpoint, p256dh=row.p256dh, auth=row.auth, user_agent=row.user_agent) for row in rows]

  async def delete_by_endpoint(self, *, endpoint: str) -> None:
    """Delete subscriptions by endpoint regardless of owner."""
    session_factory = get_session_factory()
    if session_factory is None:
      return

    async with session_factory() as session:
      await self._delete_by_endpoint_with_session(session=session, endpoint=endpoint)

  async def _delete_by_endpoint_with_session(self, *, session: AsyncSession, endpoint: str) -> None:
    # Remove invalidated endpoints immediately to avoid repeated provider errors.
    stmt = delete(WebPushSubscription).where(WebPushSubscription.endpoint == endpoint)
    await session.execute(stmt)
    await session.commit()
