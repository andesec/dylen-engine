"""Model routing and selection logic."""

from __future__ import annotations

from app.api.models import (
    KnowledgeModel,
    ModelsConfig,
    PlannerModel,
    RepairerModel,
    StructurerModel,
)
from app.config import Settings

_GEMINI_PROVIDER = "gemini"
_OPENROUTER_PROVIDER = "openrouter"

_GEMINI_KNOWLEDGE_MODELS = {
    KnowledgeModel.GEMINI_25_FLASH,
    KnowledgeModel.GEMINI_25_PRO,
}

_OPENROUTER_KNOWLEDGE_MODELS = {
    KnowledgeModel.XIAOMI_MIMO_V2_FLASH,
    KnowledgeModel.DEEPSEEK_R1_0528,
    KnowledgeModel.LLAMA_31_405B,
    KnowledgeModel.GPT_OSS_120B,
}

_GEMINI_STRUCTURER_MODELS = {StructurerModel.GEMINI_25_FLASH}

_OPENROUTER_STRUCTURER_MODELS = {
    StructurerModel.GPT_OSS_20B,
    StructurerModel.LLAMA_33_70B,
    StructurerModel.GEMMA_3_27B,
}

_GEMINI_PLANNER_MODELS = {
    PlannerModel.GEMINI_25_PRO,
    PlannerModel.GEMINI_PRO_LATEST,
}

_OPENROUTER_PLANNER_MODELS = {
    PlannerModel.GPT_OSS_120B,
    PlannerModel.XIAOMI_MIMO_V2_FLASH,
    PlannerModel.LLAMA_31_405B,
    PlannerModel.DEEPSEEK_R1_0528,
}

_GEMINI_REPAIRER_MODELS = {
    RepairerModel.GEMINI_25_FLASH,
}

_OPENROUTER_REPAIRER_MODELS = {
    RepairerModel.GPT_OSS_20B,
    RepairerModel.GEMMA_3_27B,
    RepairerModel.DEEPSEEK_R1_0528,
}

DEFAULT_KNOWLEDGE_MODEL = KnowledgeModel.LLAMA_31_405B.value


def _resolve_model_selection(
    settings: Settings, *, models: ModelsConfig | None
) -> tuple[str, str | None, str, str | None, str, str | None, str, str | None]:
    """
    Derive gatherer and structurer providers/models based on request settings.

    Falls back to environment defaults when user input is missing.
    """
    # Respect per-agent overrides when provided, otherwise use environment defaults.
    if models is not None:
        gatherer_model = models.gatherer_model or settings.gatherer_model or DEFAULT_KNOWLEDGE_MODEL
        planner_model = models.planner_model or settings.planner_model
        structurer_model = models.structurer_model or settings.structurer_model
        repairer_model = models.repairer_model or settings.repair_model
    else:
        gatherer_model = settings.gatherer_model or DEFAULT_KNOWLEDGE_MODEL
        planner_model = settings.planner_model
        structurer_model = settings.structurer_model
        repairer_model = settings.repair_model

    # Resolve provider hints to keep routing consistent for each agent.
    gatherer_provider = _provider_for_knowledge_model(settings, gatherer_model)
    planner_provider = _provider_for_model_hint(planner_model, settings.planner_provider)
    structurer_provider = _provider_for_structurer_model(settings, structurer_model)
    repairer_provider = _provider_for_model_hint(repairer_model, settings.repair_provider)

    return (
        gatherer_provider,
        gatherer_model,
        planner_provider,
        planner_model,
        structurer_provider,
        structurer_model,
        repairer_provider,
        repairer_model,
    )


def _provider_for_knowledge_model(settings: Settings, model_name: str | None) -> str:
    # Keep provider routing consistent even if the model list evolves.
    if not model_name:
        return settings.gatherer_provider

    if model_name in {model.value for model in _GEMINI_KNOWLEDGE_MODELS}:
        return _GEMINI_PROVIDER

    if model_name in {model.value for model in _OPENROUTER_KNOWLEDGE_MODELS}:
        return _OPENROUTER_PROVIDER
    return settings.gatherer_provider


def _provider_for_structurer_model(settings: Settings, model_name: str | None) -> str:
    # Keep provider routing consistent even if the model list evolves.
    if not model_name:
        return settings.structurer_provider

    if model_name in {model.value for model in _GEMINI_STRUCTURER_MODELS}:
        return _GEMINI_PROVIDER

    if model_name in {model.value for model in _OPENROUTER_STRUCTURER_MODELS}:
        return _OPENROUTER_PROVIDER
    return settings.structurer_provider


def _provider_for_model_hint(model_name: str | None, fallback_provider: str) -> str:
    """Resolve a provider from known model lists with a safe fallback."""
    # Only route to known providers when the model name matches a known set.
    if not model_name:
        return fallback_provider

    gemini_models = (
        {model.value for model in _GEMINI_KNOWLEDGE_MODELS}
        | {model.value for model in _GEMINI_STRUCTURER_MODELS}
        | {model.value for model in _GEMINI_PLANNER_MODELS}
        | {model.value for model in _GEMINI_REPAIRER_MODELS}
    )
    openrouter_models = (
        {model.value for model in _OPENROUTER_KNOWLEDGE_MODELS}
        | {model.value for model in _OPENROUTER_STRUCTURER_MODELS}
        | {model.value for model in _OPENROUTER_PLANNER_MODELS}
        | {model.value for model in _OPENROUTER_REPAIRER_MODELS}
    )

    if model_name in gemini_models:
        return _GEMINI_PROVIDER

    if model_name in openrouter_models:
        return _OPENROUTER_PROVIDER
    return fallback_provider
