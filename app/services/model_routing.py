from __future__ import annotations

from app.ai.orchestrator import DylenOrchestrator
from app.api.models import PlannerModel, RepairerModel, SectionBuilderModel
from app.config import Settings

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


def resolve_agent_defaults(settings: Settings, runtime_config: dict[str, object]) -> tuple[str, str | None, str, str | None, str, str | None]:
  """
  Resolve provider/model defaults from runtime config with settings fallbacks.

  Keeps providers aligned with model hints when possible.
  """

  def _normalize_model(value: object | None) -> str | None:
    """Normalize model values to strings when present."""
    if value is None:
      return None

    return str(value)

  # Resolve defaults from runtime config or environment-backed settings.
  section_builder_model = _normalize_model(runtime_config.get("ai.section_builder.model")) or settings.section_builder_model or DEFAULT_SECTION_BUILDER_MODEL
  planner_model = _normalize_model(runtime_config.get("ai.planner.model")) or settings.planner_model
  repairer_model = _normalize_model(runtime_config.get("ai.repair.model")) or settings.repair_model

  section_builder_provider = str(runtime_config.get("ai.section_builder.provider") or settings.section_builder_provider)
  planner_provider = str(runtime_config.get("ai.planner.provider") or settings.planner_provider)
  repairer_provider = str(runtime_config.get("ai.repair.provider") or settings.repair_provider)

  # Align providers with model hints when model names imply a different provider.
  section_builder_provider = _provider_for_section_builder_model(section_builder_model, section_builder_provider)
  planner_provider = _provider_for_model_hint(planner_model, planner_provider)
  repairer_provider = _provider_for_model_hint(repairer_model, repairer_provider)

  return (section_builder_provider, section_builder_model, planner_provider, planner_model, repairer_provider, repairer_model)


def _get_orchestrator(
  settings: Settings, *, section_builder_provider: str | None = None, section_builder_model: str | None = None, planner_provider: str | None = None, planner_model: str | None = None, repair_provider: str | None = None, repair_model: str | None = None
) -> DylenOrchestrator:
  return DylenOrchestrator(
    section_builder_provider=section_builder_provider or settings.section_builder_provider,
    section_builder_model=section_builder_model or settings.section_builder_model,
    planner_provider=planner_provider or settings.planner_provider,
    planner_model=planner_model or settings.planner_model,
    repair_provider=repair_provider or settings.repair_provider,
    repair_model=repair_model or settings.repair_model,
    schema_version=settings.schema_version,
    fenster_technical_constraints=settings.fenster_technical_constraints,
  )
