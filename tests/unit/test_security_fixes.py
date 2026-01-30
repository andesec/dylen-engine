import os
from unittest.mock import patch

import pytest
from app.ai.agents.research import ResearchAgent
from app.api.models import GenerateLessonRequest
from app.config import get_settings
from app.core.middleware import _redact_sensitive_keys
from app.telemetry.llm_audit import _scrub_pii
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def setup_test_env():
  with patch.dict(os.environ, {"TAVILY_API_KEY": "dummy", "GEMINI_API_KEY": "dummy", "DYLEN_ALLOWED_ORIGINS": "http://localhost:3000"}):
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- ResearchAgent SSRF Tests ---


@pytest.mark.anyio
async def test_research_agent_blocks_private_ip():
  agent = ResearchAgent()
  # Mock socket.gethostbyname to return a private IP
  with patch("socket.gethostbyname", return_value="192.168.1.1"):
    is_safe = await agent._is_safe_url("http://internal.service")
    assert is_safe is False


@pytest.mark.anyio
async def test_research_agent_blocks_localhost():
  agent = ResearchAgent()
  with patch("socket.gethostbyname", return_value="127.0.0.1"):
    is_safe = await agent._is_safe_url("http://localhost")
    assert is_safe is False


@pytest.mark.anyio
async def test_research_agent_allows_public_ip():
  agent = ResearchAgent()
  with patch("socket.gethostbyname", return_value="8.8.8.8"):
    is_safe = await agent._is_safe_url("http://google.com")
    assert is_safe is True


@pytest.mark.anyio
async def test_research_agent_blocks_non_http():
  agent = ResearchAgent()
  is_safe = await agent._is_safe_url("ftp://example.com")
  assert is_safe is False


# --- Log Redaction Tests ---


def test_log_redaction():
  data = {"username": "user", "password": "secret_password", "nested": {"token": "secret_token", "public": "visible"}, "list": [{"key": "secret_key"}, {"other": "visible"}]}
  redacted = _redact_sensitive_keys(data)
  assert redacted["password"] == "***"
  assert redacted["username"] == "user"
  assert redacted["nested"]["token"] == "***"
  assert redacted["nested"]["public"] == "visible"
  assert redacted["list"][0]["key"] == "***"
  assert redacted["list"][1]["other"] == "visible"


# --- PII Scrubbing Tests ---


def test_pii_scrubbing_email():
  text = "Contact me at test@example.com for info."
  scrubbed = _scrub_pii(text)
  assert "[EMAIL REDACTED]" in scrubbed
  assert "test@example.com" not in scrubbed


def test_pii_scrubbing_phone():
  text = "Call 555-123-4567 now."
  scrubbed = _scrub_pii(text)
  assert "[PHONE REDACTED]" in scrubbed
  assert "555-123-4567" not in scrubbed


# --- Input Length Tests ---


def test_generate_lesson_request_max_length():
  long_details = "a" * 301
  with pytest.raises(ValidationError) as excinfo:
    GenerateLessonRequest(topic="Topic", details=long_details)

  assert "String should have at most 300 characters" in str(excinfo.value)


def test_generate_lesson_request_valid_length():
  details = "a" * 300
  req = GenerateLessonRequest(topic="Topic", details=details)
  assert req.details == details
