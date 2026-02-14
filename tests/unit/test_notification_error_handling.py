import urllib.error
import uuid
from unittest.mock import MagicMock, patch

import pytest
from app.notifications.contracts import EmailNotification, NotificationProviderError
from app.notifications.email_sender import MailerSendConfig, MailerSendEmailSender
from app.notifications.service import NotificationService


@pytest.fixture
def mock_email_sender():
  return MagicMock()


@pytest.fixture
def mock_email_log_repo():
  return MagicMock()


@pytest.fixture
def mock_push_sender():
  return MagicMock()


@pytest.fixture
def mock_in_app_repo():
  return MagicMock()


@pytest.fixture
def mock_push_subscription_repo():
  return MagicMock()


@pytest.fixture
def notification_service(mock_email_sender, mock_email_log_repo, mock_push_sender, mock_in_app_repo, mock_push_subscription_repo):
  return NotificationService(email_sender=mock_email_sender, email_log_repo=mock_email_log_repo, push_sender=mock_push_sender, in_app_repo=mock_in_app_repo, push_subscription_repo=mock_push_subscription_repo, email_enabled=True, push_enabled=True)


@pytest.mark.anyio
async def test_send_email_template_handles_provider_error(notification_service, mock_email_sender, mock_email_log_repo):
  # Setup: mock email sender to raise NotificationProviderError
  mock_email_sender.send.side_effect = NotificationProviderError("HTTP Error 403: Forbidden")

  # Mock template rendering
  with patch("app.notifications.service.render_email_template") as mock_render:
    mock_render.return_value = ("Subject", "Text", "HTML")

    # Test
    await notification_service.send_email_template(user_id=uuid.uuid4(), to_address="test@example.com", to_name="Test User", template_id="test_template", placeholders={})

  # Verify: audit log was inserted with "error" status
  mock_email_log_repo.insert.assert_called_once()
  log_entry = mock_email_log_repo.insert.call_args[0][0]
  assert log_entry.status == "error"
  assert "HTTP Error 403" in log_entry.error_message


@pytest.mark.anyio
async def test_send_email_template_handles_rendering_error(notification_service, mock_email_log_repo):
  # Setup: mock template rendering to fail
  with patch("app.notifications.service.render_email_template") as mock_render:
    mock_render.side_effect = ValueError("Missing placeholders")

    # Test
    await notification_service.send_email_template(user_id=uuid.uuid4(), to_address="test@example.com", to_name="Test User", template_id="test_template", placeholders={})

  # Verify: audit log was inserted with "error" status
  mock_email_log_repo.insert.assert_called_once()
  log_entry = mock_email_log_repo.insert.call_args[0][0]
  assert log_entry.status == "error"
  assert "Missing placeholders" in log_entry.error_message


def test_mailer_send_email_sender_raises_provider_error():
  config = MailerSendConfig(api_key="key", from_address="from@ex.com", from_name="From", timeout_seconds=5)
  sender = MailerSendEmailSender(config=config)

  notification = EmailNotification(to_address="to@ex.com", to_name="To", subject="Sub", text="Text", html="HTML")

  # Mock urllib.request.urlopen to raise HTTPError
  with patch("urllib.request.urlopen") as mock_urlopen:
    mock_urlopen.side_effect = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)

    with pytest.raises(NotificationProviderError) as excinfo:
      sender.send(notification)

    assert "HTTP Error 403" in str(excinfo.value)
