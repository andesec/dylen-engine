from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.storage.models import LLMAuditLog

class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_event(
        self,
        user_id: int,
        model_name: str,
        status: str,
        prompt_summary: str | None = None,
        tokens_used: int | None = None
    ) -> LLMAuditLog:
        log = LLMAuditLog(
            user_id=user_id,
            prompt_summary=prompt_summary,
            model_name=model_name,
            tokens_used=tokens_used,
            status=status
        )
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)
        return log
