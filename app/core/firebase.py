import json
import logging
from typing import Any

import firebase_admin
from app.config import get_settings
from app.schema.sql import RoleLevel, UserStatus
from firebase_admin import auth, credentials, firestore
from google.cloud.firestore import Client as FirestoreClient

logger = logging.getLogger(__name__)

settings = get_settings()

_FIREBASE_CUSTOM_CLAIMS_MAX_BYTES = 1000


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


def get_firestore_client() -> FirestoreClient | None:
  """Returns a Firestore client instance. Lazily initializes if needed."""
  if not firebase_admin._apps:
    initialize_firebase()

  try:
    return firestore.client()
  except Exception as e:
    logger.error(f"Failed to get Firestore client: {e}")
    return None


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


def _claims_payload_size_bytes(claims: dict[str, Any]) -> int:
  """Return the approximate serialized size of a claims payload in bytes."""
  # Firebase enforces a tight size limit for custom claims; keep serialization minimal.
  encoded = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
  return len(encoded)


def build_rbac_claims(*, role_id: str, role_name: str, role_level: RoleLevel | Any, org_id: str | None, status: UserStatus | Any, tier: str = "Free", permissions: list[str] | None = None) -> dict[str, Any]:
  """Build RBAC claims payloads so token checks are consistent across services."""
  # Normalize enum values so Firebase receives plain JSON values.
  role_level_value = role_level.value if hasattr(role_level, "value") else role_level
  status_value = status.value if hasattr(status, "value") else status
  # Include explicit RBAC keys for middleware-level checks.
  claims = {"role": {"id": role_id, "name": role_name, "level": role_level_value}, "status": status_value, "tier": tier}
  if org_id:
    claims["orgId"] = org_id
  # Include role permissions so clients can render admin UI without extra calls.
  if permissions is not None:
    unique_permissions = sorted(set(permissions))
    claims["permissions"] = unique_permissions
    # Keep claims within Firebase limits by dropping permissions when oversized.
    if _claims_payload_size_bytes(claims) > _FIREBASE_CUSTOM_CLAIMS_MAX_BYTES:
      claims.pop("permissions", None)
      claims["permissionsOmitted"] = True
      claims["permissionsCount"] = len(unique_permissions)

  return claims
