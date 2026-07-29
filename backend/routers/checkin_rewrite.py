"""AI Description Rewrite for Job Check-ins · Feb-2026.

Small helper endpoint that lets techs (and admins creating check-ins on
their behalf) turn a rough draft description into a professional, lightly
SEO-optimized paragraph via the Emergent LLM.

Route
-----
``POST /api/checkins/rewrite-description``

Body::

    {
      "draft_description": "worked on pump, replaced filter",
      "context": {
        "service_category": "Pool Equipment Installs",
        "customer_name": "…",
        "address": "…",
        "business_name": "Pool & Landscaping of …"
      }
    }

Response::

    {"rewritten": "<text>", "original": "<draft>"}

Failure modes
-------------
* Empty draft → 400 ``{"error": "empty_draft"}``
* LLM timeout / unavailable → 502 ``{"error": "llm_unavailable"}``
* > 10 calls per user per rolling hour → 429 ``{"error": "rate_limited"}``

The endpoint does **not** persist anything to the check-ins collection —
it's a pure helper. Callers decide what to do with the rewritten text.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import EMERGENT_LLM_KEY, logger
from utils import get_current_user, new_id

router = APIRouter()

# In-memory rate limiter — 10 rewrites / rolling 3600s / user.
_RATE_WINDOW_S = 3600
_RATE_MAX = 10
_rate_state: Dict[str, Deque[float]] = defaultdict(deque)


def _rate_check(user_id: str) -> bool:
    """Return True if the caller is still within budget; otherwise
    False (and DOES NOT record the attempt)."""
    now = time.time()
    q = _rate_state[user_id]
    while q and (now - q[0]) > _RATE_WINDOW_S:
        q.popleft()
    if len(q) >= _RATE_MAX:
        return False
    q.append(now)
    return True


def _rate_reset(user_id: str) -> None:
    """Test helper — clear a specific user's window."""
    _rate_state.pop(user_id, None)


class RewriteContext(BaseModel):
    service_category: Optional[str] = None
    customer_name: Optional[str] = None
    address: Optional[str] = None
    business_name: Optional[str] = None


class RewriteBody(BaseModel):
    draft_description: str
    context: Optional[RewriteContext] = None


def _build_prompt(draft: str, ctx: Optional[RewriteContext]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the LLM."""
    biz = (ctx.business_name if ctx and ctx.business_name else "").strip()
    cat = (ctx.service_category if ctx and ctx.service_category else "").strip()
    addr = (ctx.address if ctx and ctx.address else "").strip()
    name = (ctx.customer_name if ctx and ctx.customer_name else "").strip()

    system_prompt = (
        "You are a professional copywriter for a home-service field business. "
        "Rewrite the technician's rough check-in note into a polished, "
        "customer-facing description of the work performed. "
        "Requirements:\n"
        "  * 60–150 words. One or two short paragraphs.\n"
        "  * Third person, professional, factual. No superlatives, no marketing fluff.\n"
        "  * Natural keyword density for SEO — mention the service category, "
        "location, and business name once each, woven in naturally. "
        "Never keyword-stuff.\n"
        "  * If a fact is not in the draft or context, do not invent it.\n"
        "  * Output ONLY the rewritten paragraph text. No preamble, no bullet "
        "points, no headings, no explanations, no quotation marks."
    )

    ctx_bits = []
    if biz:
        ctx_bits.append(f"Business: {biz}")
    if cat:
        ctx_bits.append(f"Service category: {cat}")
    if addr:
        ctx_bits.append(f"Address / location: {addr}")
    if name:
        ctx_bits.append(f"Customer: {name}")
    ctx_block = "\n".join(ctx_bits) if ctx_bits else "(no additional context)"

    user_prompt = (
        f"Draft check-in note:\n\"\"\"\n{draft.strip()}\n\"\"\"\n\n"
        f"Context:\n{ctx_block}\n\n"
        f"Rewrite the draft now."
    )
    return system_prompt, user_prompt


async def _call_emergent_text(system_prompt: str, user_prompt: str) -> str:
    """Emergent-LLM text-only call. Returns the raw string reply.
    Raises RuntimeError on any failure (timeout, import, empty, etc.).
    """
    key = EMERGENT_LLM_KEY or os.environ.get("EMERGENT_LLM_KEY", "")
    if not key:
        raise RuntimeError("emergent_key_missing")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:  # pragma: no cover — env-dependent
        raise RuntimeError(f"emergent_import_failed: {e}") from e
    try:
        chat = (
            LlmChat(
                api_key=key,
                session_id=new_id(),
                system_message=system_prompt,
            )
            .with_model("anthropic", "claude-sonnet-4-5")
        )
        msg = UserMessage(text=user_prompt)
        resp = await asyncio.wait_for(chat.send_message(msg), timeout=30.0)
    except asyncio.TimeoutError as e:
        raise RuntimeError("emergent_timeout") from e
    except Exception as e:
        raise RuntimeError(f"emergent_call_failed: {e}") from e
    text = str(resp or "").strip()
    # Strip surrounding quotes / codefences the model sometimes emits.
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("text\n"):
            text = text[5:]
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].strip()
    if not text:
        raise RuntimeError("emergent_empty_response")
    return text


# Test seam — the pytest suite patches this to bypass the real LLM.
async def _generate_rewrite(system_prompt: str, user_prompt: str) -> str:
    return await _call_emergent_text(system_prompt, user_prompt)


@router.post("/checkins/rewrite-description")
async def rewrite_description(
    body: RewriteBody,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    # Role gate — only tech / admin / super_admin may consume the AI.
    role = (user or {}).get("role") or ""
    if role not in ("technician", "admin", "super_admin", "manager"):
        raise HTTPException(403, {"error": "forbidden"})

    draft = (body.draft_description or "").strip()
    if not draft:
        raise HTTPException(400, {"error": "empty_draft"})

    user_id = str(user.get("id") or user.get("email") or "anon")
    if not _rate_check(user_id):
        raise HTTPException(429, {"error": "rate_limited"})

    system_prompt, user_prompt = _build_prompt(draft, body.context)
    try:
        rewritten = await _generate_rewrite(system_prompt, user_prompt)
    except Exception as e:
        logger.warning(f"[checkin_rewrite] LLM failure: {e}")
        raise HTTPException(502, {"error": "llm_unavailable"}) from e

    return {"rewritten": rewritten, "original": draft}
