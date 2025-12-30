"""Identifier utilities."""

from __future__ import annotations

import uuid


def generate_lesson_id() -> str:
    """Return a new lesson identifier."""
    return str(uuid.uuid4())


def generate_job_id() -> str:
    """Return a new job identifier."""
    return str(uuid.uuid4())
