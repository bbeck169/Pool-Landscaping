"""TD-ai-phase1 · Oct-2026 — AI draft-reply endpoint.

``POST /api/ai/draft-reply`` → operator-reviewed SMS/email draft for a
customer or lead. Pattern mirrors ``routers.reviews_ai_reply`` (141
LOC canonical sibling) with four additions:

  1. Context assembled via :mod:`services.ai.compose_context` with a
     positive allowlist of recipient fields.
  2. Per-actor rate-limit (10s) via :mod:`services.ai.draft_rate_limit`.
  3. Short-TTL cache (60s) via :mod:`services.ai.draft_cache`.
  4. Per-call audit row via extended ``services.ai.usage.record_usage``.

Role gate: ``require_admin_or_manager`` (admin + super_admin + owner +
manager). Compose surface is admin-side; manager is included per
operator decision D9.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import require_admin_or_manager

router = APIRouter(tags=["AI Draft Reply"])


# ─── Request / response models ──────────────────────────────────────
class DraftReplyIn(BaseModel):
    channel:        str = Field(..., pattern="^(sms|email)$")
    recipient_type: str = Field(..., pattern="^(customer|lead)$")
    recipient_id:   str = Field(..., min_length=1, max_length=200)
    intent_hint:    Optional[str] = Field(default=None, max_length=500)
    prior_message:  Optional[str] = Field(default=None, max_length=4000)


# ─── Helpers ────────────────────────────────────────────────────────
def _fallback_draft(channel: str, intent_hint: Optional[str]) -> Dict[str, Any]:
    """Template fallback for when the LLM path fails or the Emergent
    key is missing. Same semantic as ``reviews_ai_reply._fallback_reply``."""
    hint = (intent_hint or "").strip()
    if channel == "email":
        subject = "Following up"
        body = (
            "Hi [FIRSTNAME],\n\n"
            + (f"{hint}\n\n" if hint else "")
            + "Please let me know if there's anything else I can help with.\n\n"
            + "Thanks."
        )
        return {"draft_subject": subject, "draft_body": body}
    body = (
        "Hi [FIRSTNAME], "
        + (f"{hint} " if hint else "")
        + "let me know if you have questions."
    )
    return {"draft_subject": None, "draft_body": body}


def _parse_email_response(text: str) -> Dict[str, str]:
    """Split a Claude/GPT response of the form::

        Subject: ...
        <blank>
        body body body

    into ``{"draft_subject", "draft_body"}``. Falls back to a blank
    subject + whole-text body when the model doesn't emit the Subject
    line (defensive — happens occasionally)."""
    m = re.match(r"\s*Subject:\s*(.+?)\n\s*\n(.+)",
                   text, re.DOTALL | re.IGNORECASE)
    if m:
        return {
            "draft_subject": m.group(1).strip(),
            "draft_body":    m.group(2).strip(),
        }
    return {"draft_subject": "", "draft_body": text.strip()}


def _substitute_firstname(text: Optional[str], first_name: Optional[str]) -> Optional[str]:
    """Post-generation [FIRSTNAME] substitution. Preserves the privacy
    guarantee that the recipient's real name never reaches the LLM."""
    if not text:
        return text
    from services.ai.prompts.draft_reply import FIRSTNAME_TOKEN
    fn = (first_name or "").strip() or "there"
    return text.replace(FIRSTNAME_TOKEN, fn)


