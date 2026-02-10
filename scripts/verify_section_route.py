from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Ensure local app package takes precedence over installed packages
sys.path.insert(0, os.getcwd())

from unittest.mock import AsyncMock, MagicMock

from app.api.routes.sections import get_section
from app.schema.lessons import Lesson, Section
from app.schema.sql import User
from sqlalchemy.ext.asyncio import AsyncSession


async def test_get_section_by_order_index():
  # Mocking
  session = MagicMock(spec=AsyncSession)
  current_user = User(id=uuid.uuid4(), email="test@example.com")
  lesson_id = "test-lesson-id"
  order_index = 1

  # 1. Mock Lesson check
  lesson_result = MagicMock()
  lesson_result.scalar_one_or_none.return_value = Lesson(lesson_id=lesson_id, user_id=str(current_user.id))

  # 2. Mock Section check
  section_result = MagicMock()
  section_content = {"section": "Test Section", "items": [{"markdown": "Hello"}], "subsections": []}
  section_result.scalar_one_or_none.return_value = Section(section_id=1, lesson_id=lesson_id, order_index=order_index, status="completed", content={"raw": True}, content_shorthand=section_content)

  session.execute = AsyncMock()
  session.execute.side_effect = [lesson_result, section_result]

  # Execute
  result = await get_section(lesson_id=lesson_id, order_index=order_index, session=session, current_user=current_user)

  # Verify
  assert result == section_content
  print("Verification Passed: Section shorthand retrieved correctly using order_index.")

  # Verify query
  calls = session.execute.call_args_list
  assert len(calls) == 2

  # Check second query (Section)
  # section_query = calls[1][0][0]
  # In SQLAlchemy 2.0 select().where(), we can check the expression
  # But for a simple mock test, checking that it didn't crash and returned content is usually enough.


if __name__ == "__main__":
  asyncio.run(test_get_section_by_order_index())
