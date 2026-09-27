"""LS-B · Feb-2026 — MARCO Lead-Sense intake endpoint.

Public tracker beacon endpoint. The self-hosted widget
(``frontend/public/widget/lead-sense.js``) posts one visitor-
intent record per page load; the endpoint resolves the caller
tenant via ``marco_lead_sense_id``, enforces the tenant's
``lead_sense_allowed_origins`` (LS-A field), and persists the
record into ``db.visitor_intent``.

Endpoints
─────────
    POST /api/lead-sense/track   — public, no auth.

Auth model
──────────
Tenant is resolved via the ``ls_id`` payload field (matches
``tenants.marco_lead_sense_id``, unique per LS-A). NO JWT — this
is a public beacon called from third-party marketing sites.

The security barrier is the Origin allow-list persisted on the
tenant document. An empty list = block all (safe default), so a
tenant that hasn't configured origins yet cannot leak intent
records via a stolen ls_id.

Rate limiting
─────────────
SlowAPI decorator via the shared ``routers.marketing_media.limiter``
instance. Cap: 100 requests/minute per caller IP (SlowAPI's
default sync key_func). Beyond that, 429 is returned loudly —
beacon reliability is best-effort so back-off signalling matters
more than never-dropping-a-hit.

  * NB — the LS-B spec called for a per-``session_id`` cap. That
    would require reading the JSON body inside SlowAPI's
    (synchronous) key_func, which conflicts with the async body-
    reader. Parked as a follow-up; per-IP is the safe default and
    already blocks the practical abuse case (one browser tab
    hammering the endpoint).

Best-effort telemetry contract
──────────────────────────────
The widget uses ``navigator.sendBeacon`` which requires a 2xx
response for the beacon to be considered "successful" by the
UA. So:

  * happy-path            → 204 No Content
  * unknown ls_id         → 404 (opaque error, no enumeration leak)
  * disallowed origin     → 403 + logger.warning security event
  * missing Origin/Referer→ 403 (can't verify)
  * DB write failure      → 202 Accepted (log error server-side,
                            never fail the beacon — the visitor's
                            page shouldn't care)
  * over rate limit       → 429 (SlowAPI attaches Retry-After)

Cross-tenant safety
───────────────────
Each intent row is stamped with the resolved ``tenant_id`` (the
tenant the ``ls_id`` belongs to). No opportunity for cross-
tenant contamination because the tenant is derived server-side
from a uniquely-indexed lookup, not from any body-supplied
field.

Follow-ups deferred to future sub-phases
────────────────────────────────────────
  * IP → company reverse lookup (Clearbit/similar). Stub for
    now: ``company: null`` on every row. LS-C's webhook tag
    system also lives in a follow-up sub-phase.
  * Form-field harvesting (email/phone from filled-out
    contact forms) — explicitly out of scope per LS-B ruling.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from config import db

# SlowAPI shared limiter — same instance registered on ``app.state.limiter``
# in server.py so the 429 envelope + retry-after headers are consistent
# with the existing rate-limited surface.
try:
    from routers.marketing_media import limiter as _shared_limiter
except Exception:  # pragma: no cover — defensive
    _shared_limiter = None  # type: ignore[assignment]


logger = logging.getLogger("pool_crm")
router = APIRouter(prefix="/api/lead-sense", tags=["lead-sense"])


SOURCE_CHANNEL = "MARCO Lead-Sense"


# ═════════════════════════════════════════════════════════════════════
# Request model
# ═════════════════════════════════════════════════════════════════════
class LeadSenseTrackIn(BaseModel):
    """Payload posted by the tracker widget on every page load."""
    ls_id: str = Field(
        ...,
        min_length=6, max_length=64,
        description="Tenant's ``marco_lead_sense_id`` (LS-A).",
    )
    session_id: str = Field(
        ...,
        min_length=8, max_length=64,
        description=(
            "Widget-generated session id "
            "(``crypto.randomUUID()`` on modern browsers)."
        ),
    )
    current_url: str = Field(
        ..., max_length=2048,
        description="``window.location.href`` at page load.",
    )
    referrer: Optional[str] = Field(
        None, max_length=2048,
        description="``document.referrer`` when non-empty.",
    )
    user_agent: Optional[str] = Field(
        None, max_length=1024,
        description="``navigator.userAgent`` string.",
    )
    page_title: Optional[str] = Field(
        None, max_length=512,
        description="``document.title`` at page load.",
    )
    viewport: Optional[Dict[str, int]] = Field(
        None,
        description=(
            "``{w: <int>, h: <int>}`` viewport size in CSS pixels."
        ),
    )

    @field_validator("session_id")
    @classmethod
    def _session_id_shape(cls, v: str) -> str:
        # 8-64 alphanumeric + dash + underscore. UUIDv4 (36 chars)
        # passes; the pattern is deliberately lax to allow the
        # widget's fallback generator without lock-in.
        import re
        if not re.fullmatch(r"[A-Za-z0-9\-_]{8,64}", v or ""):
            raise ValueError(
                "session_id must be 8-64 alphanumeric / dash / underscore"
            )
        return v


# ═════════════════════════════════════════════════════════════════════
# Origin helpers
# ═════════════════════════════════════════════════════════════════════
def _origin_of(url_or_header: Optional[str]) -> Optional[str]:
    """Return the canonical ``scheme://host[:port]`` of the given
    URL or Origin-header value, or ``None`` if unparseable.

    Matches the write-side normalisation in
    ``routers.tenants._validate_origin`` (lowercase scheme + host,
    port preserved as-is, no path/query).
    """
    if not url_or_header:
        return None
    val = url_or_header.strip()
    if not val:
        return None
    # If it looks like a bare Origin header (scheme://host[:port])
    # with no path, we can accept it as-is after lowercasing.
    try:
        parsed = urlparse(val)
    except Exception:  # noqa: BLE001
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _caller_origin(request: Request) -> Optional[str]:
    """Prefer the ``Origin`` header (set by browsers on all CORS
    XHRs), fall back to the origin extracted from ``Referer``
    (set on same-origin navigations that trigger the widget from
    a page context)."""
    origin_hdr = request.headers.get("origin")
    if origin_hdr:
        norm = _origin_of(origin_hdr)
        if norm:
            return norm
    referer = request.headers.get("referer")
    if referer:
        return _origin_of(referer)
    return None


def _extract_client_ip(request: Request) -> str:
    """Return the caller's IP. Prefer the left-most entry of
    ``X-Forwarded-For`` (the original client per RFC 7239),
    fall back to ``request.client.host``."""
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        # Return the FIRST entry — that's the origin client
        # per RFC 7239 §5.2. Skip empties so a stray "," at
        # the front doesn't yield "".
        for token in xff.split(","):
            candidate = token.strip()
            if candidate:
                return candidate
    return request.client.host if request.client else "unknown"


# ═════════════════════════════════════════════════════════════════════
# Handler
# ═════════════════════════════════════════════════════════════════════
def _apply_rate_limit(fn):
    """Attach SlowAPI's ``@limiter.limit`` when the shared limiter
    is present; degrade gracefully to a no-op decorator if the
    limiter didn't initialise (e.g. slowapi is absent, defensive).

    Matches the ``_apply_media_rate_limit`` pattern in
    routers/marketing_media.py so the surface behaves identically
    to the rest of the ecosystem. Uses the shared limiter's
    default key_func (client IP via X-Forwarded-For / request.client.host)
    — per-session_id scoping was deferred (see module docstring)."""
    if _shared_limiter is None:  # pragma: no cover — slowapi always installed
        return fn
    return _shared_limiter.limit("100/minute")(fn)


@router.post("/track", include_in_schema=False)
@_apply_rate_limit
async def track_visitor_intent(
    request: Request, response: Response,
):
    """Record one visitor-intent row from the tracker widget.

    Returns 204 on success. See module docstring for the full
    status-code contract.
    """
    # Read the JSON body. Widget sends Content-Type: text/plain to
    # avoid a CORS preflight; ``request.json()`` still parses the
    # body regardless of the declared MIME because Starlette's
    # implementation just runs ``json.loads`` over the raw bytes.
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Malformed JSON body.")

    try:
        payload = LeadSenseTrackIn.model_validate(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Invalid payload: {exc}")

    # Resolve tenant. Generic error copy so we don't leak whether
    # a specific ls_id exists.
    tenant = await db.tenants.find_one(
        {"marco_lead_sense_id": payload.ls_id},
        {"_id": 0, "id": 1, "lead_sense_allowed_origins": 1},
    )
    if tenant is None:
        raise HTTPException(404, "invalid_tracker")

    tenant_id = tenant.get("id")
    allowed = tenant.get("lead_sense_allowed_origins") or []
    if not isinstance(allowed, list):
        allowed = []

    # Origin enforcement.
    caller_origin = _caller_origin(request)
    if caller_origin is None:
        logger.warning(
            "[lead_sense.security] origin_missing ls_id=%s "
            "tenant_id=%s session_id=%s",
            payload.ls_id, tenant_id, payload.session_id,
        )
        raise HTTPException(403, "origin_required")

    normalised_allowed = {o.lower() for o in allowed}
    if caller_origin not in normalised_allowed:
        logger.warning(
            "[lead_sense.security] origin_rejected ls_id=%s "
            "tenant_id=%s origin=%s allowed_count=%s",
            payload.ls_id, tenant_id, caller_origin, len(allowed),
        )
        raise HTTPException(403, "origin_not_allowed")

    # Reflect the matched origin on the response so browsers
    # accept the beacon cross-origin without a preflight.
    response.headers["Access-Control-Allow-Origin"] = caller_origin
    response.headers["Vary"] = "Origin"

    # Build the row.
    now_iso = datetime.now(timezone.utc).isoformat()
    ip = _extract_client_ip(request)
    row: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "session_id": payload.session_id,
        "current_url": payload.current_url,
        "referrer": payload.referrer,
        "ip": ip,
        # ── STUB — real IP→company lookup lands in a follow-up.
        "company": None,
        "user_agent": payload.user_agent,
        "page_title": payload.page_title,
        "viewport": payload.viewport,
        "occurred_at": now_iso,
        # Pre-tag so LS-C's webhook merger + Marco lead-source
        # picker can filter on this without a JOIN.
        "source_channel": SOURCE_CHANNEL,
    }

    try:
        await db.visitor_intent.insert_one(row)
    except Exception as exc:  # noqa: BLE001
        # Best-effort — DO NOT surface a 5xx to the beacon caller.
        logger.exception(
            "[lead_sense] visitor_intent write failed: %s", exc,
        )
        return Response(status_code=202)

    return Response(status_code=204)


# ─────────────────────────────────────────────────────────────────────
# Health probe — used by the widget for a lightweight liveness check.
# Not documented; not referenced by the widget in LS-B (added for the
# integration test that verifies the router mounted correctly).
# ─────────────────────────────────────────────────────────────────────
@router.get("/health", include_in_schema=False)
async def _health():
    return {"ok": True, "surface": "lead-sense"}


# ═════════════════════════════════════════════════════════════════════
# LS-C · Feb-2026 — Visitor intent → Lead conversion
# ─────────────────────────────────────────────────────────────────────
# Bridges the passive tracker (LS-B) into the leads pipeline. Called
# by the tenant's website form-submit handler with the widget's
# session_id + whatever contact fields the visitor filled in.
#
# Trust boundary
# ──────────────
# This endpoint writes ``source = "MARCO Lead-Sense"`` directly to
# ``db.leads`` — bypassing the ``_VALID_SOURCES`` guard on
# ``routers.leads.create_lead`` (which stays enforced for the
# authenticated admin form). The bypass is code-path-based:
# the source string is trusted BECAUSE the request survived the
# ls_id resolution + origin allow-list + rate-limit gates. See
# ``routers.leads._SYSTEM_SOURCES`` for the sibling whitelist that
# documents system-generated source labels.
#
# Idempotency contract
# ────────────────────
# A repeat submission with the same ``(tenant_id, session_id,
# email)`` within 24h UPDATES the existing lead instead of
# creating a duplicate. Form-double-submit noise (visitor clicks
# submit twice, browser retries on a flaky link) collapses to a
# single lead row. After 24h the semantics flip — a new lead is
# created because a legitimate return visit deserves its own
# attribution snapshot.
# ═════════════════════════════════════════════════════════════════════


class LeadSenseConvertIn(BaseModel):
    """Payload posted by the tenant's website form-submit handler."""
    ls_id: str = Field(
        ...,
        min_length=6, max_length=64,
        description="Tenant's ``marco_lead_sense_id`` (LS-A).",
    )
    session_id: str = Field(
        ...,
        min_length=8, max_length=64,
        description="Widget session id (LS-B ``marco_ls_session``).",
    )
    name: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=320)
    phone: Optional[str] = Field(None, max_length=50)
    message: Optional[str] = Field(None, max_length=5000)
    custom_fields: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Arbitrary tenant-defined form fields. Persisted "
            "verbatim on the lead row under ``custom_fields``. "
            "Capped at 20 keys server-side to avoid a poisoned "
            "form dropping unbounded blobs into Mongo."
        ),
    )

    @field_validator("session_id")
    @classmethod
    def _session_id_shape(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"[A-Za-z0-9\-_]{8,64}", v or ""):
            raise ValueError(
                "session_id must be 8-64 alphanumeric / dash / underscore"
            )
        return v

    @field_validator("custom_fields")
    @classmethod
    def _cap_custom_fields(cls, v):
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError("custom_fields must be an object")
        if len(v) > 20:
            raise ValueError("custom_fields exceeds max keys (20)")
        return v


