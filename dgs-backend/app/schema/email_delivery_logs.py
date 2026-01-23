"""SQLAlchemy model for tracking outbound email delivery attempts."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmailDeliveryLog(Base):
  """Persist outbound email metadata for auditing and debugging."""

  __tablename__ = "email_delivery_logs"

  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
  to_address: Mapped[str] = mapped_column(String, nullable=False, index=True)
  template_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  placeholders: Mapped[dict] = mapped_column(JSONB, nullable=False)
  provider: Mapped[str] = mapped_column(String, nullable=False)
  provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  provider_request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  provider_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  status: Mapped[str] = mapped_column(String, nullable=False)
  error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
