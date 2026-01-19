from typing import Any

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.schema.sql import User

router = APIRouter()


@router.get("/me")
async def get_my_profile(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
  """
  Get the current user's profile.
  """
  return {
    "id": str(current_user.id),
    "email": current_user.email,
    "full_name": current_user.full_name,
    "photo_url": current_user.photo_url,
    "is_approved": current_user.is_approved,
    "is_admin": current_user.is_admin,
  }
