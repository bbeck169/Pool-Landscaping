"""Phase I1.7.c.1 · Feb-2026 — AI provider registry."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from services.secrets import connection_summary

from .anthropic_provider import AnthropicProvider
from .gemini_provider import GeminiProvider
from .models import UnknownAIProvider
from .openai_provider import OpenAIProvider
from .tenant_base import AIProvider


_AI_PROVIDER_CLASSES: Dict[str, Type[AIProvider]] = {
    OpenAIProvider.provider_key: OpenAIProvider,
    AnthropicProvider.provider_key: AnthropicProvider,
    GeminiProvider.provider_key: GeminiProvider,
}
_AI_PROVIDER_CACHE: Dict[str, AIProvider] = {}
_SHORT_NAME_TO_KEY: Dict[str, str] = {
    "openai": OpenAIProvider.provider_key,
    "anthropic": AnthropicProvider.provider_key,
    "gemini": GeminiProvider.provider_key,
}


def register_ai_provider(key: str, cls: Type[AIProvider]) -> None:
    _AI_PROVIDER_CLASSES[key] = cls
    _AI_PROVIDER_CACHE.pop(key, None)


def get_ai_provider(key: str) -> AIProvider:
    if key in _AI_PROVIDER_CACHE:
        return _AI_PROVIDER_CACHE[key]
    cls = _AI_PROVIDER_CLASSES.get(key)
    if not cls:
        raise UnknownAIProvider(f"unknown ai provider: {key}")
    inst = cls()
    _AI_PROVIDER_CACHE[key] = inst
    return inst


def get_ai_provider_by_short_name(short: str) -> AIProvider:
    key = _SHORT_NAME_TO_KEY.get(short)
    if not key:
        raise UnknownAIProvider(f"unknown ai provider short-name: {short}")
    return get_ai_provider(key)


def list_registered_ai_provider_keys() -> List[str]:
    return list(_AI_PROVIDER_CLASSES.keys())


def list_short_names() -> List[str]:
    return list(_SHORT_NAME_TO_KEY.keys())


def short_name_for(provider_key: str) -> Optional[str]:
    for short, key in _SHORT_NAME_TO_KEY.items():
        if key == provider_key:
            return short
    return None


async def get_tenant_ai_provider(
    tenant_id: str, *, db=None,
) -> Optional[AIProvider]:
    """Return the tenant's saved AI provider (if any). Looks through
    the registered AI provider keys for the FIRST connected row.
    Returns ``None`` when no BYO is configured — callers should
    fall back to the Emergent LLM Key via ``dispatch_ai_completion``.
    """
    for key in _AI_PROVIDER_CLASSES.keys():
        summary = await connection_summary(tenant_id, key, db=db)
        if summary and summary.connected:
            return get_ai_provider(key)
    return None


def reset_cache_for_tests() -> None:
    _AI_PROVIDER_CACHE.clear()


def get_provider_field_schemas() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Expose each AI provider's config-field schema for the settings UI."""
    return {k: cls.config_fields for k, cls in _AI_PROVIDER_CLASSES.items()}


def get_provider_model_options() -> Dict[str, List[str]]:
    """Expose the model dropdown options for each AI provider."""
    return {k: list(cls.supported_models) for k, cls in _AI_PROVIDER_CLASSES.items()}
