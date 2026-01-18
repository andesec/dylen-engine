"""Test configuration for importing the application package."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "dgs-backend"
if str(APP_DIR) not in sys.path:
  sys.path.insert(0, str(APP_DIR))
