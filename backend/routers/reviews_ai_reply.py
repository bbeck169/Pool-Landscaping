"""Feb-2026 · Phase 20 P2 — AI review reply generator.

Real implementation of the placeholder in
``services/daily_review_digest.py``. Uses the Emergent LLM key with
Claude and injects the AI Brain system prompt so replies stay
on-brand.

Endpoint ``POST /api/reviews/suggest-reply`` (operationId
``reviews.suggestReply``) accepts a rating + review text and
returns ``{reply_text}``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user

router = APIRouter(tags=["Reviews AI"])


class SuggestReplyIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    review_text: str
    review_author: Optional[str] = None
    sentiment_hint: Optional[str] = None


def _fallback_reply(rating: int, author: Optional[str]) -> str:
    who = author or "there"
    if rating >= 4:
        return (
            f"Thanks so much for the {rating}★ review, {who}! We're thrilled "
            "you had a great experience — we'll keep the standard high on "
            "your next visit."
        )
    return (
        f"Hi {who}, thanks for taking the time to share this. We're sorry "
        "you didn't get the experience you expected. A team member will "
        "reach out today to make it right — please expect a call."
    )


async def _load_brain_system_prompt(tenant_id: str) -> str:
    """Reuse the AI Brain assembly from routers/ai_brain.py."""
    try:
        from routers.ai_brain import build_system_prompt
        return await build_system_prompt(tenant_id)
    except Exception:
        return ""


async def generate_reply(
    tenant_id: str, rating: int, review_text: str,
    review_author: Optional[str] = None,
    sentiment_hint: Optional[str] = None,
) -> str:
    """Real implementation. Falls back to a template when the LLM
    call fails or the Emergent key is missing."""
    system_prompt = await _load_brain_system_prompt(tenant_id)
    stance = (
        "The customer is happy — thank them warmly and invite them back."
        if rating >= 4
        else "The customer is unhappy — apologise, take ownership, "
             "commit to making it right, and offer a soft CTA to reach out."
    )
    # Feb-2026 · P22 — Do NOT interpolate the reviewer's name into
    # the LLM prompt. Use a symbolic placeholder that the LLM will
    # echo back verbatim; we substitute the real reviewer name into
    # the LLM's OUTPUT post-generation. This keeps the P21 privacy
    # policy claim ("we do not send customer names to LLM providers")
    # verifiably true for this surface.
    from services.ai.pii_redactor import redact_pii
    user_prompt = (
        f"Draft a short (60–90 words), warm, on-brand reply to this "
        f"{rating}★ review.\n\n"
        f"{stance}\n\n"
        f"Reviewer name: [REVIEWER]\n"
        f"Review text: {redact_pii(review_text)}\n\n"
        f"Rules:\n"
        f"- Use a natural, human tone. Do not sound like a form letter.\n"
        f"- Reference specifics from the review when possible.\n"
        f"- Never promise things outside our services.\n"
        f"- Address the reviewer as [REVIEWER] — the app will "
        f"substitute the real name after generation.\n"
        f"- Sign with the company name at the end.\n"
    )
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return _fallback_reply(rating, review_author)
    try:
        # Phase I1.7.e · Chunk 2.b · Feb-2026 — routed through the
        # central AI chokepoint so per-tenant BYO keys + AI spend
        # caps apply. Plaintext + max_tokens preserves the legacy
        # trim + [REVIEWER] substitute path.
        from services.llm_provider import call_llm_with_fallback
        from services.ai.cap_http import is_ai_cap_exceeded
        result = await call_llm_with_fallback(
            system_prompt=system_prompt or "You are a helpful assistant.",
            user_text=user_prompt,
            provider="anthropic", model="claude-sonnet-4-5-20250929",
            tenant_id=tenant_id,
            parse_json=False,
            max_tokens=400,
        )
        if is_ai_cap_exceeded(result) or result.get("error"):
            return _fallback_reply(rating, review_author)
        text = ((result.get("raw") or {}).get("text") or "").strip()
        # Post-generation substitute — the reviewer's real name is
        # NEVER in the prompt but IS in the final published reply.
        if text and review_author:
            text = text.replace("[REVIEWER]", review_author)
        elif text:
            text = text.replace("[REVIEWER]", "there")
        return text or _fallback_reply(rating, review_author)
    except Exception as e:
        logger.warning(f"[review-reply] LLM failed: {e}")
        return _fallback_reply(rating, review_author)


@router.post("/reviews/suggest-reply",
              operation_id="reviews.suggestReply")
async def suggest_reply(
    body: SuggestReplyIn,
    user: Dict[str, Any] = Depends(get_current_user),
):
    if user.get("role") not in {"admin", "super_admin"}:
        raise HTTPException(403, "Admin only")
    reply = await generate_reply(
        tenant_id=user["tenant_id"],
        rating=body.rating,
        review_text=body.review_text,
        review_author=body.review_author,
        sentiment_hint=body.sentiment_hint,
    )
    return {"reply_text": reply}
