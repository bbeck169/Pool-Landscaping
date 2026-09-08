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
* > 10 calls per user per fixed hour window → 429
  ``{"error": "rate_limited"}`` with a ``Retry-After`` header set to
  seconds remaining until the current window closes.

Phase 19 · Feb-2026 — Sub-item B: rate-limit state moved from an
in-process dict to ``db.ai_rewrite_usage`` so limits survive process
restarts and work across multiple workers. The change is a
rolling → fixed-window trade-off (accepted): the numeric budget stays
at 10 per user per hour, but window boundaries are UTC-hour aligned
instead of rolling from each call. Worst-case boundary drift ⇒ a user
could hit 20 calls in ~2 minutes if they perfectly straddle the
boundary. Acceptable for a soft cost/abuse limit.

The old in-process ``_rate_check`` / ``_rate_reset`` helpers are kept as
sync shims so ``tests/test_checkin_rewrite.py`` unit tests keep
running unchanged.

The endpoint does **not** persist anything to the check-ins collection —
it's a pure helper. Callers decide what to do with the rewritten text.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from config import EMERGENT_LLM_KEY, db, logger
from utils import get_current_user, new_id

router = APIRouter()

# ══════════════════════════════════════════════════════════════════
# Legacy in-process rate helpers — kept for the pre-Phase-19 unit
# tests in ``tests/test_checkin_rewrite.py``. Not used by the HTTP
# endpoint anymore.
# ══════════════════════════════════════════════════════════════════
_RATE_WINDOW_S = 3600
_RATE_MAX = 10
_rate_state: Dict[str, Deque[float]] = defaultdict(deque)


def _rate_check(user_id: str) -> bool:
    """Legacy in-process sliding-window check. Not used by the HTTP
    endpoint after Phase 19 — Mongo path in ``_rate_charge`` is
    authoritative. Preserved so the existing unit-test file keeps
    working without modification."""
    now = time.time()
    q = _rate_state[user_id]
    while q and (now - q[0]) > _RATE_WINDOW_S:
        q.popleft()
    if len(q) >= _RATE_MAX:
        return False
    q.append(now)
    return True


def _rate_reset(user_id: str) -> None:
    """Legacy in-process reset. Preserved as a sync no-arg-else helper."""
    _rate_state.pop(user_id, None)


# ══════════════════════════════════════════════════════════════════
# Phase 19 · Feb-2026 · Sub-item B — Mongo-backed fixed-window rate
# limit. Collection ``ai_rewrite_usage`` with a unique index on
# (tenant_id, user_id, action, window_start_utc). Atomic upsert +
# $inc means multi-worker safety without any Python-side lock.
# ══════════════════════════════════════════════════════════════════
def _current_window() -> Tuple[datetime, datetime]:
    """Return (window_start_utc, window_end_utc) — UTC-hour aligned."""
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(seconds=_RATE_WINDOW_S)
    return start, end


async def _rate_charge(tenant_id: str, user_id: str,
                        action: str = "checkin_rewrite"
                        ) -> Tuple[bool, int, int]:
    """Atomically charge one call against the current window.

    Returns ``(allowed, call_count_after, seconds_until_window_end)``.
    When ``allowed`` is False, the caller should raise 429 and set
    ``Retry-After`` to ``seconds_until_window_end``.
    """
    now = datetime.now(timezone.utc)
    start, end = _current_window()
    doc = await db.ai_rewrite_usage.find_one_and_update(
        {"tenant_id": tenant_id, "user_id": user_id,
         "action": action, "window_start_utc": start.isoformat()},
        {"$inc": {"call_count": 1},
         "$set": {"last_called_at": now.isoformat(),
                   "window_end_utc": end.isoformat()},
         "$setOnInsert": {"created_at": now.isoformat()}},
        upsert=True, return_document=True,
    )
    count = int((doc or {}).get("call_count", 1))
    retry_after = max(1, int((end - now).total_seconds()))
    if count > _RATE_MAX:
        # We just $inc'd past the limit — roll it back so the counter
        # stays truthy for dashboards and doesn't inflate under a
        # hammer-attack.
        await db.ai_rewrite_usage.update_one(
            {"tenant_id": tenant_id, "user_id": user_id,
             "action": action, "window_start_utc": start.isoformat()},
            {"$inc": {"call_count": -1},
             "$set": {"last_rejected_at": now.isoformat()}},
        )
        return False, count - 1, retry_after
    return True, count, retry_after


