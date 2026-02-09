import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.schema.lessons import Lesson, Section
from app.schema.sql import User

router = APIRouter()


def _encrypt_section_payload(payload: dict, firebase_uid: str) -> str:
  """Encrypt section payload with AES-GCM using a user-id-derived key and return a compact token."""
  # Derive a stable 256-bit key from the Firebase uid for client-specific payload wrapping.
  key = hashlib.sha256(firebase_uid.encode("utf-8")).digest()
  # Serialize payload in a compact form before encryption.
  plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
  # Use a random nonce for each response to prevent repeated ciphertext output.
  nonce = os.urandom(12)
  # Encrypt the payload and keep auth tag embedded in the ciphertext output.
  ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
  # Return nonce + ciphertext as base64 text so it can be transmitted in JSON safely.
  return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


@router.get("/{lesson_id}/sections/{order_index}")
async def get_section(lesson_id: str, order_index: int, session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)):
  """
  Get a specific section shorthand payload by its order index (1-based).
  """
  user_id = str(current_user.id)
  firebase_uid = str(current_user.firebase_uid)
  if not firebase_uid:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid authentication identity")

  # Verify lesson exists and belongs to user.
  stmt = select(Lesson).where(Lesson.lesson_id == lesson_id, Lesson.user_id == user_id)
  result = await session.execute(stmt)
  lesson = result.scalar_one_or_none()

  if not lesson:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

  # Verify section exists and is tied to a lesson owned by the same JWT user.
  query = select(Section).join(Lesson, Section.lesson_id == Lesson.lesson_id).where(Section.lesson_id == lesson_id, Section.order_index == order_index, Lesson.user_id == user_id)
  result = await session.execute(query)
  section = result.scalar_one_or_none()

  if not section:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")

  if section.status != "completed":
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Section not completed yet")

  if not section.content_shorthand:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Section shorthand is not available yet")

  # Encrypt section output per user before sending it to the UI.
  encrypted_payload = _encrypt_section_payload({"section": section.content_shorthand}, firebase_uid)
  return encrypted_payload
