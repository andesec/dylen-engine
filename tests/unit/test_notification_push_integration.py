from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.notifications.contracts import InvalidPushSubscriptionError
from app.notifications.push_subscription_repo import PushSubscriptionEntry
from app.notifications.service import NotificationService


@pytest.mark.anyio
async def test_send_email_template_schedules_push_and_deletes_invalid_subscription(monkeypatch):
  email_sender = MagicMock()
  email_sender.send.return_value = {"provider": "test", "message_id": "1", "request_id": "2"}
  email_log_repo = AsyncMock()
  push_sender = MagicMock()
  push_sender.send.side_effect = InvalidPushSubscriptionError("gone")
  in_app_repo = AsyncMock()
  push_subscription_repo = AsyncMock()

  user_id = uuid.uuid4()
  push_subscription_repo.list_for_user.return_value = [
    PushSubscriptionEntry(user_id=user_id, endpoint="https://fcm.googleapis.com/fcm/send/abc", p256dh="BEl6f5Y8X5Y_u7d8mV_AbpZfXfTLT3s1O3L4wM1x8QY2_5qWQ-jxJq7uKjv8mQ4I", auth="gq8Yh5xA9l2mQ6pR", user_agent="ua")
  ]

  service = NotificationService(email_sender=email_sender, email_log_repo=email_log_repo, push_sender=push_sender, in_app_repo=in_app_repo, push_subscription_repo=push_subscription_repo, email_enabled=True, push_enabled=True)

  tasks: list[asyncio.Task] = []

  def _capture_task(coro):
    task = asyncio.get_running_loop().create_task(coro)
    tasks.append(task)
    return task

  monkeypatch.setattr("app.notifications.service.asyncio.create_task", _capture_task)

  await service.send_email_template(user_id=user_id, to_address="to@example.com", to_name=None, template_id="lesson_generated_v1", placeholders={"topic": "Python", "lesson_id": "lesson-1"})

  if tasks:
    await asyncio.gather(*tasks)

  assert push_sender.send.call_count == 1
  push_subscription_repo.delete_by_endpoint.assert_awaited_once_with(endpoint="https://fcm.googleapis.com/fcm/send/abc")


@pytest.mark.anyio
async def test_send_email_template_does_not_schedule_push_when_email_fails(monkeypatch):
  email_sender = MagicMock()
  email_sender.send.side_effect = RuntimeError("provider down")
  email_log_repo = AsyncMock()
  push_sender = MagicMock()
  in_app_repo = AsyncMock()
  push_subscription_repo = AsyncMock()

  service = NotificationService(email_sender=email_sender, email_log_repo=email_log_repo, push_sender=push_sender, in_app_repo=in_app_repo, push_subscription_repo=push_subscription_repo, email_enabled=True, push_enabled=True)

  captured = {"count": 0}

  def _capture_task(coro):
    captured["count"] += 1
    return asyncio.get_running_loop().create_task(coro)

  monkeypatch.setattr("app.notifications.service.asyncio.create_task", _capture_task)

  await service.send_email_template(user_id=uuid.uuid4(), to_address="to@example.com", to_name=None, template_id="lesson_generated_v1", placeholders={"topic": "Python", "lesson_id": "lesson-1"})

  assert captured["count"] == 0
  assert push_sender.send.call_count == 0


@pytest.mark.anyio
async def test_dispatch_push_handles_subscription_lookup_error():
  email_sender = MagicMock()
  email_sender.send.return_value = {"provider": "test"}
  email_log_repo = AsyncMock()
  push_sender = MagicMock()
  in_app_repo = AsyncMock()
  push_subscription_repo = AsyncMock()
  push_subscription_repo.list_for_user.side_effect = RuntimeError("db unavailable")

  service = NotificationService(email_sender=email_sender, email_log_repo=email_log_repo, push_sender=push_sender, in_app_repo=in_app_repo, push_subscription_repo=push_subscription_repo, email_enabled=True, push_enabled=True)

  await service._dispatch_push_for_user(user_id=uuid.uuid4(), title="title", body="body", data={})
  assert push_sender.send.call_count == 0
