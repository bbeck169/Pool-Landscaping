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
# Feb-2026 · P1 parallel fix — AI BYO empty-credentials fallback.
# Mirrors the comms BYO hotfix in ``services.messaging.byo_passthrough``.
# When a tenant BYO row is ``connected=True`` on paper but its
# required credentials (``api_key``, etc.) are blank / whitespace,
# fall back to the Emergent Universal LLM Key. Cap-exceeded
# semantics unchanged — the ``enforce_cap_or_raise`` HARD BLOCK
# stays HARD BLOCK per the phase-I1.7.c.1 lock.
from services.byo_common import (
    byo_required_fields_present,
    looks_like_credential_failure,
)


log = logging.getLogger("ai.dispatch")


async def _emergent_platform_fallback(
    *, tenant_id: str, system_prompt: str, user_text: str,
    parse_json: bool = True,
    image_b64s: Optional[list] = None,
    llm_provider: str = "anthropic",
    llm_model: str = "claude-sonnet-4-5",
) -> AICompletionResult:
    """Last-resort platform fallback using the Emergent Universal
    LLM Key. Reuses the existing ``services.llm_provider`` wrapper
    so behaviour + error-handling stays consistent with older
    call-sites during the migration window.

    Phase I1.7.e · chunk 2 · Feb-2026 — honours ``AI_TESTMODE_MOCK``
    so the Emergent + OpenAI HTTP paths are skipped in preview /
    dev / staging. BYO providers already honour the same flag inside
    their own ``complete()`` methods (see ``_helpers.ai_testmode_mock``).

    Phase KB1.5 · Feb-2026 — ``parse_json`` is now threaded through
    so plain-text chat surfaces (Copilot, AI-Employees) get the raw
    Claude reply back verbatim instead of forcing an
    ``_extract_json`` pass on a plain-text response (the classic
    source of ``emergent_empty_json`` false-negatives leaking to
    the UI as ``[emergent fallback error: emergent_empty_json]``).
    Also retries ONCE on an empty / malformed body before giving up,
    and rewrites the leaked internal error into a user-facing
    message so the UI never sees ``emergent_empty_json`` verbatim.

    Phase AIM0 · Feb-2026 — ``image_b64s`` + ``llm_provider`` /
    ``llm_model`` are new. The AI Measure Tool POC pipes a base64
    JPEG (Google Static Maps tile) through this fallback and needs
    to choose between an OpenAI-vision (``gpt-4o``) and Anthropic-
    vision (``claude-sonnet-4-5``) round-trip. Both models are
    reached via the Emergent Universal Key's ``LlmChat`` — no forked
    call path. When ``image_b64s`` is None the behaviour is
    bit-identical to the pre-AIM0 signature.
    """
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

    async def _one_shot() -> Dict[str, Any]:
        return await call_llm_with_fallback(
            system_prompt=system_prompt, user_text=user_text,
            photo_urls=None,
            image_b64s=image_b64s,
            provider=llm_provider, model=llm_model,
            parse_json=parse_json,
        )

    result = await _one_shot()
    _err = None
    if isinstance(result, dict):
        _err = result.get("error")
    # Retry ONCE on an empty / malformed body — the Emergent
    # chokepoint occasionally streams an initial keep-alive with no
    # payload before the real response lands.
    _RETRYABLE = {"emergent_empty_json", "emergent_empty_text",
                   "openai_empty_json", "openai_empty_text"}
    if _err in _RETRYABLE:
        log.warning(
            "[ai.dispatch] emergent %s — retrying once tenant=%s",
            _err, tenant_id,
        )
        result = await _one_shot()

    content = ""
    if isinstance(result, dict):
        raw = result.get("raw") or {}
        if isinstance(raw, dict):
            content = raw.get("text") or raw.get("content") or ""
        if not content and result.get("error"):
            # Phase KB1.5 — surface a user-facing message.  Keep the
            # internal wrapper on the ``raw`` dict for observability
            # dashboards but NEVER let it become the visible reply.
            _raw_err = str(result.get("error"))
            log.warning(
                "[ai.dispatch] platform fallback failed tenant=%s "
                "error=%s prompt_len=%d",
                tenant_id, _raw_err, len(system_prompt or ""),
            )
            content = (
                "The AI provider returned an unexpected response. "
                "Please try again in a moment."
            )
    return AICompletionResult(
        content=content,
        provider_key="emergent",
        provider_used="platform:emergent",
        model=llm_model,
        tokens_prompt=0, tokens_completion=0, tokens_total=0,
        tenant_id=tenant_id,
        raw=(result if isinstance(result, dict) else {}),
    )