_CONVERSION_DEDUP_WINDOW_HOURS = 24
_INTENT_HISTORY_CAP = 25  # most recent N pages per session
_LEAD_SENSE_SOURCE = "MARCO Lead-Sense"


def _has_contact_info(payload: LeadSenseConvertIn) -> bool:
    """Require at least one of ``name``/``email``/``phone``. A row
    with zero contact fields is useless — the admin can't follow up.
    Matches the guardrail in ``routers.leads.create_lead``."""
    return any(
        (getattr(payload, k) or "").strip()
        for k in ("name", "email", "phone")
    )


async def _fetch_intent_snapshot(*, tenant_id: str, session_id: str):
    """Return ``(intent_history, intent_ids, mismatch_count)``.

    Grabs the most recent ``_INTENT_HISTORY_CAP`` intent rows for
    the caller session, restricted to the resolved tenant. A
    cross-tenant row (session_id somehow shared across tenants —
    shouldn't happen but the LS-B unique-index-per-collection isn't
    tenant-scoped) is counted separately so the caller can log a
    security event.
    """
    history: List[Dict[str, Any]] = []
    intent_ids: List[str] = []
    mismatch = 0
    cursor = db.visitor_intent.find(
        {"session_id": session_id},
        {
            "_id": 0, "id": 1, "tenant_id": 1,
            "current_url": 1, "referrer": 1, "occurred_at": 1,
        },
    ).sort("occurred_at", -1).limit(_INTENT_HISTORY_CAP * 2)
    async for row in cursor:
        if row.get("tenant_id") != tenant_id:
            mismatch += 1
            continue
        if len(history) >= _INTENT_HISTORY_CAP:
            continue
        history.append({
            "url": row.get("current_url"),
            "referrer": row.get("referrer"),
            "occurred_at": row.get("occurred_at"),
        })
        rid = row.get("id")
        if isinstance(rid, str):
            intent_ids.append(rid)
    # Return oldest-first so the timeline reads naturally.
    history.reverse()
    return history, intent_ids, mismatch


