"""SQLAlchemy model for in-app notifications."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InAppNotification(Base):
  """Persist in-app notifications for user polling."""

  __tablename__ = "notifications"

  id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
  template_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  title: Mapped[str] = mapped_column(String, nullable=False)
  body: Mapped[str] = mapped_column(Text, nullable=False)
  data_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
  read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
