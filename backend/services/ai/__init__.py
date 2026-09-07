"""services.ai — AI-powered helpers.

Existing modules (photo/voice → estimate, PII redaction, etc.) keep
their standalone entry points. Phase I1.7.c.1 (Feb-2026) adds a
tenant-BYO AI provider registry so tenants can bring their own
OpenAI / Anthropic / Gemini API keys.

Public entry points (imported here for convenience):

    from services.ai import (
        dispatch_ai_completion,
        TenantAIUsageCapExceeded,
        get_ai_provider, get_tenant_ai_provider,
    )
"""
from .dispatcher import (  # noqa: F401
    dispatch_ai_completion,
    TenantAIUsageCapExceeded,
)
from .registry import (  # noqa: F401
    get_ai_provider,
    get_ai_provider_by_short_name,
    get_tenant_ai_provider,
    list_registered_ai_provider_keys,
    list_short_names,
    short_name_for,
    reset_cache_for_tests,
    get_provider_field_schemas,
    get_provider_model_options,
)
from .models import (  # noqa: F401
    AICompletionResult,
    AIProviderUsage,
    AIUsageResponse,
    AIError,
    InvalidAIProviderConfig,
    TenantAINotConnected,
    UnknownAIProvider,
)
