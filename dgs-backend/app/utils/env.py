"""Lightweight .env loader for local configuration."""

from __future__ import annotations

import os
from pathlib import Path


def default_env_path() -> Path:
  """Return the default .env path at the repo root."""

  return Path(__file__).resolve().parents[3] / ".env"


def load_env_file(path: Path, *, override: bool = False) -> None:
  """Load key=value pairs from a .env file into the process environment."""

  if not path.is_file():
    return

  for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    if line.startswith("export "):
      line = line[len("export ") :].lstrip()
    if "=" not in line:
      continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
      continue
    if (value.startswith('"') and value.endswith('"')) or (
      value.startswith("'") and value.endswith("'")
    ):
      value = value[1:-1]
    if not override and key in os.environ:
      continue
    os.environ[key] = value
