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

  title: str
  body: str
  token: str


class EmailSender(Protocol):
  """Delivery contract for sending email notifications."""

  def send(self, notification: EmailNotification) -> dict[str, str | None]:
    """Send an email notification synchronously and return provider identifiers."""


class PushSender(Protocol):
  """Delivery contract for sending push notifications."""

  def send(self, notification: PushNotification) -> None:
    """Send a push notification synchronously."""
