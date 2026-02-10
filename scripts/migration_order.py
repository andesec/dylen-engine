"""Helpers to load Alembic migrations in a deterministic Create Date order."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_CREATE_DATE_RE = re.compile(r"^Create Date:\s*(?P<value>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class MigrationInfo:
  """Parsed migration metadata needed for ordering checks."""

  revision: str
  down_revision: str | None
  down_revisions: tuple[str, ...]
  is_merge: bool
  create_date: datetime
  path: Path


def _repo_root() -> Path:
  """Resolve the repository root so path resolution is deterministic."""
  # Anchor on this script's location to find the repo root.
  return Path(__file__).resolve().parents[1]


def load_script_directory() -> ScriptDirectory:
  """Load the Alembic script directory using repo-local config."""
  # Build the Alembic config path from the repository root.
  repo_root = _repo_root()
  config_path = repo_root / "alembic.ini"
  script_path = repo_root / "alembic"
  config = Config(str(config_path))
  # Override script_location so CI/local runs behave the same.
  config.set_main_option("script_location", str(script_path))
  return ScriptDirectory.from_config(config)


def _parse_create_date(*, text: str, path: Path) -> datetime:
  """Parse the Create Date header value into a timezone-aware datetime."""
  # Match the Create Date header line from Alembic's template.
  match = _CREATE_DATE_RE.search(text)
  if not match:
    raise RuntimeError(f"Missing Create Date header in migration: {path}")

  # Parse the timestamp using Python's ISO parser.
  raw_value = match.group("value").strip()
  try:
    parsed = datetime.fromisoformat(raw_value)
  except ValueError as exc:
    raise RuntimeError(f"Invalid Create Date value {raw_value!r} in {path}") from exc

  # Normalize to UTC when no timezone info is present.
  if parsed.tzinfo is None:
    return parsed.replace(tzinfo=UTC)

  # Convert aware timestamps to UTC for consistent ordering.
  return parsed.astimezone(UTC)


def _format_create_date(*, value: datetime) -> str:
  """Format a Create Date value to match Alembic's header style."""
  # Normalize to UTC so ordering logic stays deterministic across timezones.
  normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
  # Strip timezone info because Alembic's default header omits offsets.
  return normalized.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


def rewrite_create_date(*, path: Path, create_date: datetime) -> None:
  """Rewrite a migration file's Create Date header to the supplied timestamp."""
  # Read the migration file so we can update the header in-place.
  text = path.read_text(encoding="utf-8")
  # Format the new Create Date to match Alembic's default template output.
  formatted = _format_create_date(value=create_date)
  # Require the header to exist so updates remain explicit.
  if not _CREATE_DATE_RE.search(text):
    raise RuntimeError(f"Missing Create Date header in migration: {path}")
  # Replace the first Create Date header line with the new value.
  updated = _CREATE_DATE_RE.sub(f"Create Date: {formatted}", text, count=1)
  # Persist the rewritten migration file.
  path.write_text(updated, encoding="utf-8")


def _load_migration_info(revision: object) -> MigrationInfo:
  """Load MigrationInfo for a single Alembic revision."""
  # Read the revision's metadata from the Alembic revision object.
  revision_id = str(revision.revision)
  down_revision = revision.down_revision
  down_value = None
  down_values: tuple[str, ...] = ()
  is_merge = False
  if isinstance(down_revision, str):
    down_value = down_revision
    down_values = (down_revision,)
  elif isinstance(down_revision, (tuple, list)):
    down_values = tuple(str(value) for value in down_revision)
    is_merge = True

  # Read the migration file content to parse Create Date.
  path = Path(revision.path)
  text = path.read_text(encoding="utf-8")
  create_date = _parse_create_date(text=text, path=path)
  return MigrationInfo(revision=revision_id, down_revision=down_value, down_revisions=down_values, is_merge=is_merge, create_date=create_date, path=path)


def load_migration_chain() -> list[MigrationInfo]:
  """Return migrations ordered from base to heads (merge-aware)."""
  # Load the Alembic script directory for revision inspection.
  script = load_script_directory()
  # Walk revisions from heads to base to handle multiple heads.
  revisions = list(script.walk_revisions(base="base", head="heads"))
  # Reverse so the chain runs from base to heads.
  ordered = list(reversed(revisions))
  # Convert to MigrationInfo entries in deterministic order.
  return [_load_migration_info(revision) for revision in ordered]
