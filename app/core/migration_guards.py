"""Guarded Alembic operations with explicit table/column existence checks."""

from __future__ import annotations

from typing import Any

from alembic import op
from sqlalchemy import text


def _resolve_schema(*, schema: str | None) -> str:
  """Resolve schema names so existence checks always target a concrete schema."""
  # Default to the public schema when none is provided.
  return schema or "public"


def table_exists(*, table_name: str, schema: str | None = None) -> bool:
  """Return True when a table exists in the target schema."""
  # Resolve the schema name for information_schema queries.
  resolved_schema = _resolve_schema(schema=schema)
  # Query information_schema to avoid relying on reflection helpers.
  statement = text(
    """
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = :schema
      AND table_name = :table_name
      AND table_type = 'BASE TABLE'
    LIMIT 1
    """
  )
  # Execute the query against the Alembic connection.
  result = op.get_bind().execute(statement, {"schema": resolved_schema, "table_name": table_name})
  return result.first() is not None


def column_exists(*, table_name: str, column_name: str, schema: str | None = None) -> bool:
  """Return True when a column exists on the specified table."""
  # Resolve the schema name for information_schema queries.
  resolved_schema = _resolve_schema(schema=schema)
  # Query information_schema to confirm column existence.
  statement = text(
    """
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = :schema
      AND table_name = :table_name
      AND column_name = :column_name
    LIMIT 1
    """
  )
  # Execute the query against the Alembic connection.
  result = op.get_bind().execute(statement, {"schema": resolved_schema, "table_name": table_name, "column_name": column_name})
  return result.first() is not None


def index_exists(*, index_name: str, schema: str | None = None) -> bool:
  """Return True when an index exists in the target schema."""
  # Resolve the schema name for pg_indexes queries.
  resolved_schema = _resolve_schema(schema=schema)
  # Query pg_indexes to detect the named index.
  statement = text(
    """
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = :schema
      AND indexname = :index_name
    LIMIT 1
    """
  )
  # Execute the query against the Alembic connection.
  result = op.get_bind().execute(statement, {"schema": resolved_schema, "index_name": index_name})
  return result.first() is not None


def constraint_exists(*, constraint_name: str, schema: str | None = None) -> bool:
  """Return True when a constraint exists in the target schema."""
  # Resolve the schema name for pg_constraint queries.
  resolved_schema = _resolve_schema(schema=schema)
  # Query pg_constraint to detect named constraints.
  statement = text(
    """
    SELECT 1
    FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = :schema
      AND c.conname = :constraint_name
    LIMIT 1
    """
  )
  # Execute the query against the Alembic connection.
  result = op.get_bind().execute(statement, {"schema": resolved_schema, "constraint_name": constraint_name})
  return result.first() is not None


def guarded_create_table(table_name: str, *args: Any, **kwargs: Any) -> None:
  """Create a table only when it does not already exist."""
  # Read schema from kwargs to align checks with op.create_table behavior.
  schema = kwargs.get("schema")
  # Skip creation when the table already exists.
  if table_exists(table_name=table_name, schema=schema):
    return

  # Delegate to Alembic for actual table creation.
  op.create_table(table_name, *args, **kwargs)


def guarded_drop_table(table_name: str, *args: Any, **kwargs: Any) -> None:
  """Drop a table only when it exists."""
  # Read schema from kwargs to align checks with op.drop_table behavior.
  schema = kwargs.get("schema")
  # Skip dropping when the table does not exist.
  if not table_exists(table_name=table_name, schema=schema):
    return

  # Delegate to Alembic for actual table drop.
  op.drop_table(table_name, *args, **kwargs)


def guarded_add_column(table_name: str, column: Any, *args: Any, **kwargs: Any) -> None:
  """Add a column only when the table exists and the column is missing."""
  # Read schema from kwargs to align checks with op.add_column behavior.
  schema = kwargs.get("schema")
  # Skip when the table is missing to avoid runtime failures.
  if not table_exists(table_name=table_name, schema=schema):
    return

  # Skip when the column already exists.
  if column_exists(table_name=table_name, column_name=column.name, schema=schema):
    return

  # Delegate to Alembic for actual column creation.
  op.add_column(table_name, column, *args, **kwargs)


def guarded_drop_column(table_name: str, column_name: str, *args: Any, **kwargs: Any) -> None:
  """Drop a column only when the table and column exist."""
  # Read schema from kwargs to align checks with op.drop_column behavior.
  schema = kwargs.get("schema")
  # Skip when the table does not exist.
  if not table_exists(table_name=table_name, schema=schema):
    return

  # Skip when the column is already missing.
  if not column_exists(table_name=table_name, column_name=column_name, schema=schema):
    return

  # Delegate to Alembic for actual column drop.
  op.drop_column(table_name, column_name, *args, **kwargs)


