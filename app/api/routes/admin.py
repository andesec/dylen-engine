import datetime
import time
import uuid
from typing import Any, Literal, TypeVar

import msgspec
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.ai.utils.cost import PricingTable
from app.api.models import JobStatusResponse
from app.api.msgspec_utils import encode_msgspec_response
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.firebase import build_rbac_claims, set_custom_claims
from app.core.security import get_current_active_user, get_current_admin_user, require_permission, require_role_level
from app.jobs.models import JobRecord, JobStatus
from app.notifications.factory import build_notification_service
from app.schema.quotas import SubscriptionTier, UserTierOverride
from app.schema.sql import Role, RoleLevel, User, UserStatus
from app.services.feature_flags import delete_user_feature_flag_overrides, get_feature_flag_by_key, is_feature_enabled, list_active_user_feature_overrides, set_user_feature_flag_override
from app.services.jobs import resume_job_from_failure_admin, trigger_job_processing
from app.services.llm_pricing import load_pricing_table
from app.services.rbac import create_role as create_role_record
from app.services.rbac import get_role_by_id, get_role_by_name, list_permission_slugs_for_role, list_permissions_for_roles, set_role_permissions
from app.services.rbac import list_permissions as list_permissions_records
from app.services.rbac import list_roles as list_roles_records
from app.services.section_shorthand_backfill import backfill_section_shorthand
from app.services.users import (
  UserListFilters,
  archive_user,
  delete_user_and_reassign_content,
  get_user_by_id,
  get_user_subscription_tier,
  get_user_tier_name,
  list_users,
  restore_archived_user,
  set_user_subscription_tier,
  update_user_role,
  update_user_status,
)
from app.storage.jobs_repo import JobsRepository
from app.storage.lessons_repo import LessonRecord, LessonsRepository
from app.storage.postgres_audit_repo import PostgresLlmAuditRepository
from app.storage.postgres_jobs_repo import PostgresJobsRepository
from app.storage.postgres_lessons_repo import PostgresLessonsRepository
from app.utils.ids import generate_job_id

router = APIRouter()

T = TypeVar("T")
LlmPricingTarget = Literal["job", "lesson", "section", "illustration", "tutor", "fenster"]


class PaginatedResponse[T](BaseModel):
  items: list[T]
  total: int
  limit: int
  offset: int


class MsgspecPaginatedResponse(msgspec.Struct):
  """Serialize paginated payloads using msgspec to avoid Pydantic conversions."""

  items: list[Any]
  total: int
  limit: int
  offset: int


class LlmPricingCall(BaseModel):
  record_id: int
  started_at: datetime.datetime
  provider: str
  model: str
  prompt_tokens: int
  completion_tokens: int
  total_tokens: int
  cost_usd: float
  cost_missing: bool
  status: str
  job_id: str | None
  lesson_id: str | None
  section_id: int | None
  illustration_id: int | None
  tutor_id: int | None
  fenster_id: str | None
  fenster_public_id: str | None


class LlmPricingSummary(BaseModel):
  target_type: str
  target_id: str
  total_cost_usd: float
  total_prompt_tokens: int
  total_completion_tokens: int
  total_tokens: int
  call_count: int
  cost_missing_count: int


class LlmPricingResponse(BaseModel):
  summary: LlmPricingSummary
  calls: list[LlmPricingCall]


class LlmJobCostRecord(BaseModel):
  job_id: str
  total_cost_usd: float
  total_tokens: int
  call_count: int
  cost_missing_count: int


class LlmJobCostsResponse(BaseModel):
  items: list[LlmJobCostRecord]


class LlmPricingQuery(BaseModel):
  target_type: LlmPricingTarget
  target_id: str = Field(..., min_length=1)
  start_at: str | None = None
  end_at: str | None = None
  include_calls: bool = True


class LlmAuditCallWithCost(BaseModel):
  """Audit record with calculated cost data integrated."""

  record_id: int
  timestamp_request: datetime.datetime
  timestamp_response: datetime.datetime | None
  started_at: datetime.datetime
  duration_ms: int
  agent: str
  provider: str
  model: str
  lesson_topic: str | None
  request_payload: str
  response_payload: str | None
  prompt_tokens: int | None
  completion_tokens: int | None
  total_tokens: int | None
  request_type: str
  purpose: str | None
  call_index: str | None
  job_id: str | None
  status: str
  error_message: str | None
  cost_usd: float
  cost_missing: bool


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


def _parse_iso_datetime(value: str | None) -> datetime.datetime | None:
  """Parse ISO datetime query params into timezone-aware objects."""
  # Treat empty values as unset to keep filters optional.
  if value is None:
    return None

  # Normalize optional string inputs before parsing.
  normalized = value.strip()
  if normalized == "":
    return None

  if normalized.endswith("Z"):
    normalized = f"{normalized[:-1]}+00:00"

  try:
    return datetime.datetime.fromisoformat(normalized)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid datetime format.") from exc


def _calculate_call_cost(prompt_tokens: int, completion_tokens: int, provider: str, model: str, pricing_table: PricingTable) -> tuple[float, bool]:
  """Estimate per-call cost using database-backed pricing."""
  # Normalize pricing lookup keys so provider/model matching is stable.
  normalized_provider = str(provider or "").strip().lower()
  normalized_model = str(model or "").strip()
  provider_rates = pricing_table.get(normalized_provider, {})
  rates = provider_rates.get(normalized_model)
  if rates is None:
    return (0.0, True)

  price_in, price_out = rates
  call_cost = (prompt_tokens / 1_000_000) * price_in
  call_cost += (completion_tokens / 1_000_000) * price_out
  return (round(call_cost, 6), False)


