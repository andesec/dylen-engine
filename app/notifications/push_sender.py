"""Push notification delivery stubs.

Push notifications require a device token lifecycle and provider integration (e.g. FCM/APNs).
This module keeps a strict interface so an implementation can be added without touching callers.
"""

from __future__ import annotations

import logging

from app.notifications.contracts import PushNotification, PushSender

logger = logging.getLogger(__name__)


class NullPushSender(PushSender):
  """No-op push sender used when push notifications are disabled or unconfigured."""

  def send(self, notification: PushNotification) -> None:
    """Drop the notification while recording a debug log."""
    logger.debug("Push notifications disabled; dropping push token_prefix=%s", (notification.token or "")[:8])
