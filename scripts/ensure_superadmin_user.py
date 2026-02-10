"""Ensure the canonical superadmin user is synced between Firebase and Postgres."""

from __future__ import annotations

import asyncio
import logging
import uuid

import firebase_admin
from app.core.database import get_session_factory
from app.core.firebase import build_rbac_claims, initialize_firebase, set_custom_claims
from app.schema.quotas import SubscriptionTier
from app.schema.sql import AuthMethod, Role, User, UserStatus
from app.services.rbac import list_permission_slugs_for_role
from app.services.users import ensure_usage_row
from firebase_admin import auth
from sqlalchemy import or_, select
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger("scripts.ensure_superadmin_user")

SUPERADMIN_EMAIL = "dylen.app@gmail.com"
SUPERADMIN_PROVIDER = "google.com"
SUPERADMIN_ROLE_NAME = "Super Admin"
SUPERADMIN_TIER_NAME = "Pro"


async def ensure_superadmin_user(*, email: str = SUPERADMIN_EMAIL) -> None:
  """Reconcile the superadmin account against Firebase and Postgres state."""
  # Initialize Firebase Admin SDK before issuing identity lookups.
  initialize_firebase()

  # Skip bootstrap if Firebase is not configured (e.g. in CI or limited environments).
  if not firebase_admin._apps:
    logger.warning("Firebase not initialized; skipping superadmin bootstrap.")
    return

  # Resolve the canonical Firebase user by email and fail-fast if missing.
  # Use a timeout to ensure startup does not hang indefinitely on network issues.
  try:
    firebase_user = await asyncio.wait_for(run_in_threadpool(auth.get_user_by_email, email), timeout=10.0)
    # Ensure existing superadmin users have email verified so SSO works.
    if not firebase_user.email_verified:
      logger.info("Superadmin found but email not verified; updating Firebase record.")
      await run_in_threadpool(auth.update_user, firebase_user.uid, email_verified=True)

  except TimeoutError:
    raise RuntimeError("Timeout connecting to Firebase during superadmin check.") from None
  except auth.UserNotFoundError:
    logger.info("Superadmin not found in Firebase; creating new account for %s.", email)
    try:
      firebase_user = await asyncio.wait_for(run_in_threadpool(auth.create_user, email=email, email_verified=True, display_name="Dylen Super Admin"), timeout=10.0)
    except Exception as exc:
      raise RuntimeError(f"Failed to create superadmin Firebase account for {email}.") from exc
  except Exception as exc:  # noqa: BLE001
    raise RuntimeError(f"Superadmin Firebase account lookup failed for {email}.") from exc

  # Resolve a DB session factory so reconciliation can run inside app startup and scripts.
  session_factory = get_session_factory()
  if session_factory is None:
    raise RuntimeError("Database session factory unavailable (DYLEN_PG_DSN missing).")

  async with session_factory() as session:
    # Load the required role and tier records used by the bootstrap identity.
    role_result = await session.execute(select(Role).where(Role.name == SUPERADMIN_ROLE_NAME))
    superadmin_role = role_result.scalar_one_or_none()
    if superadmin_role is None:
      raise RuntimeError("Super Admin role not found; run seed scripts.")
    tier_result = await session.execute(select(SubscriptionTier).where(SubscriptionTier.name == SUPERADMIN_TIER_NAME))
    pro_tier = tier_result.scalar_one_or_none()
    if pro_tier is None:
      raise RuntimeError("Pro tier not found; run seed scripts.")

    # Resolve any existing row by email or Firebase UID before updating identity fields.
    user_result = await session.execute(select(User).where(or_(User.email == email, User.firebase_uid == firebase_user.uid)))
    user = user_result.scalar_one_or_none()
    if user is None:
      # Create the superadmin row when missing so first startup after migration is self-healing.
      user = User(
        id=uuid.uuid4(),
        firebase_uid=firebase_user.uid,
        email=email,
        full_name=firebase_user.display_name,
        photo_url=firebase_user.photo_url,
        provider=SUPERADMIN_PROVIDER,
        role_id=superadmin_role.id,
        org_id=None,
        status=UserStatus.APPROVED,
        auth_method=AuthMethod.GOOGLE_SSO,
        onboarding_completed=True,
      )
    else:
      # Force canonical superadmin attributes so login/admin access remains deterministic.
      user.firebase_uid = firebase_user.uid
      user.email = email
      user.provider = SUPERADMIN_PROVIDER
      user.role_id = superadmin_role.id
      user.status = UserStatus.APPROVED
      user.auth_method = AuthMethod.GOOGLE_SSO
      user.onboarding_completed = True
      if firebase_user.display_name:
        user.full_name = firebase_user.display_name
      if firebase_user.photo_url:
        user.photo_url = firebase_user.photo_url

    session.add(user)
    await session.commit()
    await session.refresh(user)

    # Enforce Pro tier usage metrics for superadmin account behavior and claim hydration.
    await ensure_usage_row(session, user.id, tier_id=int(pro_tier.id))

    # Recompute and push Firebase custom claims so auth tokens include latest RBAC context.
    permissions = await list_permission_slugs_for_role(session, role_id=superadmin_role.id)
    claims = build_rbac_claims(role_id=str(superadmin_role.id), role_name=superadmin_role.name, role_level=superadmin_role.level, org_id=None, status=user.status, tier=SUPERADMIN_TIER_NAME, permissions=permissions)
    await run_in_threadpool(set_custom_claims, user.firebase_uid, claims)

  logger.info("Superadmin bootstrap verified for %s.", email)


def main() -> None:
  """Run superadmin reconciliation from the command line."""
  logging.basicConfig(level=logging.INFO)
  asyncio.run(ensure_superadmin_user())


if __name__ == "__main__":
  main()
