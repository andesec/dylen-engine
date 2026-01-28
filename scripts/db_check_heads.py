from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _load_alembic_config() -> Config:
  """Build the Alembic config with a stable script path for CI and local runs."""
  # Resolve repository paths relative to this script.
  repo_root = Path(__file__).resolve().parents[1]
  backend_dir = repo_root / "dgs-backend"
  config_path = backend_dir / "alembic.ini"
  script_path = backend_dir / "alembic"
  config = Config(str(config_path))
  # Override script_location so alembic runs from the repo root in CI.
  config.set_main_option("script_location", str(script_path))
  return config


def check_single_head() -> int:
  """Inspect heads to block merges when multiple branches diverge."""
  # Load the Alembic script directory so we can inspect heads directly.
  config = _load_alembic_config()
  script = ScriptDirectory.from_config(config)
  heads = script.get_heads()

  # Fail CI if there is not exactly one head.
  if len(heads) != 1:
    print("ERROR: Multiple Alembic heads detected.")
    print(f"Found heads: {', '.join(heads) if heads else '(none)'}")
    print("Remediation: rebase migrations to a single head, or create a merge revision only if approved.")
    return 1

  print(f"OK: Single Alembic head detected ({heads[0]}).")
  return 0


def main() -> None:
  """Run the single-head check and return an exit status for CI gating."""
  # Exit with a non-zero code so CI blocks merges on failure.
  exit_code = check_single_head()
  sys.exit(exit_code)


if __name__ == "__main__":
  main()
