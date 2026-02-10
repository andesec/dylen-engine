"""HTML email and push notification template rendering.

Email HTML must be table-based and rely on inline styles for compatibility with major clients.
Templates are stored on disk and rendered with escaped placeholders.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@dataclass(frozen=True)
class NotificationTemplate:
  """Template metadata and file locations for email and push."""

  template_id: str
  subject_template: str
  html_filename: str
  text_filename: str
  push_filename: str
  required_placeholders: set[str]
  navigation_keys: set[str] = field(default_factory=set)


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

TEMPLATES: dict[str, NotificationTemplate] = {
  "lesson_generated_v1": NotificationTemplate(
    template_id="lesson_generated_v1",
    subject_template="Your lesson is ready: {{topic}}",
    html_filename="lesson_generated_v1.html",
    text_filename="lesson_generated_v1.txt",
    push_filename="lesson_generated_v1.push.txt",
    required_placeholders={"topic", "lesson_id"},
    navigation_keys={"lesson_id"},
  ),
  "account_approved_v1": NotificationTemplate(
    template_id="account_approved_v1", subject_template="Your account has been approved", html_filename="account_approved_v1.html", text_filename="account_approved_v1.txt", push_filename="account_approved_v1.push.txt", required_placeholders={"greeting"}
  ),
}


def render_email_template(*, template_id: str, placeholders: dict[str, Any]) -> tuple[str, str, str]:
  """Render subject/text/html for a template id using escaped placeholders."""
  template = _get_template(template_id)
  _validate_placeholders(template=template, placeholders=placeholders)
  subject = _render_text(template.subject_template, placeholders=placeholders, escape_html=False)
  html_payload = _render_text(_load_template_file(template.html_filename), placeholders=placeholders, escape_html=True)
  text_payload = _render_text(_load_template_file(template.text_filename), placeholders=placeholders, escape_html=False)
  return subject, text_payload, html_payload


def render_push_content(*, template_id: str, placeholders: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
  """Render push notification title, body and extract navigation data."""
  template = _get_template(template_id)
  _validate_placeholders(template=template, placeholders=placeholders)

  title = _render_text(template.subject_template, placeholders=placeholders, escape_html=False)
  body = _render_text(_load_template_file(template.push_filename), placeholders=placeholders, escape_html=False)

  data = {k: placeholders[k] for k in template.navigation_keys if k in placeholders}
  url = _build_push_url(template_id=template_id, placeholders=placeholders)
  if url is not None:
    data["url"] = url

  return title, body, data


def _validate_placeholders(*, template: NotificationTemplate, placeholders: dict[str, Any]) -> None:
  """Ensure required placeholders exist to avoid sending malformed emails."""
  missing = sorted(template.required_placeholders - set(placeholders.keys()))
  if missing:
    raise ValueError(f"Missing placeholders for template '{template.template_id}': {', '.join(missing)}")


def _render_text(raw_template: str, *, placeholders: dict[str, Any], escape_html: bool) -> str:
  """Replace {{placeholders}} with values, escaping for HTML when needed."""

  def _replace(match: re.Match[str]) -> str:
    key = match.group(1)
    value = placeholders.get(key, "")
    rendered = str(value) if value is not None else ""
    if escape_html:
      return html.escape(rendered, quote=True)
    return rendered

  return _PLACEHOLDER_RE.sub(_replace, raw_template)


@lru_cache(maxsize=16)
def _load_template_file(filename: str) -> str:
  """Load a template file from disk with caching."""
  path = _TEMPLATE_DIR / filename
  return path.read_text(encoding="utf-8")


def _get_template(template_id: str) -> NotificationTemplate:
  """Resolve a template configuration by id."""
  template = TEMPLATES.get(template_id)
  if template is None:
    raise ValueError(f"Unknown notification template: {template_id}")
  return template


def _build_push_url(*, template_id: str, placeholders: dict[str, Any]) -> str | None:
  """Build a frontend navigation URL for known notification templates."""
  # Keep URL mapping explicit so only approved paths are sent to clients.
  if template_id == "lesson_generated_v1":
    lesson_id = placeholders.get("lesson_id")
    if lesson_id:
      return f"/lessons/{lesson_id}"

  return None
