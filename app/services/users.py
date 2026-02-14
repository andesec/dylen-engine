"""User CRUD helpers implemented with SQLAlchemy ORM.

This module centralizes how and why user records are created/updated so transport
layers (routes, auth dependencies, workers) don't duplicate query logic.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass

from app.schema.quotas import SubscriptionTier, UserUsageMetrics
from app.schema.sql import AuthMethod, Role, User, UserStatus
from app.schema.users import OnboardingRequest
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

UserWithRoleOrg = tuple[User, str | None, str | None]
ListUsersResult = tuple[list[UserWithRoleOrg], int]


@dataclass(slots=True)
class UserListFilters:
  """Container for optional user-list filters to keep service signatures concise."""

  page: int = 1
  limit: int = 20
  email: str | None = None
  status: UserStatus | None = None
  role_id: uuid.UUID | None = None
  sort_by: str = "id"
  sort_order: str = "desc"
  with_archived: bool = False


async def get_user_by_firebase_uid(session: AsyncSession, firebase_uid: str) -> User | None:
  """Fetch a user by Firebase UID to support auth and session validation."""
  # Use a direct lookup to keep auth path predictable.
  stmt = select(User).where(User.firebase_uid == firebase_uid, User.is_archived.is_(False))
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
  """Fetch a user by primary key to support admin flows and background workers."""
  # Use primary-key lookup to keep admin flows fast.
  stmt = select(User).where(User.id == user_id)
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


async def get_user_tier_name(session: AsyncSession, user_id: uuid.UUID) -> str:
  """Fetch the subscription tier name for a user."""
  stmt = select(SubscriptionTier.name).join(UserUsageMetrics, UserUsageMetrics.subscription_tier_id == SubscriptionTier.id).where(UserUsageMetrics.user_id == user_id)
  result = await session.execute(stmt)
  tier_name = result.scalar_one_or_none()
  return tier_name or "Free"


async def get_user_subscription_tier(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, str]:
  """Fetch the subscription tier id and name for a user."""
  # Join usage metrics to tier metadata so callers can use both id and name.
  stmt = select(SubscriptionTier.id, SubscriptionTier.name).join(UserUsageMetrics, UserUsageMetrics.subscription_tier_id == SubscriptionTier.id).where(UserUsageMetrics.user_id == user_id)
  result = await session.execute(stmt)
  row = result.one_or_none()
  if row is not None:
    return int(row[0]), str(row[1])

  # Fall back to the Free tier when usage metrics are missing.
  tier_stmt = select(SubscriptionTier).where(SubscriptionTier.name == "Free")
  tier_result = await session.execute(tier_stmt)
  free_tier = tier_result.scalar_one_or_none()
  if not free_tier:
    logger.error("Default 'Free' subscription tier missing; run migrations to apply seed data.")
    raise RuntimeError("Default 'Free' subscription tier not available.")
  return int(free_tier.id), str(free_tier.name)


async def set_user_subscription_tier(session: AsyncSession, *, user_id: uuid.UUID, tier_name: str) -> tuple[int, str]:
  """Update a user's subscription tier id by tier name and return the resolved tier.

  How/Why:
    - Tier upgrades/downgrades must take effect immediately for feature flags and runtime config resolution.
    - Usage rows are the source of truth for tier selection in this service.
  """
  normalized = (tier_name or "").strip()
  if normalized == "":
    raise ValueError("tier_name is required.")
  tier_stmt = select(SubscriptionTier).where(SubscriptionTier.name == normalized)
  tier_result = await session.execute(tier_stmt)
  tier = tier_result.scalar_one_or_none()
  if tier is None:
    raise ValueError("Unknown subscription tier.")
  usage = await session.get(UserUsageMetrics, user_id)
  if usage is None:
    # Ensure the usage row exists so downstream quota and flag checks never 500.
    await ensure_usage_row(session, user_id, tier_id=int(tier.id))
    return int(tier.id), str(tier.name)
  # Persist tier changes so future requests evaluate the correct per-tier defaults.
  usage.subscription_tier_id = int(tier.id)
  session.add(usage)
  await session.commit()
  return int(tier.id), str(tier.name)


def resolve_auth_method(provider: str | None) -> AuthMethod:
  """Resolve auth method from provider so RBAC status stays consistent with Firebase sign-in."""
  # Map Firebase provider identifiers into the enum used by RBAC.
  if provider in {"password", "email"}:
    return AuthMethod.NATIVE

  # Default to Google SSO until other providers are configured.
  return AuthMethod.GOOGLE_SSO


async def create_user(
  session: AsyncSession,
  *,
  firebase_uid: str,
  email: str,
  full_name: str | None,
  profession: str | None,
  city: str | None,
  country: str | None,
  age: int | None,
  photo_url: str | None,
  provider: str | None,
  role_id: uuid.UUID,
  org_id: uuid.UUID | None,
  status: UserStatus,
  auth_method: AuthMethod,
) -> User:
  """Create a new user row and commit it so downstream flows can rely on it."""
  # Persist the DB record before returning so callers can use the generated id.
  user_create_kwargs = {
    "id": uuid.uuid4(),
    "firebase_uid": firebase_uid,
    "email": email,
    "full_name": full_name,
    "profession": profession,
    "city": city,
    "country": country,
    "age": age,
    "photo_url": photo_url,
    "provider": provider,
    "role_id": role_id,
    "org_id": org_id,
    "status": status,
    "auth_method": auth_method,
  }
  user = User(**user_create_kwargs)
  session.add(user)
  await session.commit()
  await session.refresh(user)
  await ensure_usage_row(session, user.id)
  # Provision strict tenant flag rows when users are created inside an organization.
  if org_id is not None:
    from app.services.feature_flags import ensure_org_feature_flag_rows

    await ensure_org_feature_flag_rows(session, org_id=org_id)
  return user


async def update_user_provider(session: AsyncSession, *, user: User, provider: str) -> User:
  """Update the auth provider to keep the local user record in sync with Firebase."""
  # Avoid unnecessary writes by checking for changes before committing.
  if user.provider == provider:
    return user

  # Update provider and derived auth method to match the IdP.
  user.provider = provider
  user.auth_method = resolve_auth_method(provider)
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def update_user_status(session: AsyncSession, *, user: User, status: UserStatus) -> User:
  """Update user status so access control reflects the latest admin decision."""
  # Skip writes when the status already matches the requested value.
  if user.status == status:
    return user

  # Persist status updates before notifying other systems.
  user.status = status
  session.add(user)
  await session.commit()
  await session.refresh(user)

  # Initialize quotas when a user is approved to ensure deterministic bucket availability.
  if status == UserStatus.APPROVED:
    from app.services.quota_buckets import initialize_user_quotas

    await initialize_user_quotas(session, user.id)

  return user


async def update_user_role(session: AsyncSession, *, user: User, role_id: uuid.UUID) -> User:
  """Update user role to align access with RBAC assignments."""
  # Avoid writes when role assignment is already current.
  if user.role_id == role_id:
    return user

  # Persist role changes before updating any downstream claims.
  user.role_id = role_id
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def complete_user_onboarding(session: AsyncSession, *, user: User, data: OnboardingRequest) -> User:
  """Apply onboarding data to the user record and transition status."""
  if user.onboarding_completed:
    return user

  # Update User record
  user.age = data.basic.age
  user.gender = data.basic.gender
  user.gender_other = data.basic.gender_other
  user.city = data.basic.city
  user.country = data.basic.country
  user.occupation = data.personalization.occupation

  # JSONB field: assignment ensures change tracking
  user.topics_of_interest = data.personalization.topics_of_interest
  user.intended_use = data.personalization.intended_use
  user.intended_use_other = data.personalization.intended_use_other
  user.primary_language = data.personalization.primary_language
  user.secondary_language = data.personalization.secondary_language

  user.accepted_terms_at = datetime.datetime.now(datetime.UTC)
  user.accepted_privacy_at = datetime.datetime.now(datetime.UTC)
  user.terms_version = data.legal.terms_version
  user.privacy_version = data.legal.privacy_version

  user.onboarding_completed = True
  user.status = UserStatus.PENDING

  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def list_users(session: AsyncSession, *, org_id: uuid.UUID | None, filters: UserListFilters | None = None) -> ListUsersResult:
  """List users with optional org scoping, filtering, and sorting to support admin experiences.

  Returns tuples of (User, role_name, org_name) for enriched API responses.
  """
  # Create a default filters object when callers omit optional values.
  filters = filters or UserListFilters()

  # Calculate offset from page
  offset = (filters.page - 1) * filters.limit

  # Build base query with joins for enriched data
  from app.schema.sql import Organization

  stmt = select(User, Role.name, Organization.name).outerjoin(Role, Role.id == User.role_id).outerjoin(Organization, Organization.id == User.org_id)
  if not filters.with_archived:
    stmt = stmt.where(User.is_archived.is_(False))

  # Build base query scoped by tenant when required.
  if org_id:
    stmt = stmt.where(User.org_id == org_id)

  # Apply additional filters
  if filters.email:
    stmt = stmt.where(User.email == filters.email)
  if filters.status:
    stmt = stmt.where(User.status == filters.status)
  if filters.role_id:
    stmt = stmt.where(User.role_id == filters.role_id)

  # Apply sorting
  sort_column = User.id  # default
  if filters.sort_by == "id":
    sort_column = User.id
  elif filters.sort_by == "email":
    sort_column = User.email
  elif filters.sort_by == "status":
    sort_column = User.status
  elif filters.sort_by == "created_at":
    sort_column = User.created_at

  if filters.sort_order.lower() == "asc":
    stmt = stmt.order_by(sort_column.asc())
  else:
    stmt = stmt.order_by(sort_column.desc())

  # Apply pagination in the database for predictable performance.
  stmt = stmt.limit(filters.limit).offset(offset)
  result = await session.execute(stmt)
  rows = result.all()

  # Extract users with enriched data
  users_with_enrichment = [(row[0], row[1], row[2]) for row in rows]

  # Compute total using the same filter for pagination metadata.
  count_stmt = select(func.count(User.id))
  if not filters.with_archived:
    count_stmt = count_stmt.where(User.is_archived.is_(False))
  if org_id:
    count_stmt = count_stmt.where(User.org_id == org_id)
  if filters.email:
    count_stmt = count_stmt.where(User.email == filters.email)
  if filters.status:
    count_stmt = count_stmt.where(User.status == filters.status)
  if filters.role_id:
    count_stmt = count_stmt.where(User.role_id == filters.role_id)

  count_result = await session.execute(count_stmt)
  total = int(count_result.scalar_one())
  return users_with_enrichment, total


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> bool:
  """Delete a user and all associated data (via cascade) to support GDPR erasure."""
  user = await session.get(User, user_id)
  if not user:
    return False

  await session.delete(user)
  await session.commit()
  return True


async def delete_user_and_reassign_content(session: AsyncSession, *, user_id: uuid.UUID, superadmin_email: str) -> bool:
  """Delete a user after reassigning owned content to the superadmin account."""
  if not superadmin_email:
    raise ValueError("superadmin_email is required for reassignment.")

  user = await session.get(User, user_id)
  if not user:
    return False

  superadmin_result = await session.execute(select(User).where(User.email == superadmin_email))
  superadmin = superadmin_result.scalar_one_or_none()
  if superadmin is None:
    raise RuntimeError("Superadmin user not found.")

  if superadmin.id == user.id:
    raise ValueError("Refusing to delete the superadmin user.")

  old_user_id = str(user.id)
  new_user_id = str(superadmin.id)

  from app.schema.data_transfer import DataTransferRun
  from app.schema.email_delivery_logs import EmailDeliveryLog
  from app.schema.feature_flags import UserFeatureFlagOverride
  from app.schema.fenster import FensterWidget
  from app.schema.illustrations import Illustration
  from app.schema.jobs import Job
  from app.schema.lesson_requests import LessonRequest
  from app.schema.lessons import FreeText, InputLine, Lesson
  from app.schema.notifications import InAppNotification
  from app.schema.quotas import UserQuotaBucket, UserQuotaReservation, UserTierOverride, UserUsageLog, UserUsageMetrics
  from app.schema.runtime_config import RuntimeConfigValue
  from app.schema.sql import LLMAuditLog
  from app.schema.tutor import Tutor
  from app.schema.widgets_content import (
    AsciiDiagramWidget,
    ChecklistWidget,
    CodeEditorWidget,
    CompareWidget,
    FillBlankWidget,
    FlipcardsWidget,
    InteractiveTerminalWidget,
    MarkdownWidget,
    McqsWidget,
    StepFlowWidget,
    SwipeCardWidget,
    TableDataWidget,
    TerminalDemoWidget,
    TranslationWidget,
    TreeviewWidget,
  )

  await session.execute(update(Lesson).where(Lesson.user_id == old_user_id).values(user_id=new_user_id))
  await session.execute(update(LessonRequest).where(LessonRequest.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(Job).where(Job.user_id == old_user_id).values(user_id=new_user_id))
  await session.execute(update(MarkdownWidget).where(MarkdownWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(FlipcardsWidget).where(FlipcardsWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(TranslationWidget).where(TranslationWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(FillBlankWidget).where(FillBlankWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(TableDataWidget).where(TableDataWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(CompareWidget).where(CompareWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(SwipeCardWidget).where(SwipeCardWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(StepFlowWidget).where(StepFlowWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(AsciiDiagramWidget).where(AsciiDiagramWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(ChecklistWidget).where(ChecklistWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(InteractiveTerminalWidget).where(InteractiveTerminalWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(TerminalDemoWidget).where(TerminalDemoWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(CodeEditorWidget).where(CodeEditorWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(TreeviewWidget).where(TreeviewWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(McqsWidget).where(McqsWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(Tutor).where(Tutor.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(Illustration).where(Illustration.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(FensterWidget).where(FensterWidget.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(InputLine).where(InputLine.creator_id == old_user_id).values(creator_id=new_user_id))
  await session.execute(update(FreeText).where(FreeText.creator_id == old_user_id).values(creator_id=new_user_id))

  await session.execute(delete(UserFeatureFlagOverride).where(UserFeatureFlagOverride.user_id == user.id))
  await session.execute(delete(UserTierOverride).where(UserTierOverride.user_id == user.id))
  await session.execute(delete(UserUsageLog).where(UserUsageLog.user_id == user.id))
  await session.execute(delete(UserQuotaReservation).where(UserQuotaReservation.user_id == user.id))
  await session.execute(delete(UserQuotaBucket).where(UserQuotaBucket.user_id == user.id))
  await session.execute(delete(UserUsageMetrics).where(UserUsageMetrics.user_id == user.id))
  await session.execute(delete(InAppNotification).where(InAppNotification.user_id == user.id))
  await session.execute(delete(RuntimeConfigValue).where(RuntimeConfigValue.user_id == user.id))
  await session.execute(delete(EmailDeliveryLog).where(EmailDeliveryLog.user_id == user.id))
  await session.execute(delete(DataTransferRun).where(DataTransferRun.requested_by == user.id))
  await session.execute(delete(LLMAuditLog).where(LLMAuditLog.user_id == user.id))

  await session.delete(user)
  await session.commit()
  return True


async def archive_user(session: AsyncSession, *, user: User, archived_by: uuid.UUID | None) -> User:
  """Soft-delete a user so it is hidden while data remains recoverable."""
  if user.is_archived:
    return user
  user.is_archived = True
  user.archived_at = datetime.datetime.now(datetime.UTC)
  user.archived_by = archived_by
  user.status = UserStatus.DISABLED
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def restore_archived_user(session: AsyncSession, *, user: User) -> User:
  """Restore an archived user to normal visibility."""
  if not user.is_archived:
    return user
  user.is_archived = False
  user.archived_at = None
  user.archived_by = None
  if user.status == UserStatus.DISABLED:
    user.status = UserStatus.PENDING
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def ensure_usage_row(session: AsyncSession, user_id: uuid.UUID, *, tier_id: int | None = None) -> UserUsageMetrics:
  """Ensure a usage metrics row exists for the user using atomic UPSERT."""

  # Default to provided tier or 'Free' tier if not specified.
  if tier_id is None:
    tier_stmt = select(SubscriptionTier).where(SubscriptionTier.name == "Free")
    tier_result = await session.execute(tier_stmt)
    free_tier = tier_result.scalar_one_or_none()
    if not free_tier:
      # Critical configuration error: 'Free' tier must exist for account creation.
      logger.error("Default 'Free' subscription tier missing; run migrations to apply seed data. Run 'alembic upgrade head' to apply seed migrations.")
      raise RuntimeError("Default 'Free' subscription tier not available.")
    tier_id = free_tier.id

  # Use INSERT ... ON CONFLICT DO UPDATE to ensure the tier stays in sync
  # with the intended state during bootstrap or script-driven updates.
  stmt = (
    insert(UserUsageMetrics)
    .values(user_id=user_id, subscription_tier_id=tier_id, files_uploaded_count=0, images_uploaded_count=0, sections_generated_count=0, research_usage_count=0)
    .on_conflict_do_update(index_elements=["user_id"], set_={"subscription_tier_id": tier_id})
  )

  await session.execute(stmt)
  await session.commit()

  # Fetch the row, which is now guaranteed to exist (either inserted or already there)
  usage = await session.get(UserUsageMetrics, user_id)

  # Also trigger quota initialization if the user is already approved.
  user = await session.get(User, user_id)
  if user and user.status == UserStatus.APPROVED:
    from app.services.quota_buckets import initialize_user_quotas

    await initialize_user_quotas(session, user_id)
    # Persist quota bucket initialization done in nested transaction contexts.
    await session.commit()

  return usage
