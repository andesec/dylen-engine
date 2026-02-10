"""enforce_db_managed_timestamps

Revision ID: e8f4a4b9d2c1
Revises: 30bf37f6dee4
Create Date: 2026-02-10 12:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.core.migration_guards import column_exists, table_exists

revision: str = "e8f4a4b9d2c1"
down_revision: str | Sequence[str] | None = "30bf37f6dee4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TIMESTAMP_UPDATED_AT_TABLES = ["users", "runtime_config_values", "organization_feature_flags", "subscription_tier_feature_flags", "user_feature_flag_overrides", "illustrations", "user_quota_buckets"]

_STRING_DEFAULT_EXPR = "to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"


def _set_default(*, table_name: str, column_name: str, expression: str) -> None:
  """Set a column default when the target table/column exists."""
  # Guard against environments with partial schema history.
  if not table_exists(table_name=table_name) or not column_exists(table_name=table_name, column_name=column_name):
    return
  op.execute(f'ALTER TABLE "{table_name}" ALTER COLUMN "{column_name}" SET DEFAULT {expression}')


def _create_update_trigger(*, table_name: str, trigger_name: str, function_name: str) -> None:
  """Create a BEFORE UPDATE trigger for updated_at when schema is present."""
  # Only attach triggers to tables that actually have updated_at.
  if not table_exists(table_name=table_name) or not column_exists(table_name=table_name, column_name="updated_at"):
    return
  op.execute(f'DROP TRIGGER IF EXISTS "{trigger_name}" ON "{table_name}"')
  op.execute(f'CREATE TRIGGER "{trigger_name}" BEFORE UPDATE ON "{table_name}" FOR EACH ROW EXECUTE FUNCTION "{function_name}"()')


def upgrade() -> None:
  """Upgrade schema."""
  # Create trigger function for timestamptz updated_at columns.
  op.execute(
    """
    CREATE OR REPLACE FUNCTION public.set_updated_at_timestamptz()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
        NEW.updated_at := now();
      END IF;
      RETURN NEW;
    END;
    $$;
    """
  )
  # Create trigger function for legacy text updated_at columns.
  op.execute(
    """
    CREATE OR REPLACE FUNCTION public.set_updated_at_iso8601_text()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
      IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
        NEW.updated_at := to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
      END IF;
      RETURN NEW;
    END;
    $$;
    """
  )

  # Ensure DB-level create defaults exist for legacy text timestamp columns.
  _set_default(table_name="lessons", column_name="created_at", expression=_STRING_DEFAULT_EXPR)
  _set_default(table_name="jobs", column_name="created_at", expression=_STRING_DEFAULT_EXPR)
  _set_default(table_name="jobs", column_name="updated_at", expression=_STRING_DEFAULT_EXPR)

  # Ensure DB-level create defaults exist for timestamp updated_at fields.
  for table_name in _TIMESTAMP_UPDATED_AT_TABLES:
    _set_default(table_name=table_name, column_name="updated_at", expression="now()")

  # Attach DB-level update automation for timestamp updated_at fields.
  for table_name in _TIMESTAMP_UPDATED_AT_TABLES:
    _create_update_trigger(table_name=table_name, trigger_name=f"trg_{table_name}_set_updated_at", function_name="set_updated_at_timestamptz")

  # Attach DB-level update automation for legacy text updated_at fields.
  _create_update_trigger(table_name="jobs", trigger_name="trg_jobs_set_updated_at", function_name="set_updated_at_iso8601_text")


def downgrade() -> None:
  """Downgrade schema."""
  # Drop triggers conservatively to keep downgrade safe for partial schemas.
  for table_name in _TIMESTAMP_UPDATED_AT_TABLES:
    if table_exists(table_name=table_name):
      op.execute(f'DROP TRIGGER IF EXISTS "trg_{table_name}_set_updated_at" ON "{table_name}"')
  if table_exists(table_name="jobs"):
    op.execute('DROP TRIGGER IF EXISTS "trg_jobs_set_updated_at" ON "jobs"')

  # Drop helper trigger functions.
  op.execute("DROP FUNCTION IF EXISTS public.set_updated_at_iso8601_text()")
  op.execute("DROP FUNCTION IF EXISTS public.set_updated_at_timestamptz()")
