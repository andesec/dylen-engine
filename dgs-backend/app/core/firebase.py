import logging
from typing import Any

import firebase_admin
from firebase_admin import auth, credentials

from app.config import get_settings

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