def _resolve_total_tokens(prompt_tokens: int, completion_tokens: int, total_tokens: int | None) -> int:
  """Normalize total tokens when audit rows omit a precomputed total."""
  # Respect stored totals when present.
  if total_tokens is not None:
    return int(total_tokens)

  # Fall back to prompt + completion tokens for missing totals.
  return int(prompt_tokens + completion_tokens)


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


class RoleWithPermissionsRecord(BaseModel):
  id: str
  name: str
  level: RoleLevel
  description: str | None
  permissions: list[PermissionRecord]


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
  is_archived: bool
  role_id: str
  role_name: str | None  # Enriched: role name from roles table
  org_id: str | None
  org_name: str | None  # Enriched: organization name from organizations table


class OnboardingProfileRecord(BaseModel):
  user_id: str
  email: str
  status: UserStatus
  onboarding_completed: bool
  age: int | None
  gender: str | None
  gender_other: str | None
  city: str | None
  country: str | None
  occupation: str | None
  topics_of_interest: list[str] | None
  intended_use: str | None
  intended_use_other: str | None
  primary_language: str | None
  secondary_language: str | None
  accepted_terms_at: datetime.datetime | None
  accepted_privacy_at: datetime.datetime | None
  terms_version: str | None
  privacy_version: str | None


class UserStatusUpdateRequest(BaseModel):
  status: UserStatus


class UserRoleUpdateRequest(BaseModel):
  role_id: str


class UserRoleNameUpdateRequest(BaseModel):
  role_name: str


class UserEnabledUpdateRequest(BaseModel):
  enabled: bool


class UserTierUpdateRequest(BaseModel):
  tier_name: str


class TierUpdateRequest(BaseModel):
  max_file_upload_kb: int | None = None
  highest_lesson_depth: Literal["highlights", "detailed", "training"] | None = None
  max_sections_per_lesson: int | None = None
  file_upload_quota: int | None = None
  image_upload_quota: int | None = None
  gen_sections_quota: int | None = None
  research_quota: int | None = None
  concurrent_lesson_limit: int | None = None
  concurrent_research_limit: int | None = None
  concurrent_writing_limit: int | None = None
  concurrent_tutor_limit: int | None = None
  tutor_mode_enabled: bool | None = None
  tutor_voice_tier: str | None = None


class TierRecord(BaseModel):
  id: int
  name: str
  max_file_upload_kb: int | None
  highest_lesson_depth: str | None
  max_sections_per_lesson: int | None
  file_upload_quota: int | None
  image_upload_quota: int | None
  gen_sections_quota: int | None
  research_quota: int | None
  concurrent_lesson_limit: int | None
  concurrent_research_limit: int | None
  concurrent_writing_limit: int | None
  concurrent_tutor_limit: int | None
  tutor_mode_enabled: bool
  tutor_voice_tier: str | None


class PromoQuotaOverrideRequest(BaseModel):
  max_file_upload_kb: int | None = None
  file_upload_quota: int | None = None
  image_upload_quota: int | None = None
  gen_sections_quota: int | None = None
  research_quota: int | None = None
  concurrent_lesson_limit: int | None = None
  concurrent_research_limit: int | None = None
  concurrent_writing_limit: int | None = None
  concurrent_tutor_limit: int | None = None
  tutor_mode_enabled: bool | None = None


class UserPromoUpdateRequest(BaseModel):
  expires_at: datetime.datetime
  starts_at: datetime.datetime | None = None
  tier_name: str | None = None
  quota_overrides: PromoQuotaOverrideRequest | None = None
  feature_overrides: dict[str, bool] | None = Field(default=None)


class PromoQuotaOverrideResponse(BaseModel):
  max_file_upload_kb: int | None
  file_upload_quota: int | None
  image_upload_quota: int | None
  gen_sections_quota: int | None
  research_quota: int | None
  concurrent_lesson_limit: int | None
  concurrent_research_limit: int | None
  concurrent_writing_limit: int | None
  concurrent_tutor_limit: int | None
  tutor_mode_enabled: bool | None


class UserPromoResponse(BaseModel):
  user_id: str
  tier_name: str
  starts_at: datetime.datetime | None
  expires_at: datetime.datetime | None
  quota_overrides: PromoQuotaOverrideResponse | None
  feature_overrides: dict[str, bool]


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


def _serialize_tier(tier: SubscriptionTier) -> TierRecord:
  """Convert a subscription tier ORM row into API output."""
  return TierRecord(
    id=int(tier.id),
    name=str(tier.name),
    max_file_upload_kb=tier.max_file_upload_kb,
    highest_lesson_depth=tier.highest_lesson_depth,
    max_sections_per_lesson=tier.max_sections_per_lesson,
    file_upload_quota=tier.file_upload_quota,
    image_upload_quota=tier.image_upload_quota,
    gen_sections_quota=tier.gen_sections_quota,
    research_quota=tier.research_quota,
    concurrent_lesson_limit=tier.concurrent_lesson_limit,
    concurrent_research_limit=tier.concurrent_research_limit,
    concurrent_writing_limit=tier.concurrent_writing_limit,
    concurrent_tutor_limit=tier.concurrent_tutor_limit,
    tutor_mode_enabled=bool(tier.tutor_mode_enabled),
    tutor_voice_tier=tier.tutor_voice_tier,
  )


def _extract_quota_override_payload(payload: PromoQuotaOverrideRequest) -> dict[str, bool | int | None]:
  """Extract non-null quota override fields from request payloads."""
  # Keep payload updates sparse so omitted fields do not overwrite existing values.
  return payload.model_dump(exclude_none=True)


