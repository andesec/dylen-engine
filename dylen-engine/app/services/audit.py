from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.schema.sql import LLMAuditLog

logger = logging.getLogger(__name__)


async def log_llm_interaction(user_id: uuid.UUID, model_name: str, prompt_summary: str | None = None, tokens_used: int | None = None, status: str | None = None, session: AsyncSession | None = None) -> None:
  """
  Logs an LLM interaction to the database.
  If session is provided, it uses it. Otherwise, it creates a new one.
  """
  from app.config import get_settings

  settings = get_settings()

  if not settings.llm_audit_enabled:
    return

  try:
    should_close_session = False
    if session is None:
      session_factory = get_session_factory()
      if not session_factory:
        logger.warning("Database not configured, skipping LLM audit log.")
        return
      session = session_factory()
      should_close_session = True

    audit_log = LLMAuditLog(user_id=user_id, model_name=model_name, prompt_summary=prompt_summary, tokens_used=tokens_used, status=status)
    session.add(audit_log)
    await session.commit()

    if should_close_session:
      await session.close()

  except Exception as e:
    logger.error(f"Failed to log LLM interaction: {e}")
