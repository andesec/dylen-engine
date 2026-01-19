"""Postgres-backed repository for lesson persistence using SQLAlchemy."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.schema.lessons import Lesson
from app.storage.lessons_repo import LessonRecord, LessonsRepository

logger = logging.getLogger(__name__)


class PostgresLessonsRepository(LessonsRepository):
    """Persist lessons to Postgres using SQLAlchemy."""

    def __init__(self, table_name: str = "dgs_lessons") -> None:
        # table_name is kept for signature compatibility but effectively defined by the Model
        self._session_factory = get_session_factory()
        if self._session_factory is None:
             raise RuntimeError("Database not initialized")

    async def create_lesson(self, record: LessonRecord) -> None:
        """Insert a lesson record."""
        async with self._session_factory() as session:
            tags = sorted(record.tags) if record.tags else None
            
            lesson = Lesson(
                lesson_id=record.lesson_id,
                topic=record.topic,
                title=record.title,
                created_at=record.created_at,
                schema_version=record.schema_version,
                prompt_version=record.prompt_version,
                provider_a=record.provider_a,
                model_a=record.model_a,
                provider_b=record.provider_b,
                model_b=record.model_b,
                lesson_json=record.lesson_json,
                status=record.status,
                latency_ms=record.latency_ms,
                idempotency_key=record.idempotency_key,
                tags=tags,
            )
            session.add(lesson)
            await session.commit()

    async def get_lesson(self, lesson_id: str) -> LessonRecord | None:
        """Fetch a lesson record by lesson identifier."""
        async with self._session_factory() as session:
            lesson = await session.get(Lesson, lesson_id)
            if not lesson:
                return None
            return self._model_to_record(lesson)

    async def list_lessons(
        self, limit: int, offset: int, topic: str | None = None, status: str | None = None
    ) -> tuple[list[LessonRecord], int]:
        """Return a paginated list of lessons with optional filters, and total count."""
        async with self._session_factory() as session:
            # Build query
            stmt = select(Lesson).order_by(Lesson.created_at.desc()).limit(limit).offset(offset)
            count_stmt = select(func.count()).select_from(Lesson)
            
            # Apply filters
            conditions = []
            if topic:
                conditions.append(Lesson.topic == topic)
            if status:
                conditions.append(Lesson.status == status)

            if conditions:
                stmt = stmt.where(*conditions)
                count_stmt = count_stmt.where(*conditions)

            # Execute
            total = await session.scalar(count_stmt)
            result = await session.execute(stmt)
            lessons = result.scalars().all()

            return [self._model_to_record(l) for l in lessons], (total or 0)

    def _model_to_record(self, lesson: Lesson) -> LessonRecord:
        """Convert a SQLAlchemy model to a domain record."""
        tags = set(lesson.tags) if lesson.tags else None
        return LessonRecord(
            lesson_id=lesson.lesson_id,
            topic=lesson.topic,
            title=lesson.title,
            created_at=lesson.created_at,
            schema_version=lesson.schema_version,
            prompt_version=lesson.prompt_version,
            provider_a=lesson.provider_a,
            model_a=lesson.model_a,
            provider_b=lesson.provider_b,
            model_b=lesson.model_b,
            lesson_json=lesson.lesson_json,
            status=lesson.status,
            latency_ms=lesson.latency_ms,
            idempotency_key=lesson.idempotency_key,
            tags=tags,
        )
