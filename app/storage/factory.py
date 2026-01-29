from app.config import Settings
from app.storage.jobs_repo import JobsRepository
from app.storage.lessons_repo import LessonsRepository
from app.storage.postgres_jobs_repo import PostgresJobsRepository
from app.storage.postgres_lessons_repo import PostgresLessonsRepository


def _get_repo(settings: Settings) -> LessonsRepository:
  """Return the active lessons repository."""

  # Enforce Postgres-backed storage for lessons.

  if not settings.pg_dsn:
    raise ValueError("DYLEN_PG_DSN must be set to enable Postgres persistence.")

  return PostgresLessonsRepository(table_name=settings.pg_lessons_table)


def _get_jobs_repo(settings: Settings) -> JobsRepository:
  """Return the active jobs repository."""

  # Enforce Postgres-backed storage for jobs.

  if not settings.pg_dsn:
    raise ValueError("DYLEN_PG_DSN must be set to enable Postgres persistence.")

  return PostgresJobsRepository(table_name=settings.pg_jobs_table)
