"""Context helpers for correlating LLM calls with upstream requests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class LlmCallContext:
    """Capture upstream metadata so provider calls can be audited consistently."""

    agent: str
    lesson_topic: str | None
    job_id: str | None
    purpose: str | None
    call_index: str | None


_CURRENT_LLM_CONTEXT: ContextVar[LlmCallContext | None] = ContextVar(
    "llm_call_context", default=None
)


def get_llm_call_context() -> LlmCallContext | None:
    """Return the active LLM call context so providers can log rich metadata."""
    return _CURRENT_LLM_CONTEXT.get()


@contextmanager
def llm_call_context(
    *,
    agent: str,
    lesson_topic: str | None,
    job_id: str | None,
    purpose: str | None,
    call_index: str | None,
) -> Iterator[LlmCallContext]:
    """Set contextual metadata for downstream LLM calls and reset it afterward."""
    # Store the call metadata in a contextvar so nested calls can access it.
    context = LlmCallContext(
        agent=agent,
        lesson_topic=lesson_topic,
        job_id=job_id,
        purpose=purpose,
        call_index=call_index,
    )
    token = _CURRENT_LLM_CONTEXT.set(context)

    try:
        yield context

    finally:
        _CURRENT_LLM_CONTEXT.reset(token)
