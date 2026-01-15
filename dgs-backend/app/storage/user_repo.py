from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.storage.models import User

class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_firebase_uid(self, firebase_uid: str) -> Optional[User]:
        stmt = select(User).where(User.firebase_uid == firebase_uid)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_user(self, firebase_uid: str, email: str, full_name: str | None = None) -> User:
        user = User(
            firebase_uid=firebase_uid,
            email=email,
            full_name=full_name,
            is_approved=False # Default is False
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user
