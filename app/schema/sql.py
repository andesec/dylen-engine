from __future__ import annotations

import datetime
import uuid
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.schema.audit import LlmCallAudit  # noqa: F401
from app.schema.email_delivery_logs import EmailDeliveryLog  # noqa: F401
from app.schema.jobs import Job  # noqa: F401
from app.schema.lessons import Lesson  # noqa: F401


class RoleLevel(str, Enum):
  GLOBAL = "GLOBAL"
  TENANT = "TENANT"


class UserStatus(str, Enum):
  PENDING = "PENDING"
  APPROVED = "APPROVED"
  DISABLED = "DISABLED"
  REJECTED = "REJECTED"


class AuthMethod(str, Enum):
  GOOGLE_SSO = "GOOGLE_SSO"
  NATIVE = "NATIVE"


class Organization(Base):
  __tablename__ = "organizations"

  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
  __tablename__ = "roles"

  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
  level: Mapped[RoleLevel] = mapped_column(SAEnum(RoleLevel, name="role_level"), nullable=False)
  description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Permission(Base):
  __tablename__ = "permissions"

  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
  display_name: Mapped[str] = mapped_column(String, nullable=False)
  description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RolePermission(Base):
  __tablename__ = "role_permissions"

  role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), primary_key=True)
  permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("permissions.id"), primary_key=True)


class User(Base):
  __tablename__ = "users"

  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  firebase_uid: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
  email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
  full_name: Mapped[str | None] = mapped_column(String, nullable=True)
  provider: Mapped[str | None] = mapped_column(String, nullable=True)
  role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)
  org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
  status: Mapped[UserStatus] = mapped_column(SAEnum(UserStatus, name="user_status"), default=UserStatus.PENDING, nullable=False)
  auth_method: Mapped[AuthMethod] = mapped_column(SAEnum(AuthMethod, name="auth_method"), default=AuthMethod.GOOGLE_SSO, nullable=False)
  profession: Mapped[str | None] = mapped_column(String, nullable=True)
  city: Mapped[str | None] = mapped_column(String, nullable=True)
  country: Mapped[str | None] = mapped_column(String, nullable=True)
  age: Mapped[int | None] = mapped_column(Integer, nullable=True)
  photo_url: Mapped[str | None] = mapped_column(String, nullable=True)

  # Onboarding fields
  gender: Mapped[str | None] = mapped_column(String, nullable=True)
  gender_other: Mapped[str | None] = mapped_column(String, nullable=True)
  occupation: Mapped[str | None] = mapped_column(String, nullable=True)
  topics_of_interest: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
  intended_use: Mapped[str | None] = mapped_column(String, nullable=True)
  intended_use_other: Mapped[str | None] = mapped_column(String, nullable=True)
  onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

  accepted_terms_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
  accepted_privacy_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
  terms_version: Mapped[str | None] = mapped_column(String, nullable=True)
  privacy_version: Mapped[str | None] = mapped_column(String, nullable=True)

  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LLMAuditLog(Base):
  __tablename__ = "llm_audit_logs"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
  prompt_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
  model_name: Mapped[str] = mapped_column(String, nullable=False)
  tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
  timestamp: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  status: Mapped[str | None] = mapped_column(String, nullable=True)
