from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.schema.sql import User
from app.schema.users import OnboardingRequest
from app.services.users import complete_user_onboarding

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

  user = await complete_user_onboarding(db, user=current_user, data=data)

  return {
      "status": user.status,
      "onboardingCompleted": True,
  }
