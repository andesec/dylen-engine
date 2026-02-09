from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.schema.lessons import Lesson, Section
from app.schema.sql import User

router = APIRouter()


@router.get("/{lesson_id}/sections/{order_index}")
async def get_section(lesson_id: str, order_index: int, session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)):
  """
  Get a specific section shorthand payload by its order index (1-based).
  """
  # Verify lesson exists and belongs to user
  stmt = select(Lesson).where(Lesson.lesson_id == lesson_id, Lesson.user_id == str(current_user.id))
  result = await session.execute(stmt)
  lesson = result.scalar_one_or_none()

  if not lesson:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

  # Verify section exists
  query = select(Section).where(Section.lesson_id == lesson_id, Section.order_index == order_index)
  result = await session.execute(query)
  section = result.scalar_one_or_none()

  if not section:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")

  if section.status != "completed":
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Section not completed yet")

  if not section.content_shorthand:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Section shorthand is not available yet")

  return section.content_shorthand
