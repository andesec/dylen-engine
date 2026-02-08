from __future__ import annotations

import json

import pytest
from app.notifications.contracts import InvalidPushSubscriptionError, PushNotification, TransientPushProviderError
from app.notifications.push_sender import VapidConfig, WebPushSender


class _FakeResponse:
  def __init__(self, status_code: int) -> None:
    self.status_code = status_code


class _FakeWebPushError(Exception):
  def __init__(self, status_code: int) -> None:
    super().__init__(f"status={status_code}")
    self.response = _FakeResponse(status_code)


def _notification() -> PushNotification:
  return PushNotification(endpoint="https://fcm.googleapis.com/fcm/send/abc", p256dh="BEl6f5Y8X5Y_u7d8mV_AbpZfXfTLT3s1O3L4wM1x8QY2_5qWQ-jxJq7uKjv8mQ4I", auth="gq8Yh5xA9l2mQ6pR", title="title", body="body", data={"url": "/lessons/1"})


def test_web_push_sender_raises_invalid_subscription_on_404(monkeypatch):
  monkeypatch.setattr("app.notifications.push_sender.time.sleep", lambda _: None)
  monkeypatch.setattr("app.notifications.push_sender.WebPushException", _FakeWebPushError)

  def _raise_404(**kwargs):
    raise _FakeWebPushError(404)

  monkeypatch.setattr("app.notifications.push_sender.webpush", _raise_404)

  sender = WebPushSender(vapid_config=VapidConfig(public_key="pub", private_key="priv", sub="mailto:test@example.com"))

  with pytest.raises(InvalidPushSubscriptionError):
    sender.send(_notification())


def test_web_push_sender_retries_5xx_three_times(monkeypatch):
  attempts = {"count": 0}
  monkeypatch.setattr("app.notifications.push_sender.time.sleep", lambda _: None)
  monkeypatch.setattr("app.notifications.push_sender.WebPushException", _FakeWebPushError)

  def _raise_503(**kwargs):
    attempts["count"] += 1
    raise _FakeWebPushError(503)

  monkeypatch.setattr("app.notifications.push_sender.webpush", _raise_503)

  sender = WebPushSender(vapid_config=VapidConfig(public_key="pub", private_key="priv", sub="mailto:test@example.com"))

  with pytest.raises(TransientPushProviderError):
    sender.send(_notification())

  assert attempts["count"] == 3


def test_web_push_sender_success_sends_expected_payload(monkeypatch):
  call = {}
  monkeypatch.setattr("app.notifications.push_sender.WebPushException", _FakeWebPushError)

  def _capture(**kwargs):
    call.update(kwargs)

  monkeypatch.setattr("app.notifications.push_sender.webpush", _capture)

  sender = WebPushSender(vapid_config=VapidConfig(public_key="pub", private_key="priv", sub="mailto:test@example.com"))
  sender.send(_notification())

  assert call["subscription_info"]["endpoint"] == "https://fcm.googleapis.com/fcm/send/abc"
  payload = json.loads(call["data"])
  assert payload["title"] == "title"
  assert payload["data"]["url"] == "/lessons/1"
