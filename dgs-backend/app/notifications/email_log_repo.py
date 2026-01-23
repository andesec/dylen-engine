"""Repository helpers for email delivery logs."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.schema.email_delivery_logs import EmailDeliveryLog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailDeliveryLogEntry:
  """Capture a single outbound email attempt for auditing and troubleshooting."""

  user_id: uuid.UUID | None
  to_address: str
  template_id: str
  placeholders: dict
  provider: str
  provider_message_id: str | None
  provider_request_id: str | None
  provider_response: dict | None
  status: str
  error_message: str | None


class EmailDeliveryLogRepository:
  """Persist email delivery logs to Postgres using SQLAlchemy."""

  async def insert(self, entry: EmailDeliveryLogEntry) -> None:
    """Insert a new email delivery log row."""
    session_factory = get_session_factory()
    if session_factory is None:
      return

    async with session_factory() as session:
      await self._insert_with_session(session=session, entry=entry)

  async def _insert_with_session(self, *, session: AsyncSession, entry: EmailDeliveryLogEntry) -> None:
    # Persist minimal data required to correlate provider delivery and templates.
    record = EmailDeliveryLog(
      user_id=entry.user_id,
      to_address=entry.to_address,
      template_id=entry.template_id,
      placeholders=entry.placeholders,
      provider=entry.provider,
      provider_message_id=entry.provider_message_id,
      provider_request_id=entry.provider_request_id,
      provider_response=entry.provider_response,
      status=entry.status,
      error_message=entry.error_message,
    )
    session.add(record)
    await session.commit()


class NullEmailDeliveryLogRepository(EmailDeliveryLogRepository):
  """No-op repository used when persistence is unavailable."""

  async def insert(self, entry: EmailDeliveryLogEntry) -> None:
    logger.debug("Email delivery log persistence disabled; dropping template_id=%s status=%s", entry.template_id, entry.status)
