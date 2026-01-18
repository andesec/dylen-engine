"""Postgres-backed repository for lesson persistence."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.storage.lessons_repo import LessonRecord, LessonsRepository

logger = logging.getLogger(__name__)

_KNOWN_TABLES: set[str] = set()


@dataclass(frozen=True)
class _PostgresConfig:
    """Shared configuration for Postgres repositories."""

    dsn: str
    connect_timeout: int


def _ensure_lessons_table(config: _PostgresConfig, table_name: str) -> None:
    """Create the lessons table and indexes if they are missing."""
    
    # Avoid repeated DDL within the same process.
    if table_name in _KNOWN_TABLES:
        return
    
    
    # Define the base schema for lesson storage.
    
    statement = sql.SQL(
        """
        CREATE TABLE IF NOT EXISTS {table} (
          lesson_id TEXT PRIMARY KEY,
          topic TEXT NOT NULL,
          title TEXT NOT NULL,
          created_at TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          prompt_version TEXT NOT NULL,
          provider_a TEXT NOT NULL,
          model_a TEXT NOT NULL,
          provider_b TEXT NOT NULL,
          model_b TEXT NOT NULL,
          lesson_json TEXT NOT NULL,
          status TEXT NOT NULL,
          latency_ms INTEGER NOT NULL,
          idempotency_key TEXT,
          tags TEXT[]
        )
        """
    ).format(table=sql.Identifier(table_name))
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
            cursor.execute(idempotency_index)
    
    _KNOWN_TABLES.add(table_name)
    logger.info("Ensured Postgres lessons table exists: %s", table_name)


class PostgresLessonsRepository(LessonsRepository):
    """Persist lessons to Postgres."""

    def __init__(self, *, dsn: str, connect_timeout: int, table_name: str = "dgs_lessons") -> None:
        self._config = _PostgresConfig(dsn=dsn, connect_timeout=connect_timeout)
        self._table_name = table_name
        
        # Ensure the storage tables are present before serving requests.
        
        _ensure_lessons_table(self._config, self._table_name)

    def create_lesson(self, record: LessonRecord) -> None:
        """Insert a lesson record."""
        statement = sql.SQL(
            """
            INSERT INTO {table} (
              lesson_id,
              topic,
              title,
              created_at,
              schema_version,
              prompt_version,
              provider_a,
              model_a,
              provider_b,
              model_b,
              lesson_json,
              status,
              latency_ms,
              idempotency_key,
              tags
            )
            VALUES (
              %(lesson_id)s,
              %(topic)s,
              %(title)s,
              %(created_at)s,
              %(schema_version)s,
              %(prompt_version)s,
              %(provider_a)s,
              %(model_a)s,
              %(provider_b)s,
              %(model_b)s,
              %(lesson_json)s,
              %(status)s,
              %(latency_ms)s,
              %(idempotency_key)s,
              %(tags)s
            )
            """
        ).format(table=sql.Identifier(self._table_name))
        
        # Normalize tags for Postgres array storage.
        
        tags = sorted(record.tags) if record.tags else None
        payload: dict[str, Any] = {
            "lesson_id": record.lesson_id,
            "topic": record.topic,
            "title": record.title,
            "created_at": record.created_at,
            "schema_version": record.schema_version,
            "prompt_version": record.prompt_version,
            "provider_a": record.provider_a,
            "model_a": record.model_a,
            "provider_b": record.provider_b,
            "model_b": record.model_b,
            "lesson_json": record.lesson_json,
            "status": record.status,
            "latency_ms": record.latency_ms,
            "idempotency_key": record.idempotency_key,
            "tags": tags,
        }
        
        # Use a short-lived connection to keep DB access isolated.
        
        with psycopg.connect(self._config.dsn, connect_timeout=self._config.connect_timeout) as conn:
            
            with conn.cursor() as cursor:
                cursor.execute(statement, payload)

    def get_lesson(self, lesson_id: str) -> LessonRecord | None:
        """Fetch a lesson record by lesson identifier."""
        statement = sql.SQL(
            "SELECT * FROM {table} WHERE lesson_id = %(lesson_id)s"
        ).format(table=sql.Identifier(self._table_name))
        
        # Query with a dict row factory for clarity in mapping fields.
        
        with psycopg.connect(self._config.dsn, connect_timeout=self._config.connect_timeout) as conn:
            
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(statement, {"lesson_id": lesson_id})
                row = cursor.fetchone()
        
        
        # Return None when the lesson does not exist.
        
        if row is None:
            return None
        
        # Normalize optional tags for the domain record.
        
        tags = set(row["tags"]) if row.get("tags") else None
        payload = {
            "lesson_id": row["lesson_id"],
            "topic": row["topic"],
            "title": row["title"],
            "created_at": row["created_at"],
            "schema_version": row["schema_version"],
            "prompt_version": row["prompt_version"],
            "provider_a": row["provider_a"],
            "model_a": row["model_a"],
            "provider_b": row["provider_b"],
            "model_b": row["model_b"],
            "lesson_json": row["lesson_json"],
            "status": row["status"],
            "latency_ms": row["latency_ms"],
            "idempotency_key": row.get("idempotency_key"),
            "tags": tags,
        }
        return LessonRecord(**payload)

    def list_lessons(
        self, limit: int, offset: int, topic: str | None = None, status: str | None = None
    ) -> tuple[list[LessonRecord], int]:
        """Return a paginated list of lessons with optional filters, and total count."""
        where_clauses = []
        params = {}
        
        # NOTE: 'topic' search could be partial match in future, strict for now.
        if topic:
            where_clauses.append("topic = %(topic)s")
            params["topic"] = topic
            
        if status:
            where_clauses.append("status = %(status)s")
            params["status"] = status
            
        where_sql = sql.SQL(" WHERE " if where_clauses else "") + sql.SQL(" AND ").join(
            [sql.SQL(c) for c in where_clauses]
        )

        count_query = sql.SQL("SELECT COUNT(*) FROM {table}").format(
            table=sql.Identifier(self._table_name)
        ) + where_sql
        
        items_query = (
            sql.SQL("SELECT * FROM {table}").format(table=sql.Identifier(self._table_name))
            + where_sql
            + sql.SQL(" ORDER BY created_at DESC LIMIT %(limit)s OFFSET %(offset)s")
        )
        params["limit"] = limit
        params["offset"] = offset

        with psycopg.connect(
            self._config.dsn, connect_timeout=self._config.connect_timeout
        ) as conn:
            with conn.cursor() as cursor:
                cursor.execute(count_query, params)
                total = cursor.fetchone()[0]

            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(items_query, params)
                rows = cursor.fetchall()
        
        records = []
        for row in rows:
            tags = set(row["tags"]) if row.get("tags") else None
            payload = {
                "lesson_id": row["lesson_id"],
                "topic": row["topic"],
                "title": row["title"],
                "created_at": row["created_at"],
                "schema_version": row["schema_version"],
                "prompt_version": row["prompt_version"],
                "provider_a": row["provider_a"],
                "model_a": row["model_a"],
                "provider_b": row["provider_b"],
                "model_b": row["model_b"],
                "lesson_json": row["lesson_json"],
                "status": row["status"],
                "latency_ms": row["latency_ms"],
                "idempotency_key": row.get("idempotency_key"),
                "tags": tags,
            }
            records.append(LessonRecord(**payload))
            
        return records, total
