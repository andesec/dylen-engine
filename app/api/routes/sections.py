from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schema.lessons import Lesson, Section

router = APIRouter()


@router.get("/lessons/{lesson_id}/sections/{section_id}")
async def get_section(lesson_id: str, section_id: str, session: AsyncSession = Depends(get_db)):
  """
  Get a specific section of a lesson.
  """
  # Verify lesson exists
  lesson = await session.get(Lesson, lesson_id)
  if not lesson:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

  # Verify section exists
  query = select(Section).where(Section.lesson_id == lesson_id, Section.section_id == section_id)
  result = await session.execute(query)
  section = result.scalar_one_or_none()

  if not section:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")

  if section.status != "generated":
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Section not generated yet")

  if not section.content:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Section content missing")

  return section.content
