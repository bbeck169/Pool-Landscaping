"""AI Description generator for check-ins · Feb-2026.

``POST /api/checkins/{checkin_id}/ai-description``

Given a check-in id, produces a fresh 1-2 sentence, SEO-safe,
neutral-factual description of the service visit. Unlike the
existing ``/api/checkins/rewrite-description`` endpoint (which
polishes a tech's draft), this endpoint ASSEMBLES the description
from structured context — the parent job's service type/title,
the customer's city + ZIP (with a "the local area" fallback), and
the tenant's optional ``business_settings.brand_voice`` voice
snippet.

Rate limit
----------
10 successful calls per hour per **tenant** (not per user). Enforced
via an atomic ``find_one_and_update`` on ``db.ai_description_events``
so multi-worker installs share the same counter. Boundary is fixed
UTC-hour aligned (same trade-off as ``checkin_rewrite`` — see that
file's module docstring for the rationale). 429 responses carry
``retry_after_seconds`` computed from the current window's tail.

Telemetry
---------
Every successful call writes an audit row to
``db.ai_description_events`` — the same collection used for the
rate-limit counter, keyed by ``(tenant_id, window_start_utc)``.
Individual event rows are appended into an ``events`` array so
tenant admins can inspect usage per window without a JOIN.

Authorization
-------------
Mirrors ``submit_public_checkin``:

* ``super_admin`` / ``admin`` (matching tenant) — always allowed.
* ``technician`` — only when they own the check-in (matches the
  ``technician_id`` on the raw ``checkins`` row).
* Anything else — 403.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso

router = APIRouter()

# ══════════════════════════════════════════════════════════════════
# Rate-limit constants — 10 successful calls per tenant per fixed
# UTC-hour window.
# ══════════════════════════════════════════════════════════════════
_RATE_WINDOW_SECONDS = 3600
_RATE_MAX = 10
_ACTION = "checkin_ai_description"


def _current_window() -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(seconds=_RATE_WINDOW_SECONDS)
    return start, end


async def _charge_rate_limit(tenant_id: str, user_id: str,
                              ) -> Tuple[bool, int, int]:
    """Atomically bump the tenant's counter for the current window.

    Returns ``(allowed, count_after, retry_after_seconds)``. When
    ``allowed`` is False, the counter is rolled back so the number
    remains truthy (attacker hammering doesn't inflate the row's
    ``call_count`` past the cap).
    """
    now = datetime.now(timezone.utc)
    start, end = _current_window()
    doc = await db.ai_description_events.find_one_and_update(
        {"tenant_id": tenant_id, "action": _ACTION,
         "window_start_utc": start.isoformat()},
        {"$inc": {"call_count": 1},
         "$set": {"last_called_at": now.isoformat(),
                   "last_user_id": user_id,
                   "window_end_utc": end.isoformat()},
         "$setOnInsert": {"created_at": now.isoformat(),
                            "events": []}},
        upsert=True, return_document=True,
    )
    count = int((doc or {}).get("call_count", 1))
    retry_after = max(1, int((end - now).total_seconds()))
    if count > _RATE_MAX:
        await db.ai_description_events.update_one(
            {"tenant_id": tenant_id, "action": _ACTION,
             "window_start_utc": start.isoformat()},
            {"$inc": {"call_count": -1},
             "$set": {"last_rejected_at": now.isoformat()}},
        )
        return False, count - 1, retry_after
    return True, count, retry_after


async def _log_event(tenant_id: str, user_id: str,
                       checkin_id: str, description: str,
                       provider_tag: str) -> None:
    """Append a telemetry event to the current window's row. Fire-
    and-forget — a failure here MUST NOT surface a 500 to the
    caller."""
    try:
        start, _ = _current_window()
        await db.ai_description_events.update_one(
            {"tenant_id": tenant_id, "action": _ACTION,
             "window_start_utc": start.isoformat()},
            {"$push": {"events": {
                "id": new_id(),
                "user_id": user_id,
                "checkin_id": checkin_id,
                "description_chars": len(description),
                "provider": provider_tag,
                "at": now_iso(),
            }}},
        )
    except Exception as e:                                              # noqa: BLE001
        logger.warning("ai_description_events log skipped: %s", e)


# ══════════════════════════════════════════════════════════════════
# Context gathering — check-in → job → customer → tenant
# ══════════════════════════════════════════════════════════════════
async def _load_checkin_for(user: dict, checkin_id: str
                             ) -> Tuple[Dict[str, Any], str]:
    """Load the raw check-in doc OR fall back to a public_checkin row.

    Returns ``(row, kind)`` where ``kind`` is ``"checkin"`` or
    ``"public_checkin"``. Raises 404 when neither collection carries
    the id, or 403 when the caller isn't authorized for it.
    """
    tenant_id = user.get("tenant_id")
    role = user.get("role") or ""
    caller_id = str(user.get("id") or user.get("email") or "anon")

    row = await db.checkins.find_one(
        {"id": checkin_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if row:
        # Tech role: must own the check-in.
        if role == "technician" and \
                str(row.get("technician_id") or "") != caller_id:
            raise HTTPException(403, "not_authorized_for_checkin")
        return row, "checkin"

    # Fall back to the moderation-queue row (public_checkins).
    prow = await db.public_checkins.find_one(
        {"id": checkin_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if prow:
        # Tech can rarely author the public row directly — most of
        # the time this is admin-only. Enforce admin/super_admin
        # unless the source checkin's tech is the caller.
        if role == "technician":
            src_cid = prow.get("source_checkin_id")
            src = await db.checkins.find_one(
                {"id": src_cid, "tenant_id": tenant_id},
                {"_id": 0, "technician_id": 1},
            ) if src_cid else None
            if not src or str(src.get("technician_id") or "") != caller_id:
                raise HTTPException(403, "not_authorized_for_checkin")
        return prow, "public_checkin"

    raise HTTPException(404, "checkin_not_found")


async def _resolve_context(row: Dict[str, Any], kind: str,
                            tenant_id: str) -> Dict[str, str]:
    """Assemble the LLM context bundle from job + customer + tenant."""
    job_id = row.get("job_id") or row.get("source_job_id")
    service_type = ""
    customer_id = None
    if job_id:
        for coll in ("jobs", "workorders"):
            job = await db[coll].find_one(
                {"id": job_id, "tenant_id": tenant_id},
                {"_id": 0, "service_name": 1, "service_category": 1,
                 "title": 1, "customer_id": 1},
            )
            if job:
                service_type = (job.get("service_name")
                                 or job.get("title")
                                 or job.get("service_category")
                                 or "").strip()
                customer_id = job.get("customer_id")
                break
    # Moderation-queue row already carries service_name — prefer the
    # freshly-resolved job value, fall back to what the row snapshot
    # has if the job disappeared.
    if not service_type and kind == "public_checkin":
        service_type = (row.get("service_name")
                         or row.get("service_category")
                         or "").strip()

    city = ""
    zip_code = ""
    if customer_id:
        cust = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "address_city": 1, "address_zip": 1,
             "city": 1, "zip": 1, "property": 1},
        )
        if cust:
            prop = cust.get("property") or {}
            city = (cust.get("address_city") or cust.get("city")
                     or prop.get("city") or "").strip()
            zip_code = (cust.get("address_zip") or cust.get("zip")
                         or prop.get("zip") or "").strip()

    # Fallback: public_checkin row carries a snapshot of the raw
    # address that survives even if the customer row is deleted.
    if kind == "public_checkin" and (not city or not zip_code):
        raw = row.get("raw_address") or {}
        city = city or (raw.get("city") or "").strip()
        zip_code = zip_code or (raw.get("zip") or "").strip()

    # Tenant brand voice — optional. Missing tenant / missing field
    # collapses to an empty string so the prompt template stays valid.
    tenant = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "business_settings": 1},
    ) or {}
    brand_voice = ((tenant.get("business_settings") or {})
                    .get("brand_voice") or "").strip()

    if not city:
        # Spec fallback: never leave the city slot blank in the
        # prompt — always pass "the local area" so the model doesn't
        # invent one.
        city = "the local area"

    return {
        "service_type": service_type or "a service visit",
        "city": city,
        "zip": zip_code,
        "brand_voice": brand_voice,
    }


# ══════════════════════════════════════════════════════════════════
# Prompt template
# ══════════════════════════════════════════════════════════════════
def _build_prompt(ctx: Dict[str, str]) -> Tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for a neutral-factual
    SEO-safe description.

    Prompt design (see ``FEATURE_AI_CHECKIN_DESCRIPTION.md`` §
    "Prompt tone reasoning"): explicit "no marketing hyperbole" +
    "no keyword stuffing" clauses are Google Search-spam-policy
    aligned — search engines penalise doorway-style repeated
    keyword phrasing, which is exactly what a naive AI copywriter
    would produce.
    """
    zip_bit = f" ZIP {ctx['zip']}" if ctx.get("zip") else ""
    brand_voice_bit = (f"Optional brand voice: {ctx['brand_voice']}"
                       if ctx.get("brand_voice") else
                       "Optional brand voice: (none)")
    system_prompt = (
        "You are a home-service copywriter. Compose a concise, "
        "customer-facing description of a completed service visit. "
        "Requirements:\n"
        "  * Exactly 1 to 2 sentences. No more.\n"
        "  * Tone: neutral, factual, SEO-safe.\n"
        "  * Do NOT stuff keywords. Do NOT use marketing hyperbole "
        "(no words like 'amazing', 'best-in-class', 'top-rated').\n"
        "  * Weave the service type, city, and (if present) ZIP into "
        "natural prose. Each keyword appears at most once.\n"
        "  * Return plain text only. No quotes, no markdown, no "
        "headings, no bullet points."
    )
    user_prompt = (
        f"Service type: {ctx['service_type']}\n"
        f"City: {ctx['city']}{zip_bit}\n"
        f"{brand_voice_bit}\n\n"
        "Write the description now."
    )
    return system_prompt, user_prompt


