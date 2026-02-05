"""Factory helpers for notification services."""

from __future__ import annotations

from app.config import Settings
from app.notifications.email_log_repo import EmailDeliveryLogRepository, NullEmailDeliveryLogRepository
from app.notifications.email_sender import MailerSendConfig, MailerSendEmailSender, NullEmailSender
from app.notifications.in_app_repo import InAppNotificationRepository, NullInAppNotificationRepository
from app.notifications.push_sender import NullPushSender
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

  # Push is currently a no-op until a provider integration is configured.
  push_sender = NullPushSender()
  return NotificationService(email_sender=email_sender, email_log_repo=email_log_repo, push_sender=push_sender, in_app_repo=in_app_repo, email_enabled=effective_email_enabled, push_enabled=False)
