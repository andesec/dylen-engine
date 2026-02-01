from __future__ import annotations

import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schema.sql import User, UserStatus
from app.schema.users import OnboardingRequest

router = APIRouter()


@router.get("/me")
async def get_my_profile(
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
  """
  Get the current user's profile and onboarding status.
  """
  return {
      "id": str(current_user.id),
      "email": current_user.email,
      "status": current_user.status,
      "onboardingCompleted": current_user.onboarding_completed,
  }


@router.post("/onboarding/complete")
async def complete_onboarding(
    data: OnboardingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
  """
  Complete the user onboarding process.
  """
  if current_user.onboarding_completed:
    # Idempotent: return current state if already completed
    return {
        "status": current_user.status,
        "onboardingCompleted": True,
    }

  # Update User record
  current_user.age = data.basic.age
  current_user.gender = data.basic.gender
  current_user.gender_other = data.basic.gender_other
  current_user.city = data.basic.city
  current_user.country = data.basic.country
  current_user.occupation = data.basic.occupation

  # JSONB field: assignment ensures change tracking
  current_user.topics_of_interest = data.personalization.topics_of_interest
  current_user.intended_use = data.personalization.intended_use
  current_user.intended_use_other = data.personalization.intended_use_other

  current_user.accepted_terms_at = datetime.datetime.now(datetime.UTC)
  current_user.accepted_privacy_at = datetime.datetime.now(datetime.UTC)
  current_user.terms_version = data.legal.terms_version
  current_user.privacy_version = data.legal.privacy_version

  current_user.onboarding_completed = True
  current_user.status = UserStatus.PENDING

  db.add(current_user)
  await db.commit()
  await db.refresh(current_user)

  return {
      "status": current_user.status,
      "onboardingCompleted": True,
  }
