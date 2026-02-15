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
from app.schema.illustrations import Illustration
from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import QuotaExceededError, commit_quota_reservation, get_quota_snapshot, release_quota_reservation, reserve_quota
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.storage.lessons_repo import FreeTextRecord, InputLineRecord, SubsectionRecord, SubsectionWidgetRecord
from app.telemetry.context import llm_call_context
from app.utils.db_retry import execute_with_retry
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
    records.append(SubsectionRecord(id=None, section_id=section_id, index=subsection_index, title=str(sub.section), status="completed", is_archived=False))
  return records


def _collect_subsection_widget_records(section_struct: Any, subsection_rows: list[SubsectionRecord]) -> list[SubsectionWidgetRecord]:
  """Build subsection widget rows from generated section items using 1-based widget indexes."""
  records: list[SubsectionWidgetRecord] = []
  subsection_id_by_index = {row.index: int(row.id) for row in subsection_rows if row.id is not None}
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
        # Persist all widgets, subsections, and content updates in a SINGLE transaction.
        # This prevents orphan rows if something fails partway through.
        # Wrapped in retry logic to handle transient deadlocks/serialization failures.
        if section_struct is not None:
          creator_id = str(raw_user_id)

          # Define transaction function for retry wrapper
          async def _execute_widget_creation_transaction():
            """Execute widget creation transaction atomically with retry support."""
            async with session_factory() as session:
              from app.schema.lessons import Section

              # 1. Create markdown widget
              markdown_payload = msgspec.to_builtins(section_struct.markdown)
              markdown_widget = await repo._create_widget_payload_in_session(session=session, widget_type="markdown", creator_id=creator_id, payload_json=markdown_payload)
              await session.flush()  # Flush to get markdown_id
              markdown_id = int(markdown_widget.id)

              # 2. Create subsections
              from app.schema.lessons import Subsection as SubsectionModel

              subsection_records = _collect_subsection_records(section_struct=section_struct, section_id=created_section.section_id)
              created_subsections = []
              for rec in subsection_records:
                subsection_row = SubsectionModel(section_id=rec.section_id, title=rec.title, index=rec.index, is_archived=False)
                session.add(subsection_row)
                created_subsections.append(subsection_row)

              await session.flush()  # Flush to get subsection IDs
              subsection_id_by_index = {row.index: int(row.id) for row in created_subsections if row.id is not None}

              # 3. Create Illustration and subsection_widget if illustration exists
              illustration_db_id: int | None = None

              if section_struct.illustration is not None:
                if not created_subsections:
                  logger.warning("Section %s has illustration but no subsections - cannot create subsection_widget tracking. Removing illustration.", section_index)
                  section_struct.illustration = None
                else:
                  first_subsection_id = subsection_id_by_index.get(1)
                  if first_subsection_id is None:
                    logger.warning("Section %s has illustration but first subsection ID not found. Removing illustration.", section_index)
                    section_struct.illustration = None
                  else:
                    try:
                      settings = (ctx.metadata or {}).get("settings")
                      if settings is None:
                        raise RuntimeError("SectionBuilder missing settings metadata for illustration creation.")
                      if not hasattr(settings, "illustration_bucket") or not settings.illustration_bucket:
                        raise RuntimeError("Settings missing illustration_bucket configuration.")

                      illustration_public_id = generate_nanoid()
                      illustration_tracking_id = generate_nanoid()
                      illustration_caption = section_struct.illustration.caption
                      illustration_prompt = section_struct.illustration.ai_prompt
                      illustration_keywords = section_struct.illustration.keywords

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
                      await session.flush()  # Flush to get illustration DB ID
                      illustration_db_id = int(illustration_row.id)

                      # Create subsection_widget for illustration
                      from app.schema.lessons import SubsectionWidget as SubsectionWidgetModel

                      illustration_widget = SubsectionWidgetModel(subsection_id=first_subsection_id, public_id=illustration_tracking_id, widget_id=illustration_public_id, widget_index=0, widget_type="illustration", status="pending", is_archived=False)
                      session.add(illustration_widget)
                      await session.flush()  # Flush illustration widget

                      # Set IDs in memory
                      section_struct.illustration.resource_id = illustration_public_id
                      section_struct.illustration.id = illustration_tracking_id
                      logger.info("Created Illustration DB record for section %s: resource_id=%s, tracking_id=%s", section_index, illustration_public_id, illustration_tracking_id)
                    except Exception as exc:  # noqa: BLE001
                      logger.error("Failed to create Illustration DB record for section %s: %s. Removing illustration from shorthand.", section_index, exc)
                      section_struct.illustration = None

              # 4. Create all subsection widgets
              from app.schema.lessons import FreeText as FreeTextModel
              from app.schema.lessons import InputLine as InputLineModel
              from app.schema.lessons import SubsectionWidget as SubsectionWidgetModel

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

                  # Create widget payload record
                  if widget_type == "inputLine":
                    widget_row = InputLineModel(creator_id=creator_id, ai_prompt=str(getattr(widget_payload, "ai_prompt", "") or ""), wordlist=getattr(widget_payload, "wordlist_csv", None))
                    session.add(widget_row)
                    await session.flush()
                    widget_row_id = str(widget_row.id) if widget_row.id is not None else None
                  elif widget_type == "freeText":
                    widget_row = FreeTextModel(creator_id=creator_id, ai_prompt=str(getattr(widget_payload, "ai_prompt", "") or ""), wordlist=getattr(widget_payload, "wordlist_csv", None))
                    session.add(widget_row)
                    await session.flush()
                    widget_row_id = str(widget_row.id) if widget_row.id is not None else None
                  else:
                    widget_row = await repo._create_widget_payload_in_session(session=session, widget_type=widget_type, creator_id=creator_id, payload_json=payload_json)
                    await session.flush()
                    # FensterWidget uses public_id, others use id
                    if widget_type == "fenster":
                      widget_row_id = str(widget_row.public_id) if hasattr(widget_row, "public_id") and widget_row.public_id is not None else None
                    else:
                      widget_row_id = str(widget_row.id) if widget_row.id is not None else None

                  # Set resource_id in memory
                  if hasattr(widget_payload, "resource_id"):
                    widget_payload.resource_id = widget_row_id

                  # Create subsection_widget tracking record
                  public_id = generate_nanoid()
                  subsection_widget = SubsectionWidgetModel(subsection_id=subsection_id, public_id=public_id, widget_id=widget_row_id, widget_index=widget_index, widget_type=widget_type, status="pending", is_archived=False)
                  session.add(subsection_widget)
                  await session.flush()  # Flush to ensure public_id is available

                  # Set tracking id in memory
                  if hasattr(widget_payload, "id"):
                    widget_payload.id = public_id

              # 5. Update section content with all IDs now set in memory
              section_json = _prune_none_values(msgspec.to_builtins(section_struct))
              section_row = await session.get(Section, created_section.section_id)
              if section_row is None:
                raise RuntimeError(f"Section {created_section.section_id} not found for content update.")

              section_row.content = section_json
              section_row.markdown_id = markdown_id
              if illustration_db_id is not None:
                section_row.illustration_id = illustration_db_id
              session.add(section_row)

              # 6. Commit the entire transaction
              await session.commit()
              logger.info("Successfully created all widgets and updated content for section %s in single transaction", section_index)

              # Return section_json for use after transaction
              return section_json

          # Execute transaction with retry logic for transient failures
          try:
            section_json = await execute_with_retry(operation_name=f"section_{section_index}_widget_creation", func=_execute_widget_creation_transaction, max_attempts=2, initial_backoff_ms=100, max_backoff_ms=2000)
          except Exception as exc:
            # Transaction failed even after retries (or non-retryable error)
            logger.error("Widget creation transaction failed for section %s (all retries exhausted or non-retryable error): %s", section_index, exc, exc_info=True)
            # This is a critical failure - we cannot continue with an inconsistent state
            raise RuntimeError(f"Failed to create widgets for section {section_index} in database transaction") from exc

        # Now attempt to create child jobs for illustration, fenster, and tutor widgets.
        # SectionBuilder is the boss - it asks worker to create jobs and makes decisions based on results.
        child_job_creator = (ctx.metadata or {}).get("child_job_creator")
        removed_widget_refs: list[str] = []

        if child_job_creator is not None:
          # Attempt to create illustration child job if illustration exists
          if section_struct.illustration is not None:
            try:
              illustration_payload = {"section_index": section_index, "section_id": created_section.section_id, "lesson_id": lesson_id, "topic": request.topic, "section_data": section_json}
              await child_job_creator(target_agent="illustration", payload=illustration_payload, section_id=created_section.section_id)
              logger.info("Successfully created illustration child job for section %s", section_index)
            except Exception as exc:  # noqa: BLE001
              # Job creation failed (quota or other issue) - remove illustration from shorthand
              logger.warning("Illustration job creation failed for section %s: %s", section_index, exc)
              section_struct.illustration = None
              removed_widget_refs.append(f"{section_index}.illustration")

          # Collect fenster widgets with their metadata for easier tracking
          fenster_widgets: list[tuple[str, int, int]] = []  # (public_id, subsection_idx, item_idx)
          for subsection_idx, subsection in enumerate(section_struct.subsections, start=1):
            for item_idx, item in enumerate(subsection.items, start=1):
              if item.fenster is not None and item.fenster.id is not None:
                fenster_widgets.append((item.fenster.id, subsection_idx, item_idx))

          # Attempt to create fenster child jobs
          failed_fenster_ids: set[str] = set()
          for fenster_id, subsection_idx, item_idx in fenster_widgets:
            try:
              fenster_payload = {
                "lesson_id": lesson_id,
                "section_id": created_section.section_id,
                "widget_public_ids": [fenster_id],
                "concept_context": f"Fenster widget for section {section_index} in topic {request.topic}",
                "target_audience": request.learner_level or "Student",
                "technical_constraints": {},
              }
              await child_job_creator(target_agent="fenster_builder", payload=fenster_payload, section_id=created_section.section_id)
              logger.info("Created fenster child job for widget %s in section %s", fenster_id, section_index)
            except Exception as exc:  # noqa: BLE001
              # Job creation failed - mark for removal
              logger.warning("Fenster job creation failed for widget %s in section %s: %s", fenster_id, section_index, exc)
              failed_fenster_ids.add(fenster_id)
              removed_widget_refs.append(f"{section_index}.{subsection_idx}.{item_idx}.fenster")

          # Remove failed fenster widgets from shorthand (safe iteration)
          if failed_fenster_ids:
            for subsection in section_struct.subsections:
              subsection.items = [item for item in subsection.items if item.fenster is None or item.fenster.id not in failed_fenster_ids]

          # Remove empty subsections (can happen if all widgets in a subsection failed)
          original_subsection_count = len(section_struct.subsections)
          section_struct.subsections = [sub for sub in section_struct.subsections if len(sub.items) > 0]
          if len(section_struct.subsections) < original_subsection_count:
            removed_count = original_subsection_count - len(section_struct.subsections)
            logger.warning("Removed %d empty subsection(s) from section %s after widget failures", removed_count, section_index)

          # Verify we still have at least one subsection with widgets
          if len(section_struct.subsections) == 0:
            logger.error("Section %s has no subsections remaining after widget removals - cannot generate valid shorthand", section_index)
            # Mark section as failed - no valid shorthand can be generated
            validation_errors = ["Section has no valid subsections after widget creation failures"]
            error_path, section_scope, subsection_index, item_index = _extract_error_location("No valid subsections remaining")
            await repo.create_section_errors(
              [
                SectionErrorRecord(
                  id=None, section_id=created_section.section_id, error_index=0, error_message="No valid subsections after widget failures", error_path=error_path, section_scope=section_scope, subsection_index=subsection_index, item_index=item_index
                )
              ]
            )
            # Return with error - use minimal section_json as payload since shorthand cannot be generated
            return StructuredSection(section_number=section_index, payload=section_json, validation_errors=validation_errors, db_section_id=created_section.section_id)

        # NOTE: We do NOT update section.content here. The content column retains ALL widgets (even failed ones)
        # because we want the DB records to exist for future regeneration (e.g., when free users become pro).
        # Only the shorthand will reflect the current state (with removals).

        # Record removed widgets if any
        if removed_widget_refs:
          session_factory = get_session_factory()
          if session_factory is not None:
            try:
              from app.schema.lessons import Section

              async with session_factory() as session:
                section_row = await session.get(Section, created_section.section_id)
                if section_row is not None:
                  existing_csv = str(section_row.removed_widgets_csv or "").strip()
                  added_csv = ",".join(removed_widget_refs)
                  section_row.removed_widgets_csv = f"{existing_csv},{added_csv}".strip(",") if existing_csv else added_csv
                  session.add(section_row)
                  await session.commit()
                  logger.info("Recorded %d removed widgets for section %s: %s", len(removed_widget_refs), section_index, added_csv)
                else:
                  logger.warning("Could not find section %s to record removed widgets", created_section.section_id)
            except Exception as exc:  # noqa: BLE001
              logger.error("Failed to record removed widgets for section %s: %s", section_index, exc, exc_info=True)
              # Non-fatal - continue with shorthand generation

        # NOW build and save shorthand - this is the final step after all decisions are made.
        # Generate fresh JSON from the modified section_struct (with widget removals for failed jobs).
        # This shorthand reflects only what's currently ready/available for the UI.
        if removed_widget_refs:
          logger.info("Generating shorthand for section %s with %d widget(s) removed: %s", section_index, len(removed_widget_refs), ", ".join(removed_widget_refs))
        else:
          logger.info("Generating shorthand for section %s with all widgets included", section_index)

        try:
          shorthand_section_json = _prune_none_values(msgspec.to_builtins(section_struct)) if section_struct is not None else section_json
          shorthand_content = _build_shorthand_content(section_struct=section_struct, section_json=shorthand_section_json, section_number=section_index, logger=logger)
          await repo.update_section_shorthand(created_section.section_id, shorthand_content)
          logger.info("Successfully generated and saved shorthand for section %s using Section.output() method", section_index)
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
