from __future__ import annotations

import logging
from typing import Any

from app.storage.audit_repo import AuditRepository
from app.storage.database import AsyncSessionLocal
from app.storage.models import User

logger = logging.getLogger(__name__)

async def log_llm_interaction(
    user_id: int,
    prompt_summary: str,
    model_name: str,
    tokens_used: int | None,
    status: str
) -> None:
    """Helper to log LLM interactions asynchronously."""
    async with AsyncSessionLocal() as session:
        repo = AuditRepository(session)
        try:
             await repo.log_event(
                 user_id=user_id,
                 prompt_summary=prompt_summary,
                 model_name=model_name,
                 tokens_used=tokens_used,
                 status=status
             )
        except Exception as e:
            logger.error(f"Failed to log LLM interaction: {e}")
