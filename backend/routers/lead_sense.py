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