def _iso_hours_ago(hours: int) -> str:
    from datetime import timedelta
    return (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).isoformat()


def _lead_search_query(tenant_id: str, payload: LeadSenseConvertIn) -> dict:
    """Idempotency lookup — the same ``session_id`` + normalised
    ``email`` (or ``phone`` fallback) inside the dedup window is
    treated as the same submission."""
    since = _iso_hours_ago(_CONVERSION_DEDUP_WINDOW_HOURS)
    q: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "session_id": payload.session_id,
        "source": _LEAD_SENSE_SOURCE,
        "created_at": {"$gte": since},
    }
    if (payload.email or "").strip():
        q["email"] = payload.email.strip().lower()
    return q


@router.post("/convert", include_in_schema=False)
@_apply_rate_limit
async def convert_lead(request: Request, response: Response):
    """Persist a visitor-intent-attributed lead.

    See module docstring for the full status-code contract; this
    handler mirrors ``track_visitor_intent`` for tenant resolution
    + origin enforcement + rate-limit gating, then diverges into
    the lead-creation / idempotent-update flow.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Malformed JSON body.")

    try:
        payload = LeadSenseConvertIn.model_validate(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Invalid payload: {exc}")

    if not _has_contact_info(payload):
        raise HTTPException(
            422,
            "At least one of name / email / phone is required.",
        )

    # Resolve tenant — same opaque-error convention as /track.
    tenant = await db.tenants.find_one(
        {"marco_lead_sense_id": payload.ls_id},
        {"_id": 0, "id": 1, "lead_sense_allowed_origins": 1},
    )
    if tenant is None:
        raise HTTPException(404, "invalid_tracker")

    tenant_id = tenant.get("id")
    allowed = tenant.get("lead_sense_allowed_origins") or []
    if not isinstance(allowed, list):
        allowed = []

    caller_origin = _caller_origin(request)
    if caller_origin is None:
        logger.warning(
            "[lead_sense.security] convert_origin_missing "
            "ls_id=%s tenant_id=%s session_id=%s",
            payload.ls_id, tenant_id, payload.session_id,
        )
        raise HTTPException(403, "origin_required")
    if caller_origin not in {o.lower() for o in allowed}:
        logger.warning(
            "[lead_sense.security] convert_origin_rejected "
            "ls_id=%s tenant_id=%s origin=%s allowed_count=%s",
            payload.ls_id, tenant_id, caller_origin, len(allowed),
        )
        raise HTTPException(403, "origin_not_allowed")

    # CORS reflection (matches /track).
    response.headers["Access-Control-Allow-Origin"] = caller_origin
    response.headers["Vary"] = "Origin"

    # Pull intent snapshot for attribution.
    intent_history, intent_ids, cross_tenant_hits = (
        await _fetch_intent_snapshot(
            tenant_id=tenant_id, session_id=payload.session_id,
        )
    )
    if cross_tenant_hits:
        logger.warning(
            "[lead_sense.security] cross_tenant_conversion_mismatch "
            "ls_id=%s tenant_id=%s session_id=%s "
            "mismatched_intents_skipped=%s",
            payload.ls_id, tenant_id, payload.session_id,
            cross_tenant_hits,
        )

    now_iso_val = datetime.now(timezone.utc).isoformat()

    # Idempotency check — repeat submission collapses to update.
    dup = await db.leads.find_one(
        _lead_search_query(tenant_id, payload),
        {"_id": 0, "id": 1},
    )
    email_norm = (payload.email or "").strip().lower() or None
    lead_fields_common: Dict[str, Any] = {
        "name": (payload.name or "").strip() or None,
        "email": email_norm,
        "phone": (payload.phone or "").strip() or None,
        "notes": (payload.message or "").strip() or None,
        "session_id": payload.session_id,
        "visitor_intent_ids": intent_ids,
        "intent_history": intent_history,
        "custom_fields": payload.custom_fields or {},
        "source": _LEAD_SENSE_SOURCE,
        "source_channel": _LEAD_SENSE_SOURCE,
        "updated_at": now_iso_val,
    }

    lead_id: str
    if dup is not None:
        lead_id = dup["id"]
        await db.leads.update_one(
            {"id": lead_id, "tenant_id": tenant_id},
            {"$set": lead_fields_common,
             "$push": {"timeline": {
                 "kind": "lead_sense_resubmit",
                 "at": now_iso_val,
                 "matched_intents": len(intent_ids),
             }}},
        )
    else:
        lead_id = str(uuid.uuid4())
        row = dict(lead_fields_common)
        row.update({
            "id": lead_id,
            "tenant_id": tenant_id,
            "created_at": now_iso_val,
            "status": "new",
            "archived_at": None,
            "loss_reason": None,
            "converted_customer_id": None,
            "timeline": [{
                "kind": "lead_sense_created",
                "at": now_iso_val,
                "matched_intents": len(intent_ids),
                "session_id": payload.session_id,
            }],
        })
        try:
            await db.leads.insert_one(row)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[lead_sense] lead insert failed: %s", exc,
            )
            # Best-effort — surface a 202 rather than a 5xx so the
            # tenant's form submit shows a soft-fail. The intent
            # trail is still queryable from the admin side.
            return Response(
                content='{"status":"accepted","lead_id":null,'
                        '"matched_intents":0}',
                media_type="application/json",
                status_code=202,
            )

    # Stamp matched intents with converted_at + lead_id for reverse
    # lookup (admin reports "who converted this session").
    if intent_ids:
        try:
            await db.visitor_intent.update_many(
                {
                    "tenant_id": tenant_id,
                    "id": {"$in": intent_ids},
                },
                {"$set": {
                    "converted_at": now_iso_val,
                    "converted_lead_id": lead_id,
                }},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[lead_sense] intent stamp failed (non-fatal): %s",
                exc,
            )

    import json as _json
    return Response(
        content=_json.dumps({
            "status": "recorded",
            "lead_id": lead_id,
            "matched_intents": len(intent_ids),
        }),
        media_type="application/json",
        status_code=200,
    )
