import datetime
import logging
from typing import Optional

import pyotp
from app.config import get_settings
from app.core.firebase import get_firestore_client
from cryptography.fernet import Fernet
from firebase_admin import firestore
from google.cloud.firestore import Client as FirestoreClient
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
settings = get_settings()

RATE_LIMIT_attempts = 3
RATE_LIMIT_COOLDOWN_SECONDS = 300  # 5 minutes


def get_fernet() -> Fernet:
  key = settings.totp_encryption_key
  if not key:
    raise ValueError("DYLEN_TOTP_ENCRYPTION_KEY is not set.")
  return Fernet(key)


def encrypt_secret(secret: str) -> str:
  f = get_fernet()
  return f.encrypt(secret.encode()).decode()


def decrypt_secret(encrypted_secret: str) -> str:
  f = get_fernet()
  return f.decrypt(encrypted_secret.encode()).decode()


def _verify_totp_sync(admin_uid: str, token: str, ip_address: str) -> bool:
  db: FirestoreClient | None = get_firestore_client()
  if not db:
    logger.error("Firestore client not initialized.")
    return False

  doc_ref = db.collection("artifacts").document(settings.app_id).collection("users").document(admin_uid)

  transaction = db.transaction()

  @firestore.transactional
  def update_in_transaction(transaction: firestore.Transaction, doc_ref: firestore.DocumentReference) -> bool:
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
      logger.warning(f"Admin document not found for {admin_uid}")
      return False

    data = snapshot.to_dict()
    if not data:
      return False

    # Check cooldown
    failed_attempts = data.get("totp_failed_attempts", 0)
    last_failed_str = data.get("totp_last_failed_at")

    if failed_attempts >= RATE_LIMIT_attempts:
      if last_failed_str:
        last_failed = datetime.datetime.fromisoformat(last_failed_str)
        if (datetime.datetime.now(datetime.UTC) - last_failed).total_seconds() < RATE_LIMIT_COOLDOWN_SECONDS:
          logger.warning(f"Rate limit exceeded for admin {admin_uid} from IP {ip_address}. Cooling down.")
          return False
      else:
        # Should not happen if failed_attempts > 0, but safe fallback
        pass

    if not data.get("totp_enabled"):
      logger.warning(f"TOTP not enabled for {admin_uid}")
      return False

    encrypted_secret = data.get("totp_secret_encrypted")
    if not encrypted_secret:
      logger.warning(f"No TOTP secret found for {admin_uid}")
      return False

    try:
      secret = decrypt_secret(encrypted_secret)
    except Exception as e:
      logger.error(f"Failed to decrypt TOTP secret for {admin_uid}: {e}")
      return False

    totp = pyotp.TOTP(secret)

    # valid_window=1 allows ±30 seconds (1 step back, 1 step forward)
    is_valid = totp.verify(token, valid_window=1)

    if not is_valid:
      logger.warning(f"Invalid TOTP code for {admin_uid} from IP {ip_address}")
      # Increment failed attempts
      new_failed_attempts = failed_attempts + 1
      transaction.update(doc_ref, {
        "totp_failed_attempts": new_failed_attempts,
        "totp_last_failed_at": datetime.datetime.now(datetime.UTC).isoformat()
      })
      return False

    # Replay protection
    last_used_otp = data.get("last_used_otp")
    if last_used_otp == token:
      logger.warning(f"Replay attack detected for {admin_uid} with token {token} from IP {ip_address}")
      return False

    # Success: Reset failed attempts and update last_used_otp
    transaction.update(doc_ref, {
      "last_used_otp": token,
      "last_used_otp_timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
      "totp_failed_attempts": 0,
      "totp_last_failed_at": None
    })
    return True

  try:
    return update_in_transaction(transaction, doc_ref)
  except Exception as e:
    logger.error(f"TOTP verification transaction failed for {admin_uid}: {e}")
    return False


async def verify_totp_code(admin_uid: str, token: str, ip_address: str) -> bool:
  """
  Verifies the TOTP token for the given admin user.
  Checks against Firestore storage, enforcing valid window and replay protection.
  """
  if not token:
    return False
  return await run_in_threadpool(_verify_totp_sync, admin_uid, token, ip_address)


def _setup_totp_sync(admin_uid: str) -> str | None:
  """Generates a new TOTP secret and stores it encrypted (disabled)."""
  db: FirestoreClient | None = get_firestore_client()
  if not db:
    logger.error("Firestore client not initialized.")
    return None

  doc_ref = db.collection("artifacts").document(settings.app_id).collection("users").document(admin_uid)

  secret = pyotp.random_base32()
  encrypted_secret = encrypt_secret(secret)

  # Set secret but verify first before enabling
  doc_ref.set({
      "totp_secret_encrypted": encrypted_secret,
      "totp_enabled": False,
      "totp_failed_attempts": 0,
      "last_used_otp": None
  }, merge=True)

  return secret

async def setup_totp(admin_uid: str) -> str | None:
  return await run_in_threadpool(_setup_totp_sync, admin_uid)


def _verify_setup_sync(admin_uid: str, token: str) -> bool:
  """Verifies a token against stored secret and enables TOTP if valid."""
  db: FirestoreClient | None = get_firestore_client()
  if not db:
    return False

  doc_ref = db.collection("artifacts").document(settings.app_id).collection("users").document(admin_uid)
  snapshot = doc_ref.get()

  if not snapshot.exists:
      return False

  data = snapshot.to_dict()
  encrypted_secret = data.get("totp_secret_encrypted")
  if not encrypted_secret:
      return False

  try:
      secret = decrypt_secret(encrypted_secret)
  except Exception:
      return False

  totp = pyotp.TOTP(secret)
  if totp.verify(token, valid_window=1):
      doc_ref.update({"totp_enabled": True})
      return True

  return False

async def verify_totp_setup(admin_uid: str, token: str) -> bool:
  return await run_in_threadpool(_verify_setup_sync, admin_uid, token)

def _disable_totp_sync(admin_uid: str) -> bool:
  db: FirestoreClient | None = get_firestore_client()
  if not db:
    return False

  doc_ref = db.collection("artifacts").document(settings.app_id).collection("users").document(admin_uid)
  doc_ref.update({"totp_enabled": False, "totp_secret_encrypted": firestore.DELETE_FIELD})
  return True

async def disable_totp(admin_uid: str) -> bool:
  return await run_in_threadpool(_disable_totp_sync, admin_uid)

def _is_enabled_sync(admin_uid: str) -> bool:
  db: FirestoreClient | None = get_firestore_client()
  if not db:
    return False

  doc_ref = db.collection("artifacts").document(settings.app_id).collection("users").document(admin_uid)
  snapshot = doc_ref.get()

  if not snapshot.exists:
      return False

  data = snapshot.to_dict()
  return data.get("totp_enabled", False)

async def is_totp_enabled(admin_uid: str) -> bool:
  return await run_in_threadpool(_is_enabled_sync, admin_uid)
