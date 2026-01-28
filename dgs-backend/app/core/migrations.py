from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData

from alembic import op


def include_object(object: Any, name: str, type_: str, reflected: bool, compare_to: Any) -> bool:
  """Exclude unsafe objects so autogenerate stays conservative by design."""
  # Ignore legacy meta tables that are not part of the application ORM schema.
  if type_ == "table" and name in ["llm_audit_meta", "dgs_storage_meta"]:
    return False

  # Prevent auto-dropping tables that are not in metadata.
  if type_ == "table" and reflected and compare_to is None:
    return False

  # Prevent auto-dropping columns that are not in metadata.
  if type_ == "column" and reflected and compare_to is None:
    return False

  # Allow the object to participate in autogenerate comparisons.
  return True


def build_migration_context_options(*, target_metadata: MetaData) -> dict[str, Any]:
  """Centralize Alembic options so drift checks align with migration rules."""
  # Keep comparisons strict so drift is caught early in CI and review.
  options = {
    "compare_type": True,
    "compare_server_default": True,
    "include_schemas": False,  # Set True when multiple schemas are used.
    "transaction_per_migration": True,
    "include_object": include_object,
    "target_metadata": target_metadata,
  }
  return options


def create_index_concurrently(*, statement: str) -> None:
  """Run CREATE INDEX CONCURRENTLY outside transactions to reduce lock time."""
  # Use an autocommit block so Postgres accepts CONCURRENTLY statements.
  with op.get_context().autocommit_block():
    op.execute(statement)
