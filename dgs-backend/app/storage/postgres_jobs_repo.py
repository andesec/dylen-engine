"""Postgres-backed repository for background jobs."""

from __future__ import annotations

from dataclasses import dataclass
import logging
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
    
    with psycopg.connect(config.dsn, connect_timeout=config.connect_timeout) as conn:
        
        with conn.cursor() as cursor:
            cursor.execute(statement)
            cursor.execute(status_index)
            cursor.execute(idempotency_index)
    
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
        payload = {
            "job_id": current.job_id,
            "request": current.request,
            "status": status or current.status,
            "phase": phase if phase is not None else current.phase,
            "subphase": subphase if subphase is not None else current.subphase,
            "total_steps": total_steps if total_steps is not None else current.total_steps,
            "completed_steps": completed_steps_value,
            "progress": progress if progress is not None else current.progress,
            "logs": logs if logs is not None else current.logs,
            "result_json": result_json if result_json is not None else current.result_json,
            "artifacts": artifacts if artifacts is not None else current.artifacts,
            "validation": validation if validation is not None else current.validation,
            "cost": cost if cost is not None else current.cost,
            "created_at": current.created_at,
            "updated_at": updated_at or current.updated_at,
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
