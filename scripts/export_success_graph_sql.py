"""Export successful job graph data into a SQL bundle plus binary sidecar assets.

How/Why:
- Export is code-driven (not pg_dump) so we can control filtering, relationships, and idempotent hydrate semantics.
- The bundle captures source timestamps explicitly so hydrate can preserve created_at/updated_at values exactly.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime
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


def _sha256_bytes(payload: bytes) -> str:
  """Return a stable sha256 digest for binary sidecar verification."""
  hasher = hashlib.sha256()
  hasher.update(payload)
  return hasher.hexdigest()


def _sha256_file(path: Path) -> str:
  """Return a stable sha256 digest for on-disk file verification."""
  hasher = hashlib.sha256()
  with path.open("rb") as handle:
    while True:
      chunk = handle.read(1024 * 1024)
      if not chunk:
        break
      hasher.update(chunk)
  return hasher.hexdigest()


def _json_ready(value: Any) -> Any:
  """Convert DB-driver values to JSON-serializable values."""
  if isinstance(value, bytes):
    return base64.b64encode(value).decode("ascii")
  if isinstance(value, uuid.UUID):
    return str(value)
  if isinstance(value, datetime):
    return value.isoformat()
  return value


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
  """Convert a DB row mapping into a JSON-safe dict."""
  return {key: _json_ready(value) for key, value in row.items()}


def _write_sql_bundle(*, bundle_id: str, payload: dict[str, Any], destination: Path) -> None:
  """Write a self-contained SQL file that stores the JSON payload in staging."""
  encoded = base64.b64encode(json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
  sql_text = f"""-- Auto-generated success graph export bundle.
CREATE TABLE IF NOT EXISTS import_success_bundle (
  bundle_id TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload_json JSONB NOT NULL
);

INSERT INTO import_success_bundle (bundle_id, created_at, payload_json)
VALUES (
  '{bundle_id}',
  now(),
  convert_from(decode('{encoded}', 'base64'), 'utf-8')::jsonb
)
ON CONFLICT (bundle_id) DO UPDATE
SET created_at = EXCLUDED.created_at,
    payload_json = EXCLUDED.payload_json;
