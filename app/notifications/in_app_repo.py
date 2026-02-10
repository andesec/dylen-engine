"""Repository helpers for in-app notifications."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.schema.notifications import InAppNotification

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InAppNotificationEntry:
  """Capture a single in-app notification entry."""

  user_id: uuid.UUID
  template_id: str
  title: str
  body: str
  data: dict


class InAppNotificationRepository:
  """Persist in-app notifications to Postgres."""

  async def insert(self, entry: InAppNotificationEntry) -> None:
    """Insert a new in-app notification row."""
    session_factory = get_session_factory()
    if session_factory is None:
      return
    async with session_factory() as session:
      await self._insert_with_session(session=session, entry=entry)

  async def _insert_with_session(self, *, session: AsyncSession, entry: InAppNotificationEntry) -> None:
    # Persist a minimal row for in-app notification polling.
    record = InAppNotification(user_id=entry.user_id, template_id=entry.template_id, title=entry.title, body=entry.body, data_json=entry.data, read=False)
    session.add(record)
    await session.commit()


class NullInAppNotificationRepository(InAppNotificationRepository):
  """No-op repository when persistence is unavailable."""

  async def insert(self, entry: InAppNotificationEntry) -> None:
    logger.debug("In-app notification persistence disabled; dropping template_id=%s", entry.template_id)