def _serialize_quota_override(override: UserTierOverride | None) -> PromoQuotaOverrideResponse | None:
  """Convert an active tier override row into API output."""
  if override is None:
    return None
  return PromoQuotaOverrideResponse(
    max_file_upload_kb=override.max_file_upload_kb,
    file_upload_quota=override.file_upload_quota,
    image_upload_quota=override.image_upload_quota,
    gen_sections_quota=override.gen_sections_quota,
    research_quota=override.research_quota,
    concurrent_lesson_limit=override.concurrent_lesson_limit,
    concurrent_research_limit=override.concurrent_research_limit,
    concurrent_writing_limit=override.concurrent_writing_limit,
    concurrent_tutor_limit=override.concurrent_tutor_limit,
    tutor_mode_enabled=override.tutor_mode_enabled,
  )


def _serialize_onboarding_profile(user: User) -> OnboardingProfileRecord:
  """Convert user onboarding fields into a stable admin response payload."""
  return OnboardingProfileRecord(
    user_id=str(user.id),
    email=user.email,
    status=user.status,
    onboarding_completed=bool(user.onboarding_completed),
    age=user.age,
    gender=user.gender,
    gender_other=user.gender_other,
    city=user.city,
    country=user.country,
    occupation=user.occupation,
    topics_of_interest=user.topics_of_interest,
    intended_use=user.intended_use,
    intended_use_other=user.intended_use_other,
    primary_language=user.primary_language,
    secondary_language=user.secondary_language,
    accepted_terms_at=user.accepted_terms_at,
    accepted_privacy_at=user.accepted_privacy_at,
    terms_version=user.terms_version,
    privacy_version=user.privacy_version,
  )


@router.post("/roles", response_model=RoleRecord, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("rbac:role_create"))])
async def create_role(request: RoleCreateRequest, db_session: AsyncSession = Depends(get_db)) -> RoleRecord:  # noqa: B008
  """Create a new role for RBAC management."""
  # Persist a new role for administrative configuration.
  role = await create_role_record(db_session, name=request.name, level=request.level, description=request.description)
  return RoleRecord(id=str(role.id), name=role.name, level=role.level, description=role.description)


@router.get("/roles", response_model=PaginatedResponse[RoleWithPermissionsRecord], dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("rbac:role_permissions_update"))])
async def list_roles(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), db_session: AsyncSession = Depends(get_db)) -> PaginatedResponse[RoleWithPermissionsRecord]:  # noqa: B008
  """List RBAC roles for admin role-management UIs."""
  # Fetch paginated role rows for role-management pickers.
  offset = (page - 1) * limit
  roles, total = await list_roles_records(db_session, limit=limit, offset=offset)
  role_ids = [role.id for role in roles]
  role_permissions = await list_permissions_for_roles(db_session, role_ids=role_ids)
  items: list[RoleWithPermissionsRecord] = []
  for role in roles:
    permissions = role_permissions.get(role.id, [])
    permission_records = [PermissionRecord(id=str(permission.id), slug=permission.slug, display_name=permission.display_name, description=permission.description) for permission in permissions]
    items.append(RoleWithPermissionsRecord(id=str(role.id), name=role.name, level=role.level, description=role.description, permissions=permission_records))
  return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/permissions", response_model=list[PermissionRecord], dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("rbac:role_permissions_update"))])
async def list_permissions(db_session: AsyncSession = Depends(get_db)) -> list[PermissionRecord]:  # noqa: B008
  """List available RBAC permissions for role assignment workflows."""
  # Return all permissions so admin UIs can build role grant matrices.
  permissions = await list_permissions_records(db_session)
  return [PermissionRecord(id=str(permission.id), slug=permission.slug, display_name=permission.display_name, description=permission.description) for permission in permissions]


@router.put("/roles/{role_id}/permissions", response_model=RolePermissionsResponse, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("rbac:role_permissions_update"))])
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


