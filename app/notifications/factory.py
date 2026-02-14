"""Factory helpers for notification services."""

from __future__ import annotations

from app.config import Settings
from app.notifications.email_log_repo import EmailDeliveryLogRepository, NullEmailDeliveryLogRepository
from app.notifications.email_sender import MailerSendConfig, MailerSendEmailSender, NullEmailSender
from app.notifications.in_app_repo import InAppNotificationRepository, NullInAppNotificationRepository
from app.notifications.push_sender import NullPushSender, VapidConfig, WebPushSender
from app.notifications.push_subscription_repo import PushSubscriptionRepository
from app.notifications.service import NotificationService


def build_notification_service(settings: Settings, *, email_enabled: bool | None = None) -> NotificationService:
  """Construct a notification service based on environment configuration."""
  # Allow callers to override email enablement using feature flags.
  effective_email_enabled = settings.email_notifications_enabled if email_enabled is None else bool(email_enabled)

  # Email is disabled by default to avoid accidental delivery in dev/test.
  if effective_email_enabled:
    mailersend_config = MailerSendConfig(
      api_key=settings.mailersend_api_key or "", from_address=settings.email_from_address or "", from_name=settings.email_from_name, timeout_seconds=settings.mailersend_timeout_seconds, base_url=settings.mailersend_base_url
    )
    email_sender = MailerSendEmailSender(config=mailersend_config)
  else:
    email_sender = NullEmailSender()

  # Persist email logs only when Postgres is configured.
  if settings.pg_dsn:
    email_log_repo: EmailDeliveryLogRepository = EmailDeliveryLogRepository()
  else:
    email_log_repo = NullEmailDeliveryLogRepository()

  # Persist in-app notifications only when Postgres is configured.
  if settings.pg_dsn:
    in_app_repo: InAppNotificationRepository = InAppNotificationRepository()
  else:
    in_app_repo = NullInAppNotificationRepository()

  # Push follows the same event path as email notifications in this phase.
  effective_push_enabled = bool(settings.push_notifications_enabled) and bool(effective_email_enabled)
  if effective_push_enabled and settings.push_vapid_public_key and settings.push_vapid_private_key and settings.push_vapid_sub:
    push_sender = WebPushSender(vapid_config=VapidConfig(public_key=settings.push_vapid_public_key, private_key=settings.push_vapid_private_key, sub=settings.push_vapid_sub))
  else:
    push_sender = NullPushSender()

  push_subscription_repo = PushSubscriptionRepository()
  return NotificationService(
    email_sender=email_sender, email_log_repo=email_log_repo, push_sender=push_sender, in_app_repo=in_app_repo, push_subscription_repo=push_subscription_repo, email_enabled=effective_email_enabled, push_enabled=effective_push_enabled
  )
