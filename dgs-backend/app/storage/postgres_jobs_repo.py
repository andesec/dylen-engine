"""Postgres-backed repository for background jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import time
import random
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.jobs.guardrails import maybe_truncate_artifacts, maybe_truncate_result_json, sanitize_logs
from app.jobs.models import JobRecord, JobStatus
from app.storage.jobs_repo import JobsRepository

logger = logging.getLogger(__name__)

_KNOWN_TABLES: set[str] = set()


def _now_iso() -> str:
    """Return a UTC timestamp string for job updates."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class _PostgresConfig:
    """Shared configuration for Postgres repositories."""

    dsn: str
    connect_timeout: int


def _ensure_jobs_table(config: _PostgresConfig, table_name: str) -> None:
    """Create the jobs table and indexes if they are missing."""
    
    # Avoid repeated DDL within the same process.
    if table_name in _KNOWN_TABLES:
        return
    
    
    # Define the base schema for job storage.
    
    statement = sql.SQL(
        """
        CREATE TABLE IF NOT EXISTS {table} (
          job_id TEXT PRIMARY KEY,
          request JSONB NOT NULL,
          status TEXT NOT NULL,
          phase TEXT NOT NULL,
          subphase TEXT,
          expected_sections INTEGER,
          completed_sections INTEGER,
          completed_section_indexes JSONB,
          current_section_index INTEGER,
          current_section_status TEXT,
          current_section_retry_count INTEGER,
          current_section_title TEXT,
          retry_count INTEGER,
          max_retries INTEGER,
          retry_sections JSONB,
          retry_agents JSONB,
          retry_parent_job_id TEXT,
          total_steps INTEGER,
          completed_steps INTEGER,
          progress DOUBLE PRECISION,
          logs JSONB NOT NULL,
          result_json JSONB,
          artifacts JSONB,
          validation JSONB,
          cost JSONB,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          completed_at TEXT,
          ttl INTEGER,
          idempotency_key TEXT
        )
        """
    ).format(table=sql.Identifier(table_name))

    alter_statements = [
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS expected_sections INTEGER").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS completed_sections INTEGER").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS completed_section_indexes JSONB").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS current_section_index INTEGER").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS current_section_status TEXT").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS current_section_retry_count INTEGER").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS current_section_title TEXT").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS retry_count INTEGER").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS max_retries INTEGER").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS retry_sections JSONB").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS retry_agents JSONB").format(
            table=sql.Identifier(table_name),
        ),
        sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS retry_parent_job_id TEXT").format(
            table=sql.Identifier(table_name),
        ),
    ]
    
    # Build supporting indexes for queue polling and idempotency lookups.
    
    status_index = sql.SQL(
        "CREATE INDEX IF NOT EXISTS {index} ON {table} (status, created_at)"
    ).format(
        index=sql.Identifier(f"{table_name}_status_created_idx"),
        table=sql.Identifier(table_name),
    )
    idempotency_index = sql.SQL(
        "CREATE INDEX IF NOT EXISTS {index} ON {table} (idempotency_key)"
    ).format(
        index=sql.Identifier(f"{table_name}_idempotency_idx"),
        table=sql.Identifier(table_name),
    )
    
    # Run schema creation using a short-lived connection for safety.
    max_retries = 5
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            with psycopg.connect(config.dsn, connect_timeout=config.connect_timeout) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(statement)
                    cursor.execute(status_index)
                    cursor.execute(idempotency_index)

                    for alter_statement in alter_statements:
                        cursor.execute(alter_statement)
            break
        except psycopg.OperationalError as exc:
            if attempt == max_retries - 1:
                logger.error("Failed to ensure jobs table after %d attempts: %s", max_retries, exc)
                raise
            
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            logger.warning("Database connection failed (attempt %d/%d), retrying in %.2fs: %s", attempt + 1, max_retries, delay, exc)
            time.sleep(delay)

    
    _KNOWN_TABLES.add(table_name)
    logger.info("Ensured Postgres jobs table exists: %s", table_name)


def _json_value(value: Any) -> Json | None:
    """Wrap Python values for JSONB storage when present."""
    
    # Preserve NULLs to keep optional columns unset.
    if value is None:
        return None
    
    return Json(value)