async def ensure_indexes() -> None:
    """Boot hook — idempotent unique index on the composite key.
    Registered from ``scripts/create_session_indexes.ensure_on_boot()``.
    """
    try:
        await db.ai_rewrite_usage.create_index(
            [("tenant_id", 1), ("user_id", 1),
              ("action", 1), ("window_start_utc", 1)],
            name="uq_ai_rewrite_usage_window", unique=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ai_rewrite_usage] index create skipped: {e}")


class RewriteContext(BaseModel):
    service_category: Optional[str] = None
    customer_name: Optional[str] = None
    address: Optional[str] = None
    business_name: Optional[str] = None


class RewriteBody(BaseModel):
    draft_description: str
    context: Optional[RewriteContext] = None


def _build_prompt(draft: str, ctx: Optional[RewriteContext]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the LLM.

    Feb-2026 · P22 — Privacy policy compliance:
    * Customer's full personal name is NEVER passed to the LLM.
    * Customer's exact street address is NEVER passed — only the
      generic ``[LOCATION]`` marker plus the free-text "Address /
      location" *label* the caller wanted rewritten into SEO copy
      (which is typically a city + neighbourhood, not a specific
      residence). Callers wanting to inject the customer's exact
      street address should stop doing so.
    * The technician's rough ``draft`` is redacted for emails and
      phone numbers before send — defence-in-depth against a tech
      pasting "call customer at 555-1234" into their note.
    """
    from services.ai.pii_redactor import redact_pii

    biz = (ctx.business_name if ctx and ctx.business_name else "").strip()
    cat = (ctx.service_category if ctx and ctx.service_category else "").strip()
    # Address field is preserved on the API for backwards
    # compatibility but we do NOT interpolate it verbatim. Extract
    # a coarse "city, state" hint if the caller passed one; else
    # drop it entirely.
    raw_addr = (ctx.address if ctx and ctx.address else "").strip()
    addr_hint = _coarse_location_hint(raw_addr)
    # Customer name is NEVER sent to the LLM (P21 §4 claim). The
    # rewritten copy is customer-facing but does not need the
    # customer's own name to read naturally.

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
        "  * Refer to the customer generically ('the homeowner', 'the "
        "client') — never invent a personal name.\n"
        "  * Output ONLY the rewritten paragraph text. No preamble, no bullet "
        "points, no headings, no explanations, no quotation marks."
    )

    ctx_bits = []
    if biz:
        ctx_bits.append(f"Business: {biz}")
    if cat:
        ctx_bits.append(f"Service category: {cat}")
    if addr_hint:
        ctx_bits.append(f"Service area: {addr_hint}")
    ctx_block = "\n".join(ctx_bits) if ctx_bits else "(no additional context)"

    # Redact any incidental email/phone that leaked into the tech's
    # rough note. Address of the specific property is not auto-
    # detectable so it isn't touched here.
    safe_draft = redact_pii(draft.strip(),
                              address_fields=[raw_addr] if raw_addr else None)

    user_prompt = (
        f"Draft check-in note:\n\"\"\"\n{safe_draft}\n\"\"\"\n\n"
        f"Context:\n{ctx_block}\n\n"
        f"Rewrite the draft now."
    )
    return system_prompt, user_prompt


def _coarse_location_hint(address: str) -> str:
    """Turn ``123 N 83rd Ave, Peoria, AZ 85382`` into ``Peoria, AZ``.

    Falls back to an empty string when the address cannot be
    de-specified — the SEO rewrite still runs, just without a
    location keyword.
    """
    if not address:
        return ""
    # Naive but safe: take last two comma-separated segments if
    # available; strip zip digits from the last segment.
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return ""  # single-segment strings almost always contain the
                    # street; better to drop than leak.
    tail = parts[-1]
    # Strip trailing zip.
    tail = re.sub(r"\s+\d{5}(?:-\d{4})?$", "", tail).strip()
    city = parts[-2]
    return f"{city}, {tail}".strip(", ")


async def _call_emergent_text(system_prompt: str, user_prompt: str,
                                 *, tenant_id: Optional[str] = None) -> str:
    """Emergent-LLM text-only call routed through the BYO-aware
    dispatcher chokepoint.

    Phase I1.7.e · chunk 2 · Feb-2026 — Migrated to
    ``services.llm_provider.call_llm_with_fallback(tenant_id=...)``
    so this endpoint honours per-tenant AI cap enforcement +
    tenant-BYO provider routing. Cap-exceeded surfaces as a
    ``HTTPException(429)`` via
    :func:`services.ai.cap_http.raise_if_ai_cap_exceeded` in the
    caller (:func:`rewrite_description`). Falls back to the Emergent
    Universal LLM Key when the tenant has no BYO AI provider row.

    Raises ``RuntimeError`` on any non-cap failure (timeout, import,
    empty response, etc.) — caller maps to HTTP 502. The
    cap-exceeded case is signalled by returning the raw result dict
    with ``cap_exceeded=True`` so the caller can raise 429 without
    swallowing the cap semantics in a generic 502.
    """
    from services.llm_provider import call_llm_with_fallback
    from services.ai.cap_http import is_ai_cap_exceeded

    try:
        result = await asyncio.wait_for(
            call_llm_with_fallback(
                system_prompt=system_prompt, user_text=user_prompt,
                provider="anthropic", model="claude-sonnet-4-5",
                tenant_id=tenant_id,
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError as e:
        raise RuntimeError("emergent_timeout") from e
    except Exception as e:
        raise RuntimeError(f"emergent_call_failed: {e}") from e

    # Cap-exceeded is a signalled state, not an exception. Surface it
    # to the caller in a form it can distinguish from a generic
    # failure (which maps to HTTP 502).
    if is_ai_cap_exceeded(result):
        raise _CapExceeded(result)

    if not isinstance(result, dict) or "raw" not in result:
        raise RuntimeError(f"emergent_bad_shape: {type(result).__name__}")

    raw = result.get("raw") or {}
    text = str(raw.get("text") or raw.get("content") or "").strip()
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


class _CapExceeded(Exception):
    """Sentinel exception carrying the cap-exceeded result dict so
    the endpoint handler can convert it into a proper HTTP 429 via
    :func:`services.ai.cap_http.raise_if_ai_cap_exceeded`."""

    def __init__(self, result: Dict[str, Any]) -> None:
        super().__init__("ai_spend_cap_exceeded")
        self.result = result


# Test seam — the pytest suite patches this to bypass the real LLM.
async def _generate_rewrite(system_prompt: str, user_prompt: str,
                              *, tenant_id: Optional[str] = None) -> str:
    return await _call_emergent_text(system_prompt, user_prompt,
                                        tenant_id=tenant_id)


def _test_bypass_enabled(request: Request) -> bool:
    """Return True when the request may skip the real LLM call.

    Gated by ``ALLOW_TEST_HOOKS=1`` (pod-wide env flag already used
    elsewhere in this codebase) PLUS a request header ``X-Test-Skip-Llm:
    1``. Both must be present — no way to hit this path in production
    even if a client crafts the header.
    """
    if os.environ.get("ALLOW_TEST_HOOKS") != "1":
        return False
    hv = request.headers.get("x-test-skip-llm") or ""
    return hv.strip() == "1"


@router.post("/checkins/rewrite-description")
async def rewrite_description(
    body: RewriteBody,
    request: Request,
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
    tenant_id = str(user.get("tenant_id") or "unknown")
    allowed, count, retry_after = await _rate_charge(tenant_id, user_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited"},
            headers={"Retry-After": str(retry_after)},
        )

    # Test-only bypass — skips the LLM call and returns a canned reply.
    if _test_bypass_enabled(request):
        return {"rewritten": f"[TEST-STUB] {draft}", "original": draft}

    system_prompt, user_prompt = _build_prompt(draft, body.context)
    try:
        rewritten = await _generate_rewrite(system_prompt, user_prompt,
                                              tenant_id=tenant_id)
    except _CapExceeded as cap:
        # Phase I1.7.e · chunk 2 · Feb-2026 — transactional AI
        # cap-exceeded → HTTP 429. Uses the migration helper so the
        # response shape matches the other transactional cap-exceeded
        # sites (D2D Zillow limiter, comms send-now, etc.).
        from services.ai.cap_http import raise_if_ai_cap_exceeded
        raise_if_ai_cap_exceeded(
            cap.result,
            detail={"error": "ai_spend_cap_exceeded",
                     **(cap.result.get("detail") or {})},
        )
        # `raise_if_ai_cap_exceeded` raises; the ``raise`` below is
        # unreachable but appeases the type-checker.
        raise HTTPException(429, {"error": "ai_spend_cap_exceeded"}) from cap
    except Exception as e:
        logger.warning(f"[checkin_rewrite] LLM failure: {e}")
        raise HTTPException(502, {"error": "llm_unavailable"}) from e

    return {"rewritten": rewritten, "original": draft}
