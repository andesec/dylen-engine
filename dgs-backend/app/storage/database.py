from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import get_settings

settings = get_settings()

# Use AsyncPG driver for async operations
# DGS_PG_DSN should be like: postgresql://user:pass@host:port/dbname
# We need to ensure it uses asyncpg driver scheme: postgresql+asyncpg://...
DB_URL = settings.pg_dsn
if DB_URL and not DB_URL.startswith("postgresql+asyncpg://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DB_URL, echo=settings.debug)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing async database session."""
    async with AsyncSessionLocal() as session:
        yield session

logger = logging.getLogger(__name__)

async def init_db() -> None:
    """Initialize database tables if they don't exist."""
    from app.storage.models import Base

    logger.info("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized.")