# ─── Endpoint ───────────────────────────────────────────────────────
@router.post("/ai/draft-reply", operation_id="ai.draftReply")
async def draft_reply(
    body: DraftReplyIn,
    user: Dict[str, Any] = Depends(require_admin_or_manager),
):
    tenant_id = user.get("tenant_id") or ""
    user_id = user.get("id") or ""
    if not tenant_id or not user_id:
        raise HTTPException(400, "Caller lacks tenant_id or user id")

    # 1. Context assembly (resolves recipient + applies allowlist).
    from services.ai.compose_context import assemble_context, resolve_recipient
    recipient_doc = await resolve_recipient(
        db=db, tenant_id=tenant_id,
        recipient_type=body.recipient_type, recipient_id=body.recipient_id,
    )
    if not recipient_doc:
        raise HTTPException(404, "Recipient not found")
    ctx = await assemble_context(
        db=db, tenant_id=tenant_id,
        recipient_type=body.recipient_type, recipient_id=body.recipient_id,
        prior_message=body.prior_message,
    )
    if ctx is None:
        raise HTTPException(404, "Recipient not found")

    # 2. Prompt composition.
    from services.ai.prompts.draft_reply import (
        build_system_prompt, build_user_prompt,
    )
    try:
        from routers.ai_brain import build_system_prompt as _brain_sp
        brand_voice = await _brain_sp(tenant_id)
    except Exception:
        brand_voice = ""
    system_prompt = build_system_prompt(brand_voice, body.channel)
    user_prompt = build_user_prompt(
        channel=body.channel,
        service_type=ctx.get("service_type"),
        upcoming_visit_date=ctx.get("upcoming_visit_date_iso"),
        redacted_prior_message=ctx.get("redacted_prior_message"),
        intent_hint=body.intent_hint,
    )

    # 3. Cache lookup (BEFORE rate-limit: a cache hit carries zero LLM
    #    cost, so operator double-click should pass through without
    #    tripping the cooldown).
    from services.ai import draft_cache
    prompt_hash = draft_cache.compute_prompt_hash(system_prompt, user_prompt)
    cached = draft_cache.get(
        tenant_id=tenant_id, recipient_id=body.recipient_id,
        prompt_hash=prompt_hash,
    )
    if cached is not None:
        return {**cached, "cached": True}

    # 4. Rate-limit check (per-actor cooldown — only applies to
    #    cache-miss paths that will spend an LLM call).
    from services.ai import draft_rate_limit
    wait = draft_rate_limit.check(tenant_id=tenant_id, user_id=user_id)
    if wait > 0:
        raise HTTPException(
            429,
            {"detail": "Rate limited — slow down between drafts.",
              "retry_after_seconds": round(wait, 2)},
        )

    # 5. LLM call via chokepoint. In-function import so pytest can
    #    monkeypatch ``services.llm_provider.call_llm_with_fallback``.
    from services.llm_provider import call_llm_with_fallback
    from services.ai.cap_http import is_ai_cap_exceeded
    max_tokens = 120 if body.channel == "sms" else 400
    model_name = "claude-sonnet-4-5-20250929"
    try:
        result = await call_llm_with_fallback(
            system_prompt=system_prompt, user_text=user_prompt,
            provider="anthropic", model=model_name,
            tenant_id=tenant_id, parse_json=False,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.warning(f"[ai-draft-reply] chokepoint raised: {e}")
        result = {"error": str(e)}

    # 6. Cap-exceeded → 429 (reuse the existing HTTP translator).
    if is_ai_cap_exceeded(result):
        raise HTTPException(
            429,
            {"detail": "Monthly AI spend cap exceeded for this tenant.",
              "cap_exceeded": True},
        )

    # 7. Compose the response. Fail-soft to template fallback when the
    #    LLM errors — never surface a hard 500 to the operator.
    text = ((result.get("raw") or {}).get("text") or "").strip()
    tokens_prompt = int(((result.get("raw") or {}).get("prompt_tokens") or 0))
    tokens_completion = int(((result.get("raw") or {}).get("completion_tokens") or 0))
    provider = result.get("provider") or ("fallback" if result.get("error") else "unknown")

    if not text or result.get("error"):
        fb = _fallback_draft(body.channel, body.intent_hint)
        draft_subject = fb["draft_subject"]
        draft_body = fb["draft_body"]
        provider = "fallback"
    elif body.channel == "email":
        parts = _parse_email_response(text)
        draft_subject = parts["draft_subject"]
        draft_body = parts["draft_body"]
    else:
        draft_subject = None
        draft_body = text

    # 8. Post-generation [FIRSTNAME] substitution.
    first_name = ctx.get("first_name")
    draft_subject = _substitute_firstname(draft_subject, first_name)
    draft_body = _substitute_firstname(draft_body, first_name) or ""

    response: Dict[str, Any] = {
        "draft_subject":     draft_subject,
        "draft_body":        draft_body,
        "model":             model_name,
        "prompt_tokens":     tokens_prompt,
        "completion_tokens": tokens_completion,
        "cost_usd":          0.0,
        "cached":            False,
    }

    # 9. Cache + stamp + audit (all best-effort; must not block the
    #    response if any step fails).
    try:
        draft_cache.put(
            tenant_id=tenant_id, recipient_id=body.recipient_id,
            prompt_hash=prompt_hash, response=response,
        )
    except Exception:
        logger.warning("[ai-draft-reply] cache put failed", exc_info=True)
    try:
        draft_rate_limit.stamp(tenant_id=tenant_id, user_id=user_id)
    except Exception:
        logger.warning("[ai-draft-reply] rate-limit stamp failed", exc_info=True)
    try:
        from services.ai.usage import record_usage
        await record_usage(
            tenant_id=tenant_id,
            provider=("anthropic" if provider != "fallback" else "fallback"),
            tokens_prompt=tokens_prompt, tokens_completion=tokens_completion,
            actor_user_id=user_id,
            recipient_type=body.recipient_type,
            recipient_id=body.recipient_id,
            prompt_hash=prompt_hash,
        )
    except Exception:
        logger.warning("[ai-draft-reply] audit emit failed", exc_info=True)

    return response
