"""Phase I1.7.c.1 · Feb-2026 — ``dispatch_ai_completion`` wrapper.

Routes an AI completion request through the tenant's BYO provider
if configured, else falls back to the platform's Emergent LLM Key.

Fallback rules (per problem-statement — locked):
  1. No BYO row for this tenant → fallback to the Emergent LLM key.
  2. BYO row exists but its ``monthly_token_cap`` is reached → HARD
     BLOCK; raise ``TenantAIUsageCapExceeded``. Do NOT fall back.
  3. BYO row exists and cap ok → dispatch, record usage on success.

**This module deliberately does NOT rewire any existing app AI
call-sites** — that migration is scoped to phase I1.7.e. Today,
``dispatch_ai_completion`` is exercised by the I1.7.c.1 test suite.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .models import (
    AICompletionResult,
    TenantAIUsageCapExceeded,
)
from .registry import get_tenant_ai_provider, short_name_for
from .usage import enforce_cap_or_raise, record_usage


log = logging.getLogger("ai.dispatch")


async def _emergent_platform_fallback(
    *, tenant_id: str, system_prompt: str, user_text: str,
) -> AICompletionResult:
    """Last-resort platform fallback using the Emergent Universal
    LLM Key. Reuses the existing ``services.llm_provider`` wrapper
    so behaviour + error-handling stays consistent with older
    call-sites during the migration window.

    Phase I1.7.e · chunk 2 · Feb-2026 — honours ``AI_TESTMODE_MOCK``
    so the Emergent + OpenAI HTTP paths are skipped in preview /
    dev / staging. BYO providers already honour the same flag inside
    their own ``complete()`` methods (see ``_helpers.ai_testmode_mock``)."""
    from ._helpers import ai_testmode_mock
    if ai_testmode_mock():
        from .testmode import mock_completion_result
        return mock_completion_result(
            tenant_id=tenant_id, system_prompt=system_prompt,
            user_text=user_text,
            provider_key="emergent",
            provider_used="platform:emergent",
        )
    from services.llm_provider import call_llm_with_fallback
    result = await call_llm_with_fallback(
        system_prompt=system_prompt, user_text=user_text,
        photo_urls=None,
        provider="anthropic", model="claude-sonnet-4-5",
    )
    # ``call_llm_with_fallback`` returns ``{"raw": <json>, "provider": "emergent"|"openai"}``
    # on success or ``{"error": ..., "provider": ...}`` on failure.
    content = ""
    if isinstance(result, dict):
        raw = result.get("raw") or {}
        if isinstance(raw, dict):
            content = raw.get("text") or raw.get("content") or ""
        if not content and result.get("error"):
            content = f"[emergent fallback error: {result.get('error')}]"
    return AICompletionResult(
        content=content,
        provider_key="emergent",
        provider_used="platform:emergent",
        model="claude-sonnet-4-5",
        tokens_prompt=0, tokens_completion=0, tokens_total=0,
        tenant_id=tenant_id,
        raw=(result if isinstance(result, dict) else {}),
    )


async def dispatch_ai_completion(
    *, tenant_id: str, system_prompt: str, user_text: str,
    model: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    db=None,
) -> AICompletionResult:
    """Dispatch an AI completion request.

    Raises:
      TenantAIUsageCapExceeded: When a BYO provider IS configured and
        its monthly cap has been reached. HTTP-layer callers should
        translate this to a **429 Too Many Requests** and MUST NOT
        transparently fall back to the platform key.
    """
    provider = await get_tenant_ai_provider(tenant_id, db=db)
    if provider is None:
        # Rule 1: no BYO → platform fallback.
        log.info("[ai.dispatch] tenant=%s no BYO — using platform Emergent key",
                 tenant_id)
        return await _emergent_platform_fallback(
            tenant_id=tenant_id,
            system_prompt=system_prompt, user_text=user_text,
        )
    short = short_name_for(provider.provider_key) or provider.provider_key
    # Rule 2: BYO exists — cap check FIRST.
    await enforce_cap_or_raise(tenant_id=tenant_id, provider=short, db=db)
    # Phase I1.7.e · chunk 2 · Feb-2026 — AI_TESTMODE_MOCK short-circuit
    # for the BYO path is honoured DEEPER IN the provider adapters
    # (``services/ai/{openai,anthropic,gemini}_provider.py`` each
    # check ``ai_testmode_mock()`` and return a deterministic
    # AICompletionResult without any outbound HTTP call). No
    # short-circuit is needed here — deferring keeps
    # ``result.provider_used == "tenant:{short}"`` semantics
    # unchanged, which downstream analytics + admin UI depend on.
    # Rule 3: dispatch + record.
    result = await provider.complete(
        tenant_id=tenant_id,
        system_prompt=system_prompt, user_text=user_text,
        model=model, metadata=metadata,
    )
    # Fire-and-forget usage record (still awaited so tests see it).
    try:
        await record_usage(
            tenant_id=tenant_id, provider=short,
            tokens_prompt=result.tokens_prompt,
            tokens_completion=result.tokens_completion,
            db=db,
        )
    except Exception as e:  # pragma: no cover — best-effort
        log.warning("[ai.dispatch] record_usage failed: %s", e)
    return result


__all__ = [
    "dispatch_ai_completion",
    "TenantAIUsageCapExceeded",
]
