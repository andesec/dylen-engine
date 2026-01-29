import logging
from typing import Any

import firebase_admin
from app.config import get_settings
from app.schema.sql import RoleLevel, UserStatus
from firebase_admin import auth, credentials

logger = logging.getLogger(__name__)

settings = get_settings()


def initialize_firebase() -> None:
  """Initializes the Firebase Admin SDK."""
  if firebase_admin._apps:
    return

  if not settings.firebase_project_id:
    logger.warning("Firebase Project ID not set. Firebase Admin SDK not initialized.")
    return

  try:
    if settings.firebase_service_account_json_path:
      cred = credentials.Certificate(settings.firebase_service_account_json_path)
      firebase_admin.initialize_app(cred, {"projectId": settings.firebase_project_id})
    else:
      # Use default credentials (e.g. Google Application Default Credentials)
      firebase_admin.initialize_app(options={"projectId": settings.firebase_project_id})
    logger.info("Firebase Admin SDK initialized successfully.")
  except Exception as e:
    logger.error(f"Failed to initialize Firebase Admin SDK: {e}")


def verify_id_token(id_token: str) -> dict[str, Any] | None:
  """Verifies a Firebase ID token. Lazily initializes if needed."""
  if not firebase_admin._apps:
    initialize_firebase()

  try:
    decoded_token = auth.verify_id_token(id_token)
    return decoded_token
  except Exception as e:
    logger.error(f"Token verification failed: {e}")
    return None


def set_custom_claims(firebase_uid: str, claims: dict[str, Any]) -> None:
  """Update Firebase custom claims so RBAC data stays in sync for tokens."""
  # Ensure Firebase is initialized before issuing admin SDK calls.
  if not firebase_admin._apps:
    initialize_firebase()

  # Push claims to Firebase so clients receive updated auth context.
  auth.set_custom_user_claims(firebase_uid, claims)


def build_rbac_claims(*, role_id: str, role_name: str, role_level: RoleLevel | Any, org_id: str | None, status: UserStatus | Any, tier: str = "Free") -> dict[str, Any]:
  """Build RBAC claims payloads so token checks are consistent across services."""
  # Normalize enum values so Firebase receives plain JSON values.
  role_level_value = role_level.value if hasattr(role_level, "value") else role_level
  status_value = status.value if hasattr(status, "value") else status
  # Include explicit RBAC keys for middleware-level checks.
  claims = {"role": {"id": role_id, "name": role_name, "level": role_level_value}, "status": status_value, "tier": tier}
  if org_id:
    claims["orgId"] = org_id

  return claims
