"""Phase I1.7.e · chunk 2 · Feb-2026 — AI test-mode helpers used by
the platform-fallback path and the ``call_llm_with_fallback``
chokepoint. BYO provider adapters (openai / anthropic / gemini)
already honour ``AI_TESTMODE_MOCK`` inside their own ``complete()``
methods via :func:`services.ai._helpers.ai_testmode_mock` and return
their own deterministic ``AICompletionResult`` — this module ONLY
handles the two paths that don't naturally flow through a provider
adapter:

  1. ``services.ai.dispatcher._emergent_platform_fallback`` — Rule
     1 of the dispatcher when no tenant BYO is configured. Would
     otherwise call the Emergent + OpenAI HTTP paths.
  2. ``services.llm_provider.call_llm_with_fallback`` when the
     caller passes NO ``tenant_id`` (existing legacy callers). Would
     otherwise call Emergent + OpenAI HTTP paths.

Enable in preview ``.env`` with::

    AI_TESTMODE_MOCK=true

:func:`is_ai_testmode` is a thin re-export of the existing
:func:`services.ai._helpers.ai_testmode_mock` so both spellings work
and there is a single source of truth for the env-flag read.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from ._helpers import ai_testmode_mock as _ai_testmode_mock
from .models import AICompletionResult


def is_ai_testmode() -> bool:
    """Return True when ``AI_TESTMODE_MOCK`` is set to any truthy
    value. Alias for :func:`services.ai._helpers.ai_testmode_mock` so
    both spellings work at callsites."""
    return _ai_testmode_mock()


def _hash_prompt(system_prompt: str, user_text: str) -> str:
    seed = f"{system_prompt}||{user_text}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def mock_completion_result(
    *,
    tenant_id: str,
    system_prompt: str,
    user_text: str,
    model: Optional[str] = None,
    provider_key: str = "emergent",
    provider_used: str = "platform:emergent",
) -> AICompletionResult:
    """Return a deterministic mock completion. Same (system, user)
    input pair → same content + same token counts, indefinitely.

    Default ``provider_used`` is ``"platform:emergent"`` because this
    factory is only invoked from the platform-fallback path — BYO
    provider adapters have their own mock helpers that tag the
    result with ``tenant:<short>`` for analytics parity."""
    hp = _hash_prompt(system_prompt, user_text)
    preview = (user_text or "")[:120].replace("\n", " ").strip()
    content = f"[testmode-mock:{hp}] {preview}" if preview else f"[testmode-mock:{hp}]"
    tokens_prompt = max(1, (len(system_prompt or "") + len(user_text or "")) // 4)
    tokens_completion = 32
    return AICompletionResult(
        content=content,
        provider_key=provider_key,
        provider_used=provider_used,
        model=model or "testmode-mock",
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
        tokens_total=tokens_prompt + tokens_completion,
        tenant_id=tenant_id,
        raw={"testmode_mock": True, "hash": hp},
    )


def mock_llm_provider_response(
    *,
    system_prompt: str,
    user_text: str,
    provider: str = "emergent",
) -> Dict[str, Any]:
    """Return a deterministic mock response in the SHAPE that
    ``services.llm_provider.call_llm_with_fallback`` returns
    (``{"raw": {"text": ...}, "provider": ...}``). Used by the
    llm_provider chokepoint when a caller does NOT pass
    ``tenant_id`` — pure platform-mode test-mode short-circuit."""
    hp = _hash_prompt(system_prompt, user_text)
    preview = (user_text or "")[:120].replace("\n", " ").strip()
    text = f"[testmode-mock:{hp}] {preview}" if preview else f"[testmode-mock:{hp}]"
    return {
        "raw": {"text": text, "testmode_mock": True, "hash": hp},
        "provider": provider,
        "testmode_mock": True,
    }


__all__ = [
    "is_ai_testmode",
    "mock_completion_result",
    "mock_llm_provider_response",
]
