"""Identifier utilities."""

from __future__ import annotations

import uuid


def generate_lesson_id() -> str:
    """Return a new lesson identifier."""
    return str(uuid.uuid4())