@router.get("/users", response_model=PaginatedResponse[UserRecord], dependencies=[Depends(require_permission("user_data:view"))])
async def list_user_accounts(
  page: int = Query(1, ge=1),
  limit: int = Query(20, ge=1, le=100),
  email: str | None = Query(None),
  status: UserStatus | None = Query(None),
  role_id: str | None = Query(None),
  include_archived: bool = Query(False),
  sort_by: str = Query("id"),
  sort_order: str = Query("desc"),
  current_user: User = Depends(get_current_admin_user),
  db_session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[UserRecord]:  # noqa: B008
  """List users with tenant scoping for org admins."""
  # Determine tenant scoping based on the requesting user's role.
  role = await check_tenant_permissions(db_session, current_user)

  # Apply org filtering for tenant-scoped admins.
  org_filter = None
  if role.level == RoleLevel.TENANT:
    org_filter = current_user.org_id

  # Parse role_id if provided
  parsed_role_id = None
  if role_id:
    try:
      parsed_role_id = uuid.UUID(role_id)
    except ValueError:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role_id format.") from None

  # Load users with pagination, filtering, and sorting applied.
  filters = UserListFilters(page=page, limit=limit, email=email, status=status, role_id=parsed_role_id, sort_by=sort_by, sort_order=sort_order, with_archived=include_archived)
  users_with_enrichment, total = await list_users(db_session, org_id=org_filter, filters=filters)
  # Format records for response payloads with enriched data.
  records: list[UserRecord] = []
  for user, role_name, org_name in users_with_enrichment:
    records.append(UserRecord(id=str(user.id), email=user.email, status=user.status, is_archived=bool(user.is_archived), role_id=str(user.role_id), role_name=role_name, org_id=str(user.org_id) if user.org_id else None, org_name=org_name))
  return PaginatedResponse(items=records, total=total, limit=limit, offset=(page - 1) * limit)


@router.patch("/users/{user_id}/discard", response_model=UserStatusResponse, dependencies=[Depends(require_permission("user_data:discard"))])
async def discard_user_account(user_id: str, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
  """Soft-delete a user so they are hidden from active flows."""
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)
  user = await archive_user(db_session, user=user, archived_by=current_user.id)
  role = await get_role_by_id(db_session, user.role_id)
  if role is not None:
    await _update_firebase_claims(db_session, user, role)
  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.patch("/users/{user_id}/restore", response_model=UserStatusResponse, dependencies=[Depends(require_permission("user_data:restore"))])
async def restore_user_account(user_id: str, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
  """Restore a discarded user."""
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)
  user = await restore_archived_user(db_session, user=user)
  role = await get_role_by_id(db_session, user.role_id)
  if role is not None:
    await _update_firebase_claims(db_session, user, role)
  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.get("/users/{user_id}/onboarding", response_model=OnboardingProfileRecord, dependencies=[Depends(require_permission("user_data:view"))])
async def get_user_onboarding_profile(user_id: str, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> OnboardingProfileRecord:  # noqa: B008
  """Return onboarding details so admins can review and approve/reject accounts."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user and enforce tenant-level access scoping.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)
  return _serialize_onboarding_profile(user)


@router.patch("/users/{user_id}/status", response_model=UserStatusResponse, dependencies=[Depends(require_permission("user_data:edit"))])
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
    email_enabled = await is_feature_enabled(db_session, key="feature.notifications.email", org_id=user.org_id, subscription_tier_id=tier_id, user_id=user.id)
    await build_notification_service(settings, email_enabled=email_enabled).notify_account_approved(user_id=user.id, user_email=user.email, full_name=user.full_name)

  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.patch("/users/{user_id}/role", response_model=UserStatusResponse, dependencies=[Depends(require_permission("user_data:edit"))])
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


@router.patch("/users/{user_id}/role-by-name", response_model=UserStatusResponse, dependencies=[Depends(require_permission("user_data:edit"))])
async def update_user_account_role_by_name(user_id: str, request: UserRoleNameUpdateRequest, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
  """Promote or demote a user by assigning a role using its canonical name."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user and enforce tenant-level access scoping.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  current_role = await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  # Resolve target role by name and apply tenant guardrails for global roles.
  target_role = await get_role_by_name(db_session, request.role_name.strip())
  if target_role is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
  if current_role.level == RoleLevel.TENANT and target_role.level == RoleLevel.GLOBAL:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

  # Persist role changes and sync Firebase claims.
  user = await update_user_role(db_session, user=user, role_id=target_role.id)
  await _update_firebase_claims(db_session, user, target_role)
  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.patch("/users/{user_id}/enabled", response_model=UserStatusResponse, dependencies=[Depends(require_permission("user_data:edit"))])
async def update_user_enabled_state(user_id: str, request: UserEnabledUpdateRequest, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
  """Enable or disable a user account explicitly for admin workflows."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user and enforce tenant-level access scoping.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  # Map boolean enabled flag to explicit status transitions with onboarding guardrails.
  next_status = UserStatus.DISABLED
  if request.enabled:
    # Keep incomplete onboarding users in PENDING so approval is still intentional.
    next_status = UserStatus.APPROVED if user.onboarding_completed else UserStatus.PENDING
  user = await update_user_status(db_session, user=user, status=next_status)

  # Sync claims so token context reflects enabled/disabled state immediately.
  role = await get_role_by_id(db_session, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User role missing.")
  await _update_firebase_claims(db_session, user, role)
  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.patch("/users/{user_id}/tier", response_model=UserStatusResponse, dependencies=[Depends(require_permission("user_data:edit"))])
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


@router.patch("/tiers/{tier_name}", response_model=TierRecord, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("config:write_tier"))])
async def update_subscription_tier(tier_name: str, request: TierUpdateRequest, db_session: AsyncSession = Depends(get_db)) -> TierRecord:  # noqa: B008
  """Update subscription tier quotas and limits for admin plan management."""
  # Dependency require_role_level(RoleLevel.GLOBAL) enforces GLOBAL role level.

  # Require at least one patch field so no-op calls are rejected early.
  update_payload = request.model_dump(exclude_none=True)
  if not update_payload:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one field is required.")

  # Resolve the target tier by name.
  tier_result = await db_session.execute(select(SubscriptionTier).where(SubscriptionTier.name == tier_name.strip()))
  tier = tier_result.scalar_one_or_none()
  if tier is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found.")

  # Apply field-level updates onto the ORM row.
  for key, value in update_payload.items():
    setattr(tier, key, value)

  db_session.add(tier)
  await db_session.commit()
  await db_session.refresh(tier)
  return _serialize_tier(tier)


@router.put("/users/{user_id}/promo", response_model=UserPromoResponse, dependencies=[Depends(require_permission("user_data:edit"))])
async def upsert_user_promo(user_id: str, request: UserPromoUpdateRequest, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserPromoResponse:  # noqa: B008
  """Upsert promo tier/quota/feature overrides for a user."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Validate promo window constraints with UTC normalization.
  now = datetime.datetime.now(datetime.UTC)
  starts_at = request.starts_at or now
  if starts_at.tzinfo is None:
    starts_at = starts_at.replace(tzinfo=datetime.UTC)
  expires_at = request.expires_at
  if expires_at.tzinfo is None:
    expires_at = expires_at.replace(tzinfo=datetime.UTC)
  if expires_at <= starts_at:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="expires_at must be after starts_at.")
  if expires_at <= now:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="expires_at must be in the future.")

  # Require at least one promo mutation in the request body.
  has_quota_fields = request.quota_overrides is not None and bool(_extract_quota_override_payload(request.quota_overrides))
  has_feature_fields = request.feature_overrides is not None and len(request.feature_overrides) > 0
  if request.tier_name is None and not has_quota_fields and not has_feature_fields:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one promo update field is required.")

  # Load the target user and enforce tenant scope checks.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  # Validate feature flag keys up front to avoid partial promo writes.
  feature_flag_ids: dict[str, uuid.UUID] = {}
  if has_feature_fields and request.feature_overrides is not None:
    for key in request.feature_overrides.keys():
      feature_flag = await get_feature_flag_by_key(db_session, key=key)
      if feature_flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Feature flag not found: {key}")
      feature_flag_ids[key] = feature_flag.id

  # Update persistent tier assignment when requested.
  if request.tier_name is not None:
    try:
      await set_user_subscription_tier(db_session, user_id=user.id, tier_name=request.tier_name)
    except ValueError as exc:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

  # Upsert a single active tier override row when quota overrides are provided.
  if has_quota_fields and request.quota_overrides is not None:
    quota_payload = _extract_quota_override_payload(request.quota_overrides)
    override_stmt = select(UserTierOverride).where(UserTierOverride.user_id == user.id, UserTierOverride.starts_at <= now, UserTierOverride.expires_at >= now).order_by(UserTierOverride.starts_at.desc(), UserTierOverride.id.desc()).limit(1)
    override_result = await db_session.execute(override_stmt)
    override = override_result.scalar_one_or_none()
    if override is None:
      override = UserTierOverride(user_id=user.id, starts_at=starts_at, expires_at=expires_at)
    else:
      override.starts_at = starts_at
      override.expires_at = expires_at
    for key, value in quota_payload.items():
      setattr(override, key, value)
    db_session.add(override)
    await db_session.commit()

  # Upsert per-user feature overrides for the promo window.
  if has_feature_fields and request.feature_overrides is not None:
    for key, enabled in request.feature_overrides.items():
      await set_user_feature_flag_override(db_session, user_id=user.id, feature_flag_id=feature_flag_ids[key], enabled=bool(enabled), starts_at=starts_at, expires_at=expires_at)

  # Sync claims when tier-level metadata may have changed for immediate auth consistency.
  role = await get_role_by_id(db_session, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User role missing.")
  await _update_firebase_claims(db_session, user, role)

  # Load active promo state for response shaping.
  active_override_stmt = select(UserTierOverride).where(UserTierOverride.user_id == user.id, UserTierOverride.starts_at <= now, UserTierOverride.expires_at >= now).order_by(UserTierOverride.starts_at.desc(), UserTierOverride.id.desc()).limit(1)
  active_override_result = await db_session.execute(active_override_stmt)
  active_override = active_override_result.scalar_one_or_none()
  _tier_id, tier_name_value = await get_user_subscription_tier(db_session, user.id)
  feature_overrides = await list_active_user_feature_overrides(db_session, user_id=user.id, at=now)
  return UserPromoResponse(
    user_id=str(user.id),
    tier_name=tier_name_value,
    starts_at=active_override.starts_at if active_override else None,
    expires_at=active_override.expires_at if active_override else None,
    quota_overrides=_serialize_quota_override(active_override),
    feature_overrides=feature_overrides,
  )


@router.delete("/users/{user_id}/promo", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_permission("user_data:edit"))])
async def delete_user_promo(user_id: str, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> None:  # noqa: B008
  """Delete active promo overrides for a user."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user and enforce tenant scope restrictions.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  # Delete active quota promo rows and all user feature promo overrides.
  now = datetime.datetime.now(datetime.UTC)
  await db_session.execute(delete(UserTierOverride).where(UserTierOverride.user_id == user.id, UserTierOverride.expires_at >= now))
  await db_session.commit()
  await delete_user_feature_flag_overrides(db_session, user_id=user.id)


@router.post("/maintenance/archive-lessons", response_model=MaintenanceJobResponse, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:maintenance_archive_lessons"))])
async def trigger_archive_lessons(background_tasks: BackgroundTasks, current_user: User = Depends(get_current_active_user), settings: Settings = Depends(get_settings), db_session: AsyncSession = Depends(get_db)) -> MaintenanceJobResponse:  # noqa: B008
  """Trigger a maintenance job to archive old lessons based on tier retention limits."""
  job_id = generate_job_id()
  timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
  record = JobRecord(
    job_id=job_id,
    user_id=str(current_user.id),
    job_kind="maintenance",
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
    idempotency_key=f"maintenance:{job_id}",
  )
  repo = get_jobs_repo()
  await repo.create_job(record)
  trigger_job_processing(background_tasks, job_id, settings, auto_process=True)
  return MaintenanceJobResponse(job_id=job_id)


@router.patch("/users/{user_id}/approve", response_model=UserStatusResponse, dependencies=[Depends(get_current_admin_user), Depends(require_permission("user_data:edit"))])
async def approve_user(user_id: str, db_session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
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
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

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
  email_enabled = await is_feature_enabled(db_session, key="feature.notifications.email", org_id=user.org_id, subscription_tier_id=tier_id, user_id=user.id)
  await build_notification_service(settings, email_enabled=email_enabled).notify_account_approved(user_id=user.id, user_email=user.email, full_name=user.full_name)
  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.patch("/users/{user_id}/reject", response_model=UserStatusResponse, dependencies=[Depends(get_current_admin_user), Depends(require_permission("user_data:edit"))])
async def reject_user(user_id: str, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_admin_user)) -> UserStatusResponse:  # noqa: B008
  """Reject a user account after onboarding review."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user record and enforce tenant-level access rules.
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  # Persist rejection status and sync Firebase claims.
  user = await update_user_status(db_session, user=user, status=UserStatus.REJECTED)
  role = await get_role_by_id(db_session, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User role missing.")
  await _update_firebase_claims(db_session, user, role)
  return UserStatusResponse(id=str(user.id), email=user.email, status=user.status)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("user_data:delete_permanent"))])
