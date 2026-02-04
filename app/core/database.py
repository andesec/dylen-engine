from __future__ import annotations

from collections.abc import AsyncGenerator

from app.config import get_database_settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
  pass


engine = None
SessionLocal = None


def _database_url() -> str | None:
  """Build the SQLAlchemy database URL while keeping settings evaluation minimal."""
  settings = get_database_settings()
  database_url = settings.pg_dsn
  if database_url and database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

  return database_url


DATABASE_URL = _database_url()


def get_db_engine():  # type: ignore
  global engine
  settings = get_database_settings()
  database_url = _database_url()
  if engine is None and database_url:
    engine = create_async_engine(database_url, echo=settings.debug, future=True)
  return engine


def get_session_factory():  # type: ignore
  global SessionLocal
  if SessionLocal is None:
    db_engine = get_db_engine()
    if db_engine:
      SessionLocal = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)
  return SessionLocal


async def get_db() -> AsyncGenerator[AsyncSession]:
  """Dependency to get a database session."""
  session_factory = get_session_factory()
  if session_factory is None:
    # If no DB is configured, we can't yield a session.
    # In a real scenario, this might raise an error or yield None depending on requirements.
    # For now, we assume DB is required for auth-protected endpoints if auth is enabled.
    raise RuntimeError("Database connection is not configured (DYLEN_PG_DSN is missing).")

  async with session_factory() as session:
    try:
      yield session
    finally:
      await session.close()
