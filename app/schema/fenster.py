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
  __tablename__ = "fenster_widgets"

  fenster_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  type: Mapped[FensterWidgetType] = mapped_column(Enum(FensterWidgetType), nullable=False)
  content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # brotli compressed content
  url: Mapped[str | None] = mapped_column(String, nullable=True)  # cdn url
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
