"""Ticket LL · Feb-2026 — ``POST /api/ai/rewrite`` endpoint.

Operator-authored compose fields across the Customers / Leads /
Templates / Mass-Text surfaces now ship an "AI rewrite" button
that polishes the current draft text in-place.  This endpoint is
the backend chokepoint.

Pattern (byte-for-byte parity with
``backend/routers/ai_draft_reply.py`` — the canonical operator-
side AI endpoint in this codebase):

  * ``require_admin_or_manager`` role gate (admin / super_admin /
    owner / manager — operator decision, same tier as draft-reply).
  * In-function imports of
    :mod:`services.llm_provider.call_llm_with_fallback` so pytest
    can monkeypatch the chokepoint without touching this module.
  * Rate limit via :mod:`services.ai.draft_rate_limit` with
    ``feature="rewrite"`` + 2-second cooldown (operator spec).
  * Hourly 20-call soft cap via sibling module
    :mod:`services.ai.rewrite_hourly_cap`.
  * Dispatcher config: Anthropic ``claude-sonnet-4-5-20250929`` on
    the Emergent key, ``max_tokens=400`` (same body-size budget as
    the email branch of draft-reply).
  * Cap-exceeded → 429 reusing ``services.ai.cap_http``.
  * Dispatcher failure → graceful 503 (not 500) so the FE toast
    can render a friendly "AI service unavailable, try again"
    message without exposing an uncaught server error.

Scope locks (ticket LL):
  * Minimum 10 characters on the input (defense-in-depth matching
    the FE gate at ``AiRewriteButton.jsx:minLength``).
  * Maximum 4,000 characters on the input (safety ceiling — above
    this we'd be rewriting an email body that exceeds any SMS
    carrier limit and most email composers' practical scope).
  * Merge-tag tokens are preserved verbatim by the system prompt
    so the downstream resolver (Ticket NN) continues to work
    unchanged.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import logger
from utils import require_admin_or_manager

router = APIRouter(tags=["AI Rewrite"])


# ─── Request / response models ──────────────────────────────────────
class RewriteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    tone: str = Field(default="professional", pattern="^(professional)$")


_MIN_REWRITE_CHARS = 10  # mirrors ``AiRewriteButton.minLength`` on the FE


# ─── Endpoint ───────────────────────────────────────────────────────
@router.post("/ai/rewrite", operation_id="ai.rewrite")
async def ai_rewrite(
    body: RewriteIn,
    user: Dict[str, Any] = Depends(require_admin_or_manager),
):
    tenant_id = user.get("tenant_id") or ""
    user_id = user.get("id") or ""
    if not tenant_id or not user_id:
        raise HTTPException(400, "Caller lacks tenant_id or user id")

    # 1. Minimum-length guard — matches the FE threshold so a bad
    #    client can't bypass by posting directly.  Trim leading /
    #    trailing whitespace before counting so a textarea full of
    #    spaces fails the gate.
    cleaned = (body.text or "").strip()
    if len(cleaned) < _MIN_REWRITE_CHARS:
        raise HTTPException(400, {
            "code": "REWRITE_TOO_SHORT",
            "message": (
                f"Draft must be at least {_MIN_REWRITE_CHARS} characters "
                "to rewrite."
            ),
            "min_length": _MIN_REWRITE_CHARS,
            "received_length": len(cleaned),
        })

    # 2. Short-cooldown rate limit — 2s per user, keyed on
    #    ``feature="rewrite"`` so the key space is disjoint from the
    #    draft-reply cooldown.
    from services.ai import draft_rate_limit
    wait = draft_rate_limit.check(
        tenant_id=tenant_id, user_id=user_id,
        feature="rewrite", window_seconds=2.0,
    )
    if wait > 0:
        raise HTTPException(429, {
            "code": "REWRITE_COOLDOWN",
            "detail": "Rate limited — slow down between rewrites.",
            "retry_after_seconds": round(wait, 2),
        })

    # 3. Hourly 20-call soft cap — per-user, per-hour-bucket counter.
    from services.ai import rewrite_hourly_cap
    allowed, retry_after = rewrite_hourly_cap.check(
        tenant_id=tenant_id, user_id=user_id,
    )
    if not allowed:
        raise HTTPException(429, {
            "code": "REWRITE_HOURLY_CAP",
            "detail": (
                "You've hit the hourly rewrite limit — try again "
                "after the top of the hour."
            ),
            "retry_after_seconds": round(retry_after, 2),
        })

    # 4. Prompt composition (static system prompt + per-call user
    #    wrapper around the draft text).
    from services.ai.prompts.rewrite import SYSTEM_PROMPT, build_user_prompt
    user_prompt = build_user_prompt(cleaned)

    # 5. LLM call via chokepoint.  In-function import so pytest can
    #    monkeypatch ``services.llm_provider.call_llm_with_fallback``.
    from services.llm_provider import call_llm_with_fallback
    from services.ai.cap_http import is_ai_cap_exceeded
    model_name = "claude-sonnet-4-5-20250929"
    t_start = time.monotonic()
    try:
        result = await call_llm_with_fallback(
            system_prompt=SYSTEM_PROMPT, user_text=user_prompt,
            provider="anthropic", model=model_name,
            tenant_id=tenant_id, parse_json=False,
            max_tokens=400,
        )
    except Exception as e:
        logger.warning(f"[ai-rewrite] chokepoint raised: {e}")
        raise HTTPException(503, {
            "code": "REWRITE_UPSTREAM_UNAVAILABLE",
            "detail": "AI service is temporarily unavailable. Please try again.",
        })
    latency_ms = int((time.monotonic() - t_start) * 1000)

    # 6. Cap-exceeded → 429 (reuse the existing HTTP translator).
    if is_ai_cap_exceeded(result):
        raise HTTPException(429, {
            "code": "AI_CAP_EXCEEDED",
            "detail": "Monthly AI spend cap exceeded for this tenant.",
            "cap_exceeded": True,
        })

    # 7. Compose the response.  Fail-soft on empty / error — surface
    #    a 503 rather than returning a stub, matching the operator-
    #    facing "temporarily unavailable" contract.
    text = ((result.get("raw") or {}).get("text") or "").strip()
    if not text or result.get("error"):
        logger.warning(
            "[ai-rewrite] empty/error result for tenant=%s user=%s err=%s",
            tenant_id, user_id, result.get("error"),
        )
        raise HTTPException(503, {
            "code": "REWRITE_EMPTY_RESULT",
            "detail": "AI returned an empty rewrite. Please try again.",
        })

    tokens_prompt = int(((result.get("raw") or {}).get("prompt_tokens") or 0))
    tokens_completion = int(
        ((result.get("raw") or {}).get("completion_tokens") or 0)
    )

    response: Dict[str, Any] = {
        "rewritten":         text,
        "model":             model_name,
        "latency_ms":        latency_ms,
        "prompt_tokens":     tokens_prompt,
        "completion_tokens": tokens_completion,
    }

    # 8. Stamp both rate-limit slots on the SUCCESS path only — a
    #    failed LLM call must not consume quota.  Best-effort so a
    #    bookkeeping failure never blocks the response.
    try:
        draft_rate_limit.stamp(
            tenant_id=tenant_id, user_id=user_id, feature="rewrite",
        )
    except Exception:
        logger.warning("[ai-rewrite] cooldown stamp failed", exc_info=True)
    try:
        rewrite_hourly_cap.stamp(tenant_id=tenant_id, user_id=user_id)
    except Exception:
        logger.warning("[ai-rewrite] hourly stamp failed", exc_info=True)

    # 9. Usage audit — best-effort, mirrors the draft-reply contract.
    try:
        from services.ai.usage import record_usage
        await record_usage(
            tenant_id=tenant_id,
            provider="anthropic",
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            actor_user_id=user_id,
            recipient_type="rewrite",
            recipient_id="n/a",
            prompt_hash=None,
        )
    except Exception:
        logger.warning("[ai-rewrite] audit emit failed", exc_info=True)

    return response
