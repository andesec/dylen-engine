from typing import TypeVar

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.config import get_settings
from app.core.security import get_current_active_user
from app.jobs.models import JobRecord, JobStatus
from app.storage.jobs_repo import JobsRepository
from app.storage.lessons_repo import LessonRecord, LessonsRepository
from app.storage.postgres_audit_repo import LlmAuditRecord, PostgresLlmAuditRepository
from app.storage.postgres_jobs_repo import PostgresJobsRepository
from app.storage.postgres_lessons_repo import PostgresLessonsRepository

router = APIRouter()

T = TypeVar("T")


class PaginatedResponse[T](BaseModel):
  items: list[T]
  total: int
  limit: int
  offset: int


# Helpers to get repos (could be true dependencies in future)
def get_jobs_repo() -> JobsRepository:
  settings = get_settings()
  return PostgresJobsRepository(dsn=settings.pg_dsn, connect_timeout=settings.pg_connect_timeout)


def get_lessons_repo() -> LessonsRepository:
  settings = get_settings()
  return PostgresLessonsRepository(dsn=settings.pg_dsn, connect_timeout=settings.pg_connect_timeout)


def get_audit_repo() -> PostgresLlmAuditRepository:
  settings = get_settings()
  return PostgresLlmAuditRepository(dsn=settings.pg_dsn, connect_timeout=settings.pg_connect_timeout)


@router.get("/jobs", response_model=PaginatedResponse[JobRecord], dependencies=[Depends(get_current_active_user)])
def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), status: JobStatus | None = None, job_id: str | None = None):
  repo = get_jobs_repo()
  items, total = repo.list_jobs(limit=limit, offset=offset, status=status, job_id=job_id)
  return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/lessons", response_model=PaginatedResponse[LessonRecord], dependencies=[Depends(get_current_active_user)])
def list_lessons(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), topic: str | None = None, status: str | None = None):
  repo = get_lessons_repo()
  items, total = repo.list_lessons(limit=limit, offset=offset, topic=topic, status=status)
  return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/llm-calls", response_model=PaginatedResponse[LlmAuditRecord], dependencies=[Depends(get_current_active_user)])
def list_llm_calls(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), job_id: str | None = None, agent: str | None = None, status: str | None = None):
  repo = get_audit_repo()
  items, total = repo.list_records(limit=limit, offset=offset, job_id=job_id, agent=agent, status=status)
  return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)
