from app.api.models import MAX_REQUEST_BYTES, GenerateLessonRequest, WritingCheckRequest
from app.config import Settings
from app.jobs.guardrails import estimate_bytes
from fastapi import HTTPException, status


def _count_words(text: str) -> int:
  """Approximate word count by splitting on whitespace."""
  return len(text.split())


def _validate_generate_request(request: GenerateLessonRequest, settings: Settings, *, max_topic_length: int | None = None) -> None:
  """Enforce topic/detail length and persistence size constraints."""
  # Allow callers to override max topic length using runtime configuration.
  effective_max_topic_length = settings.max_topic_length if max_topic_length is None else int(max_topic_length)
  if effective_max_topic_length <= 0:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid max topic length configuration.")
  if len(request.topic) > effective_max_topic_length:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Topic exceeds max length of {effective_max_topic_length} chars.")
  if request.details:
    # Guardrail to keep user-provided detail payloads within size limits.
    word_count = _count_words(request.details)
    if word_count > 250:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"User details are too long ({word_count} words). Max 250 words.")
  if estimate_bytes(request.model_dump(mode="python", by_alias=True)) > MAX_REQUEST_BYTES:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request payload is too large for persistence.")
  # Keep validation deterministic; avoid request-shape checks that drift from the current pipeline.


def _validate_writing_request(request: WritingCheckRequest) -> None:
  """Validate writing check inputs."""
  word_count = _count_words(request.text)
  if word_count > 300:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"User text is too long ({word_count} words). Max 300 words.")
  if not request.criteria:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Evaluation criteria are required.")
  if estimate_bytes(request.model_dump(mode="python")) > MAX_REQUEST_BYTES:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Request payload is too large for persistence.")


def _resolve_primary_language(request: GenerateLessonRequest) -> str | None:
  """Return the requested primary language for orchestration prompts."""
  # This feeds prompt guidance but does not change response schema.
  return request.primary_language


def _resolve_learner_level(request: GenerateLessonRequest) -> str | None:
  """Return the learner level from the request."""
  # Prefer the explicit request field for prompt guidance.
  if request.learner_level:
    return request.learner_level
  return None