async def delete_user_account(user_id: str, db_session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> None:  # noqa: B008
  """Delete a user account permanently (GDPR erasure)."""
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  if not settings.superadmin_email:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Superadmin email not configured.")

  try:
    success = await delete_user_and_reassign_content(db_session, user_id=parsed_user_id, superadmin_email=settings.superadmin_email)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
  except RuntimeError as exc:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

  if not success:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")


@router.get("/jobs", response_model=PaginatedResponse[JobRecord], dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:jobs_read"))])
async def list_jobs(
  page: int = Query(1, ge=1),
  limit: int = Query(20, ge=1, le=100),
  status: JobStatus | None = None,
  job_id: str | None = None,
  job_kind: str | None = None,
  user_id: str | None = None,
  target_agent: str | None = None,
  sort_by: str = Query("created_at"),
  sort_order: str = Query("desc"),
) -> PaginatedResponse[JobRecord]:
  """List jobs for admins with pagination, filtering, and sorting to control load and exposure."""
  # Resolve the repository here to keep handler orchestration focused.
  repo = get_jobs_repo()
  # Fetch results and totals together for consistent pagination output.
  items, total = await repo.list_jobs(page=page, limit=limit, status=status, job_id=job_id, job_kind=job_kind, user_id=user_id, target_agent=target_agent, sort_by=sort_by, sort_order=sort_order)
  # Return a typed pagination envelope that callers can rely on.
  return PaginatedResponse(items=items, total=total, limit=limit, offset=(page - 1) * limit)


@router.post("/jobs/{job_id}/resume-from-failure", response_model=JobStatusResponse, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:jobs_read"))])
async def resume_job_from_failure(
  job_id: str,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobStatusResponse:
  """Fork a new resumable lesson-pipeline job from a failed job id."""
  return await resume_job_from_failure_admin(job_id=job_id, settings=settings, background_tasks=background_tasks, sections=None, agents=None)


@router.get("/lessons", response_model=PaginatedResponse[LessonRecord], dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:lessons_read"))])
async def list_lessons(
  page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), topic: str | None = None, status: str | None = None, user_id: str | None = None, is_archived: bool | None = None, sort_by: str = Query("created_at"), sort_order: str = Query("desc")
) -> PaginatedResponse[LessonRecord]:
  """List lessons with pagination, filtering, and sorting to keep responses bounded and predictable."""
  # Resolve the repository here to keep handler orchestration focused.
  repo = get_lessons_repo()
  # Fetch results and totals together for consistent pagination output.
  items, total = await repo.list_lessons(page=page, limit=limit, topic=topic, status=status, user_id=user_id, is_archived=is_archived, sort_by=sort_by, sort_order=sort_order)
  # Return a typed pagination envelope that callers can rely on.
  return PaginatedResponse(items=items, total=total, limit=limit, offset=(page - 1) * limit)


@router.get("/llm-calls", response_model=PaginatedResponse[LlmAuditCallWithCost], dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:llm_calls_read"))])
async def list_llm_calls(
  page: int = Query(1, ge=1),
  limit: int = Query(20, ge=1, le=100),
  job_id: str | None = None,
  agent: str | None = None,
  status: str | None = None,
  provider: str | None = None,
  model: str | None = None,
  request_type: str | None = None,
  sort_by: str = Query("started_at"),
  sort_order: str = Query("desc"),
  db_session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[LlmAuditCallWithCost]:
  """List LLM audit records with pagination, filtering, sorting, and cost data integrated."""
  # Resolve the repository here to keep handler orchestration focused.
  repo = get_audit_repo()
  # Fetch results and totals together for consistent pagination output.
  items, total = await repo.list_records(page=page, limit=limit, job_id=job_id, agent=agent, status=status, provider=provider, model=model, request_type=request_type, sort_by=sort_by, sort_order=sort_order)

  # Load pricing table to calculate costs for each audit record.
  pricing_table = await load_pricing_table(db_session)

  # Convert audit records to response model with cost data.
  items_with_cost: list[LlmAuditCallWithCost] = []
  for item in items:
    prompt_tokens = int(item.prompt_tokens or 0)
    completion_tokens = int(item.completion_tokens or 0)
    call_cost, cost_missing = _calculate_call_cost(prompt_tokens, completion_tokens, item.provider, item.model, pricing_table)

    items_with_cost.append(
      LlmAuditCallWithCost(
        record_id=item.record_id,
        timestamp_request=item.timestamp_request,
        timestamp_response=item.timestamp_response,
        started_at=item.started_at,
        duration_ms=item.duration_ms,
        agent=item.agent,
        provider=item.provider,
        model=item.model,
        lesson_topic=item.lesson_topic,
        request_payload=item.request_payload,
        response_payload=item.response_payload,
        prompt_tokens=item.prompt_tokens,
        completion_tokens=item.completion_tokens,
        total_tokens=item.total_tokens,
        request_type=item.request_type,
        purpose=item.purpose,
        call_index=item.call_index,
        job_id=item.job_id,
        status=item.status,
        error_message=item.error_message,
        cost_usd=call_cost,
        cost_missing=cost_missing,
      )
    )

  # Return a typed pagination envelope that callers can rely on.
  return PaginatedResponse(items=items_with_cost, total=total, limit=limit, offset=(page - 1) * limit)


@router.get("/llm-pricing", response_model=LlmPricingResponse, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:llm_calls_read"))])
async def get_llm_pricing(params: LlmPricingQuery = Depends(), db_session: AsyncSession = Depends(get_db)) -> LlmPricingResponse:  # noqa: B008
  """Aggregate LLM pricing by a target type and id."""
  # Parse optional date filters before querying audit rows.
  parsed_start = _parse_iso_datetime(params.start_at)
  parsed_end = _parse_iso_datetime(params.end_at)
  if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_at must be before end_at.")

  # Fetch audit rows that match the requested target.
  repo = get_audit_repo()
  try:
    rows = await repo.list_pricing_rows_for_target(target_type=params.target_type, target_id=params.target_id, start_at=parsed_start, end_at=parsed_end)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

  # Load active pricing configuration for cost calculations.
  pricing_table = await load_pricing_table(db_session)

  total_cost = 0.0
  total_prompt_tokens = 0
  total_completion_tokens = 0
  total_tokens = 0
  cost_missing_count = 0
  calls: list[LlmPricingCall] = []

  # Accumulate totals and optional per-call rows.
  for row in rows:
    prompt_tokens = int(row.prompt_tokens or 0)
    completion_tokens = int(row.completion_tokens or 0)
    resolved_total = _resolve_total_tokens(prompt_tokens, completion_tokens, row.total_tokens)
    call_cost, cost_missing = _calculate_call_cost(prompt_tokens, completion_tokens, row.provider, row.model, pricing_table)
    total_cost += call_cost
    total_prompt_tokens += prompt_tokens
    total_completion_tokens += completion_tokens
    total_tokens += resolved_total
    if cost_missing:
      cost_missing_count += 1

    if params.include_calls:
      # Assemble the call payload to keep the constructor call short.
      call_payload = {
        "record_id": row.record_id,
        "started_at": row.started_at,
        "provider": row.provider,
        "model": row.model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": resolved_total,
        "cost_usd": call_cost,
        "cost_missing": cost_missing,
        "status": row.status,
        "job_id": row.job_id,
        "lesson_id": row.lesson_id,
        "section_id": row.section_id,
        "illustration_id": row.illustration_id,
        "tutor_id": row.tutor_id,
        "fenster_id": row.fenster_id,
        "fenster_public_id": row.fenster_public_id,
      }
      calls.append(LlmPricingCall(**call_payload))

  # Summarize the aggregate cost and usage totals.
  # Build the summary payload to keep the constructor call short.
  summary_payload = {
    "target_type": params.target_type,
    "target_id": params.target_id,
    "total_cost_usd": round(total_cost, 6),
    "total_prompt_tokens": total_prompt_tokens,
    "total_completion_tokens": total_completion_tokens,
    "total_tokens": total_tokens,
    "call_count": len(rows),
    "cost_missing_count": cost_missing_count,
  }
  summary = LlmPricingSummary(**summary_payload)
  return LlmPricingResponse(summary=summary, calls=calls)


@router.get("/llm-pricing/jobs", response_model=LlmJobCostsResponse, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:llm_calls_read"))])
async def get_llm_job_costs(job_ids: list[str] = Query(...), start_at: str | None = None, end_at: str | None = None, db_session: AsyncSession = Depends(get_db)) -> LlmJobCostsResponse:  # noqa: B008
  """Return aggregated LLM pricing totals for a list of job ids."""
  # Parse optional date filters before querying audit rows.
  parsed_start = _parse_iso_datetime(start_at)
  parsed_end = _parse_iso_datetime(end_at)
  if parsed_start is not None and parsed_end is not None and parsed_start > parsed_end:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_at must be before end_at.")

  # Fetch audit rows for the requested job ids.
  repo = get_audit_repo()
  rows = await repo.list_pricing_rows_for_jobs(job_ids=job_ids, start_at=parsed_start, end_at=parsed_end)

  # Load active pricing configuration for cost calculations.
  pricing_table = await load_pricing_table(db_session)

  # Seed totals with requested job ids to keep ordering stable.
  totals_by_job: dict[str, dict[str, int | float]] = {}
  for job_id in job_ids:
    totals_by_job[job_id] = {"total_cost": 0.0, "total_tokens": 0, "call_count": 0, "cost_missing": 0}

  # Accumulate totals from each audit row.
  for row in rows:
    if row.job_id is None:
      continue

    if row.job_id not in totals_by_job:
      totals_by_job[row.job_id] = {"total_cost": 0.0, "total_tokens": 0, "call_count": 0, "cost_missing": 0}

    prompt_tokens = int(row.prompt_tokens or 0)
    completion_tokens = int(row.completion_tokens or 0)
    resolved_total = _resolve_total_tokens(prompt_tokens, completion_tokens, row.total_tokens)
    call_cost, cost_missing = _calculate_call_cost(prompt_tokens, completion_tokens, row.provider, row.model, pricing_table)
    totals_by_job[row.job_id]["total_cost"] = float(totals_by_job[row.job_id]["total_cost"]) + call_cost
    totals_by_job[row.job_id]["total_tokens"] = int(totals_by_job[row.job_id]["total_tokens"]) + resolved_total
    totals_by_job[row.job_id]["call_count"] = int(totals_by_job[row.job_id]["call_count"]) + 1
    if cost_missing:
      totals_by_job[row.job_id]["cost_missing"] = int(totals_by_job[row.job_id]["cost_missing"]) + 1

  # Serialize totals in the same order as requested.
  items: list[LlmJobCostRecord] = []
  for job_id in job_ids:
    totals = totals_by_job.get(job_id)
    if totals is None:
      continue
    # Assemble the job totals payload to keep the constructor call short.
    job_payload = {"job_id": job_id, "total_cost_usd": round(float(totals["total_cost"]), 6), "total_tokens": int(totals["total_tokens"]), "call_count": int(totals["call_count"]), "cost_missing_count": int(totals["cost_missing"])}
    items.append(LlmJobCostRecord(**job_payload))

  return LlmJobCostsResponse(items=items)


@router.post("/sections/backfill-shorthand", response_model=SectionShorthandBackfillResponse, dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:artifacts_read"))])
async def backfill_sections_shorthand(request: SectionShorthandBackfillRequest) -> SectionShorthandBackfillResponse:
  """Backfill section shorthand content from stored raw section JSON."""
  result = await backfill_section_shorthand(request.section_ids)
  return SectionShorthandBackfillResponse(updated_section_ids=result.updated_section_ids, missing_section_ids=result.missing_section_ids, failed=result.failed)


# Individual User Endpoint
class UserDetailResponse(BaseModel):
  """Complete user details for admin view."""

  id: str
  firebase_uid: str
  email: str
  full_name: str | None
  provider: str | None
  role_id: str
  role_name: str | None
  org_id: str | None
  org_name: str | None
  status: UserStatus
  is_archived: bool
  auth_method: str
  profession: str | None
  city: str | None
  country: str | None
  age: int | None
  photo_url: str | None
  gender: str | None
  gender_other: str | None
  occupation: str | None
  topics_of_interest: list[str] | None
  intended_use: str | None
  intended_use_other: str | None
  primary_language: str | None
  secondary_language: str | None
  onboarding_completed: bool
  accepted_terms_at: str | None
  accepted_privacy_at: str | None
  terms_version: str | None
  privacy_version: str | None
  created_at: str
  updated_at: str


@router.get("/users/{user_id}/details", response_model=UserDetailResponse, dependencies=[Depends(require_permission("user_data:view"))])
async def get_user_details(user_id: str, current_user: User = Depends(get_current_admin_user), db_session: AsyncSession = Depends(get_db)) -> UserDetailResponse:  # noqa: B008
  """Get complete user details for admin view."""
  # Validate user id inputs early to avoid leaking query behavior.
  try:
    parsed_user_id = uuid.UUID(user_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc

  # Load the user record with role and org details
  stmt = select(User, Role.name, Role.id).outerjoin(Role, Role.id == User.role_id).where(User.id == parsed_user_id)
  result = await db_session.execute(stmt)
  row = result.one_or_none()

  if row is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

  user, role_name, _ = row

  # Check tenant permissions
  await check_tenant_permissions(db_session, current_user, target_org_id=user.org_id)

  # Get org name if applicable
  org_name = None
  if user.org_id:
    from app.schema.sql import Organization

    org_stmt = select(Organization.name).where(Organization.id == user.org_id)
    org_result = await db_session.execute(org_stmt)
    org_name = org_result.scalar_one_or_none()

  return UserDetailResponse(
    id=str(user.id),
    firebase_uid=user.firebase_uid,
    email=user.email,
    full_name=user.full_name,
    provider=user.provider,
    role_id=str(user.role_id),
    role_name=role_name,
    org_id=str(user.org_id) if user.org_id else None,
    org_name=org_name,
    status=user.status,
    is_archived=bool(user.is_archived),
    auth_method=user.auth_method.value,
    profession=user.profession,
    city=user.city,
    country=user.country,
    age=user.age,
    photo_url=user.photo_url,
    gender=user.gender,
    gender_other=user.gender_other,
    occupation=user.occupation,
    topics_of_interest=user.topics_of_interest,
    intended_use=user.intended_use,
    intended_use_other=user.intended_use_other,
    primary_language=user.primary_language,
    secondary_language=user.secondary_language,
    onboarding_completed=user.onboarding_completed,
    accepted_terms_at=user.accepted_terms_at.isoformat() if user.accepted_terms_at else None,
    accepted_privacy_at=user.accepted_privacy_at.isoformat() if user.accepted_privacy_at else None,
    terms_version=user.terms_version,
    privacy_version=user.privacy_version,
    created_at=user.created_at.isoformat(),
    updated_at=user.updated_at.isoformat(),
  )


# Fenster Widgets Endpoint
@router.get("/fenster", dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:artifacts_read"))])
async def list_fenster_widgets(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), fenster_id: str | None = None, widget_type: str | None = None, sort_by: str = Query("created_at"), sort_order: str = Query("desc")):
  """List fenster widgets with pagination, filtering, and sorting."""
  from app.storage.postgres_fenster_repo import PostgresFensterRepository

  repo = PostgresFensterRepository()
  items, total = await repo.list_fenster(page=page, limit=limit, fenster_id=fenster_id, widget_type=widget_type, sort_by=sort_by, sort_order=sort_order)
  return encode_msgspec_response(MsgspecPaginatedResponse(items=items, total=total, limit=limit, offset=(page - 1) * limit))


# Illustrations Endpoint
@router.get("/illustrations", dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:artifacts_read"))])
async def list_illustrations(
  page: int = Query(1, ge=1),
  limit: int = Query(20, ge=1, le=100),
  status: str | None = None,
  is_archived: bool | None = None,
  mime_type: str | None = None,
  section_id: int | None = None,
  sort_by: str = Query("created_at"),
  sort_order: str = Query("desc"),
):
  """List illustrations with pagination, filtering, and sorting."""
  from app.storage.postgres_illustrations_repo import PostgresIllustrationsRepository

  repo = PostgresIllustrationsRepository()
  items, total = await repo.list_illustrations(page=page, limit=limit, status=status, is_archived=is_archived, mime_type=mime_type, section_id=section_id, sort_by=sort_by, sort_order=sort_order)
  return encode_msgspec_response(MsgspecPaginatedResponse(items=items, total=total, limit=limit, offset=(page - 1) * limit))


# Tutor Endpoint
@router.get("/tutors", dependencies=[Depends(require_role_level(RoleLevel.GLOBAL)), Depends(require_permission("admin:artifacts_read"))])
async def list_tutors(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), job_id: str | None = None, section_number: int | None = None, sort_by: str = Query("created_at"), sort_order: str = Query("desc")):
  """List tutors with pagination, filtering, and sorting."""
  from app.storage.postgres_tutor_repo import PostgresTutorRepository

  repo = PostgresTutorRepository()
  items, total = await repo.list_tutors(page=page, limit=limit, job_id=job_id, section_number=section_number, sort_by=sort_by, sort_order=sort_order)
  return encode_msgspec_response(MsgspecPaginatedResponse(items=items, total=total, limit=limit, offset=(page - 1) * limit))
