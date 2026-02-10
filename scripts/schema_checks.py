"""Schema verification helpers for migrations and repair."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.core.database import Base
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection
from sqlalchemy.sql.elements import TextClause


@dataclass(frozen=True)
class MissingColumn:
  """Describe a missing or mismatched column."""

  table: str
  column: str
  expected_type: str
  expected_nullable: bool
  expected_default: str | None
  reason: str


@dataclass(frozen=True)
class MissingIndex:
  """Describe a missing index."""

  table: str
  index: str


@dataclass(frozen=True)
class MissingConstraint:
  """Describe a missing constraint."""

  table: str
  constraint: str


@dataclass
class SchemaVerificationResult:
  """Aggregate verification findings for schema repair."""

  missing_tables: list[str] = field(default_factory=list)
  missing_columns: list[MissingColumn] = field(default_factory=list)
  missing_indexes: list[MissingIndex] = field(default_factory=list)
  missing_constraints: list[MissingConstraint] = field(default_factory=list)
  missing_enums: list[str] = field(default_factory=list)
  missing_extensions: list[str] = field(default_factory=list)
  search_path: str | None = None
  current_schema: str | None = None

  def has_failures(self) -> bool:
    """Return True when any schema requirement is missing."""
    # Treat any missing item as a failure.
    return bool(self.missing_tables or self.missing_columns or self.missing_indexes or self.missing_constraints or self.missing_enums or self.missing_extensions)


def _normalize_type(value: Any) -> str:
  """Normalize SQLAlchemy type objects to a comparable string."""
  # Compile SQLAlchemy types using the Postgres dialect for deterministic names.
  try:
    compiled = value.compile(dialect=postgresql.dialect())
  except Exception:
    compiled = str(value)
  return str(compiled).lower()


def _normalize_default(value: Any) -> str | None:
  """Normalize server defaults into a comparable string."""
  # Normalize None so comparisons skip when no default is expected.
  if value is None:
    return None

  # Extract text from server_default constructs when possible.
  if isinstance(value, TextClause):
    return str(value.text).strip().lower()

  # Fall back to string conversion for other default objects.
  return str(value).strip().lower()


def _expected_default(column: Any) -> str | None:
  """Return the expected server default for a column."""
  # Read the server_default from SQLAlchemy metadata.
  server_default = getattr(column, "server_default", None)
  if server_default is None:
    return None

  # Prefer the .arg attribute when available for raw SQL defaults.
  arg = getattr(server_default, "arg", None)
  if arg is not None:
    return _normalize_default(arg)

  return _normalize_default(server_default)


def _actual_default(value: Any) -> str | None:
  """Normalize the database-reported default string."""
  # The inspector returns default strings, so just normalize them.
  if value is None:
    return None
  return str(value).strip().lower()


def _should_compare_default(expected_default: str | None) -> bool:
  """Return True when defaults should be compared for drift detection."""
  # Skip comparisons when no default is expected.
  if expected_default is None:
    return False
  # Avoid comparing function-like defaults that vary by backend representation.
  if "(" in expected_default or ")" in expected_default:
    return False
  # Compare simple literal defaults only.
  return True


def _collect_expected_tables() -> dict[str, Any]:
  """Collect expected tables from SQLAlchemy metadata."""
  # Restrict to tables in the public schema to avoid surprises.
  return {name: table for name, table in Base.metadata.tables.items() if table.schema in (None, "public")}


def _collect_expected_enums() -> set[str]:
  """Collect enum types declared in SQLAlchemy metadata."""
  # Look for explicit postgres ENUM types in metadata.
  enums: set[str] = set()
  for table in Base.metadata.tables.values():
    for column in table.columns:
      column_type = column.type
      if isinstance(column_type, postgresql.ENUM) and column_type.name:
        enums.add(str(column_type.name))
  return enums


def _collect_expected_extensions() -> set[str]:
  """Collect required Postgres extensions from metadata usage."""
  # No explicit extensions are required by default.
  return set()


def _expected_indexes(table: Any) -> Iterable[str]:
  """Collect expected index names for a table."""
  # Only compare named indexes to avoid implicit/unnamed inconsistencies.
  for index in table.indexes:
    if index.name:
      yield index.name


def _expected_unique_constraints(table: Any) -> Iterable[str]:
  """Collect expected unique constraint names for a table."""
  # Scan table constraints for named unique constraints.
  for constraint in table.constraints:
    if getattr(constraint, "unique", False) and constraint.name:
      yield constraint.name


def _fetch_search_path(connection: Connection) -> tuple[str | None, str | None]:
  """Return the current search_path and current_schema values."""
  # Read the active search_path so logs can highlight schema drift.
  search_path = connection.execute(text("SHOW search_path")).scalar_one_or_none()
  current_schema = connection.execute(text("SELECT current_schema()")).scalar_one_or_none()
  return (str(search_path) if search_path is not None else None, str(current_schema) if current_schema is not None else None)


def verify_schema(connection: Connection, schema: str = "public") -> SchemaVerificationResult:
  """Verify the schema against SQLAlchemy metadata."""
  # Initialize the results container.
  result = SchemaVerificationResult()
  # Capture current schema metadata for reporting.
  search_path, current_schema = _fetch_search_path(connection)
  result.search_path = search_path
  result.current_schema = current_schema

  # Inspect the current schema state.
  inspector = inspect(connection)
  existing_tables = set(inspector.get_table_names(schema=schema))
  expected_tables = _collect_expected_tables()

  # Identify missing tables.
  for table_name in expected_tables:
    if table_name not in existing_tables:
      result.missing_tables.append(table_name)

  # Validate columns, indexes, and constraints for existing tables.
  for table_name, table in expected_tables.items():
    if table_name not in existing_tables:
      continue

    # Gather actual column metadata from the inspector.
    actual_columns = {col["name"]: col for col in inspector.get_columns(table_name, schema=schema)}
    # Compare expected columns against actual columns.
    for column in table.columns:
      if column.name not in actual_columns:
        result.missing_columns.append(MissingColumn(table=table_name, column=column.name, expected_type=_normalize_type(column.type), expected_nullable=bool(column.nullable), expected_default=_expected_default(column), reason="missing"))
        continue

      # Compare type, nullability, and defaults for present columns.
      actual = actual_columns[column.name]
      expected_type = _normalize_type(column.type)
      actual_type = _normalize_type(actual.get("type"))
      if expected_type != actual_type:
        result.missing_columns.append(MissingColumn(table=table_name, column=column.name, expected_type=expected_type, expected_nullable=bool(column.nullable), expected_default=_expected_default(column), reason=f"type mismatch (actual={actual_type})"))

      expected_nullable = bool(column.nullable)
      actual_nullable = bool(actual.get("nullable", True))
      if expected_nullable != actual_nullable:
        result.missing_columns.append(
          MissingColumn(table=table_name, column=column.name, expected_type=expected_type, expected_nullable=expected_nullable, expected_default=_expected_default(column), reason=f"nullability mismatch (actual={actual_nullable})")
        )

      expected_default = _expected_default(column)
      if _should_compare_default(expected_default):
        actual_default = _actual_default(actual.get("default"))
        if actual_default is None or expected_default not in actual_default:
          result.missing_columns.append(MissingColumn(table=table_name, column=column.name, expected_type=expected_type, expected_nullable=expected_nullable, expected_default=expected_default, reason=f"default mismatch (actual={actual_default})"))

    # Compare indexes.
    existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name, schema=schema) if idx.get("name")}
    for index_name in _expected_indexes(table):
      if index_name not in existing_indexes:
        result.missing_indexes.append(MissingIndex(table=table_name, index=index_name))

    # Compare unique constraints.
    existing_uniques = {uq["name"] for uq in inspector.get_unique_constraints(table_name, schema=schema) if uq.get("name")}
    for constraint_name in _expected_unique_constraints(table):
      if constraint_name not in existing_uniques:
        result.missing_constraints.append(MissingConstraint(table=table_name, constraint=constraint_name))

  # Verify enum types.
  expected_enums = _collect_expected_enums()
  if expected_enums:
    actual_enums = {
      row[0]
      for row in connection.execute(
        text(
          """
          SELECT t.typname
          FROM pg_type t
          JOIN pg_namespace n ON n.oid = t.typnamespace
          WHERE n.nspname = :schema
            AND t.typtype = 'e'
          """
        ),
        {"schema": schema},
      ).fetchall()
    }
    for enum_name in expected_enums:
      if enum_name not in actual_enums:
        result.missing_enums.append(enum_name)

  # Verify extensions when required.
  expected_extensions = _collect_expected_extensions()
  if expected_extensions:
    actual_extensions = {
      row[0]
      for row in connection.execute(
        text(
          """
          SELECT extname
          FROM pg_extension
          """
        )
      ).fetchall()
    }
    for extension in expected_extensions:
      if extension not in actual_extensions:
        result.missing_extensions.append(extension)

  return result


def format_failure_report(result: SchemaVerificationResult) -> str:
  """Format a single actionable failure report block."""
  # Build a structured report so operators can remediate quickly.
  lines = ["Schema verification failed:"]
  if result.missing_tables:
    lines.append("missing tables:")
    lines.extend([f"- {name}" for name in sorted(result.missing_tables)])

  if result.missing_columns:
    lines.append("missing or mismatched columns:")
    for entry in result.missing_columns:
      lines.append(f"- {entry.table}.{entry.column} expected_type={entry.expected_type} nullable={entry.expected_nullable} default={entry.expected_default} reason={entry.reason}")

  if result.missing_indexes:
    lines.append("missing indexes:")
    for entry in result.missing_indexes:
      lines.append(f"- {entry.table}.{entry.index}")

  if result.missing_constraints:
    lines.append("missing constraints:")
    for entry in result.missing_constraints:
      lines.append(f"- {entry.table}.{entry.constraint}")

  if result.missing_enums:
    lines.append("missing enums:")
    lines.extend([f"- {name}" for name in sorted(result.missing_enums)])

  if result.missing_extensions:
    lines.append("missing extensions:")
    lines.extend([f"- {name}" for name in sorted(result.missing_extensions)])

  lines.append(f"search_path={result.search_path}")
  lines.append(f"current_schema={result.current_schema}")
  return "\n".join(lines)
