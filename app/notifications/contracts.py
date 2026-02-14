"""Contracts for user notification delivery channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmailNotification:
  """Represents an email notification payload."""

  to_address: str
  to_name: str | None
  subject: str
  text: str
  html: str


@dataclass(frozen=True)
class PushNotification:
  """Represents a push notification payload."""

  endpoint: str
  p256dh: str
  auth: str
  title: str
  body: str
  data: dict[str, str]


class NotificationError(Exception):
  """Base class for all notification delivery failures."""


class NotificationProviderError(NotificationError):
  """Exception raised when a specific provider (e.g. MailerSend) returns a delivery error."""


class InvalidPushSubscriptionError(NotificationProviderError):
  """Exception raised when a push subscription endpoint is expired or invalid."""


class TransientPushProviderError(NotificationProviderError):
  """Exception raised when transient push provider failures exhaust retries."""


class EmailSender(Protocol):
  """Delivery contract for sending email notifications."""

  def send(self, notification: EmailNotification) -> dict[str, str | None]:
    """Send an email notification synchronously and return provider identifiers."""


class PushSender(Protocol):
  """Delivery contract for sending push notifications."""

  def send(self, notification: PushNotification) -> None:
    """Send a push notification synchronously."""
