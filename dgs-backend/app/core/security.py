from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.firebase import verify_id_token
from app.schema.sql import User
from app.services.users import get_user_by_firebase_uid, update_user_provider

security_scheme = HTTPBearer()


async def get_current_user(token: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)], db: AsyncSession = Depends(get_db)) -> User:  # noqa: B008
  """
  Verifies the Firebase ID Token (Bearer) and retrieves the current user.
  """
  id_token = token.credentials
  decoded_claims = await run_in_threadpool(verify_id_token, id_token)

  if not decoded_claims:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials", headers={"WWW-Authenticate": "Bearer"})

  firebase_uid = decoded_claims.get("uid")
  provider_id = decoded_claims.get("firebase", {}).get("sign_in_provider")

  if not firebase_uid:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token claims")

  # Resolve the user from Postgres using ORM queries.
  user = await get_user_by_firebase_uid(db, firebase_uid)

  if not user:
    # User must explicitly sign up first.
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

  # Optional: Update provider if it changed or wasn't set (passive sync)
  if provider_id and user.provider != provider_id:
    await update_user_provider(db, user=user, provider=provider_id)

  return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:  # noqa: B008
  if not current_user.is_approved:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
  return current_user


async def get_current_admin_user(current_user: User = Depends(get_current_active_user)) -> User:  # noqa: B008
  if not current_user.is_admin:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
  return current_user
