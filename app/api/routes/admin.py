import time
import uuid
from typing import TypeVar

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.firebase import build_rbac_claims, set_custom_claims
from app.core.security import get_current_admin_user, require_role_level
from app.jobs.models import JobRecord, JobStatus
from app.notifications.factory import build_notification_service
from app.schema.sql import Role, RoleLevel, User, UserStatus
from app.services.feature_flags import is_feature_enabled
from app.services.jobs import trigger_job_processing
from app.services.rbac import create_role as create_role_record
from app.services.rbac import get_role_by_id, list_permission_slugs_for_role, set_role_permissions
from app.services.section_shorthand_backfill import backfill_section_shorthand
from app.services.users import delete_user, get_user_by_id, get_user_subscription_tier, get_user_tier_name, list_users, set_user_subscription_tier, update_user_role, update_user_status
from app.storage.jobs_repo import JobsRepository
from app.storage.lessons_repo import LessonRecord, LessonsRepository
from app.storage.postgres_audit_repo import LlmAuditRecord, PostgresLlmAuditRepository
from app.storage.postgres_jobs_repo import PostgresJobsRepository
from app.storage.postgres_lessons_repo import PostgresLessonsRepository
from app.utils.ids import generate_job_id

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


async def check_tenant_permissions(db_session: AsyncSession, current_user: User, target_org_id: uuid.UUID | None = None) -> Role:
  """
  Verifies that the current user has permission to access resources for the target organization.
  Returns the current user's role.
  """
  role = await get_role_by_id(db_session, current_user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Requester role missing.")

  if role.level == RoleLevel.TENANT:
    if current_user.org_id is None:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

    # If target_org_id provided, verify match
    if target_org_id and current_user.org_id != target_org_id:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

  return role


class UserStatusResponse(BaseModel):
  id: str
  email: str
  status: UserStatus


class RoleRecord(BaseModel):
  id: str
  name: str
  level: RoleLevel
  description: str | None


class PermissionRecord(BaseModel):
  id: str
  slug: str
  display_name: str
  description: str | None


class RoleCreateRequest(BaseModel):
  name: str
  level: RoleLevel
  description: str | None = None


class RolePermissionsUpdateRequest(BaseModel):
  permission_ids: list[str]


class RolePermissionsResponse(BaseModel):
  role_id: str
  permissions: list[PermissionRecord]


class UserRecord(BaseModel):
  id: str
  email: str
  status: UserStatus
  role_id: str
  org_id: str | None


class UserStatusUpdateRequest(BaseModel):
  status: UserStatus


class UserRoleUpdateRequest(BaseModel):
  role_id: str


class UserTierUpdateRequest(BaseModel):
  tier_name: str


class MaintenanceJobResponse(BaseModel):
  job_id: str


class SectionShorthandBackfillRequest(BaseModel):
  section_ids: list[int]


class SectionShorthandBackfillResponse(BaseModel):
  updated_section_ids: list[int]
  missing_section_ids: list[int]
  failed: dict[int, str]


async def _update_firebase_claims(db_session: AsyncSession, user: User, role: Role, *, permissions: list[str] | None = None) -> None:
  """Helper to sync user RBAC claims to Firebase."""
  tier_name = await get_user_tier_name(db_session, user.id)
  if permissions is None:
    permissions = await list_permission_slugs_for_role(db_session, role_id=role.id)
  claims = build_rbac_claims(role_id=str(role.id), role_name=role.name, role_level=role.level, org_id=str(user.org_id) if user.org_id else None, status=user.status, tier=tier_name, permissions=permissions)
  await run_in_threadpool(set_custom_claims, user.firebase_uid, claims)


@router.post("/roles", response_model=RoleRecord, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL))])
async def create_role(request: RoleCreateRequest, db_session: AsyncSession = Depends(get_db)) -> RoleRecord:  # noqa: B008
  """Create a new role for RBAC management."""
  # Persist a new role for administrative configuration.
  role = await create_role_record(db_session, name=request.name, level=request.level, description=request.description)
  return RoleRecord(id=str(role.id), name=role.name, level=role.level, description=role.description)


