from __future__ import annotations

import io
import logging
import uuid
from typing import Any

from PIL import Image

from app.ai.agents.base import BaseAgent
from app.ai.pipeline.contracts import JobContext
from app.core.database import get_session_factory
from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import QuotaExceededError, commit_quota_reservation, release_quota_reservation, reserve_quota
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import get_user_by_id, get_user_subscription_tier

logger = logging.getLogger(__name__)


class IllustrationAgent(BaseAgent[dict[str, Any], dict[str, Any]]):
  """Generate section illustration bytes and normalized illustration metadata."""

  name = "IllustrationAgent"

  async def run(self, input_data: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
    """Generate a section illustration in one attempt with quota accounting."""
    section_index = int(input_data.get("section_index") or 0)
    topic = str(input_data.get("topic") or "").strip()
    section_data = input_data.get("section_data") or {}
    section_title = str(section_data.get("section") or f"Section {section_index}").strip()
    markdown_text = _extract_markdown_text(section_data)
    reservation_limit = 0
    reservation_active = False
    reservation_user_id: uuid.UUID | None = None
    session_factory = get_session_factory()
    if not session_factory:
      raise RuntimeError("Database session factory unavailable for illustration quota reservation.")
    raw_user_id = (ctx.metadata or {}).get("user_id")
    if not raw_user_id:
      raise RuntimeError("Illustration agent missing user_id metadata for quota reservation.")
    try:
      reservation_user_id = uuid.UUID(str(raw_user_id))
    except ValueError as exc:
      raise RuntimeError("Illustration agent received invalid user_id metadata.") from exc

    async with session_factory() as session:
      user = await get_user_by_id(session, reservation_user_id)
      if user is None:
        raise RuntimeError("Illustration quota reservation failed: user not found.")
      tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
      settings = (ctx.metadata or {}).get("settings")
      if settings is None:
        raise RuntimeError("Illustration agent missing settings metadata for quota resolution.")
      runtime_config = await resolve_effective_runtime_config(session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
      reservation_limit = int(runtime_config.get("limits.image_generations_per_month") or 0)
      if reservation_limit <= 0:
        raise QuotaExceededError("image.generate quota disabled")

    try:
      async with session_factory() as session:
        reserve_metadata = {"job_id": str(ctx.job_id), "section_index": section_index}
        await reserve_quota(session, user_id=reservation_user_id, metric_key="image.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=section_index, metadata=reserve_metadata)
      reservation_active = True

      caption, ai_prompt, keywords = _resolve_illustration_metadata(section_data=section_data, topic=topic, section_title=section_title, markdown_text=markdown_text)
      raw_image = await self._model.generate_image(ai_prompt)
      webp_image = _convert_to_webp(raw_image)

      async with session_factory() as session:
        commit_metadata = {"job_id": str(ctx.job_id), "section_index": section_index}
        await commit_quota_reservation(session, user_id=reservation_user_id, metric_key="image.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=section_index, metadata=commit_metadata)
      return {"caption": caption, "ai_prompt": ai_prompt, "keywords": keywords, "image_bytes": webp_image, "mime_type": "image/webp"}
    except Exception:  # noqa: BLE001
      logger.error("Illustration agent failed during execution.", exc_info=True)
      if reservation_active and reservation_user_id is not None:
        try:
          async with session_factory() as session:
            release_metadata = {"job_id": str(ctx.job_id), "section_index": section_index, "reason": "illustration_failed"}
            await release_quota_reservation(session, user_id=reservation_user_id, metric_key="image.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=section_index, metadata=release_metadata)
        except Exception:  # noqa: BLE001
          logger.error("Illustration agent failed to release image quota reservation.", exc_info=True)
      raise


def _extract_markdown_text(section_data: dict[str, Any]) -> str:
  """Extract canonical markdown body text from section content."""
  markdown_payload = section_data.get("markdown")
  if isinstance(markdown_payload, dict):
    markdown_text = markdown_payload.get("markdown")
    if isinstance(markdown_text, str):
      return markdown_text.strip()
  return ""


def _normalize_keywords(raw_keywords: Any) -> list[str] | None:
  """Validate and normalize builder-provided keyword lists."""
  if not isinstance(raw_keywords, list):
    return None
  normalized = [str(item).strip() for item in raw_keywords if str(item).strip()]
  if len(normalized) != 4:
    return None
  return normalized


def _resolve_illustration_metadata(*, section_data: dict[str, Any], topic: str, section_title: str, markdown_text: str) -> tuple[str, str, list[str]]:
  """Resolve builder metadata first, then synthesize fallback values."""
  illustration_data = section_data.get("illustration")
  if isinstance(illustration_data, dict):
    caption = str(illustration_data.get("caption") or "").strip()
    ai_prompt = str(illustration_data.get("ai_prompt") or "").strip()
    keywords = _normalize_keywords(illustration_data.get("keywords"))
    if caption and ai_prompt and keywords is not None:
      return caption, ai_prompt, keywords

  # Build deterministic fallback metadata when builder output is missing/invalid.
  fallback_caption = f"{section_title} visual summary"
  focus_line = markdown_text[:700] if markdown_text else f"Illustrate the key concept of {section_title}."
  fallback_prompt = (
    f"Create a clean educational illustration for the lesson topic '{topic}'. "
    f"Section title: '{section_title}'. "
    f"Use this guidance from section markdown: {focus_line}. "
    "Style: informative, simple layout, minimal clutter, no logos, no watermarks, no text-heavy poster."
  )
  fallback_keywords = _build_keywords(topic=topic, section_title=section_title, markdown_text=markdown_text)
  return fallback_caption, fallback_prompt, fallback_keywords


def _build_keywords(*, topic: str, section_title: str, markdown_text: str) -> list[str]:
  """Generate four deterministic keywords from topic/section context."""
  candidates = [topic.strip(), section_title.strip()]
  for token in markdown_text.replace("\n", " ").split(" "):
    normalized = token.strip(" ,.;:!?()[]{}\"'").lower()
    if len(normalized) >= 5:
      candidates.append(normalized)
    if len(candidates) >= 10:
      break
  deduped: list[str] = []
  for item in candidates:
    if item and item not in deduped:
      deduped.append(item)
    if len(deduped) == 4:
      break
  while len(deduped) < 4:
    deduped.append(f"concept-{len(deduped) + 1}")
  return deduped[:4]


def _convert_to_webp(image_bytes: bytes) -> bytes:
  """Convert provider image bytes into a WebP payload."""
  image = Image.open(io.BytesIO(image_bytes))
  # Convert alpha-free and alpha images consistently to avoid mode-related encoder errors.
  converted = image.convert("RGBA") if image.mode not in {"RGB", "RGBA"} else image
  output = io.BytesIO()
  converted.save(output, format="WEBP", quality=88, method=6)
  return output.getvalue()