async def dispatch_ai_completion(
    *, tenant_id: str, system_prompt: str, user_text: str,
    model: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    parse_json: bool = True,
    db=None,
    image_b64s: Optional[list] = None,
    route: Optional[str] = None,
) -> AICompletionResult:
    """Dispatch an AI completion request.

    Raises:
      TenantAIUsageCapExceeded: When a BYO provider IS configured and
        its monthly cap has been reached. HTTP-layer callers should
        translate this to a **429 Too Many Requests** and MUST NOT
        transparently fall back to the platform key.

    Phase KB1.5 · Feb-2026 — ``parse_json`` is threaded through to
    the platform fallback so chat surfaces (Copilot, AI-Employees)
    that expect plain text don't get an ``emergent_empty_json``
    false-negative when Claude replies with prose.

    Phase AIM0 · Feb-2026 — vision routing. ``route`` selects the
    platform vision path used by the AI Measure Tool POC:

    * ``route="openai_vision"``    → Emergent Universal Key +
      ``gpt-4o`` (image analysis / polygon extraction).
    * ``route="anthropic_vision"`` → Emergent Universal Key +
      ``claude-sonnet-4-5`` (image analysis / polygon extraction).
    * ``route=None`` (default)     → pre-AIM0 behaviour: BYO first
      then Anthropic on the Emergent key.

    When ``image_b64s`` is passed the request bypasses BYO entirely
    and goes straight to the platform fallback — BYO provider
    adapters don't yet accept image payloads and forcing one through
    a JSON-body POST would drop the image. Both kwargs default to
    ``None`` so all pre-AIM0 call-sites are byte-identical.
    """
    # Phase AIM0 · Feb-2026 — vision + route resolution.
    if route == "openai_vision":
        _llm_provider, _llm_model = "openai", (model or "gpt-4o")
    elif route == "anthropic_vision":
        _llm_provider, _llm_model = "anthropic", (model or "claude-sonnet-4-5")
    else:
        _llm_provider, _llm_model = "anthropic", (model or "claude-sonnet-4-5")

    # Phase AIM0 · Feb-2026 — vision requests skip BYO. See docstring.
    if image_b64s:
        log.info(
            "[ai.dispatch] vision route=%s tenant=%s images=%d — platform fallback",
            route or "default", tenant_id, len(image_b64s),
        )
        return await _emergent_platform_fallback(
            tenant_id=tenant_id,
            system_prompt=system_prompt, user_text=user_text,
            parse_json=parse_json,
            image_b64s=image_b64s,
            llm_provider=_llm_provider, llm_model=_llm_model,
        )

    provider = await get_tenant_ai_provider(tenant_id, db=db)
    if provider is None:
        # Rule 1: no BYO → platform fallback.
        log.info("[ai.dispatch] tenant=%s no BYO — using platform Emergent key",
                 tenant_id)
        return await _emergent_platform_fallback(
            tenant_id=tenant_id,
            system_prompt=system_prompt, user_text=user_text,
            parse_json=parse_json,
        )
    # Feb-2026 · P1 parallel fix — BYO empty-credentials guard.
    # When the tenant's BYO row exists but every ``required=True``
    # field on the provider schema is blank / whitespace, treat it
    # as "not configured" and fall through to platform. This runs
    # BEFORE the cap check on purpose: a mis-typed / blanked row
    # shouldn't count against the tenant's monthly cap either.
    from ._helpers import load_provider_config as _ai_load_cfg
    if not await byo_required_fields_present(
        provider, tenant_id, config_loader=_ai_load_cfg, db=db,
    ):
        log.warning(
            "[byo] tenant=%s provider=%s credential fallback → platform",
            tenant_id, getattr(provider, "provider_key", "?"),
        )
        return await _emergent_platform_fallback(
            tenant_id=tenant_id,
            system_prompt=system_prompt, user_text=user_text,
            parse_json=parse_json,
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
    try:
        result = await provider.complete(
            tenant_id=tenant_id,
            system_prompt=system_prompt, user_text=user_text,
            model=model, metadata=metadata,
        )
    except TenantAIUsageCapExceeded:
        # Cap-exceeded stays HARD BLOCK — never silently degrade.
        raise
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        # Feb-2026 · P1 parallel fix — credential-shaped failures
        # (auth 401/403, "invalid api key") mean the BYO row's key
        # was rejected upstream. Fall through to platform without
        # recording usage on the tenant's BYO row (there wasn't a
        # real call).
        if looks_like_credential_failure(err):
            log.warning(
                "[byo] tenant=%s provider=%s credential-shaped failure "
                "→ platform: %s",
                tenant_id, short, err,
            )
            return await _emergent_platform_fallback(
                tenant_id=tenant_id,
                system_prompt=system_prompt, user_text=user_text,
                parse_json=parse_json,
            )
        raise
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
