from __future__ import annotations

from app.api.models import PlannerModel, RepairerModel, SectionBuilderModel

_GEMINI_PROVIDER = "gemini"
_OPENROUTER_PROVIDER = "openrouter"
_VERTEXAI_PROVIDER = "vertexai"
_VERTEX_MODEL_PREFIX = "vertex-"

_GEMINI_SECTION_BUILDER_MODELS = {SectionBuilderModel.GEMINI_25_FLASH, SectionBuilderModel.GEMINI_25_PRO}

_OPENROUTER_SECTION_BUILDER_MODELS = {
  SectionBuilderModel.XIAOMI_MIMO_V2_FLASH,
  SectionBuilderModel.DEEPSEEK_R1_0528,
  SectionBuilderModel.LLAMA_31_405B,
  SectionBuilderModel.GPT_OSS_120B,
  SectionBuilderModel.GPT_OSS_20B,
  SectionBuilderModel.LLAMA_33_70B,
  SectionBuilderModel.GEMMA_3_27B,
}

_GEMINI_PLANNER_MODELS = {PlannerModel.GEMINI_25_PRO, PlannerModel.GEMINI_PRO_LATEST}

_OPENROUTER_PLANNER_MODELS = {PlannerModel.GPT_OSS_120B, PlannerModel.XIAOMI_MIMO_V2_FLASH, PlannerModel.LLAMA_31_405B, PlannerModel.DEEPSEEK_R1_0528}

_GEMINI_REPAIRER_MODELS = {RepairerModel.GEMINI_25_FLASH}

_OPENROUTER_REPAIRER_MODELS = {RepairerModel.GPT_OSS_20B, RepairerModel.GEMMA_3_27B, RepairerModel.DEEPSEEK_R1_0528}

DEFAULT_SECTION_BUILDER_MODEL = SectionBuilderModel.GEMINI_25_PRO.value
DEFAULT_PLANNER_MODEL = PlannerModel.GEMINI_25_PRO.value
DEFAULT_REPAIRER_MODEL = RepairerModel.GEMINI_25_FLASH.value


def _is_vertex_model(model_name: str | None) -> bool:
  """Return True when a model id is explicitly routed to Vertex AI."""
  if not model_name:
    return False
  return model_name.startswith(_VERTEX_MODEL_PREFIX)


def _provider_for_section_builder_model(model_name: str | None, fallback_provider: str) -> str:
  """Resolve provider for section builder model."""
  if not model_name:
    return fallback_provider
  if _is_vertex_model(model_name):
    return _VERTEXAI_PROVIDER
  if model_name in {model.value for model in _GEMINI_SECTION_BUILDER_MODELS}:
    return _GEMINI_PROVIDER
  if model_name in {model.value for model in _OPENROUTER_SECTION_BUILDER_MODELS}:
    return _OPENROUTER_PROVIDER
  return fallback_provider


def _provider_for_model_hint(model_name: str | None, fallback_provider: str) -> str:
  """Resolve a provider from known model lists with a safe fallback."""
  # Only route to known providers when the model name matches a known set.

  if not model_name:
    return fallback_provider

  if _is_vertex_model(model_name):
    return _VERTEXAI_PROVIDER

  gemini_models = {model.value for model in _GEMINI_SECTION_BUILDER_MODELS} | {model.value for model in _GEMINI_PLANNER_MODELS} | {model.value for model in _GEMINI_REPAIRER_MODELS}
  openrouter_models = {model.value for model in _OPENROUTER_SECTION_BUILDER_MODELS} | {model.value for model in _OPENROUTER_PLANNER_MODELS} | {model.value for model in _OPENROUTER_REPAIRER_MODELS}

  if model_name in gemini_models:
    return _GEMINI_PROVIDER

  if model_name in openrouter_models:
    return _OPENROUTER_PROVIDER

  return fallback_provider


def split_provider_model(raw_value: str | None, fallback_provider: str) -> tuple[str, str | None]:
  """Parse provider/model values with a fallback provider."""
  if not raw_value:
    return (fallback_provider, None)
  normalized = str(raw_value).strip()
  if "/" not in normalized:
    return (fallback_provider, normalized)
  provider, model = normalized.split("/", 1)
  provider = provider.strip() or fallback_provider
  model = model.strip()
  return (provider, model if model != "" else None)


def resolve_agent_defaults(runtime_config: dict[str, object]) -> tuple[str, str | None, str, str | None, str, str | None]:
  """
  Resolve provider/model defaults from runtime config with hardcoded fallbacks.

  Keeps providers aligned with model hints when possible.
  """

  def _normalize_model(value: object | None) -> str | None:
    """Normalize model values to strings when present."""
    if value is None:
      return None

    return str(value)

  # Resolve defaults from runtime config or hardcoded defaults.
  section_builder_raw = _normalize_model(runtime_config.get("ai.section_builder.model")) or DEFAULT_SECTION_BUILDER_MODEL
  planner_raw = _normalize_model(runtime_config.get("ai.planner.model")) or DEFAULT_PLANNER_MODEL
  repairer_raw = _normalize_model(runtime_config.get("ai.repair.model")) or DEFAULT_REPAIRER_MODEL

  section_builder_provider, section_builder_model = split_provider_model(section_builder_raw, _GEMINI_PROVIDER)
  planner_provider, planner_model = split_provider_model(planner_raw, _GEMINI_PROVIDER)
  repairer_provider, repairer_model = split_provider_model(repairer_raw, _GEMINI_PROVIDER)

  if not section_builder_model:
    section_builder_model = DEFAULT_SECTION_BUILDER_MODEL

  # Align providers with model hints when model names imply a different provider.
  section_builder_provider = _provider_for_section_builder_model(section_builder_model, section_builder_provider)
  planner_provider = _provider_for_model_hint(planner_model, planner_provider)
  repairer_provider = _provider_for_model_hint(repairer_model, repairer_provider)

  return (section_builder_provider, section_builder_model, planner_provider, planner_model, repairer_provider, repairer_model)
