from __future__ import annotations

import os

from app.api.models import ModelsConfig
from app.config import get_settings
from app.services import model_routing


def test_vertex_model_prefix_routes_to_vertexai_provider() -> None:
  """Ensure vertex-* model ids infer the Vertex AI provider."""
  # Provide required settings for get_settings.
  os.environ["DYLEN_ALLOWED_ORIGINS"] = "http://localhost"
  os.environ["DYLEN_SECTION_BUILDER_PROVIDER"] = "openrouter"
  os.environ["DYLEN_PLANNER_PROVIDER"] = "openrouter"
  os.environ["DYLEN_REPAIR_PROVIDER"] = "gemini"
  settings = get_settings.__wrapped__()
  models = ModelsConfig(section_builder_model="vertex-gemini-3.0-pro", planner_model="vertex-gemini-3.0-pro", repairer_model="vertex-gemini-3.0-flash")
  (section_builder_provider, _, planner_provider, _, repairer_provider, _) = model_routing._resolve_model_selection(settings, models=models)
  assert section_builder_provider == "vertexai"
  assert planner_provider == "vertexai"
  assert repairer_provider == "vertexai"


def test_unprefixed_unknown_model_keeps_fallback_provider() -> None:
  """Ensure unknown model ids do not change provider routing."""
  # Provide required settings for get_settings.
  os.environ["DYLEN_ALLOWED_ORIGINS"] = "http://localhost"
  os.environ["DYLEN_PLANNER_PROVIDER"] = "openrouter"
  settings = get_settings.__wrapped__()
  assert model_routing._provider_for_model_hint("gemini-3.0-pro", settings.planner_provider) == "openrouter"
