"""Run consolidated seed logic for the squashed baseline revision."""

from __future__ import annotations

import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncConnection

_LEGACY_SEED_REVISIONS: tuple[str, ...] = ("3a941f60baac", "7c3d9e2a1f44", "3055a1cfd37e", "b4629cbd83a3", "de1ca932736f", "c0d661232a11", "9ca2ccec4b98")


def _load_seed_callable(*, revision: str) -> Callable[[AsyncConnection], Awaitable[None]]:
  """Load a legacy seed module from disk and return its async seed entrypoint."""
  # Resolve the historical seed script path relative to this baseline seed file.
  seed_path = Path(__file__).resolve().parent / f"{revision}.py"
  if not seed_path.exists():
    raise RuntimeError(f"Legacy seed script not found: {seed_path}")
  # Use importlib so revision-style filenames remain loadable as Python modules.
  spec = importlib.util.spec_from_file_location(f"seed_{revision}", seed_path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load legacy seed script: {seed_path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  # Require an async seed() function for consistency with the seed runner.
  seed_callable = getattr(module, "seed", None)
  if seed_callable is None:
    raise RuntimeError(f"Legacy seed script missing seed(): {seed_path}")
  return seed_callable


async def seed(connection: AsyncConnection) -> None:
  """Replay legacy seed revisions so squashed installs keep required baseline data."""
  # Execute each historical seed step in migration order to preserve data semantics.
  for revision in _LEGACY_SEED_REVISIONS:
    seed_callable = _load_seed_callable(revision=revision)
    await seed_callable(connection)
