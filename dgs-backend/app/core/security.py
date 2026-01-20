from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from firebase_admin import auth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.database import get_db
from app.schema.sql import User

settings = get_settings()


from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.firebase import verify_id_token

security_scheme = HTTPBearer()


async def get_current_user(token: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)], db: AsyncSession = Depends(get_db)) -> User:
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

  stmt = select(User).where(User.firebase_uid == firebase_uid)
  result = await db.execute(stmt)
  user = result.scalar_one_or_none()

  if not user:
    # User must explicitly sign up first.
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

  # Optional: Update provider if it changed or wasn't set (passive sync)
  if provider_id and user.provider != provider_id:
    user.provider = provider_id
    db.add(user)
    await db.commit()
    await db.refresh(user)

  return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:  # noqa: B008
  if not current_user.is_approved:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
  return current_user


async def get_current_admin_user(current_user: User = Depends(get_current_active_user)) -> User:  # noqa: B008
  if not current_user.is_admin:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
  return current_user
