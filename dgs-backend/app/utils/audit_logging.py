import functools
import logging
import time
from typing import Callable, Any, Awaitable, Dict

from app.config import get_settings
from app.storage.db import get_db_session
from app.storage.models import LlmAuditLog
from sqlalchemy import select
from app.storage.models import User

logger = logging.getLogger(__name__)

async def log_llm_call(
    user_id: int | None,
    prompt_summary: str | None,
    model_name: str | None,
    tokens_used: int | None,
    status: str | None
):
    settings = get_settings()
    if not settings.llm_audit_enabled:
        return

    try:
        async with get_db_session() as session:
            audit_log = LlmAuditLog(
                user_id=user_id,
                prompt_summary=prompt_summary,
                model_name=model_name,
                tokens_used=tokens_used,
                status=status
            )
            session.add(audit_log)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to log LLM call: {e}")

def audit_llm_call(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """
    Decorator to audit LLM calls.
    It expects the decorated function to return a result that can be parsed for usage stats.
    Alternatively, it logs the call initiation and completion status.

    Assumption: The wrapped function is a method of a class (like Orchestrator) or a standalone function.
    We need access to `user_id`. This is difficult if it's not passed as an argument.

    If used on API endpoints, we can get `current_user` from dependencies.
    But requirement says "associated with the authenticated user_id" for "every LLM API call".

    If we wrap the `orchestrator.generate_lesson` method, we need to ensure `user_id` is passed to it.
    Currently `generate_lesson` does not take `user_id`.

    I will update `generate_lesson` to accept an optional `user_id` (or kwargs) and pass it through.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # Extract user_id if present in kwargs
        user_id = kwargs.get('user_id')

        # Extract prompt or topic.
        # generate_lesson signature: (self, topic, ...)
        # args[0] is self, args[1] is topic (if positional)
        prompt_summary = kwargs.get('topic')
        if not prompt_summary and len(args) > 1:
             prompt_summary = str(args[1])

        model_name = kwargs.get('gatherer_model') or kwargs.get('structurer_model') or "unknown"

        start_time = time.time()
        status_code = "success"
        tokens_used = 0 # Placeholder as we might not get token usage easily from return value without parsing

        try:
            result = await func(*args, **kwargs)

            # Try to extract usage from result if possible
            # Result of generate_lesson is DgsOrchestratorResult which has logs but maybe not tokens explicitly
            # If result has usage info, use it.

            return result
        except Exception as e:
            status_code = "error"
            raise e
        finally:
            # Log the call
            # We fire and forget logging to not block main thread if possible,
            # but since log_llm_call is async, we await it.
            # To avoid blocking response, we could use BackgroundTasks if we were in a route handler,
            # but here we are in a deeper function.
            await log_llm_call(
                user_id=user_id,
                prompt_summary=prompt_summary[:100] if prompt_summary else None, # Truncate
                model_name=model_name,
                tokens_used=tokens_used,
                status=status_code
            )

    return wrapper
