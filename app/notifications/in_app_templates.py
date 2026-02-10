"""Templates for in-app notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InAppTemplate:
  """Define an in-app notification template."""

  template_id: str
  title_template: str
  body_template: str
  required_keys: set[str]


TEMPLATES: dict[str, InAppTemplate] = {
  "lesson_job_failed_retry_v1": InAppTemplate(template_id="lesson_job_failed_retry_v1", title_template="Lesson job failed", body_template="Your lesson job failed. Retry is available for job {{job_id}}.", required_keys={"job_id"}),
  "child_job_failed_retry_v1": InAppTemplate(template_id="child_job_failed_retry_v1", title_template="Lesson helper job failed", body_template="A helper job failed. Retry is available for job {{job_id}}.", required_keys={"job_id"}),
}


def render_in_app_template(*, template_id: str, data: dict[str, Any]) -> tuple[str, str]:
  """Render a template into a title and body string."""
  template = TEMPLATES.get(template_id)
  if template is None:
    raise ValueError(f"Unknown in-app template: {template_id}")
  missing = sorted(template.required_keys - set(data.keys()))
  if missing:
    raise ValueError(f"Missing placeholders for template '{template_id}': {', '.join(missing)}")
  title = template.title_template
  body = template.body_template
  for key, value in data.items():
    title = title.replace(f"{{{{{key}}}}}", str(value))
    body = body.replace(f"{{{{{key}}}}}", str(value))
  return title, body
