"""Push notification delivery implementations."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from http import HTTPStatus

try:
  from pywebpush import WebPushException, webpush
except Exception:  # noqa: BLE001
  WebPushException = Exception  # type: ignore[assignment]
  webpush = None

from app.notifications.contracts import InvalidPushSubscriptionError, PushNotification, PushSender, TransientPushProviderError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VapidConfig:
  """Configuration required to sign Web Push requests."""

  public_key: str
  private_key: str
  sub: str


class WebPushSender(PushSender):
  """`pywebpush` backed sender with retry and invalid-endpoint handling."""

  def __init__(self, *, vapid_config: VapidConfig, timeout_seconds: float = 10.0) -> None:
    if webpush is None:
      raise RuntimeError("pywebpush is required when push notifications are enabled.")
    self._vapid_config = vapid_config
    self._timeout_seconds = timeout_seconds

  def send(self, notification: PushNotification) -> None:
    """Send a Web Push payload with bounded retries for transient failures."""
    payload = {"title": notification.title, "body": notification.body, "data": notification.data}
    subscription_info = {"endpoint": notification.endpoint, "keys": {"p256dh": notification.p256dh, "auth": notification.auth}}
    backoff_seconds = [0.5, 1.0]

    for attempt in range(3):
      # Send with VAPID signing so browser push services can verify origin.
      try:
        webpush(subscription_info=subscription_info, data=json.dumps(payload), vapid_private_key=self._vapid_config.private_key, vapid_claims={"sub": self._vapid_config.sub}, timeout=self._timeout_seconds)
        return
      except WebPushException as exc:
        status_code = _extract_status_code(exc)

        if status_code in {HTTPStatus.GONE, HTTPStatus.NOT_FOUND}:
          raise InvalidPushSubscriptionError(f"Push subscription is invalid (status={int(status_code)})") from exc

        if status_code is not None and 500 <= int(status_code) < 600:
          if attempt < len(backoff_seconds):
            # Back off briefly to avoid amplifying transient provider incidents.
            time.sleep(backoff_seconds[attempt])
            continue

          raise TransientPushProviderError(f"Transient push provider failure after retries (status={int(status_code)})") from exc

        # Treat other provider responses as non-retriable delivery failures.
        raise TransientPushProviderError(f"Push delivery failed (status={int(status_code) if status_code else 'unknown'})") from exc


class NullPushSender(PushSender):
  """No-op push sender used when push notifications are disabled or unconfigured."""

  def send(self, notification: PushNotification) -> None:
    """Drop the notification while recording a debug log."""
    logger.debug("Push notifications disabled; dropping push endpoint_present=%s", bool(notification.endpoint))


def _extract_status_code(exc: WebPushException) -> int | None:
  """Extract an HTTP status code from a pywebpush exception when available."""
  response = getattr(exc, "response", None)
  if response is None:
    return None

  status = getattr(response, "status_code", None)
  if isinstance(status, int):
    return status

  return None
