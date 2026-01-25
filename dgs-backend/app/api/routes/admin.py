import uuid
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_admin_user
from app.jobs.models import JobRecord, JobStatus
from app.notifications.factory import build_notification_service
from app.services.users import approve_user as approve_user_record
from app.services.users import get_user_by_id
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
  """Provide a jobs repository to keep transport decoupled from storage selection."""
  # Construct the concrete repository here to keep handlers thin and swappable.
  return PostgresJobsRepository()


def get_lessons_repo() -> LessonsRepository:
  """Provide a lessons repository to keep transport decoupled from storage selection."""
  # Construct the concrete repository here to keep handlers thin and swappable.
  return PostgresLessonsRepository()


def get_audit_repo() -> PostgresLlmAuditRepository:
  """Provide an audit repository so handlers can focus on orchestration logic."""
  # Construct the concrete repository here to keep handlers thin and swappable.
  return PostgresLlmAuditRepository()


class UserApprovalResponse(BaseModel):
  id: str
  email: str
  is_approved: bool


@router.patch("/users/{user_id}/approve", response_model=UserApprovalResponse, dependencies=[Depends(get_current_admin_user)])
async def approve_user(user_id: str, db_session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> UserApprovalResponse:  # noqa: B008
  """Approve a user account and notify the user."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user record so approval is explicit and auditable.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

  # Avoid resending notifications on repeated approval calls.
  if user.is_approved:
    return UserApprovalResponse(id=str(user.id), email=user.email, is_approved=True)

  # Persist approval before notifying so delivery failures cannot block access.
  user = await approve_user_record(db_session, user=user)
  # Notify the user on best-effort basis.
  await build_notification_service(settings).notify_account_approved(user_id=user.id, user_email=user.email, full_name=user.full_name)
  return UserApprovalResponse(id=str(user.id), email=user.email, is_approved=user.is_approved)


@router.get("/jobs", response_model=PaginatedResponse[JobRecord], dependencies=[Depends(get_current_admin_user)])
async def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), status: JobStatus | None = None, job_id: str | None = None) -> PaginatedResponse[JobRecord]:
  """List jobs for admins with pagination to control load and exposure."""
  # Resolve the repository here to keep handler orchestration focused.
  repo = get_jobs_repo()
  # Fetch results and totals together for consistent pagination output.
  items, total = await repo.list_jobs(limit=limit, offset=offset, status=status, job_id=job_id)
  # Return a typed pagination envelope that callers can rely on.
  return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/lessons", response_model=PaginatedResponse[LessonRecord], dependencies=[Depends(get_current_admin_user)])
async def list_lessons(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), topic: str | None = None, status: str | None = None) -> PaginatedResponse[LessonRecord]:
  """List lessons with pagination to keep responses bounded and predictable."""
  # Resolve the repository here to keep handler orchestration focused.
  repo = get_lessons_repo()
  # Fetch results and totals together for consistent pagination output.
  items, total = await repo.list_lessons(limit=limit, offset=offset, topic=topic, status=status)
  # Return a typed pagination envelope that callers can rely on.
  return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/llm-calls", response_model=PaginatedResponse[LlmAuditRecord], dependencies=[Depends(get_current_admin_user)])
async def list_llm_calls(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), job_id: str | None = None, agent: str | None = None, status: str | None = None) -> PaginatedResponse[LlmAuditRecord]:
  """List LLM audit records with pagination to keep admin views efficient."""
  # Resolve the repository here to keep handler orchestration focused.
  repo = get_audit_repo()
  # Fetch results and totals together for consistent pagination output.
  items, total = await repo.list_records(limit=limit, offset=offset, job_id=job_id, agent=agent, status=status)
  # Return a typed pagination envelope that callers can rely on.
  return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)
