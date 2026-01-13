import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import get_settings
from app.storage.models import Base

settings = get_settings()

# Convert standard postgres URL to asyncpg URL
database_url = settings.database_url
if database_url and database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

if not database_url:
    # Fallback or error if not set
    # Using a dummy or raising an error depending on strictness
    # For now assuming it will be set or we handle it gracefully
    logger = logging.getLogger(__name__)
    logger.warning("DATABASE_URL not set. Database operations will fail.")
    engine = None
    AsyncSessionLocal = None
else:
    engine = create_async_engine(database_url, echo=False)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    if engine is None:
        return
    async with engine.begin() as conn:
        # Create tables if they don't exist
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_db_session():
    if AsyncSessionLocal is None:
        raise RuntimeError("Database URL not configured")
    async with AsyncSessionLocal() as session:
        yield session
