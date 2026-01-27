from __future__ import annotations

import os

from app.api.models import ModelsConfig
from app.config import get_settings
from app.services import model_routing


def test_vertex_model_prefix_routes_to_vertexai_provider() -> None:
  """Ensure vertex-* model ids infer the Vertex AI provider."""
  # Provide required settings for get_settings.
  os.environ["DGS_ALLOWED_ORIGINS"] = "http://localhost"
  os.environ["DGS_GATHERER_PROVIDER"] = "openrouter"
  os.environ["DGS_PLANNER_PROVIDER"] = "openrouter"
  os.environ["DGS_STRUCTURER_PROVIDER"] = "openrouter"
  os.environ["DGS_REPAIR_PROVIDER"] = "gemini"
  settings = get_settings.__wrapped__()
  models = ModelsConfig(gatherer_model="vertex-gemini-3.0-pro", planner_model="vertex-gemini-3.0-pro", structurer_model="vertex-gemini-3.0-pro", repairer_model="vertex-gemini-3.0-flash")
  (gatherer_provider, _, planner_provider, _, structurer_provider, _, repairer_provider, _) = model_routing._resolve_model_selection(settings, models=models)
  assert gatherer_provider == "vertexai"
  assert planner_provider == "vertexai"
  assert structurer_provider == "vertexai"
  assert repairer_provider == "vertexai"


def test_unprefixed_unknown_model_keeps_fallback_provider() -> None:
  """Ensure unknown model ids do not change provider routing."""
  # Provide required settings for get_settings.
  os.environ["DGS_ALLOWED_ORIGINS"] = "http://localhost"
  os.environ["DGS_PLANNER_PROVIDER"] = "openrouter"
  settings = get_settings.__wrapped__()
  assert model_routing._provider_for_model_hint("gemini-3.0-pro", settings.planner_provider) == "openrouter"