@router.put("/roles/{role_id}/permissions", response_model=RolePermissionsResponse, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL))])
async def update_role_permissions(role_id: str, request: RolePermissionsUpdateRequest, db_session: AsyncSession = Depends(get_db)) -> RolePermissionsResponse:  # noqa: B008
  """Assign permissions to a role in bulk."""
  # Parse the target role id for validation.
  try:
    parsed_role_id = uuid.UUID(role_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role id.") from exc

  # Load the role so updates are explicit.
  role = await get_role_by_id(db_session, parsed_role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")

  # Validate permission ids before updating assignments.
  try:
    permission_ids = [uuid.UUID(value) for value in request.permission_ids]
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid permission id.") from exc

  # Update role mappings with the provided permission ids.
  permissions = await set_role_permissions(db_session, role=role, permission_ids=permission_ids)
  if len(permissions) != len(permission_ids):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more permissions were not found.")

  # Sync Firebase claims for users with this role so permission hints update without extra API calls.
  permission_slugs = [permission.slug for permission in permissions]
  users_result = await db_session.execute(select(User).where(User.role_id == role.id))
  users = list(users_result.scalars().all())
  for user in users:
    await _update_firebase_claims(db_session, user, role, permissions=permission_slugs)

  # Shape permissions for API response payloads.
  permission_records = [PermissionRecord(id=str(permission.id), slug=permission.slug, display_name=permission.display_name, description=permission.description) for permission in permissions]
  return RolePermissionsResponse(role_id=str(role.id), permissions=permission_records)


@router.get("/users", response_model=PaginatedResponse[UserRecord])
async def list_user_accounts(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), current_user: User = Depends(get_current_admin_user), db_session: AsyncSession = Depends(get_db)) -> PaginatedResponse[UserRecord]:  # noqa: B008
  """List users with tenant scoping for org admins."""
  # Determine tenant scoping based on the requesting user's role.
  role = await check_tenant_permissions(db_session, current_user)

  # Apply org filtering for tenant-scoped admins.
  org_filter = None
  org_filter = None
  if role.level == RoleLevel.TENANT:
    org_filter = current_user.org_id

  # Load users with pagination and tenant scoping applied.
  users, total = await list_users(db_session, org_id=org_filter, limit=limit, offset=offset)
  # Format records for response payloads.
  records = [UserRecord(id=str(user.id), email=user.email, status=user.status, role_id=str(user.role_id), org_id=str(user.org_id) if user.org_id else None) for user in users]
  return PaginatedResponse(items=records, total=total, limit=limit, offset=offset)


@router.patch("/users/{user_id}/status", response_model=UserStatusResponse)
async def update_user_account_status(user_id: str, request: UserStatusUpdateRequest, db_session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
  """Update a user's approval status and refresh RBAC claims."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user record so updates are explicit and auditable.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

  # Enforce tenant scoping for org admins.
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  # Persist status before syncing notifications or claims.
  user = await update_user_status(db_session, user=user, status=request.status)

  # Update Firebase custom claims so tokens reflect the new status.
  role = await get_role_by_id(db_session, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User role missing.")

  await _update_firebase_claims(db_session, user, role)

  # Notify the user on best-effort basis when approved.
  if user.status == UserStatus.APPROVED:
    tier_id, _tier_name = await get_user_subscription_tier(db_session, user.id)
    email_enabled = await is_feature_enabled(db_session, key="feature.notifications.email", org_id=user.org_id, subscription_tier_id=tier_id)
    await build_notification_service(settings, email_enabled=email_enabled).notify_account_approved(user_id=user.id, user_email=user.email, full_name=user.full_name)

  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.patch("/users/{user_id}/role", response_model=UserStatusResponse)
async def update_user_account_role(user_id: str, request: UserRoleUpdateRequest, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
  """Update a user's role assignment and refresh RBAC claims."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Parse requested role id early for validation.
  try:
    parsed_role_id = uuid.UUID(request.role_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role id.") from exc

  # Load the user record so updates are explicit and auditable.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

  # Enforce tenant scoping for org admins.
  current_role = await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  # Ensure the target role exists before assignment.
  new_role = await get_role_by_id(db_session, parsed_role_id)
  if new_role is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")

  # Prevent tenant admins from assigning global roles.
  if current_role.level == RoleLevel.TENANT and new_role.level == RoleLevel.GLOBAL:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

  # Persist role updates before syncing claims.
  user = await update_user_role(db_session, user=user, role_id=new_role.id)

  # Update Firebase custom claims so tokens reflect the new role.
  await _update_firebase_claims(db_session, user, new_role)

  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.patch("/users/{user_id}/tier", response_model=UserStatusResponse)
async def update_user_account_tier(user_id: str, request: UserTierUpdateRequest, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
  """Update a user's subscription tier and refresh RBAC claims."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user record so tier changes are explicit and auditable.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

  # Enforce tenant scoping for org admins.
  _role = await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  try:
    _tier_id, _tier_name = await set_user_subscription_tier(db_session, user_id=user.id, tier_name=request.tier_name)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

  # Sync Firebase claims so the client tier gates update immediately.
  role = await get_role_by_id(db_session, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User role missing.")
  await _update_firebase_claims(db_session, user, role)

  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.post("/maintenance/archive-lessons", response_model=MaintenanceJobResponse)
async def trigger_archive_lessons(background_tasks: BackgroundTasks, settings: Settings = Depends(get_settings), current_user: User = Depends(get_current_admin_user), db_session: AsyncSession = Depends(get_db)) -> MaintenanceJobResponse:  # noqa: B008
  """Trigger a maintenance job to archive old lessons based on tier retention limits."""
  job_id = generate_job_id()
  timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
  record = JobRecord(
    job_id=job_id,
    user_id=str(current_user.id),
    request={"action": "archive_old_lessons", "_meta": {"user_id": str(current_user.id)}},
    status="queued",
    target_agent="maintenance",
    phase="queued",
    created_at=timestamp,
    updated_at=timestamp,
    expected_sections=0,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=0,
    logs=["Maintenance job queued by admin."],
    progress=0.0,
    ttl=int(time.time()) + 3600,
  )
  repo = get_jobs_repo()
  await repo.create_job(record)
  trigger_job_processing(background_tasks, job_id, settings)
  return MaintenanceJobResponse(job_id=job_id)


@router.patch("/users/{user_id}/approve", response_model=UserStatusResponse, dependencies=[Depends(get_current_admin_user)])
async def approve_user(user_id: str, db_session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> UserStatusResponse:  # noqa: B008
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
  if user.status == UserStatus.APPROVED:
    return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)

  # Persist approval before notifying so delivery failures cannot block access.
  user = await update_user_status(db_session, user=user, status=UserStatus.APPROVED)
  role = await get_role_by_id(db_session, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User role missing.")

  await _update_firebase_claims(db_session, user, role)

  # Notify the user on best-effort basis.
  tier_id, _tier_name = await get_user_subscription_tier(db_session, user.id)
  email_enabled = await is_feature_enabled(db_session, key="feature.notifications.email", org_id=user.org_id, subscription_tier_id=tier_id)
  await build_notification_service(settings, email_enabled=email_enabled).notify_account_approved(user_id=user.id, user_email=user.email, full_name=user.full_name)
  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL))])
async def delete_user_account(user_id: str, db_session: AsyncSession = Depends(get_db)) -> None:  # noqa: B008
  """Delete a user account permanently (GDPR erasure)."""
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  success = await delete_user(db_session, parsed_user_id)
  if not success:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")


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


@router.post("/sections/backfill-shorthand", response_model=SectionShorthandBackfillResponse, dependencies=[Depends(get_current_admin_user)])
async def backfill_sections_shorthand(request: SectionShorthandBackfillRequest) -> SectionShorthandBackfillResponse:
  """Backfill section shorthand content from stored raw section JSON."""
  result = await backfill_section_shorthand(request.section_ids)
  return SectionShorthandBackfillResponse(updated_section_ids=result.updated_section_ids, missing_section_ids=result.missing_section_ids, failed=result.failed)
