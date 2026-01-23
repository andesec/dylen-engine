from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schema.audit import LlmCallAudit  # noqa: F401
from app.schema.email_delivery_logs import EmailDeliveryLog  # noqa: F401
from app.schema.jobs import Job  # noqa: F401
from app.schema.lessons import Lesson  # noqa: F401


class User(Base):
  __tablename__ = "users"

  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  firebase_uid: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
  email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
  full_name: Mapped[str | None] = mapped_column(String, nullable=True)
  provider: Mapped[str | None] = mapped_column(String, nullable=True)
  profession: Mapped[str | None] = mapped_column(String, nullable=True)
  city: Mapped[str | None] = mapped_column(String, nullable=True)
  country: Mapped[str | None] = mapped_column(String, nullable=True)
  age: Mapped[int | None] = mapped_column(Integer, nullable=True)
  photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
  is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
  is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMAuditLog(Base):
  __tablename__ = "llm_audit_logs"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
  prompt_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
  model_name: Mapped[str] = mapped_column(String, nullable=False)
  tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
  timestamp: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  status: Mapped[str | None] = mapped_column(String, nullable=True)