# ══════════════════════════════════════════════════════════════════
# LLM dispatch — thin wrapper so tests can monkeypatch cleanly.
# ══════════════════════════════════════════════════════════════════
async def _call_llm(system_prompt: str, user_prompt: str,
                     tenant_id: str) -> Tuple[str, str]:
    """Delegate to ``call_llm_with_fallback``. Returns
    ``(text, model_tag)``. Raises ``RuntimeError`` on any failure
    the caller should surface as HTTP 502.

    ``tenant_id`` is intentionally NOT forwarded — the BYO dispatch
    hop re-enters ``call_llm_with_fallback`` with the default
    ``parse_json=True`` and would corrupt our plaintext contract
    with an "empty_json" error. This endpoint's own per-tenant
    rate limit (10 / UTC hour) is the primary abuse gate; BYO
    cap enforcement isn't needed for a 1-2 sentence response.
    """
    from services.llm_provider import call_llm_with_fallback

    try:
        result = await asyncio.wait_for(
            call_llm_with_fallback(
                system_prompt=system_prompt, user_text=user_prompt,
                provider="anthropic", model="claude-sonnet-4-5",
                parse_json=False,
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError as e:
        raise RuntimeError("llm_timeout") from e
    except Exception as e:
        raise RuntimeError(f"llm_call_failed: {e}") from e

    if not isinstance(result, dict) or result.get("error"):
        raise RuntimeError(
            f"llm_error: {result.get('error') if isinstance(result, dict) else 'bad_shape'}"
        )
    raw = result.get("raw") or {}
    text = str(raw.get("text") or raw.get("content") or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("text\n"):
            text = text[5:]
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].strip()
    if not text:
        raise RuntimeError("llm_empty_response")

    provider = str(result.get("provider") or "").strip()
    model_tag = "gpt-4o" if provider == "openai" else "claude-sonnet-4-5"
    return text, model_tag


def _test_bypass_enabled(request: Request) -> bool:
    """When ``ALLOW_TEST_HOOKS=1`` AND the caller sends
    ``X-Test-Skip-Llm: 1``, skip the real LLM and return a canned
    response. Both flags must be present — production requests
    never satisfy the ``ALLOW_TEST_HOOKS`` env, so no client can
    hit this path outside the test pod."""
    if os.environ.get("ALLOW_TEST_HOOKS") != "1":
        return False
    return (request.headers.get("x-test-skip-llm") or "").strip() == "1"


# ══════════════════════════════════════════════════════════════════
# Route
# ══════════════════════════════════════════════════════════════════
class AIDescriptionBody(BaseModel):
    tone: str = Field(
        default="neutral_factual",
        description="Reserved for future extensibility. Only "
                     "``neutral_factual`` is supported in v1.",
    )


@router.post("/checkins/{checkin_id}/ai-description")
async def generate_ai_description(
    checkin_id: str,
    request: Request,
    body: Optional[AIDescriptionBody] = None,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    role = (user or {}).get("role") or ""
    if role not in ("technician", "admin", "super_admin", "manager"):
        raise HTTPException(403, "forbidden")
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(403, "tenant_scope_missing")

    # Tone is future-proofing — accept anything today, only
    # support the default. Non-default values fall through to the
    # default template.
    _tone = (body.tone if body else "neutral_factual") or "neutral_factual"

    # Load + auth check.
    row, kind = await _load_checkin_for(user, checkin_id)
    caller_id = str(user.get("id") or user.get("email") or "anon")

    # Rate limit — 10/tenant/hour.
    allowed, _count, retry_after = await _charge_rate_limit(
        tenant_id, caller_id,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limit_exceeded",
                     "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    # Context bundle → prompt.
    ctx = await _resolve_context(row, kind, tenant_id)
    system_prompt, user_prompt = _build_prompt(ctx)

    # Test hook — skip the LLM entirely.
    if _test_bypass_enabled(request):
        canned = (
            f"[TEST-STUB] Completed {ctx['service_type']} in "
            f"{ctx['city']}"
            + (f" (ZIP {ctx['zip']})" if ctx.get("zip") else "")
            + "."
        )
        generated_at = now_iso()
        await _log_event(tenant_id, caller_id, checkin_id,
                          canned, provider_tag="test-stub")
        return {"description": canned, "model": "gpt-4o",
                "generated_at": generated_at}

    try:
        text, model_tag = await _call_llm(system_prompt, user_prompt,
                                             tenant_id)
    except Exception as e:                                              # noqa: BLE001
        logger.warning("[ai-description] LLM failure: %s", e)
        raise HTTPException(502, {"code": "llm_unavailable"}) from e

    generated_at = now_iso()
    await _log_event(tenant_id, caller_id, checkin_id,
                      text, provider_tag=model_tag)
    return {"description": text, "model": model_tag,
            "generated_at": generated_at}


async def ensure_indexes() -> None:
    """Idempotent unique index on the composite rate-limit key."""
    try:
        await db.ai_description_events.create_index(
            [("tenant_id", 1), ("action", 1),
              ("window_start_utc", 1)],
            name="uq_ai_description_events_window", unique=True,
        )
    except Exception as e:                                              # noqa: BLE001
        logger.warning("[ai_description_events] index skipped: %s", e)