class PostgresJobsRepository(JobsRepository):
    """Persist jobs to Postgres."""

    def __init__(self, *, dsn: str, connect_timeout: int, table_name: str = "dgs_jobs") -> None:
        self._config = _PostgresConfig(dsn=dsn, connect_timeout=connect_timeout)
        self._table_name = table_name
        
        # Ensure the storage tables are present before serving requests.
        
        _ensure_jobs_table(self._config, self._table_name)

    def create_job(self, record: JobRecord) -> None:
        """Insert a new job record."""
        statement = sql.SQL(
            """
            INSERT INTO {table} (
              job_id,
              request,
              status,
              phase,
              subphase,
              expected_sections,
              completed_sections,
              completed_section_indexes,
              current_section_index,
              current_section_status,
              current_section_retry_count,
              current_section_title,
              retry_count,
              max_retries,
              retry_sections,
              retry_agents,
              retry_parent_job_id,
              total_steps,
              completed_steps,
              progress,
              logs,
              result_json,
              artifacts,
              validation,
              cost,
              created_at,
              updated_at,
              completed_at,
              ttl,
              idempotency_key
            )
            VALUES (
              %(job_id)s,
              %(request)s,
              %(status)s,
              %(phase)s,
              %(subphase)s,
              %(expected_sections)s,
              %(completed_sections)s,
              %(completed_section_indexes)s,
              %(current_section_index)s,
              %(current_section_status)s,
              %(current_section_retry_count)s,
              %(current_section_title)s,
              %(retry_count)s,
              %(max_retries)s,
              %(retry_sections)s,
              %(retry_agents)s,
              %(retry_parent_job_id)s,
              %(total_steps)s,
              %(completed_steps)s,
              %(progress)s,
              %(logs)s,
              %(result_json)s,
              %(artifacts)s,
              %(validation)s,
              %(cost)s,
              %(created_at)s,
              %(updated_at)s,
              %(completed_at)s,
              %(ttl)s,
              %(idempotency_key)s
            )
            """
        ).format(table=sql.Identifier(self._table_name))
        
        # Apply guardrails to keep logs and payload sizes consistent.
        
        safe_logs = sanitize_logs(record.logs)
        safe_result = maybe_truncate_result_json(record.result_json)
        safe_artifacts = maybe_truncate_artifacts(record.artifacts)
        payload: dict[str, Any] = {
            "job_id": record.job_id,
            "request": _json_value(record.request),
            "status": record.status,
            "phase": record.phase,
            "subphase": record.subphase,
            "expected_sections": record.expected_sections,
            "completed_sections": record.completed_sections,
            "completed_section_indexes": _json_value(record.completed_section_indexes),
            "current_section_index": record.current_section_index,
            "current_section_status": record.current_section_status,
            "current_section_retry_count": record.current_section_retry_count,
            "current_section_title": record.current_section_title,
            "retry_count": record.retry_count,
            "max_retries": record.max_retries,
            "retry_sections": _json_value(record.retry_sections),
            "retry_agents": _json_value(record.retry_agents),
            "retry_parent_job_id": record.retry_parent_job_id,
            "total_steps": record.total_steps,
            "completed_steps": record.completed_steps,
            "progress": record.progress,
            "logs": _json_value(safe_logs),
            "result_json": _json_value(safe_result),
            "artifacts": _json_value(safe_artifacts),
            "validation": _json_value(record.validation),
            "cost": _json_value(record.cost),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "completed_at": record.completed_at,
            "ttl": record.ttl,
            "idempotency_key": record.idempotency_key,
        }
        
        # Use a short-lived connection to keep DB access isolated.
        
        with psycopg.connect(self._config.dsn, connect_timeout=self._config.connect_timeout) as conn:
            
            with conn.cursor() as cursor:
                cursor.execute(statement, payload)

    def get_job(self, job_id: str) -> JobRecord | None:
        """Fetch a job record by identifier."""
        statement = sql.SQL(
            "SELECT * FROM {table} WHERE job_id = %(job_id)s"
        ).format(table=sql.Identifier(self._table_name))
        
        # Query with a dict row factory for clarity in mapping fields.
        
        with psycopg.connect(self._config.dsn, connect_timeout=self._config.connect_timeout) as conn:
            
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(statement, {"job_id": job_id})
                row = cursor.fetchone()
        
        
        # Return None when the job does not exist.
        
        if row is None:
            return None
        
        # Map the database row into the domain record.
        return self._row_to_record(row)

    def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        phase: str | None = None,
        subphase: str | None = None,
        expected_sections: int | None = None,
        completed_sections: int | None = None,
        completed_section_indexes: list[int] | None = None,
        current_section_index: int | None = None,
        current_section_status: str | None = None,
        current_section_retry_count: int | None = None,
        current_section_title: str | None = None,
        retry_count: int | None = None,
        max_retries: int | None = None,
        retry_sections: list[int] | None = None,
        retry_agents: list[str] | None = None,
        retry_parent_job_id: str | None = None,
        total_steps: int | None = None,
        completed_steps: int | None = None,
        progress: float | None = None,
        logs: list[str] | None = None,
        result_json: dict | None = None,
        artifacts: dict | None = None,
        validation: dict | None = None,
        cost: dict | None = None,
        completed_at: str | None = None,
        updated_at: str | None = None,
    ) -> JobRecord | None:
        """Apply partial updates to a job record."""
        current = self.get_job(job_id)
        
        
        # Stop early if the job does not exist.
        
        if current is None:
            return None
        
        # Preserve canceled status if already set.
        if current.status == "canceled" and status is not None and status != "canceled":
            return current
        
        # Merge the incoming changes with persisted values.
        completed_steps_value = completed_steps if completed_steps is not None else current.completed_steps
        # Always stamp an update timestamp when writing job changes.
        updated_at_value = updated_at or _now_iso()
        payload = {
            "job_id": current.job_id,
            "request": current.request,
            "status": status or current.status,
            "phase": phase if phase is not None else current.phase,
            "subphase": subphase if subphase is not None else current.subphase,
            "expected_sections": expected_sections if expected_sections is not None else current.expected_sections,
            "completed_sections": completed_sections if completed_sections is not None else current.completed_sections,
            "completed_section_indexes": completed_section_indexes if completed_section_indexes is not None else current.completed_section_indexes,
            "current_section_index": current_section_index if current_section_index is not None else current.current_section_index,
            "current_section_status": current_section_status if current_section_status is not None else current.current_section_status,
            "current_section_retry_count": current_section_retry_count if current_section_retry_count is not None else current.current_section_retry_count,
            "current_section_title": current_section_title if current_section_title is not None else current.current_section_title,
            "retry_count": retry_count if retry_count is not None else current.retry_count,
            "max_retries": max_retries if max_retries is not None else current.max_retries,
            "retry_sections": retry_sections if retry_sections is not None else current.retry_sections,
            "retry_agents": retry_agents if retry_agents is not None else current.retry_agents,
            "retry_parent_job_id": retry_parent_job_id if retry_parent_job_id is not None else current.retry_parent_job_id,
            "total_steps": total_steps if total_steps is not None else current.total_steps,
            "completed_steps": completed_steps_value,
            "progress": progress if progress is not None else current.progress,
            "logs": logs if logs is not None else current.logs,
            "result_json": result_json if result_json is not None else current.result_json,
            "artifacts": artifacts if artifacts is not None else current.artifacts,
            "validation": validation if validation is not None else current.validation,
            "cost": cost if cost is not None else current.cost,
            "created_at": current.created_at,
            "updated_at": updated_at_value,
            "completed_at": completed_at if completed_at is not None else current.completed_at,
            "ttl": current.ttl,
            "idempotency_key": current.idempotency_key,
        }
        updated_record = JobRecord(**payload)
        
        # Apply guardrails to keep logs and payload sizes consistent.
        
        safe_logs = sanitize_logs(updated_record.logs)
        safe_result = maybe_truncate_result_json(updated_record.result_json)
        safe_artifacts = maybe_truncate_artifacts(updated_record.artifacts)
        statement = sql.SQL(
            """
            UPDATE {table}
            SET
              request = %(request)s,
              status = %(status)s,
              phase = %(phase)s,
              subphase = %(subphase)s,
              expected_sections = %(expected_sections)s,
              completed_sections = %(completed_sections)s,
              completed_section_indexes = %(completed_section_indexes)s,
              current_section_index = %(current_section_index)s,
              current_section_status = %(current_section_status)s,
              current_section_retry_count = %(current_section_retry_count)s,
              current_section_title = %(current_section_title)s,
              retry_count = %(retry_count)s,
              max_retries = %(max_retries)s,
              retry_sections = %(retry_sections)s,
              retry_agents = %(retry_agents)s,
              retry_parent_job_id = %(retry_parent_job_id)s,
              total_steps = %(total_steps)s,
              completed_steps = %(completed_steps)s,
              progress = %(progress)s,
              logs = %(logs)s,
              result_json = %(result_json)s,
              artifacts = %(artifacts)s,
              validation = %(validation)s,
              cost = %(cost)s,
              created_at = %(created_at)s,
              updated_at = %(updated_at)s,
              completed_at = %(completed_at)s,
              ttl = %(ttl)s,
              idempotency_key = %(idempotency_key)s
            WHERE job_id = %(job_id)s
            """
        ).format(table=sql.Identifier(self._table_name))
        db_payload: dict[str, Any] = {
            "job_id": updated_record.job_id,
            "request": _json_value(updated_record.request),
            "status": updated_record.status,
            "phase": updated_record.phase,
            "subphase": updated_record.subphase,
            "expected_sections": updated_record.expected_sections,
            "completed_sections": updated_record.completed_sections,
            "completed_section_indexes": _json_value(updated_record.completed_section_indexes),
            "current_section_index": updated_record.current_section_index,
            "current_section_status": updated_record.current_section_status,
            "current_section_retry_count": updated_record.current_section_retry_count,
            "current_section_title": updated_record.current_section_title,
            "retry_count": updated_record.retry_count,
            "max_retries": updated_record.max_retries,
            "retry_sections": _json_value(updated_record.retry_sections),
            "retry_agents": _json_value(updated_record.retry_agents),
            "retry_parent_job_id": updated_record.retry_parent_job_id,
            "total_steps": updated_record.total_steps,
            "completed_steps": updated_record.completed_steps,
            "progress": updated_record.progress,
            "logs": _json_value(safe_logs),
            "result_json": _json_value(safe_result),
            "artifacts": _json_value(safe_artifacts),
            "validation": _json_value(updated_record.validation),
            "cost": _json_value(updated_record.cost),
            "created_at": updated_record.created_at,
            "updated_at": updated_record.updated_at,
            "completed_at": updated_record.completed_at,
            "ttl": updated_record.ttl,
            "idempotency_key": updated_record.idempotency_key,
        }
        
        # Persist the merged record back into Postgres.
        
        with psycopg.connect(self._config.dsn, connect_timeout=self._config.connect_timeout) as conn:
            
            with conn.cursor() as cursor:
                cursor.execute(statement, db_payload)
        
        return updated_record

    def find_queued(self, limit: int = 5) -> list[JobRecord]:
        """Return a batch of queued jobs."""
        statement = sql.SQL(
            "SELECT * FROM {table} WHERE status = %(status)s ORDER BY created_at ASC LIMIT %(limit)s"
        ).format(table=sql.Identifier(self._table_name))
        
        # Fetch queued jobs in a deterministic order.
        
        with psycopg.connect(self._config.dsn, connect_timeout=self._config.connect_timeout) as conn:
            
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(statement, {"status": "queued", "limit": limit})
                rows = cursor.fetchall()
        
        
        # Map queued rows into domain records.
        
        return [self._row_to_record(row) for row in rows]

    def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        """Find a job matching a given idempotency key."""
        statement = sql.SQL(
            "SELECT * FROM {table} WHERE idempotency_key = %(key)s ORDER BY created_at ASC LIMIT 1"
        ).format(table=sql.Identifier(self._table_name))
        
        # Look up the earliest job with the requested idempotency key.
        
        with psycopg.connect(self._config.dsn, connect_timeout=self._config.connect_timeout) as conn:
            
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(statement, {"key": idempotency_key})
                row = cursor.fetchone()
        
        
        # Return None when the job does not exist.
        
        if row is None:
            return None
        
        # Map the database row into the domain record.
        
        return self._row_to_record(row)

    def _row_to_record(self, row: dict[str, Any]) -> JobRecord:
        """Convert a database row to a JobRecord."""
        # Normalize logs to a list even when the column is NULL.
        logs = row.get("logs") or []
        payload = {
            "job_id": row["job_id"],
            "request": row["request"],
            "status": row["status"],
            "phase": row["phase"],
            "subphase": row.get("subphase"),
            "expected_sections": row.get("expected_sections"),
            "completed_sections": row.get("completed_sections"),
            "completed_section_indexes": row.get("completed_section_indexes"),
            "current_section_index": row.get("current_section_index"),
            "current_section_status": row.get("current_section_status"),
            "current_section_retry_count": row.get("current_section_retry_count"),
            "current_section_title": row.get("current_section_title"),
            "retry_count": row.get("retry_count"),
            "max_retries": row.get("max_retries"),
            "retry_sections": row.get("retry_sections"),
            "retry_agents": row.get("retry_agents"),
            "retry_parent_job_id": row.get("retry_parent_job_id"),
            "total_steps": row.get("total_steps"),
            "completed_steps": row.get("completed_steps"),
            "progress": row.get("progress"),
            "logs": logs,
            "result_json": row.get("result_json"),
            "artifacts": row.get("artifacts"),
            "validation": row.get("validation"),
            "cost": row.get("cost"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row.get("completed_at"),
            "ttl": row.get("ttl"),
            "idempotency_key": row.get("idempotency_key"),
        }
        return JobRecord(**payload)
