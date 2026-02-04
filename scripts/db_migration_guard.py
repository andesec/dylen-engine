"""Post-process Alembic migrations to wrap DDL with guarded helpers."""

from __future__ import annotations

import re
from pathlib import Path

_GUARD_IMPORT = (
  "from app.core.migration_guards import guarded_add_column, guarded_create_check_constraint, "
  "guarded_create_foreign_key, guarded_create_index, guarded_create_table, "
  "guarded_create_unique_constraint, guarded_drop_column, guarded_drop_constraint, "
  "guarded_drop_index, guarded_drop_table\n"
)

_REPLACEMENTS = {
  r"\bop\.create_table\s*\(": "guarded_create_table(",
  r"\bop\.drop_table\s*\(": "guarded_drop_table(",
  r"\bop\.add_column\s*\(": "guarded_add_column(",
  r"\bop\.drop_column\s*\(": "guarded_drop_column(",
  r"\bop\.create_index\s*\(": "guarded_create_index(",
  r"\bop\.drop_index\s*\(": "guarded_drop_index(",
  r"\bop\.create_foreign_key\s*\(": "guarded_create_foreign_key(",
  r"\bop\.create_unique_constraint\s*\(": "guarded_create_unique_constraint(",
  r"\bop\.create_check_constraint\s*\(": "guarded_create_check_constraint(",
  r"\bop\.drop_constraint\s*\(": "guarded_drop_constraint(",
}


def _ensure_guard_import(*, text: str) -> str:
  """Ensure guarded helper imports are present in the migration file."""
  # Skip insertion when the guard import already exists.
  if "from app.core.migration_guards import" in text:
    return text

  # Prefer inserting after the sqlalchemy import to keep layout predictable.
  marker = "import sqlalchemy as sa\n"
  if marker in text:
    return text.replace(marker, marker + _GUARD_IMPORT, 1)

  # Fall back to inserting after the alembic import if sqlalchemy is missing.
  fallback = "from alembic import op\n"
  if fallback in text:
    return text.replace(fallback, fallback + _GUARD_IMPORT, 1)

  # If no safe insertion point exists, append to the top of the file.
  return _GUARD_IMPORT + text


def _apply_replacements(*, text: str) -> str:
  """Replace op.* DDL calls with guarded_* equivalents."""
  # Apply each regex replacement deterministically.
  updated = text
  for pattern, replacement in _REPLACEMENTS.items():
    updated = re.sub(pattern, replacement, updated)

  return updated


def guard_migration_file(*, path: Path) -> None:
  """Rewrite a migration file to use guarded helpers."""
  # Read the migration file content.
  text = path.read_text(encoding="utf-8")
  # Ensure guarded imports exist before replacements.
  text = _ensure_guard_import(text=text)
  # Replace op.* DDL calls with guarded_* equivalents.
  text = _apply_replacements(text=text)
  # Persist the updated migration file.
  path.write_text(text, encoding="utf-8")


def guard_latest_revision(*, versions_dir: Path) -> Path:
  """Guard the most recently modified migration file and return its path."""
  # Identify migration files in the versions directory.
  candidates = [path for path in versions_dir.glob("*.py") if path.is_file()]
  if not candidates:
    raise RuntimeError(f"No migration files found in {versions_dir}.")

  # Choose the latest file by modification time.
  latest = max(candidates, key=lambda path: path.stat().st_mtime)
  guard_migration_file(path=latest)
  return latest
