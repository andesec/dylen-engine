from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.schema.sql import User
from app.services.rbac import get_role_by_id

router = APIRouter()


@router.get("/me")
async def get_my_profile(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Get the current user's profile.
  """
  # Fetch role metadata to return friendly profile details.
  role = await get_role_by_id(db, current_user.role_id)
  if role is None:
    return {
      "id": str(current_user.id),
      "email": current_user.email,
      "full_name": current_user.full_name,
      "photo_url": current_user.photo_url,
      "status": current_user.status,
      "role": None,
      "org_id": str(current_user.org_id) if current_user.org_id else None,
    }

  return {
    "id": str(current_user.id),
    "email": current_user.email,
    "full_name": current_user.full_name,
    "photo_url": current_user.photo_url,
    "status": current_user.status,
    "role": {"id": str(role.id), "name": role.name, "level": role.level},
    "org_id": str(current_user.org_id) if current_user.org_id else None,
  }
