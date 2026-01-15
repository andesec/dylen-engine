"""Audit wrapper for AI models."""

from __future__ import annotations

import logging
from typing import Any

from app.ai.providers.base import (
  AIModel,
  ModelResponse,
  StructuredModelResponse,
)
from app.utils.logging_helper import log_llm_interaction
from app.storage.database import get_db

logger = logging.getLogger(__name__)

class AuditedModel(AIModel):
  """Wraps an AIModel to audit interactions."""

  def __init__(self, inner: AIModel, user_id: int | None = None) -> None:
    self.inner = inner
    self.name = inner.name
    self.supports_structured_output = inner.supports_structured_output
    self.user_id = user_id

  async def generate(self, prompt: str) -> ModelResponse:
    try:
        response = await self.inner.generate(prompt)
        status = "success"
    except Exception:
        status = "error"
        # Log failure even if we re-raise
        if self.user_id:
             await log_llm_interaction(
                user_id=self.user_id,
                prompt_summary=prompt[:100] + "..." if len(prompt) > 100 else prompt,
                model_name=self.name,
                tokens_used=None, # Usage might not be available on error
                status=status
            )
        raise

    if self.user_id:
        usage = response.usage
        tokens_used = usage.get("total_tokens") if usage else None

        await log_llm_interaction(
            user_id=self.user_id,
            prompt_summary=prompt[:100] + "..." if len(prompt) > 100 else prompt,
            model_name=self.name,
            tokens_used=tokens_used,
            status=status
        )

    return response

  async def generate_structured(
      self, prompt: str, schema: dict[str, Any]
  ) -> StructuredModelResponse:
    try:
        response = await self.inner.generate_structured(prompt, schema)
        status = "success"
    except Exception:
        status = "error"
        if self.user_id:
             await log_llm_interaction(
                user_id=self.user_id,
                prompt_summary=prompt[:100] + "..." if len(prompt) > 100 else prompt,
                model_name=self.name,
                tokens_used=None,
                status=status
            )
        raise

    if self.user_id:
        usage = response.usage
        tokens_used = usage.get("total_tokens") if usage else None

        await log_llm_interaction(
            user_id=self.user_id,
            prompt_summary=prompt[:100] + "..." if len(prompt) > 100 else prompt,
            model_name=self.name,
            tokens_used=tokens_used,
            status=status
        )

    return response
