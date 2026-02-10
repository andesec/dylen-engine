"""Targeted schema repair runner for migrations."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from alembic import op as alembic_op
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from scripts.migration_order import load_migration_chain
from scripts.schema_checks import SchemaVerificationResult, format_failure_report, verify_schema
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

logger = logging.getLogger("scripts.repair_schema")


@dataclass(frozen=True)
class RepairTarget:
  """Describe a missing schema item for targeted repair."""

  kind: str
  name: str


@dataclass(frozen=True)
class RepairRevision:
  """Describe a revision eligible for repair."""

  revision: str
  path: Path
  repair_safe: bool
  targets: dict[str, list[str]]


def _normalize_async_dsn(raw_dsn: str) -> str:
  """Normalize DSNs so repairs consistently use asyncpg."""
  # Convert sync postgres URLs to asyncpg for consistent async execution.
  dsn = raw_dsn.strip()
  if dsn.startswith("postgresql+asyncpg://"):
    return dsn
  if dsn.startswith("postgresql://"):
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
  if dsn.startswith("postgres://"):
    return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
  return dsn


def _load_revision_module(path: Path) -> ModuleType:
  """Load a revision module from disk."""
  # Load the module using importlib to avoid sys.path collisions.
  spec = importlib.util.spec_from_file_location(path.stem, path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load migration module: {path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def _load_repair_revisions() -> list[RepairRevision]:
  """Load repair metadata for each migration in chain order."""
  # Build the ordered migration chain so repairs stay deterministic.
  chain = load_migration_chain()
  revisions: list[RepairRevision] = []
  # Load each revision module to extract repair metadata.
  for info in chain:
    module = _load_revision_module(info.path)
    targets = getattr(module, "REPAIR_TARGETS", {})
    repair_safe = bool(getattr(module, "REPAIR_SAFE", True))
    revisions.append(RepairRevision(revision=info.revision, path=info.path, repair_safe=repair_safe, targets=targets))
  return revisions


def _targets_for_result(result: SchemaVerificationResult) -> list[RepairTarget]:
  """Flatten verification results into repair targets."""
  # Collect missing objects by kind for mapping to revisions.
  targets: list[RepairTarget] = []
  # Map missing tables to repair targets.
  for table in result.missing_tables:
    targets.append(RepairTarget(kind="tables", name=table))
  # Map missing columns to repair targets.
  for column in result.missing_columns:
    targets.append(RepairTarget(kind="columns", name=f"{column.table}.{column.column}"))
  # Map missing indexes to repair targets.
  for index in result.missing_indexes:
    targets.append(RepairTarget(kind="indexes", name=index.index))
  # Map missing constraints to repair targets.
  for constraint in result.missing_constraints:
    targets.append(RepairTarget(kind="constraints", name=constraint.constraint))
  # Map missing enums to repair targets.
  for enum_name in result.missing_enums:
    targets.append(RepairTarget(kind="enums", name=enum_name))
  # Map missing extensions to repair targets.
  for extension in result.missing_extensions:
    targets.append(RepairTarget(kind="extensions", name=extension))
  return targets


def _matches_target(*, revision: RepairRevision, target: RepairTarget) -> bool:
  """Return True when a revision declares ownership of a target."""
  # Use explicit target lists to map missing objects to revisions.
  entries = revision.targets.get(target.kind, [])
  if "*" in entries:
    return True
  return target.name in entries


def _select_revisions(result: SchemaVerificationResult) -> tuple[list[RepairRevision], list[RepairTarget]]:
  """Select revisions to repair and targets that could not be mapped."""
  # Load declared repair targets for each revision.
  revisions = _load_repair_revisions()
  targets = _targets_for_result(result)
  selected: list[RepairRevision] = []
  unresolved: list[RepairTarget] = []

  # Map targets to revisions, preferring explicit matches over wildcards.
  for target in targets:
    # Track explicit matches separately from wildcard matches.
    matched = None
    wildcard = None
    for revision in revisions:
      if _matches_target(revision=revision, target=target):
        if target.name in revision.targets.get(target.kind, []):
          matched = revision
          break
        wildcard = revision
    if matched is None and wildcard is not None:
      matched = wildcard
    if matched is None:
      unresolved.append(target)
      continue
    # Avoid duplicate repair runs for the same revision.
    if matched not in selected:
      selected.append(matched)

  # Preserve chain order when running repairs.
  ordered = [rev for rev in revisions if rev in selected]
  return ordered, unresolved


def _run_revision_upgrade(connection: Connection, module: ModuleType) -> None:
  """Run a revision's upgrade using Alembic's op proxy."""
  # Build a migration context for the current connection.
  context = MigrationContext.configure(connection)
  operations = Operations(context)

  # Install the operations proxy so migration code can use alembic.op.
  alembic_op._proxy = operations
  try:
    module.upgrade()
  finally:
    alembic_op._proxy = None


async def _repair_schema(*, connection: AsyncConnection, schema: str = "public") -> SchemaVerificationResult:
  """Verify and repair missing schema objects."""
  # Enforce schema at the transaction level.
  await connection.execute(text("SET LOCAL search_path TO public"))
  # Verify the schema before attempting repair.
  verification = await connection.run_sync(verify_schema, schema=schema)
  if not verification.has_failures():
    logger.info("Schema verification passed; no repair needed.")
    return verification

  # Emit a detailed report before attempting repairs.
  logger.warning("Schema verification failed; beginning targeted repair.")
  logger.warning("%s", format_failure_report(verification))

  # Resolve which revisions to replay based on missing objects.
  revisions, unresolved = _select_revisions(verification)
  if unresolved:
    unresolved_list = ", ".join(f"{item.kind}:{item.name}" for item in unresolved)
    logger.warning("Unmapped repair targets: %s", unresolved_list)

  # Replay only the revisions that own missing objects.
  for revision in revisions:
    if not revision.repair_safe:
      logger.error("Skipping repair for %s because REPAIR_SAFE is false.", revision.revision)
      continue
    logger.info("Replaying revision %s (%s).", revision.revision, revision.path.name)
    module = _load_revision_module(revision.path)
    await connection.run_sync(_run_revision_upgrade, module)

  # Re-verify to confirm repairs succeeded.
  await connection.execute(text("SET LOCAL search_path TO public"))
  return await connection.run_sync(verify_schema, schema=schema)


def main() -> None:
  """Entrypoint for targeted schema repair."""
  # Configure base logging for CLI usage.
  logging.basicConfig(level=logging.INFO)
  # Allow fail-open behavior for environments that must not hard-fail.
  fail_open = (os.getenv("DYLEN_MIGRATOR_FAIL_OPEN") or "").strip().lower() in {"1", "true", "yes", "on"}
  # Read the database DSN from the environment for safety.
  raw_dsn = (os.getenv("DYLEN_PG_DSN") or "").strip()
  if not raw_dsn:
    raise RuntimeError("DYLEN_PG_DSN must be set to run schema repair.")

  # Normalize the DSN so async connections are consistent.
  normalized_dsn = _normalize_async_dsn(raw_dsn)
  # Create the async engine for repair.
  engine = create_async_engine(normalized_dsn, future=True)

  async def _runner() -> None:
    # Wrap execution so the engine always disposes.
    try:
      # Open a transaction so SET LOCAL applies within repair.
      async with engine.begin() as connection:
        result = await _repair_schema(connection=connection)
        if result.has_failures():
          report = format_failure_report(result)
          if fail_open:
            logger.error("%s", report)
            logger.error("DYLEN_MIGRATOR_FAIL_OPEN enabled; continuing despite repair failures.")
          else:
            raise RuntimeError(report)
        # Log successful completion for operators and CI visibility.
        logger.info("Schema repair completed successfully.")
    finally:
      # Dispose the engine to close connections cleanly.
      await engine.dispose()

  # Run the async repair flow.
  asyncio.run(_runner())


if __name__ == "__main__":
  main()
