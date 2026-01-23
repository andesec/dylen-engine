"""User CRUD helpers implemented with SQLAlchemy ORM.

This module centralizes how and why user records are created/updated so transport
layers (routes, auth dependencies, workers) don't duplicate query logic.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schema.sql import User

logger = logging.getLogger(__name__)


async def get_user_by_firebase_uid(session: AsyncSession, firebase_uid: str) -> User | None:
  """Fetch a user by Firebase UID to support auth and session validation."""
  stmt = select(User).where(User.firebase_uid == firebase_uid)
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
  """Fetch a user by primary key to support admin flows and background workers."""
  stmt = select(User).where(User.id == user_id)
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


async def create_user(session: AsyncSession, *, firebase_uid: str, email: str, full_name: str | None, profession: str | None, city: str | None, country: str | None, age: int | None, photo_url: str | None, provider: str | None, is_approved: bool) -> User:
  """Create a new user row and commit it so downstream flows can rely on it."""
  # Persist the DB record before returning so callers can use the generated id.
  user = User(firebase_uid=firebase_uid, email=email, full_name=full_name, profession=profession, city=city, country=country, age=age, photo_url=photo_url, provider=provider, is_approved=is_approved)
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def update_user_provider(session: AsyncSession, *, user: User, provider: str) -> User:
  """Update the auth provider to keep the local user record in sync with Firebase."""
  # Avoid unnecessary writes by checking for changes before committing.
  if user.provider == provider:
    return user

  user.provider = provider
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def approve_user(session: AsyncSession, *, user: User) -> User:
  """Approve a user record and commit so access control checks pass immediately."""
  # Ensure approval is durable before triggering any notifications.
  if user.is_approved:
    return user

  user.is_approved = True
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user