"""
  destination.parent.mkdir(parents=True, exist_ok=True)
  destination.write_text(sql_text, encoding="utf-8")


async def _fetch_rows(connection: AsyncConnection, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
  """Execute a SQL query and return mapping rows."""
  result = await connection.execute(text(statement), params or {})
  return [dict(row) for row in result.mappings().all()]


async def _collect_export_data(connection: AsyncConnection, *, sidecar_dir: Path, strict: bool, max_rows: int | None, include_illustrations: bool, include_audios: bool, include_fensters: bool) -> dict[str, Any]:
  """Collect successful graph rows and write binary sidecars."""
  # Keep sidecar directories stable so hydrate can load deterministic paths.
  coach_dir = sidecar_dir / "coach_audios"
  fenster_dir = sidecar_dir / "fenster_widgets"
  illustration_dir = sidecar_dir / "illustrations"
  coach_dir.mkdir(parents=True, exist_ok=True)
  fenster_dir.mkdir(parents=True, exist_ok=True)
  illustration_dir.mkdir(parents=True, exist_ok=True)

  # Export successful jobs as the root graph.
  jobs_rows = await _fetch_rows(
    connection,
    """
    SELECT
      job_id, user_id, job_kind, request, status, parent_job_id, lesson_id, section_id,
      target_agent, phase, subphase, expected_sections, completed_sections, completed_section_indexes,
      current_section_index, current_section_status, current_section_retry_count, current_section_title,
      retry_count, max_retries, retry_sections, retry_agents, retry_parent_job_id, total_steps,
      completed_steps, progress, logs, result_json, artifacts, validation, cost,
      created_at, updated_at, completed_at, ttl, idempotency_key
    FROM jobs
    WHERE status = 'done'
    ORDER BY created_at ASC
    """,
  )
  if max_rows is not None:
    jobs_rows = jobs_rows[:max_rows]

  if not jobs_rows:
    return {
      "schema_version": "success_bundle/v1",
      "generated_at": datetime.now(UTC).isoformat(),
      "counts": {"jobs": 0},
      "data": {"jobs": [], "lessons": [], "sections": [], "section_errors": [], "subjective_input_widgets": [], "illustrations": [], "section_illustrations": [], "fenster_widgets": [], "coach_audios": []},
      "sidecar_manifest": [],
    }

  # Resolve lesson ids from explicit column and job result payload.
  lesson_ids: set[str] = set()
  for job in jobs_rows:
    lesson_id = job.get("lesson_id")
    if isinstance(lesson_id, str) and lesson_id.strip():
      lesson_ids.add(lesson_id.strip())
    result_json = job.get("result_json")
    if isinstance(result_json, dict):
      result_lesson_id = result_json.get("lesson_id")
      if isinstance(result_lesson_id, str) and result_lesson_id.strip():
        lesson_ids.add(result_lesson_id.strip())

  lessons_rows: list[dict[str, Any]] = []
  if lesson_ids:
    lessons_rows = await _fetch_rows(
      connection,
      """
      SELECT
        lesson_id, user_id, topic, title, created_at, schema_version, prompt_version,
        provider_a, model_a, provider_b, model_b, lesson_plan, status, latency_ms,
        idempotency_key, tags, is_archived
      FROM lessons
      WHERE lesson_id = ANY(:lesson_ids)
      ORDER BY created_at ASC
      """,
      {"lesson_ids": list(lesson_ids)},
    )

  sections_rows: list[dict[str, Any]] = []
  if lesson_ids:
    sections_rows = await _fetch_rows(
      connection,
      """
      SELECT
        section_id, lesson_id, title, order_index, status, content, content_shorthand
      FROM sections
      WHERE lesson_id = ANY(:lesson_ids)
      ORDER BY lesson_id ASC, order_index ASC
      """,
      {"lesson_ids": list(lesson_ids)},
    )
  section_ids = [int(row["section_id"]) for row in sections_rows]

  section_errors_rows: list[dict[str, Any]] = []
  subjective_widget_rows: list[dict[str, Any]] = []
  section_illustration_rows: list[dict[str, Any]] = []
  if section_ids:
    section_errors_rows = await _fetch_rows(
      connection,
      """
      SELECT
        id, section_id, error_index, error_message, error_path, section_scope, subsection_index, item_index
      FROM section_errors
      WHERE section_id = ANY(:section_ids)
      ORDER BY section_id ASC, error_index ASC
      """,
      {"section_ids": section_ids},
    )
    subjective_widget_rows = await _fetch_rows(
      connection,
      """
      SELECT
        id, section_id, widget_type, ai_prompt, wordlist, created_at
      FROM subjective_input_widgets
      WHERE section_id = ANY(:section_ids)
      ORDER BY section_id ASC, id ASC
      """,
      {"section_ids": section_ids},
    )
    if include_illustrations:
      section_illustration_rows = await _fetch_rows(
        connection,
        """
        SELECT
          id, section_id, illustration_id, created_at
        FROM section_illustrations
        WHERE section_id = ANY(:section_ids)
        ORDER BY section_id ASC, id ASC
        """,
        {"section_ids": section_ids},
      )

  illustration_ids = list({int(row["illustration_id"]) for row in section_illustration_rows}) if include_illustrations else []
  illustration_rows: list[dict[str, Any]] = []
  if include_illustrations and illustration_ids:
    illustration_rows = await _fetch_rows(
      connection,
      """
      SELECT
        id, storage_bucket, storage_object_name, mime_type, caption, ai_prompt, keywords,
        status, is_archived, regenerate, created_at, updated_at
      FROM illustrations
      WHERE id = ANY(:illustration_ids)
      ORDER BY id ASC
      """,
      {"illustration_ids": illustration_ids},
    )

  # Extract fenster ids from successful job result payloads.
  fenster_ids: set[str] = set()
  for job in jobs_rows:
    result_json = job.get("result_json")
    if not isinstance(result_json, dict):
      continue
    fenster_id = result_json.get("fenster_id")
    if isinstance(fenster_id, str):
      try:
        fenster_ids.add(str(uuid.UUID(fenster_id)))
      except ValueError:
        continue

  fenster_rows: list[dict[str, Any]] = []
  if include_fensters and fenster_ids:
    fenster_rows = await _fetch_rows(
      connection,
      """
      SELECT
        fenster_id, type, content, url, created_at
      FROM fenster_widgets
      WHERE fenster_id::text = ANY(:fenster_ids)
      ORDER BY created_at ASC
      """,
      {"fenster_ids": list(fenster_ids)},
    )

  # Export coach rows tied to successful jobs.
  job_ids = [str(row["job_id"]) for row in jobs_rows]
  coach_rows: list[dict[str, Any]] = []
  if include_audios and job_ids:
    coach_rows = await _fetch_rows(
      connection,
      """
      SELECT
        id, job_id, section_number, subsection_index, text_content, audio_data, created_at
      FROM coach_audios
      WHERE job_id = ANY(:job_ids)
      ORDER BY job_id ASC, section_number ASC, subsection_index ASC, id ASC
      """,
      {"job_ids": job_ids},
    )

  sidecar_manifest: list[dict[str, Any]] = []

  # Move coach binary blobs to sidecar files.
  for row in coach_rows:
    source_id = int(row["id"])
    audio_bytes = row.pop("audio_data", None)
    if not isinstance(audio_bytes, (bytes, bytearray)):
      message = f"coach_audios.id={source_id} missing audio_data bytes."
      if strict:
        raise RuntimeError(message)
      print(f"WARN: {message}")
      continue
    relative_path = Path("coach_audios") / f"{source_id}.bin"
    target_path = sidecar_dir / relative_path
    payload = bytes(audio_bytes)
    target_path.write_bytes(payload)
    row["audio_data_ref"] = str(relative_path)
    row["audio_data_sha256"] = _sha256_bytes(payload)
    row["audio_data_size"] = len(payload)
    sidecar_manifest.append({"entity": "coach_audios", "source_id": source_id, "relative_path": str(relative_path), "sha256": row["audio_data_sha256"], "size": len(payload)})

  # Move fenster binary blobs to sidecar files.
  for row in fenster_rows:
    fenster_id = str(row["fenster_id"])
    content_bytes = row.pop("content", None)
    if content_bytes is None:
      row["content_ref"] = None
      row["content_sha256"] = None
      row["content_size"] = 0
      continue
    if not isinstance(content_bytes, (bytes, bytearray)):
      message = f"fenster_widgets.fenster_id={fenster_id} content is not bytes."
      if strict:
        raise RuntimeError(message)
      print(f"WARN: {message}")
      continue
    relative_path = Path("fenster_widgets") / f"{fenster_id}.bin"
    target_path = sidecar_dir / relative_path
    payload = bytes(content_bytes)
    target_path.write_bytes(payload)
    row["content_ref"] = str(relative_path)
    row["content_sha256"] = _sha256_bytes(payload)
    row["content_size"] = len(payload)
    sidecar_manifest.append({"entity": "fenster_widgets", "source_id": fenster_id, "relative_path": str(relative_path), "sha256": row["content_sha256"], "size": len(payload)})

  # Copy illustration object files into sidecar when available.
  local_storage_root = Path("storage_data")
  for row in illustration_rows:
    illustration_id = int(row["id"])
    bucket = str(row["storage_bucket"])
    object_name = str(row["storage_object_name"])
    source_path = local_storage_root / bucket / object_name
    if not source_path.exists():
      message = f"Missing local illustration object for illustrations.id={illustration_id}: {source_path}"
      if strict:
        raise RuntimeError(message)
      print(f"WARN: {message}")
      row["object_ref"] = None
      row["object_sha256"] = None
      row["object_size"] = 0
      continue
    safe_name = object_name.replace("/", "__")
    relative_path = Path("illustrations") / f"{illustration_id}__{safe_name}"
    target_path = sidecar_dir / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    row["object_ref"] = str(relative_path)
    row["object_sha256"] = _sha256_file(target_path)
    row["object_size"] = target_path.stat().st_size
    sidecar_manifest.append({"entity": "illustrations", "source_id": illustration_id, "relative_path": str(relative_path), "sha256": row["object_sha256"], "size": row["object_size"]})

  # Convert rows to JSON-safe structures after binary extraction.
  payload = {
    "schema_version": "success_bundle/v1",
    "generated_at": datetime.now(UTC).isoformat(),
    "counts": {
      "jobs": len(jobs_rows),
      "lessons": len(lessons_rows),
      "sections": len(sections_rows),
      "section_errors": len(section_errors_rows),
      "subjective_input_widgets": len(subjective_widget_rows),
      "illustrations": len(illustration_rows),
      "section_illustrations": len(section_illustration_rows),
      "fenster_widgets": len(fenster_rows),
      "coach_audios": len(coach_rows),
    },
    "data": {
      "jobs": [_row_to_dict(row) for row in jobs_rows],
      "lessons": [_row_to_dict(row) for row in lessons_rows],
      "sections": [_row_to_dict(row) for row in sections_rows],
      "section_errors": [_row_to_dict(row) for row in section_errors_rows],
      "subjective_input_widgets": [_row_to_dict(row) for row in subjective_widget_rows],
      "illustrations": [_row_to_dict(row) for row in illustration_rows],
      "section_illustrations": [_row_to_dict(row) for row in section_illustration_rows],
      "fenster_widgets": [_row_to_dict(row) for row in fenster_rows],
      "coach_audios": [_row_to_dict(row) for row in coach_rows],
    },
    "sidecar_manifest": sidecar_manifest,
  }
  return payload


async def _run_export(*, dsn: str, out_sql: Path, sidecar_dir: Path, strict: bool, max_rows: int | None, include_illustrations: bool = True, include_audios: bool = True, include_fensters: bool = True) -> None:
  """Run export end-to-end using one DB connection."""
  if sidecar_dir.exists():
    # Recreate sidecar deterministically to avoid stale files from previous exports.
    shutil.rmtree(sidecar_dir)
  sidecar_dir.mkdir(parents=True, exist_ok=True)

  engine = create_async_engine(dsn, future=True)
  try:
    async with engine.connect() as connection:
      await connection.execute(text("SET LOCAL search_path TO public"))
      payload = await _collect_export_data(connection, sidecar_dir=sidecar_dir, strict=strict, max_rows=max_rows, include_illustrations=include_illustrations, include_audios=include_audios, include_fensters=include_fensters)
  finally:
    await engine.dispose()

  bundle_id = f"success-bundle-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
  _write_sql_bundle(bundle_id=bundle_id, payload=payload, destination=out_sql)
  manifest_path = sidecar_dir / "manifest.json"
  manifest_path.write_text(json.dumps(payload.get("sidecar_manifest", []), ensure_ascii=True, indent=2), encoding="utf-8")
  print(f"Exported SQL bundle: {out_sql}")
  print(f"Exported sidecar dir: {sidecar_dir}")
  print(f"Counts: {json.dumps(payload.get('counts', {}), ensure_ascii=True)}")


def main() -> None:
  """Parse CLI args and export successful graph bundle."""
  parser = argparse.ArgumentParser(description="Export successful graph data as SQL bundle with sidecar binaries.")
  parser.add_argument("--dsn", type=str, default=(os.getenv("DYLEN_PG_DSN") or "").strip(), help="Source PostgreSQL DSN.")
  parser.add_argument("--out-sql", type=Path, required=True, help="Output SQL bundle file path.")
  parser.add_argument("--sidecar-dir", type=Path, required=True, help="Output sidecar asset directory path.")
  parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True, help="Fail on missing binary links.")
  parser.add_argument("--max-rows", type=int, default=None, help="Optional cap on successful root jobs.")
  parser.add_argument("--include-illustrations", action=argparse.BooleanOptionalAction, default=True, help="Include illustration rows and sidecar files.")
  parser.add_argument("--include-audios", action=argparse.BooleanOptionalAction, default=True, help="Include coach audio rows and sidecar files.")
  parser.add_argument("--include-fensters", action=argparse.BooleanOptionalAction, default=True, help="Include fenster rows and sidecar files.")
  args = parser.parse_args()

  if not args.dsn:
    raise RuntimeError("DSN is required. Pass --dsn or set DYLEN_PG_DSN.")
  if args.max_rows is not None and args.max_rows <= 0:
    raise RuntimeError("--max-rows must be a positive integer when provided.")

  normalized_dsn = _normalize_async_dsn(args.dsn)
  asyncio.run(
    _run_export(
      dsn=normalized_dsn,
      out_sql=args.out_sql,
      sidecar_dir=args.sidecar_dir,
      strict=bool(args.strict),
      max_rows=args.max_rows,
      include_illustrations=bool(args.include_illustrations),
      include_audios=bool(args.include_audios),
      include_fensters=bool(args.include_fensters),
    )
  )


if __name__ == "__main__":
  try:
    main()
  except Exception as exc:  # noqa: BLE001
    print(f"ERROR: {exc}", file=sys.stderr)
    raise
