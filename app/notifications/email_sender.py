"""Email delivery implementations.

MailerSend is used via its HTTP API (not SMTP) so credentials are never shared with clients.
The implementation uses the standard library to avoid additional runtime dependencies.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.notifications.contracts import EmailNotification, EmailSender

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailerSendConfig:
  """MailerSend configuration needed to send emails."""

  api_key: str
  from_address: str
  from_name: str | None
  timeout_seconds: int
  base_url: str = "https://api.mailersend.com/v1"


class MailerSendEmailSender(EmailSender):
  """MailerSend-backed email sender using the provider API."""

  def __init__(self, *, config: MailerSendConfig) -> None:
    self._config = config

  def send(self, notification: EmailNotification) -> dict[str, str | None]:
    """Send an email using the MailerSend API and return provider identifiers."""
    from_payload: dict[str, str] = {"email": self._config.from_address}
    if self._config.from_name:
      from_payload["name"] = self._config.from_name

    to_payload: dict[str, str] = {"email": notification.to_address}
    if notification.to_name:
      to_payload["name"] = notification.to_name

    payload: dict[str, object] = {"from": from_payload, "to": [to_payload], "subject": notification.subject, "text": notification.text, "html": notification.html}

    request = urllib.request.Request(
      url=f"{self._config.base_url}/email", data=json.dumps(payload).encode("utf-8"), method="POST", headers={"Authorization": f"Bearer {self._config.api_key}", "Content-Type": "application/json", "Accept": "application/json"}
    )

    try:
      with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
        raw_body = response.read().decode("utf-8") if response else ""
        headers = dict(response.headers.items()) if response else {}
        message_id = headers.get("X-Message-Id") or headers.get("X-Message-ID")

        if raw_body:
          try:
            body_json = json.loads(raw_body)
            message_id = message_id or str(body_json.get("message_id") or body_json.get("messageId") or body_json.get("id") or "")
          except json.JSONDecodeError:
            body_json = {}
        else:
          body_json = {}

        return {"provider": "mailersend", "message_id": message_id or None, "request_id": headers.get("X-Request-Id") or headers.get("X-Request-ID")}

    except urllib.error.HTTPError as exc:
      raw_error = exc.read().decode("utf-8") if exc.fp else ""
      logger.error("MailerSend email request failed status=%s body=%s", exc.code, raw_error)
      raise

    except urllib.error.URLError as exc:
      logger.error("MailerSend email request failed: %s", exc)
      raise


class NullEmailSender(EmailSender):
  """No-op email sender used when notifications are disabled."""

  def send(self, notification: EmailNotification) -> dict[str, str | None]:
    """Drop the notification while recording a debug log."""
    logger.debug("Email notifications disabled; dropping email to=%s subject=%s", notification.to_address, notification.subject)
    return {"provider": None, "message_id": None, "request_id": None}
