"""Hydrate a success graph SQL bundle into a target database with idempotent remapping.

How/Why:
- Hydrate preserves source timestamps as authoritative values across reruns.
- Integer primary keys are remapped to target autoincrement ids while preserving deep links.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


def _normalize_async_dsn(raw_dsn: str) -> str:
  """Normalize DSNs so scripts consistently use asyncpg."""
  dsn = raw_dsn.strip()
  if dsn.startswith("postgresql+asyncpg://"):
    return dsn
  if dsn.startswith("postgresql://"):
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
  if dsn.startswith("postgres://"):
    return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
  return dsn


def _safe_int(value: Any) -> int | None:
  """Convert a value to int when possible."""
  if value is None:
    return None
  try:
    return int(value)
  except (TypeError, ValueError):
    return None


def _rewrite_json_links(value: Any, *, section_id_map: dict[int, int], illustration_id_map: dict[int, int], coach_audio_id_map: dict[int, int]) -> Any:
  """Rewrite known deep-link keys that reference remapped integer ids."""
  if isinstance(value, list):
    return [_rewrite_json_links(item, section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map) for item in value]
  if not isinstance(value, dict):
    return value

  rewritten: dict[str, Any] = {}
  for key, raw in value.items():
    if key == "section_id":
      source = _safe_int(raw)
      if source is not None and source in section_id_map:
        rewritten[key] = section_id_map[source]
      else:
        rewritten[key] = raw
      continue
    if key == "illustration_id":
      source = _safe_int(raw)
      if source is not None and source in illustration_id_map:
        rewritten[key] = illustration_id_map[source]
      else:
        rewritten[key] = raw
      continue
    if key == "audio_ids" and isinstance(raw, list):
      remapped: list[Any] = []
      for item in raw:
        source = _safe_int(item)
        if source is not None and source in coach_audio_id_map:
          remapped.append(coach_audio_id_map[source])
        else:
          remapped.append(item)
      rewritten[key] = remapped
      continue
    rewritten[key] = _rewrite_json_links(raw, section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map)
  return rewritten


def _sha256_file(path: Path) -> str:
  """Compute sha256 for sidecar integrity checks."""
  import hashlib

  hasher = hashlib.sha256()
  with path.open("rb") as handle:
    while True:
      chunk = handle.read(1024 * 1024)
      if not chunk:
        break
      hasher.update(chunk)
  return hasher.hexdigest()


def _load_binary(*, sidecar_dir: Path, relative_path: str | None, expected_sha256: str | None, strict: bool) -> bytes | None:
  """Load a sidecar binary file and verify checksum when provided."""
  if not relative_path:
    return None
  root = sidecar_dir.resolve()
  path = (sidecar_dir / relative_path).resolve()
  if root not in path.parents and path != root:
    message = f"Unsafe sidecar path traversal attempt: {relative_path}"
    if strict:
      raise RuntimeError(message)
    print(f"WARN: {message}")
    return None
  if not path.exists():
    message = f"Missing sidecar file: {path}"
    if strict:
      raise RuntimeError(message)
    print(f"WARN: {message}")
    return None
  if expected_sha256:
    actual = _sha256_file(path)
    if actual != expected_sha256:
      message = f"Checksum mismatch for sidecar file: {path}"
      if strict:
        raise RuntimeError(message)
      print(f"WARN: {message}")
  return path.read_bytes()


async def _execute_sql_file(connection: AsyncConnection, sql_path: Path) -> None:
  """Execute export SQL to load the latest bundle payload into staging."""
  sql_text = sql_path.read_text(encoding="utf-8")
  upper_sql = sql_text.upper()
  # Fail closed if the input bundle contains destructive statements.
  forbidden_tokens = [" DROP TABLE ", " TRUNCATE ", " DELETE FROM ", " ALTER TABLE "]
  for token in forbidden_tokens:
    if token in f" {upper_sql} ":
      raise RuntimeError(f"Unsafe SQL bundle: contains forbidden token `{token.strip()}`.")
  if "IMPORT_SUCCESS_BUNDLE" not in upper_sql:
    raise RuntimeError("Unsafe SQL bundle: expected import_success_bundle payload statements.")
  # Execute statements one-by-one because asyncpg prepared statements do not accept multi-command SQL blobs.
  for statement in sql_text.split(";"):
    trimmed = statement.strip()
    if not trimmed:
      continue
    await connection.execute(text(trimmed))


async def _load_bundle_payload(connection: AsyncConnection) -> dict[str, Any]:
  """Load the newest import bundle payload from staging."""
  result = await connection.execute(
    text(
      """
      SELECT payload_json
      FROM import_success_bundle
      ORDER BY created_at DESC
      LIMIT 1
      """
    )
  )
  payload = result.scalar_one_or_none()
  if payload is None or not isinstance(payload, dict):
    raise RuntimeError("No import payload found in import_success_bundle.")
  return payload


async def _ensure_advisory_lock(connection: AsyncConnection, lock_key: int) -> None:
  """Take an advisory transaction lock for single-writer hydrate safety."""
  await connection.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


async def _upsert_lessons(connection: AsyncConnection, lessons_rows: list[dict[str, Any]]) -> None:
  """Upsert lessons while preserving source created_at."""
  for row in lessons_rows:
    await connection.execute(
      text(
        """
        INSERT INTO lessons (
          lesson_id, user_id, topic, title, created_at, schema_version, prompt_version,
          provider_a, model_a, provider_b, model_b, lesson_plan, status, latency_ms,
          idempotency_key, tags, is_archived
        ) VALUES (
          :lesson_id, :user_id, :topic, :title, :created_at, :schema_version, :prompt_version,
          :provider_a, :model_a, :provider_b, :model_b, CAST(:lesson_plan AS jsonb), :status, :latency_ms,
          :idempotency_key, :tags, :is_archived
        )
        ON CONFLICT (lesson_id) DO UPDATE SET
          user_id = EXCLUDED.user_id,
          topic = EXCLUDED.topic,
          title = EXCLUDED.title,
          created_at = EXCLUDED.created_at,
          schema_version = EXCLUDED.schema_version,
          prompt_version = EXCLUDED.prompt_version,
          provider_a = EXCLUDED.provider_a,
          model_a = EXCLUDED.model_a,
          provider_b = EXCLUDED.provider_b,
          model_b = EXCLUDED.model_b,
          lesson_plan = EXCLUDED.lesson_plan,
          status = EXCLUDED.status,
          latency_ms = EXCLUDED.latency_ms,
          idempotency_key = EXCLUDED.idempotency_key,
          tags = EXCLUDED.tags,
          is_archived = EXCLUDED.is_archived
        """
      ),
      {
        "lesson_id": row["lesson_id"],
        "user_id": row.get("user_id"),
        "topic": row["topic"],
        "title": row["title"],
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
        "prompt_version": row["prompt_version"],
        "provider_a": row["provider_a"],
        "model_a": row["model_a"],
        "provider_b": row["provider_b"],
        "model_b": row["model_b"],
        "lesson_plan": json.dumps(row.get("lesson_plan"), ensure_ascii=True),
        "status": row["status"],
        "latency_ms": row["latency_ms"],
        "idempotency_key": row.get("idempotency_key"),
        "tags": row.get("tags"),
        "is_archived": bool(row.get("is_archived", False)),
      },
    )


async def _upsert_sections(connection: AsyncConnection, sections_rows: list[dict[str, Any]]) -> dict[int, int]:
  """Upsert sections by logical key and return source->target id map."""
  mapping: dict[int, int] = {}
  for row in sections_rows:
    source_section_id = int(row["section_id"])
    existing = await connection.execute(text("SELECT section_id FROM sections WHERE lesson_id = :lesson_id AND order_index = :order_index LIMIT 1"), {"lesson_id": row["lesson_id"], "order_index": row["order_index"]})
    existing_section_id = existing.scalar_one_or_none()
    if existing_section_id is None:
      inserted = await connection.execute(
        text(
          """
          INSERT INTO sections (lesson_id, title, order_index, status, content, content_shorthand)
          VALUES (:lesson_id, :title, :order_index, :status, CAST(:content AS jsonb), CAST(:content_shorthand AS jsonb))
          RETURNING section_id
          """
        ),
        {
          "lesson_id": row["lesson_id"],
          "title": row["title"],
          "order_index": row["order_index"],
          "status": row["status"],
          "content": json.dumps(row.get("content"), ensure_ascii=True),
          "content_shorthand": json.dumps(row.get("content_shorthand"), ensure_ascii=True),
        },
      )
      target_section_id = int(inserted.scalar_one())
      mapping[source_section_id] = target_section_id
      continue
    target_section_id = int(existing_section_id)
    await connection.execute(
      text(
        """
        UPDATE sections
        SET
          title = :title,
          status = :status,
          content = CAST(:content AS jsonb),
          content_shorthand = CAST(:content_shorthand AS jsonb)
        WHERE section_id = :section_id
        """
      ),
      {"section_id": target_section_id, "title": row["title"], "status": row["status"], "content": json.dumps(row.get("content"), ensure_ascii=True), "content_shorthand": json.dumps(row.get("content_shorthand"), ensure_ascii=True)},
    )
    mapping[source_section_id] = target_section_id
  return mapping


async def _upsert_section_errors(connection: AsyncConnection, section_error_rows: list[dict[str, Any]], *, section_id_map: dict[int, int]) -> None:
  """Insert section error rows idempotently based on logical uniqueness."""
  for row in section_error_rows:
    source_section_id = int(row["section_id"])
    target_section_id = section_id_map.get(source_section_id)
    if target_section_id is None:
      continue
    exists = await connection.execute(
      text(
        """
        SELECT 1
        FROM section_errors
        WHERE section_id = :section_id
          AND error_index = :error_index
          AND error_message = :error_message
          AND COALESCE(error_path, '') = COALESCE(:error_path, '')
          AND COALESCE(section_scope, '') = COALESCE(:section_scope, '')
          AND COALESCE(subsection_index, -1) = COALESCE(:subsection_index, -1)
          AND COALESCE(item_index, -1) = COALESCE(:item_index, -1)
        LIMIT 1
        """
      ),
      {
        "section_id": target_section_id,
        "error_index": row["error_index"],
        "error_message": row["error_message"],
        "error_path": row.get("error_path"),
        "section_scope": row.get("section_scope"),
        "subsection_index": row.get("subsection_index"),
        "item_index": row.get("item_index"),
      },
    )
    if exists.scalar_one_or_none() is not None:
      continue
    await connection.execute(
      text(
        """
        INSERT INTO section_errors (
          section_id, error_index, error_message, error_path, section_scope, subsection_index, item_index
        ) VALUES (
          :section_id, :error_index, :error_message, :error_path, :section_scope, :subsection_index, :item_index
        )
        """
      ),
      {
        "section_id": target_section_id,
        "error_index": row["error_index"],
        "error_message": row["error_message"],
        "error_path": row.get("error_path"),
        "section_scope": row.get("section_scope"),
        "subsection_index": row.get("subsection_index"),
        "item_index": row.get("item_index"),
      },
    )


async def _upsert_subjective_widgets(connection: AsyncConnection, widget_rows: list[dict[str, Any]], *, section_id_map: dict[int, int]) -> None:
  """Upsert subjective input widgets while preserving created_at."""
  for row in widget_rows:
    source_section_id = int(row["section_id"])
    target_section_id = section_id_map.get(source_section_id)
    if target_section_id is None:
      continue
    existing = await connection.execute(
      text(
        """
        SELECT id
        FROM subjective_input_widgets
        WHERE section_id = :section_id
          AND widget_type = :widget_type
          AND ai_prompt = :ai_prompt
          AND COALESCE(wordlist, '') = COALESCE(:wordlist, '')
        LIMIT 1
        """
      ),
      {"section_id": target_section_id, "widget_type": row["widget_type"], "ai_prompt": row["ai_prompt"], "wordlist": row.get("wordlist")},
    )
    existing_id = existing.scalar_one_or_none()
    if existing_id is None:
      await connection.execute(
        text(
          """
          INSERT INTO subjective_input_widgets (
            section_id, widget_type, ai_prompt, wordlist, created_at
          ) VALUES (
            :section_id, :widget_type, :ai_prompt, :wordlist, :created_at
          )
          """
        ),
        {"section_id": target_section_id, "widget_type": row["widget_type"], "ai_prompt": row["ai_prompt"], "wordlist": row.get("wordlist"), "created_at": row["created_at"]},
      )
      continue
    await connection.execute(
      text(
        """
        UPDATE subjective_input_widgets
        SET
          widget_type = :widget_type,
          ai_prompt = :ai_prompt,
          wordlist = :wordlist,
          created_at = :created_at
        WHERE id = :id
        """
      ),
      {"id": existing_id, "widget_type": row["widget_type"], "ai_prompt": row["ai_prompt"], "wordlist": row.get("wordlist"), "created_at": row["created_at"]},
    )


async def _upsert_illustrations(connection: AsyncConnection, illustration_rows: list[dict[str, Any]], *, sidecar_dir: Path, strict: bool) -> dict[int, int]:
  """Upsert illustrations with timestamp preservation and source->target id map."""
  mapping: dict[int, int] = {}
  local_storage_root = Path("storage_data")

  for row in illustration_rows:
    source_id = int(row["id"])
    existing = await connection.execute(
      text(
        """
        SELECT id
        FROM illustrations
        WHERE storage_bucket = :storage_bucket
          AND storage_object_name = :storage_object_name
        LIMIT 1
        """
      ),
      {"storage_bucket": row["storage_bucket"], "storage_object_name": row["storage_object_name"]},
    )
    existing_id = existing.scalar_one_or_none()
    if existing_id is None:
      inserted = await connection.execute(
        text(
          """
          INSERT INTO illustrations (
            storage_bucket, storage_object_name, mime_type, caption, ai_prompt, keywords,
            status, is_archived, regenerate, created_at, updated_at
          ) VALUES (
            :storage_bucket, :storage_object_name, :mime_type, :caption, :ai_prompt, CAST(:keywords AS jsonb),
            :status, :is_archived, :regenerate, :created_at, :updated_at
          )
          RETURNING id
          """
        ),
        {
          "storage_bucket": row["storage_bucket"],
          "storage_object_name": row["storage_object_name"],
          "mime_type": row["mime_type"],
          "caption": row["caption"],
          "ai_prompt": row["ai_prompt"],
          "keywords": json.dumps(row.get("keywords"), ensure_ascii=True),
          "status": row["status"],
          "is_archived": bool(row.get("is_archived", False)),
          "regenerate": bool(row.get("regenerate", False)),
          "created_at": row["created_at"],
          "updated_at": row["updated_at"],
        },
      )
      target_id = int(inserted.scalar_one())
    else:
      target_id = int(existing_id)
      await connection.execute(
        text(
          """
          UPDATE illustrations
          SET
            mime_type = :mime_type,
            caption = :caption,
            ai_prompt = :ai_prompt,
            keywords = CAST(:keywords AS jsonb),
            status = :status,
            is_archived = :is_archived,
            regenerate = :regenerate,
            created_at = :created_at,
            updated_at = :updated_at
          WHERE id = :id
          """
        ),
        {
          "id": target_id,
          "mime_type": row["mime_type"],
          "caption": row["caption"],
          "ai_prompt": row["ai_prompt"],
          "keywords": json.dumps(row.get("keywords"), ensure_ascii=True),
          "status": row["status"],
          "is_archived": bool(row.get("is_archived", False)),
          "regenerate": bool(row.get("regenerate", False)),
          "created_at": row["created_at"],
          "updated_at": row["updated_at"],
        },
      )
    mapping[source_id] = target_id

    # Best-effort local object hydration for environments using local storage_data.
    object_ref = row.get("object_ref")
    object_sha = row.get("object_sha256")
    payload = _load_binary(sidecar_dir=sidecar_dir, relative_path=object_ref, expected_sha256=object_sha, strict=strict)
    if payload is None:
      continue
    target_path = local_storage_root / str(row["storage_bucket"]) / str(row["storage_object_name"])
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(payload)

  return mapping


async def _upsert_section_illustrations(connection: AsyncConnection, section_illustration_rows: list[dict[str, Any]], *, section_id_map: dict[int, int], illustration_id_map: dict[int, int]) -> None:
  """Upsert section->illustration links while preserving created_at."""
  for row in section_illustration_rows:
    source_section_id = int(row["section_id"])
    source_illustration_id = int(row["illustration_id"])
    target_section_id = section_id_map.get(source_section_id)
    target_illustration_id = illustration_id_map.get(source_illustration_id)
    if target_section_id is None or target_illustration_id is None:
      continue
    existing = await connection.execute(text("SELECT id FROM section_illustrations WHERE section_id = :section_id AND illustration_id = :illustration_id LIMIT 1"), {"section_id": target_section_id, "illustration_id": target_illustration_id})
    existing_id = existing.scalar_one_or_none()
    if existing_id is None:
      await connection.execute(
        text(
          """
          INSERT INTO section_illustrations (section_id, illustration_id, created_at)
          VALUES (:section_id, :illustration_id, :created_at)
          """
        ),
        {"section_id": target_section_id, "illustration_id": target_illustration_id, "created_at": row["created_at"]},
      )
      continue
    await connection.execute(text("UPDATE section_illustrations SET created_at = :created_at WHERE id = :id"), {"id": existing_id, "created_at": row["created_at"]})


async def _upsert_fenster_widgets(connection: AsyncConnection, fenster_rows: list[dict[str, Any]], *, sidecar_dir: Path, strict: bool) -> None:
  """Upsert fenster widgets while preserving created_at and binary payload."""
  for row in fenster_rows:
    content_ref = row.get("content_ref")
    content_bytes = _load_binary(sidecar_dir=sidecar_dir, relative_path=content_ref, expected_sha256=row.get("content_sha256"), strict=strict)
    # Never overwrite existing content with NULL/empty payload due to missing sidecar artifacts.
    if content_ref and content_bytes is None:
      print(f"WARN: Skipping fenster upsert for missing content sidecar. fenster_id={row['fenster_id']}")
      continue
    await connection.execute(
      text(
        """
        INSERT INTO fenster_widgets (fenster_id, type, content, url, created_at)
        VALUES (:fenster_id::uuid, :type, :content, :url, :created_at)
        ON CONFLICT (fenster_id) DO UPDATE SET
          type = EXCLUDED.type,
          content = EXCLUDED.content,
          url = EXCLUDED.url,
          created_at = EXCLUDED.created_at
        """
      ),
      {"fenster_id": row["fenster_id"], "type": row["type"], "content": content_bytes, "url": row.get("url"), "created_at": row["created_at"]},
    )


async def _upsert_coach_audios(connection: AsyncConnection, coach_rows: list[dict[str, Any]], *, sidecar_dir: Path, strict: bool) -> dict[int, int]:
  """Upsert coach audio rows while preserving created_at and mapping ids."""
  mapping: dict[int, int] = {}
  for row in coach_rows:
    source_id = int(row["id"])
    audio_ref = row.get("audio_data_ref")
    audio_bytes = _load_binary(sidecar_dir=sidecar_dir, relative_path=audio_ref, expected_sha256=row.get("audio_data_sha256"), strict=strict)
    # Never overwrite existing audio bytes due to missing sidecar artifacts.
    if audio_ref and audio_bytes is None:
      print(f"WARN: Skipping coach audio upsert for missing sidecar. source_id={source_id}")
      continue
    if audio_bytes is None:
      audio_bytes = b""
    existing = await connection.execute(
      text(
        """
        SELECT id
        FROM coach_audios
        WHERE job_id = :job_id
          AND section_number = :section_number
          AND subsection_index = :subsection_index
        LIMIT 1
        """
      ),
      {"job_id": row["job_id"], "section_number": row["section_number"], "subsection_index": row["subsection_index"]},
    )
    existing_id = existing.scalar_one_or_none()
    if existing_id is None:
      inserted = await connection.execute(
        text(
          """
          INSERT INTO coach_audios (
            job_id, section_number, subsection_index, text_content, audio_data, created_at
          ) VALUES (
            :job_id, :section_number, :subsection_index, :text_content, :audio_data, :created_at
          )
          RETURNING id
          """
        ),
        {"job_id": row["job_id"], "section_number": row["section_number"], "subsection_index": row["subsection_index"], "text_content": row.get("text_content"), "audio_data": audio_bytes, "created_at": row["created_at"]},
      )
      target_id = int(inserted.scalar_one())
      mapping[source_id] = target_id
      continue
    target_id = int(existing_id)
    await connection.execute(
      text(
        """
        UPDATE coach_audios
        SET
          text_content = :text_content,
          audio_data = :audio_data,
          created_at = :created_at
        WHERE id = :id
        """
      ),
      {"id": target_id, "text_content": row.get("text_content"), "audio_data": audio_bytes, "created_at": row["created_at"]},
    )
    mapping[source_id] = target_id
  return mapping


async def _refresh_section_content_links(connection: AsyncConnection, section_rows: list[dict[str, Any]], *, section_id_map: dict[int, int], illustration_id_map: dict[int, int], coach_audio_id_map: dict[int, int]) -> None:
  """Rewrite remapped links inside section JSON payloads."""
  for row in section_rows:
    source_section_id = int(row["section_id"])
    target_section_id = section_id_map.get(source_section_id)
    if target_section_id is None:
      continue
    content = _rewrite_json_links(row.get("content"), section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map)
    shorthand = _rewrite_json_links(row.get("content_shorthand"), section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map)
    await connection.execute(
      text(
        """
        UPDATE sections
        SET
          content = CAST(:content AS jsonb),
          content_shorthand = CAST(:content_shorthand AS jsonb)
        WHERE section_id = :section_id
        """
      ),
      {"section_id": target_section_id, "content": json.dumps(content, ensure_ascii=True), "content_shorthand": json.dumps(shorthand, ensure_ascii=True)},
    )


async def _upsert_jobs(connection: AsyncConnection, jobs_rows: list[dict[str, Any]], *, section_id_map: dict[int, int], illustration_id_map: dict[int, int], coach_audio_id_map: dict[int, int]) -> None:
  """Upsert jobs while preserving created_at/updated_at/completed_at exactly."""
  for row in jobs_rows:
    remapped_result_json = _rewrite_json_links(row.get("result_json"), section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map)
    remapped_request = _rewrite_json_links(row.get("request"), section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map)
    source_section_id = _safe_int(row.get("section_id"))
    target_section_id = section_id_map.get(source_section_id, source_section_id) if source_section_id is not None else None
    await connection.execute(
      text(
        """
        INSERT INTO jobs (
          job_id, user_id, job_kind, request, status, parent_job_id, lesson_id, section_id,
          target_agent, phase, subphase, expected_sections, completed_sections, completed_section_indexes,
          current_section_index, current_section_status, current_section_retry_count, current_section_title,
          retry_count, max_retries, retry_sections, retry_agents, retry_parent_job_id, total_steps,
          completed_steps, progress, logs, result_json, artifacts, validation, cost,
          created_at, updated_at, completed_at, ttl, idempotency_key
        ) VALUES (
          :job_id, :user_id, :job_kind, CAST(:request AS jsonb), :status, :parent_job_id, :lesson_id, :section_id,
          :target_agent, :phase, :subphase, :expected_sections, :completed_sections, CAST(:completed_section_indexes AS jsonb),
          :current_section_index, :current_section_status, :current_section_retry_count, :current_section_title,
          :retry_count, :max_retries, CAST(:retry_sections AS jsonb), CAST(:retry_agents AS jsonb), :retry_parent_job_id, :total_steps,
          :completed_steps, :progress, CAST(:logs AS jsonb), CAST(:result_json AS jsonb), CAST(:artifacts AS jsonb), CAST(:validation AS jsonb), CAST(:cost AS jsonb),
          :created_at, :updated_at, :completed_at, :ttl, :idempotency_key
        )
        ON CONFLICT (job_id) DO UPDATE SET
          user_id = EXCLUDED.user_id,
          job_kind = EXCLUDED.job_kind,
          request = EXCLUDED.request,
          status = EXCLUDED.status,
          parent_job_id = EXCLUDED.parent_job_id,
          lesson_id = EXCLUDED.lesson_id,
          section_id = EXCLUDED.section_id,
          target_agent = EXCLUDED.target_agent,
          phase = EXCLUDED.phase,
          subphase = EXCLUDED.subphase,
          expected_sections = EXCLUDED.expected_sections,
          completed_sections = EXCLUDED.completed_sections,
          completed_section_indexes = EXCLUDED.completed_section_indexes,
          current_section_index = EXCLUDED.current_section_index,
          current_section_status = EXCLUDED.current_section_status,
          current_section_retry_count = EXCLUDED.current_section_retry_count,
          current_section_title = EXCLUDED.current_section_title,
          retry_count = EXCLUDED.retry_count,
          max_retries = EXCLUDED.max_retries,
          retry_sections = EXCLUDED.retry_sections,
          retry_agents = EXCLUDED.retry_agents,
          retry_parent_job_id = EXCLUDED.retry_parent_job_id,
          total_steps = EXCLUDED.total_steps,
          completed_steps = EXCLUDED.completed_steps,
          progress = EXCLUDED.progress,
          logs = EXCLUDED.logs,
          result_json = EXCLUDED.result_json,
          artifacts = EXCLUDED.artifacts,
          validation = EXCLUDED.validation,
          cost = EXCLUDED.cost,
          created_at = EXCLUDED.created_at,
          updated_at = EXCLUDED.updated_at,
          completed_at = EXCLUDED.completed_at,
          ttl = EXCLUDED.ttl,
          idempotency_key = EXCLUDED.idempotency_key
        """
      ),
      {
        "job_id": row["job_id"],
        "user_id": row.get("user_id"),
        "job_kind": row["job_kind"],
        "request": json.dumps(remapped_request, ensure_ascii=True),
        "status": row["status"],
        "parent_job_id": row.get("parent_job_id"),
        "lesson_id": row.get("lesson_id"),
        "section_id": target_section_id,
        "target_agent": row.get("target_agent"),
        "phase": row.get("phase"),
        "subphase": row.get("subphase"),
        "expected_sections": row.get("expected_sections"),
        "completed_sections": row.get("completed_sections"),
        "completed_section_indexes": json.dumps(row.get("completed_section_indexes"), ensure_ascii=True),
        "current_section_index": row.get("current_section_index"),
        "current_section_status": row.get("current_section_status"),
        "current_section_retry_count": row.get("current_section_retry_count"),
        "current_section_title": row.get("current_section_title"),
        "retry_count": row.get("retry_count"),
        "max_retries": row.get("max_retries"),
        "retry_sections": json.dumps(row.get("retry_sections"), ensure_ascii=True),
        "retry_agents": json.dumps(row.get("retry_agents"), ensure_ascii=True),
        "retry_parent_job_id": row.get("retry_parent_job_id"),
        "total_steps": row.get("total_steps"),
        "completed_steps": row.get("completed_steps"),
        "progress": row.get("progress"),
        "logs": json.dumps(row.get("logs"), ensure_ascii=True),
        "result_json": json.dumps(remapped_result_json, ensure_ascii=True),
        "artifacts": json.dumps(row.get("artifacts"), ensure_ascii=True),
        "validation": json.dumps(row.get("validation"), ensure_ascii=True),
        "cost": json.dumps(row.get("cost"), ensure_ascii=True),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row.get("completed_at"),
        "ttl": row.get("ttl"),
        "idempotency_key": row.get("idempotency_key"),
      },
    )


async def _verify_timestamp_preservation(
  connection: AsyncConnection, payload_data: dict[str, Any], *, section_id_map: dict[int, int], illustration_id_map: dict[int, int], coach_audio_id_map: dict[int, int], include_illustrations: bool, include_audios: bool, include_fensters: bool
) -> None:
  """Verify source timestamps are preserved exactly on target rows."""
  # Verify jobs timestamps.
  for row in payload_data.get("jobs", []):
    result = await connection.execute(text("SELECT created_at, updated_at, completed_at FROM jobs WHERE job_id = :job_id"), {"job_id": row["job_id"]})
    target = result.mappings().one_or_none()
    if target is None:
      raise RuntimeError(f"Timestamp verify failed: missing jobs.job_id={row['job_id']}")
    if str(target["created_at"]) != str(row["created_at"]):
      raise RuntimeError(f"Timestamp verify failed for jobs.created_at job_id={row['job_id']}")
    if str(target["updated_at"]) != str(row["updated_at"]):
      raise RuntimeError(f"Timestamp verify failed for jobs.updated_at job_id={row['job_id']}")
    source_completed = row.get("completed_at")
    target_completed = target.get("completed_at")
    if str(target_completed) != str(source_completed):
      raise RuntimeError(f"Timestamp verify failed for jobs.completed_at job_id={row['job_id']}")

  # Verify lessons created_at.
  for row in payload_data.get("lessons", []):
    result = await connection.execute(text("SELECT created_at FROM lessons WHERE lesson_id = :lesson_id"), {"lesson_id": row["lesson_id"]})
    target = result.scalar_one_or_none()
    if target is None:
      raise RuntimeError(f"Timestamp verify failed: missing lessons.lesson_id={row['lesson_id']}")
    if str(target) != str(row["created_at"]):
      raise RuntimeError(f"Timestamp verify failed for lessons.created_at lesson_id={row['lesson_id']}")

  # Verify illustration timestamps using mapped ids.
  if include_illustrations:
    for row in payload_data.get("illustrations", []):
      source_id = int(row["id"])
      target_id = illustration_id_map.get(source_id)
      if target_id is None:
        raise RuntimeError(f"Timestamp verify failed: missing illustration id map for source_id={source_id}")
      result = await connection.execute(text("SELECT created_at, updated_at FROM illustrations WHERE id = :id"), {"id": target_id})
      target = result.mappings().one_or_none()
      if target is None:
        raise RuntimeError(f"Timestamp verify failed: missing illustrations.id={target_id}")
      if str(target["created_at"]) != str(row["created_at"]):
        raise RuntimeError(f"Timestamp verify failed for illustrations.created_at source_id={source_id}")
      if str(target["updated_at"]) != str(row["updated_at"]):
        raise RuntimeError(f"Timestamp verify failed for illustrations.updated_at source_id={source_id}")

  # Verify section_illustrations created_at.
  if include_illustrations:
    for row in payload_data.get("section_illustrations", []):
      source_section_id = int(row["section_id"])
      source_illustration_id = int(row["illustration_id"])
      target_section_id = section_id_map.get(source_section_id)
      target_illustration_id = illustration_id_map.get(source_illustration_id)
      if target_section_id is None or target_illustration_id is None:
        continue
      result = await connection.execute(text("SELECT created_at FROM section_illustrations WHERE section_id = :section_id AND illustration_id = :illustration_id LIMIT 1"), {"section_id": target_section_id, "illustration_id": target_illustration_id})
      target = result.scalar_one_or_none()
      if target is None:
        raise RuntimeError(f"Timestamp verify failed: missing section_illustration ({target_section_id}, {target_illustration_id})")
      if str(target) != str(row["created_at"]):
        raise RuntimeError("Timestamp verify failed for section_illustrations.created_at")

  # Verify fenster created_at.
  if include_fensters:
    for row in payload_data.get("fenster_widgets", []):
      result = await connection.execute(text("SELECT created_at FROM fenster_widgets WHERE fenster_id = :fenster_id::uuid"), {"fenster_id": row["fenster_id"]})
      target = result.scalar_one_or_none()
      if target is None:
        raise RuntimeError(f"Timestamp verify failed: missing fenster_widgets.fenster_id={row['fenster_id']}")
      if str(target) != str(row["created_at"]):
        raise RuntimeError(f"Timestamp verify failed for fenster_widgets.created_at fenster_id={row['fenster_id']}")

  # Verify coach_audios created_at.
  if include_audios:
    for row in payload_data.get("coach_audios", []):
      source_id = int(row["id"])
      target_id = coach_audio_id_map.get(source_id)
      if target_id is None:
        raise RuntimeError(f"Timestamp verify failed: missing coach audio id map for source_id={source_id}")
      result = await connection.execute(text("SELECT created_at FROM coach_audios WHERE id = :id"), {"id": target_id})
      target = result.scalar_one_or_none()
      if target is None:
        raise RuntimeError(f"Timestamp verify failed: missing coach_audios.id={target_id}")
      if str(target) != str(row["created_at"]):
        raise RuntimeError(f"Timestamp verify failed for coach_audios.created_at source_id={source_id}")

  # Verify subjective_input_widgets created_at by logical key.
  for row in payload_data.get("subjective_input_widgets", []):
    source_section_id = int(row["section_id"])
    target_section_id = section_id_map.get(source_section_id)
    if target_section_id is None:
      continue
    result = await connection.execute(
      text(
        """
        SELECT created_at
        FROM subjective_input_widgets
        WHERE section_id = :section_id
          AND widget_type = :widget_type
          AND ai_prompt = :ai_prompt
          AND COALESCE(wordlist, '') = COALESCE(:wordlist, '')
        LIMIT 1
        """
      ),
      {"section_id": target_section_id, "widget_type": row["widget_type"], "ai_prompt": row["ai_prompt"], "wordlist": row.get("wordlist")},
    )
    target = result.scalar_one_or_none()
    if target is None:
      raise RuntimeError("Timestamp verify failed: missing subjective_input_widgets row.")
    if str(target) != str(row["created_at"]):
      raise RuntimeError("Timestamp verify failed for subjective_input_widgets.created_at")


async def _merge_once(connection: AsyncConnection, payload_data: dict[str, Any], *, sidecar_dir: Path, strict: bool, include_illustrations: bool, include_audios: bool, include_fensters: bool) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
  """Run one full merge pass and return remapping dictionaries."""
  lessons_rows = list(payload_data.get("lessons", []))
  sections_rows = list(payload_data.get("sections", []))
  section_error_rows = list(payload_data.get("section_errors", []))
  widget_rows = list(payload_data.get("subjective_input_widgets", []))
  illustration_rows = list(payload_data.get("illustrations", [])) if include_illustrations else []
  section_illustration_rows = list(payload_data.get("section_illustrations", [])) if include_illustrations else []
  fenster_rows = list(payload_data.get("fenster_widgets", [])) if include_fensters else []
  coach_rows = list(payload_data.get("coach_audios", [])) if include_audios else []
  jobs_rows = list(payload_data.get("jobs", []))

  await _upsert_lessons(connection, lessons_rows)
  section_id_map = await _upsert_sections(connection, sections_rows)
  await _upsert_section_errors(connection, section_error_rows, section_id_map=section_id_map)
  await _upsert_subjective_widgets(connection, widget_rows, section_id_map=section_id_map)
  illustration_id_map = await _upsert_illustrations(connection, illustration_rows, sidecar_dir=sidecar_dir, strict=strict)
  await _upsert_section_illustrations(connection, section_illustration_rows, section_id_map=section_id_map, illustration_id_map=illustration_id_map)
  await _upsert_fenster_widgets(connection, fenster_rows, sidecar_dir=sidecar_dir, strict=strict)
  coach_audio_id_map = await _upsert_coach_audios(connection, coach_rows, sidecar_dir=sidecar_dir, strict=strict)
  await _refresh_section_content_links(connection, sections_rows, section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map)
  await _upsert_jobs(connection, jobs_rows, section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map)
  return section_id_map, illustration_id_map, coach_audio_id_map


async def _validate_manifest(*, sidecar_dir: Path, manifest_rows: list[dict[str, Any]], strict: bool) -> None:
  """Verify sidecar manifest files exist and checksums match."""
  for entry in manifest_rows:
    relative_path = str(entry.get("relative_path") or "")
    if not relative_path:
      continue
    path = sidecar_dir / relative_path
    if not path.exists():
      message = f"Missing sidecar manifest file: {path}"
      if strict:
        raise RuntimeError(message)
      print(f"WARN: {message}")
      continue
    expected_sha = entry.get("sha256")
    if not expected_sha:
      continue
    actual_sha = _sha256_file(path)
    if actual_sha != expected_sha:
      message = f"Manifest checksum mismatch for {path}"
      if strict:
        raise RuntimeError(message)
      print(f"WARN: {message}")


async def _run_hydrate(*, dsn: str, in_sql: Path, sidecar_dir: Path, strict: bool, dry_run: bool, advisory_lock_key: int, verify_rerun: bool, include_illustrations: bool = True, include_audios: bool = True, include_fensters: bool = True) -> None:
  """Execute hydrate flow with one transaction and optional rerun verification."""
  if not in_sql.exists():
    raise RuntimeError(f"Input SQL bundle not found: {in_sql}")
  if not sidecar_dir.exists():
    raise RuntimeError(f"Sidecar directory not found: {sidecar_dir}")

  engine = create_async_engine(dsn, future=True)
  try:
    async with engine.begin() as connection:
      await connection.execute(text("SET LOCAL search_path TO public"))
      await _ensure_advisory_lock(connection, advisory_lock_key)
      await _execute_sql_file(connection, in_sql)
      payload = await _load_bundle_payload(connection)
      if payload.get("schema_version") != "success_bundle/v1":
        raise RuntimeError(f"Unsupported bundle schema version: {payload.get('schema_version')}")

      payload_data = dict(payload.get("data") or {})
      manifest_rows = list(payload.get("sidecar_manifest") or [])
      await _validate_manifest(sidecar_dir=sidecar_dir, manifest_rows=manifest_rows, strict=strict)

      section_id_map, illustration_id_map, coach_audio_id_map = await _merge_once(
        connection, payload_data, sidecar_dir=sidecar_dir, strict=strict, include_illustrations=include_illustrations, include_audios=include_audios, include_fensters=include_fensters
      )
      await _verify_timestamp_preservation(
        connection, payload_data, section_id_map=section_id_map, illustration_id_map=illustration_id_map, coach_audio_id_map=coach_audio_id_map, include_illustrations=include_illustrations, include_audios=include_audios, include_fensters=include_fensters
      )

      # Re-run merge once more to verify idempotent replay keeps timestamps unchanged.
      if verify_rerun:
        rerun_section_map, rerun_illustration_map, rerun_coach_map = await _merge_once(
          connection, payload_data, sidecar_dir=sidecar_dir, strict=strict, include_illustrations=include_illustrations, include_audios=include_audios, include_fensters=include_fensters
        )
        await _verify_timestamp_preservation(
          connection,
          payload_data,
          section_id_map=rerun_section_map,
          illustration_id_map=rerun_illustration_map,
          coach_audio_id_map=rerun_coach_map,
          include_illustrations=include_illustrations,
          include_audios=include_audios,
          include_fensters=include_fensters,
        )

      if dry_run:
        raise RuntimeError("DRY_RUN_ROLLBACK")
  except RuntimeError as exc:
    if str(exc) == "DRY_RUN_ROLLBACK":
      print("Dry-run completed: all checks passed; transaction rolled back.")
      return
    raise
  finally:
    await engine.dispose()

  print("Hydrate completed successfully.")
  if verify_rerun:
    print("Idempotency rerun verification passed.")


def main() -> None:
  """CLI entrypoint for success graph hydrate script."""
  parser = argparse.ArgumentParser(description="Hydrate success graph bundle with id remapping and timestamp preservation.")
  parser.add_argument("--dsn", type=str, default=(os.getenv("DYLEN_PG_DSN") or "").strip(), help="Target PostgreSQL DSN.")
  parser.add_argument("--in-sql", type=Path, required=True, help="Path to exported SQL bundle.")
  parser.add_argument("--sidecar-dir", type=Path, required=True, help="Path to exported sidecar asset directory.")
  parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True, help="Fail on missing/corrupt sidecar references.")
  parser.add_argument("--dry-run", action="store_true", help="Run full validation/merge logic and rollback transaction at end.")
  parser.add_argument("--advisory-lock-key", type=int, default=819224151, help="Transaction advisory lock key.")
  parser.add_argument("--verify-rerun", action=argparse.BooleanOptionalAction, default=True, help="Run a second merge pass to verify idempotency/timestamps.")
  parser.add_argument("--include-illustrations", action=argparse.BooleanOptionalAction, default=True, help="Hydrate illustration rows and links.")
  parser.add_argument("--include-audios", action=argparse.BooleanOptionalAction, default=True, help="Hydrate coach audio rows.")
  parser.add_argument("--include-fensters", action=argparse.BooleanOptionalAction, default=True, help="Hydrate fenster rows.")
  args = parser.parse_args()

  if not args.dsn:
    raise RuntimeError("DSN is required. Pass --dsn or set DYLEN_PG_DSN.")
  normalized_dsn = _normalize_async_dsn(args.dsn)
  asyncio.run(
    _run_hydrate(
      dsn=normalized_dsn,
      in_sql=args.in_sql,
      sidecar_dir=args.sidecar_dir,
      strict=bool(args.strict),
      dry_run=bool(args.dry_run),
      advisory_lock_key=int(args.advisory_lock_key),
      verify_rerun=bool(args.verify_rerun),
      include_illustrations=bool(args.include_illustrations),
      include_audios=bool(args.include_audios),
      include_fensters=bool(args.include_fensters),
    )
  )


if __name__ == "__main__":
  try:
    main()
  except Exception as exc:  # noqa: BLE001
    if str(exc) == "DRY_RUN_ROLLBACK":
      print("Dry-run completed: transaction rolled back.")
      sys.exit(0)
    print(f"ERROR: {exc}", file=sys.stderr)
    raise
