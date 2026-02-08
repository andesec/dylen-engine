"""Notification orchestration for user-facing events."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from app.notifications.contracts import EmailNotification, EmailSender, InvalidPushSubscriptionError, NotificationProviderError, PushNotification, PushSender
from app.notifications.email_log_repo import EmailDeliveryLogEntry, EmailDeliveryLogRepository
from app.notifications.in_app_repo import InAppNotificationEntry, InAppNotificationRepository
from app.notifications.in_app_templates import render_in_app_template
from app.notifications.push_subscription_repo import PushSubscriptionRepository
from app.notifications.template_renderer import render_email_template, render_push_content

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationPreferences:
  """Represents per-user notification preferences."""

  enable_email: bool
  enable_push: bool


class NotificationService:
  """Dispatches notifications over email and push channels."""

  def __init__(
    self, *, email_sender: EmailSender, email_log_repo: EmailDeliveryLogRepository, push_sender: PushSender, in_app_repo: InAppNotificationRepository, push_subscription_repo: PushSubscriptionRepository, email_enabled: bool, push_enabled: bool
  ) -> None:
    self._email_sender = email_sender
    self._email_log_repo = email_log_repo
    self._push_sender = push_sender
    self._in_app_repo = in_app_repo
    self._push_subscription_repo = push_subscription_repo
    self._email_enabled = email_enabled
    self._push_enabled = push_enabled

  async def send_email_template(self, *, user_id: uuid.UUID | None, to_address: str, to_name: str | None, template_id: str, placeholders: dict) -> None:
    """Send a templated email and persist a delivery audit row on a best-effort basis."""
    # Avoid sending notifications when the feature is not configured.
    if not self._email_enabled:
      return

    provider = "unknown"
    provider_message_id: str | None = None
    provider_request_id: str | None = None
    error_message: str | None = None
    status = "sent"

    try:
      # Render templates inside the try block to catch rendering errors gracefully.
      subject, text_body, html_body = render_email_template(template_id=template_id, placeholders=placeholders)
      notification = EmailNotification(to_address=to_address, to_name=to_name, subject=subject, text=text_body, html=html_body)

      send_result = await run_in_threadpool(self._email_sender.send, notification)
      provider = str(send_result.get("provider") or "unknown")
      provider_message_id = str(send_result.get("message_id") or "") or None
      provider_request_id = str(send_result.get("request_id") or "") or None

    except NotificationProviderError as exc:
      status = "error"
      error_message = str(exc)
      # Log provider-level errors without full traceback as they are often expected (e.g. 403 Forbidden).
      logger.error("Email notification delivery failed (provider error): %s", exc)

    except Exception as exc:  # noqa: BLE001
      status = "error"
      error_message = str(exc)
      logger.error("Email notification delivery failed: %s", exc, exc_info=True)

    # Persist a minimal audit record so delivery can be correlated later.
    try:
      await self._email_log_repo.insert(
        EmailDeliveryLogEntry(
          user_id=user_id,
          to_address=to_address,
          template_id=template_id,
          placeholders=placeholders,
          provider=provider,
          provider_message_id=provider_message_id,
          provider_request_id=provider_request_id,
          provider_response=None,
          status=status,
          error_message=error_message,
        )
      )
    except Exception as exc:  # noqa: BLE001
      logger.error("Email delivery log insert failed: %s", exc, exc_info=True)

    # Schedule push in the background so API responses are never blocked by push delivery.
    if self._push_enabled and user_id is not None and status == "sent":
      try:
        title, body, data = render_push_content(template_id=template_id, placeholders=placeholders)
      except Exception as exc:  # noqa: BLE001
        logger.error("Push content render failed template_id=%s error=%s", template_id, exc, exc_info=True)
      else:
        task = asyncio.create_task(self._dispatch_push_for_user(user_id=user_id, title=title, body=body, data={k: str(v) for k, v in data.items()}))
        task.add_done_callback(self._log_task_error)

  async def _dispatch_push_for_user(self, *, user_id: uuid.UUID, title: str, body: str, data: dict[str, str]) -> None:
    """Deliver a push payload to each subscription endpoint for a user."""
    # Read all endpoints first so partial failures do not block remaining devices.
    try:
      subscriptions = await self._push_subscription_repo.list_for_user(user_id=user_id)
    except Exception as exc:  # noqa: BLE001
      logger.error("Push subscription lookup failed user_id=%s error=%s", user_id, exc, exc_info=True)
      return

    for subscription in subscriptions:
      try:
        push_notification = PushNotification(endpoint=subscription.endpoint, p256dh=subscription.p256dh, auth=subscription.auth, title=title, body=body, data=data)
        await run_in_threadpool(self._push_sender.send, push_notification)
      except InvalidPushSubscriptionError:
        # Remove invalid subscriptions immediately to prevent repeated failed sends.
        try:
          await self._push_subscription_repo.delete_by_endpoint(endpoint=subscription.endpoint)
        except Exception as exc:  # noqa: BLE001
          logger.error("Failed deleting invalid push subscription endpoint=%s error=%s", subscription.endpoint, exc, exc_info=True)
      except NotificationProviderError as exc:
        logger.error("Push notification delivery failed (provider error): %s", exc)
      except Exception as exc:  # noqa: BLE001
        logger.error("Push notification delivery failed: %s", exc, exc_info=True)

  @staticmethod
  def _log_task_error(task: asyncio.Task[None]) -> None:
    """Log background task exceptions to avoid silent delivery failures."""
    try:
      _ = task.result()
    except Exception as exc:  # noqa: BLE001
      logger.error("Background push dispatch task failed: %s", exc, exc_info=True)

  async def notify_lesson_generated(self, *, user_id: uuid.UUID | None, user_email: str, lesson_id: str, topic: str) -> None:
    """Notify a user that a lesson generation job has completed successfully."""
    # Keep the payload minimal to reduce accidental data leakage over email.
    await self.send_email_template(user_id=user_id, to_address=user_email, to_name=None, template_id="lesson_generated_v1", placeholders={"topic": topic, "lesson_id": lesson_id})

  async def notify_account_approved(self, *, user_id: uuid.UUID | None, user_email: str, full_name: str | None) -> None:
    """Notify a user that their account has been approved for access."""
    # Avoid including any admin or internal state; only confirm approval.
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    await self.send_email_template(user_id=user_id, to_address=user_email, to_name=full_name, template_id="account_approved_v1", placeholders={"greeting": greeting})

  async def notify_in_app(self, *, user_id: uuid.UUID, template_id: str, data: dict) -> None:
    """Persist an in-app notification for polling clients."""
    # Render the template into a title/body payload.
    title, body = render_in_app_template(template_id=template_id, data=data)
    entry = InAppNotificationEntry(user_id=user_id, template_id=template_id, title=title, body=body, data=data)
    await self._in_app_repo.insert(entry)
