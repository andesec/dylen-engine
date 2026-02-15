"""Section builder agent implementation."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import msgspec

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import render_section_builder_prompt
from app.ai.pipeline.contracts import JobContext, PlanSection, StructuredSection
from app.core.database import get_session_factory
from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import QuotaExceededError, commit_quota_reservation, get_quota_snapshot, release_quota_reservation, reserve_quota
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.storage.lessons_repo import FreeTextRecord, InputLineRecord, SubsectionRecord, SubsectionWidgetRecord
from app.telemetry.context import llm_call_context
from app.utils.ids import generate_nanoid


def _is_non_blocking_length_validation_error(message: str) -> bool:
  """Treat string/item length violations as non-blocking generation warnings."""
  lowered = message.lower()
  if "length" not in lowered:
    return False
  return "expected `str`" in lowered or "expected `array`" in lowered


def _resolve_section_title(section_struct: Any, section_json: dict[str, Any], fallback_title: str) -> str:
  """Resolve a stable section title from strict output, raw payload, or planner fallback."""
  if section_struct is not None:
    return str(getattr(section_struct, "section", None) or fallback_title)
  return str(section_json.get("section") or section_json.get("title") or fallback_title)


def _prune_none_values(value: Any) -> Any:
  """Preserve `None` placeholders to keep fixed-position payloads intact."""
  return value


def _normalize_provider_section_payload(payload: dict[str, Any], logger: logging.Logger) -> dict[str, Any]:
  """Normalize provider payload keys and drop unsupported top-level section fields."""
  from app.schema.section_normalizer import normalize_section_payload_keys

  normalized_payload = normalize_section_payload_keys(payload)
  if not isinstance(normalized_payload, dict):
    return payload
  allowed_top_level_fields = {"section", "markdown", "subsections", "illustration"}
  extra_fields = [field_name for field_name in normalized_payload.keys() if field_name not in allowed_top_level_fields]
  if extra_fields:
    # Drop non-schema top-level fields (for example, learning_data_points) to reduce avoidable hard failures.
    logger.warning("SectionBuilder dropped unsupported top-level fields from provider payload: %s", sorted(extra_fields))
  sanitized_payload = {field_name: field_value for field_name, field_value in normalized_payload.items() if field_name in allowed_top_level_fields}
  return sanitized_payload


def _build_shorthand_content(section_struct: Any, section_json: Any, section_number: int, logger: logging.Logger) -> dict[str, Any]:
  """Build shorthand JSON from canonical section struct output."""
  if section_struct is not None and hasattr(section_struct, "output"):
    try:
      return section_struct.output()
    except Exception as exc:  # noqa: BLE001
      logger.warning("SectionBuilder shorthand conversion failed from canonical struct for section %s: %s", section_number, exc)
  if not isinstance(section_json, dict):
    raise RuntimeError(f"SectionBuilder received non-dict payload for section {section_number}.")
  from app.services.section_shorthand import build_section_shorthand_content

  if section_struct is None:
    logger.warning("SectionBuilder shorthand conversion retried from raw payload for section %s.", section_number)
  return build_section_shorthand_content(section_json)


def _extract_error_location(error_message: str) -> tuple[str | None, str | None, int | None, int | None]:
  """Extract section/subsection location from validation error text."""
  normalized_path = None
  path_match = re.search(r"at `([^`]+)`", error_message)
  if path_match:
    normalized_path = str(path_match.group(1)).strip()
  section_scope = "section"
  subsection_index = None
  subsection_match = re.search(r"subsections\[(\d+)\]", error_message)
  if subsection_match:
    section_scope = "subsection"
    subsection_index = int(subsection_match.group(1))
  item_index = None
  item_match = re.search(r"items\[(\d+)\]", error_message)
  if item_match:
    item_index = int(item_match.group(1))
  return normalized_path, section_scope, subsection_index, item_index


def _collect_subjective_input_widget_records(section_struct: Any, creator_id: str) -> tuple[list[InputLineRecord], list[FreeTextRecord], list[tuple[str, Any, int]]]:
  """Collect subjective widget rows and keep payload references for id backfill."""
  input_lines: list[InputLineRecord] = []
  free_texts: list[FreeTextRecord] = []
  pending_updates: list[tuple[str, Any, int]] = []
  for sub in section_struct.subsections:
    for item in sub.items:
      if item.inputLine and item.inputLine.ai_prompt:
        input_lines.append(InputLineRecord(id=None, creator_id=creator_id, ai_prompt=item.inputLine.ai_prompt, wordlist=item.inputLine.wordlist_csv))
        pending_updates.append(("inputLine", item.inputLine, len(input_lines) - 1))
      if item.freeText and item.freeText.ai_prompt:
        free_texts.append(FreeTextRecord(id=None, creator_id=creator_id, ai_prompt=item.freeText.ai_prompt, wordlist=item.freeText.wordlist_csv))
        pending_updates.append(("freeText", item.freeText, len(free_texts) - 1))
  return input_lines, free_texts, pending_updates


def _collect_subsection_records(section_struct: Any, section_id: int) -> list[SubsectionRecord]:
  """Build subsection rows using 1-based subsection indexes."""
  records: list[SubsectionRecord] = []
  for subsection_index, sub in enumerate(section_struct.subsections, start=1):
    records.append(SubsectionRecord(id=None, section_id=section_id, subsection_index=subsection_index, subsection_title=str(sub.section), status="completed", is_archived=False))
  return records


def _collect_subsection_widget_records(section_struct: Any, subsection_rows: list[SubsectionRecord]) -> list[SubsectionWidgetRecord]:
  """Build subsection widget rows from generated section items using 1-based widget indexes."""
  records: list[SubsectionWidgetRecord] = []
  subsection_id_by_index = {row.subsection_index: int(row.id) for row in subsection_rows if row.id is not None}
  for subsection_index, sub in enumerate(section_struct.subsections, start=1):
    subsection_id = subsection_id_by_index.get(subsection_index)
    if subsection_id is None:
      continue
    for widget_index, item in enumerate(sub.items, start=1):
      widget_type = str(item.type if hasattr(item, "type") else "unknown")
      records.append(SubsectionWidgetRecord(id=None, subsection_id=subsection_id, widget_id=str(getattr(item, "id", "")) or None, widget_index=widget_index, widget_type=widget_type, status="pending", is_archived=False))
  return records


def _resolve_widget_entry(item: Any) -> tuple[str, Any] | None:
  """Resolve the active widget key/payload from a one-of item struct."""
  from app.schema.widget_models import get_widget_shorthand_names

  for widget_key in get_widget_shorthand_names():
    payload = getattr(item, widget_key, None)
    if payload is not None:
      return widget_key, payload
  return None


def _normalize_allowed_widgets(widget_names: list[str] | None) -> list[str] | None:
  """Normalize widget keys for schema filtering and always keep markdown available."""
  if widget_names is None:
    return None
  logger = logging.getLogger(__name__)
  from app.schema.widget_models import resolve_widget_shorthand_name

  normalized_widgets: list[str] = []
  seen_widgets: set[str] = set()
  for widget_name in widget_names:
    try:
      canonical_name = resolve_widget_shorthand_name(widget_name)
    except ValueError:
      # Ignore unknown widget keys so stale clients do not break section generation.
      logger.warning("SectionBuilder ignored unsupported widget key: %s", widget_name)
      continue
    if canonical_name in seen_widgets:
      continue
    seen_widgets.add(canonical_name)
    normalized_widgets.append(canonical_name)

  # Markdown is backend-required and planner-aligned, so include it even when callers omit it.
  if "markdown" not in seen_widgets:
    normalized_widgets.append("markdown")
  return normalized_widgets


def _collect_planned_widgets(section: PlanSection) -> list[str]:
  """Collect planner widget keys in order across all subsections."""
  planned: list[str] = []
  for subsection in section.subsections:
    planned.extend(subsection.planned_widgets or [])
  return planned


class SectionBuilder(BaseAgent[PlanSection, StructuredSection]):
  """Collect and structure a planned section in a single call."""

  name = "SectionBuilder"

  async def run(self, input_data: PlanSection, ctx: JobContext) -> StructuredSection:
    """Generate a structured section directly from the planner output."""
    from app.storage.lessons_repo import SectionErrorRecord, SectionRecord
    from app.storage.postgres_lessons_repo import PostgresLessonsRepository

    logger = logging.getLogger(__name__)
    request = ctx.request
    reservation_limit = 0
    reservation_active = False
    reservation_user_id: uuid.UUID | None = None
    section_index = input_data.section_number
    lesson_id = (ctx.metadata or {}).get("lesson_id")
    if not lesson_id:
      raise RuntimeError("SectionBuilder missing lesson_id metadata for section persistence.")
    repo = PostgresLessonsRepository()

    # Resolve the user id from metadata so quota reservations are scoped correctly.
    raw_user_id = (ctx.metadata or {}).get("user_id")
    if not raw_user_id:
      raise RuntimeError("SectionBuilder missing user_id metadata for quota reservation.")
    try:
      reservation_user_id = uuid.UUID(str(raw_user_id))
    except ValueError as exc:
      raise RuntimeError("SectionBuilder received invalid user_id metadata.") from exc

    # Resolve runtime configuration to determine the monthly section quota limit.
    session_factory = get_session_factory()
    if session_factory is None:
      raise RuntimeError("Database session factory unavailable for quota reservation.")
    async with session_factory() as session:
      # Resolve the user and tier so runtime config can be enforced.
      user = await get_user_by_id(session, reservation_user_id)
      if user is None:
        raise RuntimeError("SectionBuilder quota reservation failed: user not found.")
      tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
      # Require settings in metadata so runtime config resolution remains deterministic.
      settings = (ctx.metadata or {}).get("settings")
      if settings is None:
        raise RuntimeError("SectionBuilder missing settings metadata for quota resolution.")
      runtime_config = await resolve_effective_runtime_config(session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
      reservation_limit = int(runtime_config.get("limits.sections_per_month") or 0)
      if reservation_limit <= 0:
        raise QuotaExceededError("section.generate quota disabled")

    try:
      # Reserve monthly section quota before running the section builder.
      async with session_factory() as session:
        # Re-check live availability right before reservation so queued jobs fail fast with a clear quota reason.
        snapshot = await get_quota_snapshot(session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, limit=reservation_limit)
        if snapshot.remaining <= 0:
          raise QuotaExceededError("section.generate quota exceeded")
        # Build quota metadata for audit logging.
        section_metadata = {"job_id": str(ctx.job_id), "section_index": int(input_data.section_number)}
        await reserve_quota(
          session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(input_data.section_number), metadata=section_metadata
        )
      reservation_active = True

      # Prefer deterministic fixture output during local/test runs.
      dummy_json = self._load_dummy_json()

      if dummy_json is not None:
        topic = request.topic
        # For dummy data, we still use the full validator to ensure fixtures are correct
        validator = self._schema_service.validate_section_payload
        ok, errors, _ = validator(dummy_json, topic=topic, section_index=section_index)
        validation_errors = [] if ok else errors
        if not isinstance(dummy_json, dict):
          raise RuntimeError(f"SectionBuilder received non-dict dummy payload for section {section_index}.")
        section_title = _resolve_section_title(section_struct=None, section_json=dummy_json, fallback_title=input_data.title)
        record = SectionRecord(section_id=None, lesson_id=str(lesson_id), title=section_title, order_index=int(input_data.section_number), status="completed", content=dummy_json, content_shorthand=None)
        created_sections = await repo.create_sections([record])
        created_section = created_sections[0]
        if created_section.section_id is None:
          raise RuntimeError("SectionBuilder failed to persist section row before validation handling.")
        if validation_errors:
          error_records = []
          for index, message in enumerate(validation_errors):
            error_path, section_scope, subsection_index, item_index = _extract_error_location(message)
            error_records.append(SectionErrorRecord(id=None, section_id=created_section.section_id, error_index=index, error_message=message, error_path=error_path, section_scope=section_scope, subsection_index=subsection_index, item_index=item_index))
          await repo.create_section_errors(error_records)
        else:
          try:
            shorthand_content = _build_shorthand_content(section_struct=None, section_json=dummy_json, section_number=section_index, logger=logger)
            await repo.update_section_shorthand(created_section.section_id, shorthand_content)
          except Exception as exc:  # noqa: BLE001
            shorthand_error = f"payload: shorthand conversion failed: {exc}"
            error_path, section_scope, subsection_index, item_index = _extract_error_location(shorthand_error)
            await repo.create_section_errors(
              [SectionErrorRecord(id=None, section_id=created_section.section_id, error_index=0, error_message=shorthand_error, error_path=error_path, section_scope=section_scope, subsection_index=subsection_index, item_index=item_index)]
            )
            validation_errors = [shorthand_error]
        logger.info("SectionBuilder saved section %s to DB", input_data.section_number)
        # Commit quota reservation once section generation succeeds.
        async with session_factory() as session:
          # Build quota metadata for audit logging.
          commit_metadata = {"job_id": str(ctx.job_id), "section_index": int(input_data.section_number)}
          await commit_quota_reservation(
            session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(input_data.section_number), metadata=commit_metadata
          )
        return StructuredSection(section_number=section_index, payload=dummy_json, validation_errors=validation_errors, db_section_id=created_section.section_id)

      schema_version = str((ctx.metadata or {}).get("schema_version", ""))
      structured_output = bool((ctx.metadata or {}).get("structured_output", True))
      prompt_text = render_section_builder_prompt(request, input_data, schema_version)

      # Determine allowed widgets
      if request.widgets:
        allowed_widgets = _normalize_allowed_widgets(request.widgets)
      elif request.blueprint:
        from app.schema.widget_preference import get_widget_preference

        allowed_widgets = _normalize_allowed_widgets(get_widget_preference(request.blueprint, request.teaching_style))
      else:
        allowed_widgets = None

      planned_widgets = _collect_planned_widgets(input_data)
      if planned_widgets:
        planned_allowed = _normalize_allowed_widgets(planned_widgets)
        if allowed_widgets:
          allowed_set = set(allowed_widgets)
          planned_allowed = [widget for widget in planned_allowed if widget in allowed_set]
          if "markdown" not in planned_allowed:
            planned_allowed.append("markdown")
        allowed_widgets = planned_allowed

      purpose = f"build_section_{input_data.section_number}_of_{request.depth}"
      call_index = f"{input_data.section_number}/{request.depth}"

      # Apply context to correlate provider calls with the agent and lesson topic.
      with llm_call_context(agent=self.name, lesson_topic=request.topic, job_id=ctx.job_id, purpose=purpose, call_index=call_index):
        if structured_output:
          # 1. Generate and Sanitize Schema explicitly
          section_struct = None
          try:
            from app.schema.schema_builder import build_section_schema
            from app.schema.widget_models import get_widget_shorthand_names

            widget_set = allowed_widgets or get_widget_shorthand_names()
            final_schema = build_section_schema(widget_set)
          except Exception as e:
            logger.error("Failed to generate schema for section builder: %s", e)
            raise

          try:
            # 2. Call the Provider directly (No Mirascope)
            # self._model is likely an AuditModel wrapper, which handles logging automatically.
            response = await self._model.generate_structured(prompt_text, final_schema)

            # 3. Parse the result
            result_dict = response.content
            usage = response.usage

            self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=usage)
            if not isinstance(result_dict, dict):
              raise RuntimeError(f"Structured output provider returned non-object JSON payload: {type(result_dict).__name__}.")
            result_dict = _normalize_provider_section_payload(result_dict, logger)
            if not result_dict:
              raise RuntimeError("Structured output provider returned an empty JSON object.")

            # Validate provider output against canonical runtime model.
            from app.schema.widget_models import Section as CanonicalSection

            section_struct = msgspec.convert(result_dict, type=CanonicalSection)
            section_json = _prune_none_values(msgspec.to_builtins(section_struct))

            # Validation successful
            validation_errors = []

          except msgspec.ValidationError as e:
            # Capture validation errors from msgspec
            err_msg = str(e)
            if _is_non_blocking_length_validation_error(err_msg):
              logger.warning("Section validation violated string/item length constraints and was accepted: %s", err_msg)
              raw_payload = locals().get("result_dict", {})
              if isinstance(raw_payload, dict):
                section_json = _prune_none_values(raw_payload)
                validation_errors = []
              else:
                section_json = {}
                validation_errors = ["payload: provider returned non-object JSON payload."]
            else:
              logger.warning(f"Section validation failed: {e}")
              # We return the raw (potentially invalid) payload but mark it with errors
              # so the worker can run a single repair attempt.
              # If result_dict is available, use it; otherwise empty dict
              raw_payload = locals().get("result_dict", {})
              section_json = _prune_none_values(raw_payload) if isinstance(raw_payload, dict) else {}
              validation_errors = [err_msg]

          except Exception as e:
            # Log failure
            logger.error(f"Structured output generation failed: {e}", exc_info=True)
            raise
        else:
          raise RuntimeError("Structured output is required for section builder generation.")

      if not isinstance(section_json, dict):
        raise RuntimeError(f"SectionBuilder received non-dict payload for section {section_index}.")
      section_title = _resolve_section_title(section_struct=section_struct, section_json=section_json, fallback_title=input_data.title)
      record = SectionRecord(section_id=None, lesson_id=str(lesson_id), title=section_title, order_index=int(input_data.section_number), status="completed", content=section_json, content_shorthand=None)
      created_sections = await repo.create_sections([record])
      created_section = created_sections[0]
      if created_section.section_id is None:
        raise RuntimeError("SectionBuilder failed to persist section row before validation handling.")
      if validation_errors:
        error_records = []
        for index, message in enumerate(validation_errors):
          error_path, section_scope, subsection_index, item_index = _extract_error_location(message)
          error_records.append(SectionErrorRecord(id=None, section_id=created_section.section_id, error_index=index, error_message=message, error_path=error_path, section_scope=section_scope, subsection_index=subsection_index, item_index=item_index))
        await repo.create_section_errors(error_records)
      else:
        # Persist subjective input widgets if structured output is available.
        if section_struct is not None:
          creator_id = str(raw_user_id)
          markdown_payload = msgspec.to_builtins(section_struct.markdown)
          markdown_id = await repo.create_widget_payload(widget_type="markdown", creator_id=creator_id, payload_json=markdown_payload)
          await repo.update_section_links(created_section.section_id, markdown_id=int(markdown_id))

          subsection_records = _collect_subsection_records(section_struct=section_struct, section_id=created_section.section_id)
          created_subsections = await repo.create_subsections(subsection_records) if subsection_records else []
          subsection_id_by_index = {row.subsection_index: int(row.id) for row in created_subsections if row.id is not None}

          # Create Illustration record and subsection_widget tracking record for section-level illustration if it exists.
          # This follows the same pattern as other widgets: create all DB records, set IDs, THEN generate shorthand.
          if section_struct.illustration is not None and created_subsections:
            from app.schema.illustrations import Illustration

            first_subsection_id = subsection_id_by_index.get(1)
            if first_subsection_id is not None:
              # Get settings from metadata for storage bucket configuration
              settings = (ctx.metadata or {}).get("settings")
              if settings is None:
                raise RuntimeError("SectionBuilder missing settings metadata for illustration creation.")

              # Create Illustration record with status="pending" (image will be generated later)
              illustration_public_id = generate_nanoid()
              illustration_tracking_id = generate_nanoid()

              # Get illustration metadata from the payload
              illustration_caption = section_struct.illustration.caption
              illustration_prompt = section_struct.illustration.ai_prompt
              illustration_keywords = section_struct.illustration.keywords

              async with session_factory() as session:
                illustration_row = Illustration(
                  public_id=illustration_public_id,
                  creator_id=creator_id,
                  storage_bucket=settings.illustration_bucket,
                  storage_object_name=f"pending-{illustration_public_id}.webp",
                  mime_type="image/webp",
                  caption=illustration_caption,
                  ai_prompt=illustration_prompt,
                  keywords=illustration_keywords,
                  status="pending",
                  is_archived=False,
                  regenerate=False,
                )
                session.add(illustration_row)
                await session.commit()
                await session.refresh(illustration_row)
                illustration_db_id = int(illustration_row.id)

              # Create subsection_widget tracking record
              subsection_widget_record = SubsectionWidgetRecord(
                subsection_id=first_subsection_id,
                public_id=illustration_tracking_id,
                widget_id=illustration_public_id,  # Points to Illustration.public_id
                widget_index=0,  # Use 0 to indicate section-level widget
                widget_type="illustration",
                status="pending",
                is_archived=False,
              )
              await repo.create_subsection_widgets([subsection_widget_record])

              # Update section row to link the illustration
              await repo.update_section_links(created_section.section_id, illustration_id=illustration_db_id)

              # Set both resource_id and tracking id on the illustration payload before generating shorthand
              section_struct.illustration.resource_id = illustration_public_id
              section_struct.illustration.id = illustration_tracking_id
          for subsection_index, subsection in enumerate(section_struct.subsections, start=1):
            subsection_id = subsection_id_by_index.get(subsection_index)
            if subsection_id is None:
              continue
            for widget_index, item in enumerate(subsection.items, start=1):
              entry = _resolve_widget_entry(item)
              if entry is None:
                continue
              widget_type, widget_payload = entry
              payload_json = msgspec.to_builtins(widget_payload)
              if widget_type == "inputLine":
                record = InputLineRecord(id=None, creator_id=creator_id, ai_prompt=str(getattr(widget_payload, "ai_prompt", "") or ""), wordlist=getattr(widget_payload, "wordlist_csv", None))
                created_rows = await repo.create_input_lines([record])
                widget_row_id = str(created_rows[0].id) if created_rows and created_rows[0].id is not None else None
              elif widget_type == "freeText":
                record = FreeTextRecord(id=None, creator_id=creator_id, ai_prompt=str(getattr(widget_payload, "ai_prompt", "") or ""), wordlist=getattr(widget_payload, "wordlist_csv", None))
                created_rows = await repo.create_free_texts([record])
                widget_row_id = str(created_rows[0].id) if created_rows and created_rows[0].id is not None else None
              else:
                widget_row_id = await repo.create_widget_payload(widget_type=widget_type, creator_id=creator_id, payload_json=payload_json)
              if hasattr(widget_payload, "resource_id"):
                widget_payload.resource_id = widget_row_id
              public_id = generate_nanoid()
              subsection_widget_rows = await repo.create_subsection_widgets(
                [SubsectionWidgetRecord(subsection_id=subsection_id, public_id=public_id, widget_id=widget_row_id, widget_index=widget_index, widget_type=widget_type, status="pending", is_archived=False)]
              )
              if subsection_widget_rows and hasattr(widget_payload, "id"):
                widget_payload.id = subsection_widget_rows[0].public_id

        try:
          if section_struct is not None:
            section_json = _prune_none_values(msgspec.to_builtins(section_struct))
          shorthand_content = _build_shorthand_content(section_struct=section_struct, section_json=section_json, section_number=section_index, logger=logger)
          await repo.update_section_content_and_shorthand(created_section.section_id, section_json, shorthand_content)
        except Exception as exc:  # noqa: BLE001
          shorthand_error = f"payload: shorthand conversion failed: {exc}"
          error_path, section_scope, subsection_index, item_index = _extract_error_location(shorthand_error)
          await repo.create_section_errors(
            [SectionErrorRecord(id=None, section_id=created_section.section_id, error_index=0, error_message=shorthand_error, error_path=error_path, section_scope=section_scope, subsection_index=subsection_index, item_index=item_index)]
          )
          validation_errors = [shorthand_error]
      logger.info("SectionBuilder saved section %s to DB", input_data.section_number)

      # Commit quota reservation once section generation succeeds (or we return a result).
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        commit_metadata = {"job_id": str(ctx.job_id), "section_index": int(input_data.section_number)}
        await commit_quota_reservation(
          session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(input_data.section_number), metadata=commit_metadata
        )

      return StructuredSection(section_number=section_index, payload=section_json, validation_errors=validation_errors, db_section_id=created_section.section_id)
    except Exception:  # noqa: BLE001
      # Release quota reservation when section builder fails.
      logger.error("SectionBuilder failed during execution.", exc_info=True)
      if reservation_active and reservation_user_id is not None:
        try:
          async with session_factory() as session:
            # Build quota metadata for audit logging.
            release_metadata = {"job_id": str(ctx.job_id), "section_index": int(input_data.section_number), "reason": "section_builder_failed"}
            await release_quota_reservation(
              session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(input_data.section_number), metadata=release_metadata
            )
        except Exception:  # noqa: BLE001
          logger.error("SectionBuilder failed to release section quota reservation.", exc_info=True)
      raise
