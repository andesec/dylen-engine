"""SQLAlchemy model for browser Web Push subscriptions."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WebPushSubscription(Base):
  """Persist a single browser push subscription endpoint for a user."""

  __tablename__ = "web_push_subscriptions"
  __table_args__ = (Index("ux_web_push_subscriptions_endpoint", "endpoint", unique=True),)

  id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
  endpoint: Mapped[str] = mapped_column(Text, nullable=False)
  p256dh: Mapped[str] = mapped_column(Text, nullable=False)
  auth: Mapped[str] = mapped_column(Text, nullable=False)
  user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