def guarded_create_index(index_name: str, table_name: str, *args: Any, **kwargs: Any) -> None:
  """Create an index only when it does not already exist."""
  # Read schema from kwargs to align checks with op.create_index behavior.
  schema = kwargs.get("schema")
  # Skip creation when the table is missing.
  if not table_exists(table_name=table_name, schema=schema):
    return

  # When columns are specified by name, ensure they exist before creating the index.
  if args:
    columns = args[0]
    if isinstance(columns, (list, tuple)):
      for column in columns:
        if isinstance(column, str) and not column_exists(table_name=table_name, column_name=column, schema=schema):
          return

    if isinstance(columns, str) and not column_exists(table_name=table_name, column_name=columns, schema=schema):
      return

  # Skip creation when the index already exists.
  if index_exists(index_name=index_name, schema=schema):
    return

  # Delegate to Alembic for index creation.
  op.create_index(index_name, table_name, *args, **kwargs)


def guarded_drop_index(index_name: str, *args: Any, **kwargs: Any) -> None:
  """Drop an index only when it exists."""
  # Read schema from kwargs to align checks with op.drop_index behavior.
  schema = kwargs.get("schema")
  # Skip dropping when the table is missing.
  table_name = kwargs.get("table_name")
  if table_name and not table_exists(table_name=table_name, schema=schema):
    return

  # Skip dropping when the index is missing.
  if not index_exists(index_name=index_name, schema=schema):
    return

  # Delegate to Alembic for index drop.
  op.drop_index(index_name, *args, **kwargs)


def guarded_create_foreign_key(constraint_name: str, source_table: str, referent_table: str, *args: Any, **kwargs: Any) -> None:
  """Create a foreign key constraint only when missing."""
  # Read schema from kwargs to align checks with op.create_foreign_key behavior.
  source_schema = kwargs.get("source_schema")
  referent_schema = kwargs.get("referent_schema")
  # Skip creation when the source table is missing.
  if not table_exists(table_name=source_table, schema=source_schema):
    return

  # Skip creation when the referent table is missing.
  if not table_exists(table_name=referent_table, schema=referent_schema):
    return

  # Ensure source columns exist when provided as names.
  if len(args) >= 2:
    local_cols = args[0]
    remote_cols = args[1]
    if isinstance(local_cols, (list, tuple)):
      for column in local_cols:
        if isinstance(column, str) and not column_exists(table_name=source_table, column_name=column, schema=source_schema):
          return

    if isinstance(local_cols, str) and not column_exists(table_name=source_table, column_name=local_cols, schema=source_schema):
      return

    if isinstance(remote_cols, (list, tuple)):
      for column in remote_cols:
        if isinstance(column, str) and not column_exists(table_name=referent_table, column_name=column, schema=referent_schema):
          return

    if isinstance(remote_cols, str) and not column_exists(table_name=referent_table, column_name=remote_cols, schema=referent_schema):
      return

  # Skip creation when the constraint already exists.
  if constraint_exists(constraint_name=constraint_name, schema=source_schema):
    return

  # Delegate to Alembic for constraint creation.
  op.create_foreign_key(constraint_name, source_table, referent_table, *args, **kwargs)


def guarded_create_unique_constraint(constraint_name: str, table_name: str, *args: Any, **kwargs: Any) -> None:
  """Create a unique constraint only when missing."""
  # Read schema from kwargs to align checks with op.create_unique_constraint behavior.
  schema = kwargs.get("schema")
  # Skip creation when the table is missing.
  if not table_exists(table_name=table_name, schema=schema):
    return

  # Ensure column names exist when provided by name.
  if args:
    columns = args[0]
    if isinstance(columns, (list, tuple)):
      for column in columns:
        if isinstance(column, str) and not column_exists(table_name=table_name, column_name=column, schema=schema):
          return

    if isinstance(columns, str) and not column_exists(table_name=table_name, column_name=columns, schema=schema):
      return

  # Skip creation when the constraint already exists.
  if constraint_exists(constraint_name=constraint_name, schema=schema):
    return

  # Delegate to Alembic for constraint creation.
  op.create_unique_constraint(constraint_name, table_name, *args, **kwargs)


def guarded_create_check_constraint(constraint_name: str, table_name: str, *args: Any, **kwargs: Any) -> None:
  """Create a check constraint only when missing."""
  # Read schema from kwargs to align checks with op.create_check_constraint behavior.
  schema = kwargs.get("schema")
  # Skip creation when the table is missing.
  if not table_exists(table_name=table_name, schema=schema):
    return

  # Skip creation when the constraint already exists.
  if constraint_exists(constraint_name=constraint_name, schema=schema):
    return

  # Delegate to Alembic for constraint creation.
  op.create_check_constraint(constraint_name, table_name, *args, **kwargs)


def guarded_drop_constraint(constraint_name: str, table_name: str, *args: Any, **kwargs: Any) -> None:
  """Drop a constraint only when it exists."""
  # Read schema from kwargs to align checks with op.drop_constraint behavior.
  schema = kwargs.get("schema")
  # Skip dropping when the table is missing.
  if not table_exists(table_name=table_name, schema=schema):
    return

  # Skip dropping when the constraint is missing.
  if not constraint_exists(constraint_name=constraint_name, schema=schema):
    return

  # Delegate to Alembic for constraint drop.
  op.drop_constraint(constraint_name, table_name, *args, **kwargs)
