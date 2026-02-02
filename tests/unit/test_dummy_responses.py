"""Tests for deterministic dummy AI responses."""

from __future__ import annotations

import pytest


def test_load_dummy_response_resolves_repo_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
  # Ensure the helper does not attempt to load the repo `.env` during this unit test.
  from app.ai.providers import base

  base._ENV_LOADED = True
  # Enable the SECTION_BUILDER dummy response without providing an explicit path.
  monkeypatch.setenv("DYLEN_USE_DUMMY_SECTION_BUILDER_RESPONSE", "1")
  monkeypatch.delenv("DYLEN_DUMMY_SECTION_BUILDER_RESPONSE_PATH", raising=False)
  # The repo includes `fixtures/dummy_section_builder_response.md`, so this should load successfully.
  text = base.AIModel.load_dummy_response("SECTION_BUILDER")
  assert text is not None
  assert len(text) > 0


def test_env_agent_key_snake_cases_agent_names() -> None:
  from app.ai.agents.base import BaseAgent

  assert BaseAgent._env_agent_key("SectionBuilder") == "SECTION_BUILDER"
  assert BaseAgent._env_agent_key("Planner") == "PLANNER"
