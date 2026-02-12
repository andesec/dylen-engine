"""Identifier utilities."""

from __future__ import annotations

import secrets
import string
import uuid


def generate_lesson_id() -> str:
  """Return a new lesson identifier."""
  return str(uuid.uuid4())


def generate_job_id() -> str:
  """Return a new job identifier."""
  return str(uuid.uuid4())


def generate_nanoid(size: int = 16) -> str:
  """Return a short non-sequential id suitable for public references."""
  alphabet = string.ascii_letters + string.digits
  return "".join(secrets.choice(alphabet) for _ in range(size))
