from __future__ import annotations

import datetime
import uuid
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FensterWidgetType(str, PyEnum):
  INLINE_BLOB = "inline_blob"
  CDN_URL = "cdn_url"


class FensterWidget(Base):
  __tablename__ = "fensters"

  fenster_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  public_id: Mapped[str] = mapped_column(String, nullable=False, index=True, unique=True)
  creator_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
  is_archived: Mapped[bool] = mapped_column(nullable=False, default=False)
  type: Mapped[FensterWidgetType] = mapped_column(Enum(FensterWidgetType), nullable=False)
  content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # brotli compressed content
  url: Mapped[str | None] = mapped_column(String, nullable=True)  # cdn url
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
