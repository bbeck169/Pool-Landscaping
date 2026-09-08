"""Phase I1.7.e · chunk 2 · Feb-2026 — HTTP-layer helpers for
propagating AI cap-exceeded events to FastAPI callers.

The AI dispatcher raises :class:`services.ai.models.TenantAIUsageCapExceeded`
when a tenant's BYO provider hits its monthly token cap.
Transactional HTTP endpoints (estimate-generation-on-user-click,
check-in rewrite, quote assistant) call :func:`raise_if_ai_cap_exceeded`
after their LLM dispatch to translate that signal — OR a legacy
``call_llm_with_fallback`` result dict carrying ``cap_exceeded=True``
— into ``HTTPException(429)``. Scheduled / bulk callsites (autopilot
brief generation, weekly summary crons) DO NOT call this helper —
they persist ``skipped_cap_exceeded`` in their job log and continue
with the next tenant / next batch item.

Sibling of :func:`services.messaging.byo_passthrough.raise_if_cap_exceeded`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

from .models import TenantAIUsageCapExceeded


CAP_EXCEEDED_HTTP_STATUS = 429
CAP_EXCEEDED_ERROR_CODE = "ai_spend_cap_exceeded"


def is_ai_cap_exceeded(result: Optional[Dict[str, Any]]) -> bool:
    """Return True when a legacy ``call_llm_with_fallback`` result
    dict indicates a tenant BYO cap hit. Sibling of
    :func:`services.messaging.byo_passthrough.is_cap_exceeded`."""
    if not result:
        return False
    if result.get("cap_exceeded"):
        return True
    if result.get("error") == CAP_EXCEEDED_ERROR_CODE:
        return True
    if result.get("http_status") == CAP_EXCEEDED_HTTP_STATUS:
        return True
    return False


def raise_if_ai_cap_exceeded(
    result: Optional[Dict[str, Any]],
    *,
    detail: str = "Monthly AI spend cap exceeded for this tenant",
) -> None:
    """Raise ``HTTPException(429)`` when the given ``call_llm_with_fallback``
    result dict carries a cap-exceeded flag. No-op for any other
    result shape (including plain success, plain error, or ``None``)."""
    if is_ai_cap_exceeded(result):
        raise HTTPException(
            status_code=CAP_EXCEEDED_HTTP_STATUS, detail=detail,
        )


def translate_tenant_cap_exception(
    exc: TenantAIUsageCapExceeded,
    *,
    detail: Optional[str] = None,
) -> HTTPException:
    """Convert a raw :class:`TenantAIUsageCapExceeded` (from a direct
    ``dispatch_ai_completion`` call) into an ``HTTPException(429)``.
    Callers that use the dispatcher directly (not via
    ``call_llm_with_fallback``) can::

        try:
            await dispatch_ai_completion(tenant_id=..., ...)
        except TenantAIUsageCapExceeded as cap:
            raise translate_tenant_cap_exception(cap)
    """
    msg = detail or (
        f"Monthly AI spend cap exceeded for provider {exc.provider} "
        f"(cap={exc.cap}, used={exc.used})"
    )
    return HTTPException(status_code=CAP_EXCEEDED_HTTP_STATUS, detail=msg)


__all__ = [
    "CAP_EXCEEDED_HTTP_STATUS",
    "CAP_EXCEEDED_ERROR_CODE",
    "is_ai_cap_exceeded",
    "raise_if_ai_cap_exceeded",
    "translate_tenant_cap_exception",
]
