import asyncio
import logging
import sys
from logging.config import fileConfig
from os.path import abspath, dirname
from time import perf_counter

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add the project root to the path so we can import 'app'
sys.path.insert(0, dirname(dirname(abspath(__file__))))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
  fileConfig(config.config_file_name)

import app.schema.audit  # noqa: E402, F401
import app.schema.email_delivery_logs  # noqa: E402, F401
import app.schema.jobs  # noqa: E402, F401
import app.schema.lessons  # noqa: E402, F401

# Must import models so they are attached to Base.metadata
import app.schema.sql  # noqa: E402, F401
from app.core.database import DATABASE_URL, Base  # noqa: E402
from app.core.migrations import build_migration_context_options  # noqa: E402

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# Track migration timing so logs include per-revision durations.
_MIGRATION_TIMER = {"current_start": None}

# Use alembic's migration logger for consistent log routing.
_migration_logger = logging.getLogger("alembic.runtime.migration")


def _on_version_apply(*, ctx: object, step: object, heads: set[str], run_args: dict[str, object]) -> None:
  """Emit per-revision logs so operators see timing and progress."""
  # Capture the current time to compute per-revision durations.
  end_time = perf_counter()
  start_time = _MIGRATION_TIMER.get("current_start")
  revision = getattr(step, "up_revision_id", None) or "unknown"
  # Emit a log entry for each migration step with timing when available.
  if start_time is None:
    _migration_logger.info("Applied migration %s", revision)
  else:
    duration = end_time - start_time
    _migration_logger.info("Applied migration %s in %.3fs", revision, duration)

  _MIGRATION_TIMER["current_start"] = perf_counter()


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def _build_context_options() -> dict[str, object]:
  """Keep Alembic options centralized so drift checks match runtime behavior."""
  # Reuse shared context options so lint and drift checks stay aligned.
  options = build_migration_context_options(target_metadata=target_metadata)
  # Capture per-revision timing as migrations are applied.
  options["on_version_apply"] = _on_version_apply
  return options


def run_migrations_offline() -> None:
  """Configure offline migrations so generated SQL mirrors runtime settings."""
  # Use the configured DB URL so offline migrations match runtime settings.
  url = DATABASE_URL
  # Apply shared strict comparison options for offline autogenerate output.
  options = _build_context_options()
  context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **options)

  # Wrap offline migration execution in a transaction.
  with context.begin_transaction():
    context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
  """Run migrations on the provided connection while logging revisions."""
  # Apply shared strict comparison options for online migrations.
  options = _build_context_options()
  context.configure(connection=connection, **options)
  # Log the migration boundaries using the current and target revisions.
  migration_context = context.get_context()
  current_revision = migration_context.get_current_revision() or "base"
  # Prefer script heads to represent the target revision for this run.
  target_list = migration_context.script.get_heads() if migration_context.script else []
  target_heads = ", ".join(target_list) or "none"
  _migration_logger.info("Starting migration run from %s to %s", current_revision, target_heads)
  # Reset the per-revision timer at the start of the run.
  _MIGRATION_TIMER["current_start"] = perf_counter()

  # Wrap online migration execution in a transaction.
  with context.begin_transaction():
    context.run_migrations()

  # Log completion so operators can correlate the final revision.
  final_heads = ", ".join(migration_context.get_current_heads()) or "none"
  _migration_logger.info("Completed migration run at %s", final_heads)


async def run_async_migrations() -> None:
  """Run migrations with an async engine so settings match runtime drivers."""
  # Load Alembic configuration for the async engine.
  configuration = config.get_section(config.config_ini_section)
  configuration["sqlalchemy.url"] = DATABASE_URL
  connectable = async_engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

  # Run migrations using an async connection.
  async with connectable.connect() as connection:
    await connection.run_sync(do_run_migrations)

  # Dispose the engine so connections close cleanly.
  await connectable.dispose()


def run_migrations_online() -> None:
  """Run migrations online using asyncio to match runtime execution."""
  # Run migrations using an async engine to match runtime configuration.
  asyncio.run(run_async_migrations())


if context.is_offline_mode():
  run_migrations_offline()
else:
  run_migrations_online()
