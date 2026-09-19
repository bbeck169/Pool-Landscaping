"""Feb-2026 · Proposal Analytics — Flipbook Estimate Tracking.

Customer-facing flipbook viewer instrumentation ingest + admin-side
dashboard endpoints. First-party analytics only — no third-party
providers, no cookies, no PII stored.

Endpoints (mounted under ``/api``)::

    POST /api/analytics/proposal/{estimate_id}/event    (magic-link)
    GET  /api/analytics/proposal/{estimate_id}/summary  (admin)
    GET  /api/analytics/proposal/{estimate_id}/events   (admin)
    GET  /api/analytics/proposals/overview              (admin)

Data model (``proposal_analytics_events`` collection)::

    {
      "id":         uuid,
      "tenant_id":  <str>,
      "estimate_id":<str>,
      "session_id": <uuid, client-generated, sessionStorage-scoped>,
      "event_type": "open" | "click" | "page_view" | "close",
      "page_index": <int|None>,
      "page_key":   <str|None>,     # "cover" | "service:{id}" | "total"…
      "button_id":  <str|None>,     # "approve" | "decline" | "download_pdf"
      "duration_ms":<int|None>,     # page_view close-out only
      "user_agent": <str|None>,     # truncated 256
      "ip_hash":    "sha256:…",     # SHA-256(ip + tenant-scoped salt)
      "referrer":   <str|None>,     # truncated 256
      "created_at": <iso>,
    }

Privacy contract:
  * Raw client IP is NEVER stored. Always SHA-256 with a per-tenant
    salt (auto-created on first write; stored in
    ``tenants.settings.analytics.ip_salt``).
  * ``session_id`` is a client-generated UUID persisted in
    ``sessionStorage`` — no cross-tab, no cross-session correlation.
  * ``open`` events are deduplicated per ``(session_id, estimate_id)``
    so refreshing the page doesn't inflate unique-view counts.

Rate limiting: bespoke Mongo-backed sliding-window counter — 120 events
per 60s per ``session_id``. Rejected requests return 429 with a
``retry_after_seconds`` hint but never break the customer viewer
(client swallows all analytics errors silently).

Auth model:
  * The ingest endpoint (``POST /event``) is public but token-gated —
    it consumes the SAME magic-link JWT the customer viewer already
    trusts (``routers.estimate_viewer._verify_estimate_token``). Token
    is passed in the body so ``navigator.sendBeacon`` (which can't set
    headers) can fire close/unload events. Cross-tenant / stale /
    expired tokens all bounce with 401 or 404.
  * The 3 admin endpoints require ``role in {admin, super_admin}``
    and tenant-scope every query to the caller's tenant.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user, now_iso
from routers.tenants import get_current_tenant


logger = logging.getLogger("analytics_proposal")
router = APIRouter()


COLLECTION = "proposal_analytics_events"

# ── Client-facing constants ──────────────────────────────────────────
_VALID_EVENT_TYPES = {"open", "click", "page_view", "close"}
_UA_MAX_LEN = 256
_REFERRER_MAX_LEN = 256
_PAGE_KEY_MAX_LEN = 64
_BUTTON_ID_MAX_LEN = 64
_SESSION_ID_MAX_LEN = 64
_DURATION_MS_MAX = 30 * 60 * 1000  # 30 minutes — sanity ceiling

# ── Rate limiter (Mongo-backed sliding window) ───────────────────────
_RL_COLLECTION = "proposal_analytics_rate"
_RL_WINDOW_S = 60
_RL_MAX_EVENTS = 120


# ═════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════
async def _get_or_create_tenant_salt(tenant_id: str) -> str:
    """Fetch (or lazily create) the per-tenant analytics IP salt.

    The salt is stored under ``tenants.settings.analytics.ip_salt`` —
    a fresh 32-char hex string generated on first write. Keeping it
    tenant-scoped means the same client IP hashes DIFFERENTLY for
    different tenants → cross-tenant enumeration is not possible even
    if two tenants' analytics tables leak.
    """
    row = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "settings.analytics.ip_salt": 1},
    )
    salt = (
        ((row or {}).get("settings") or {}).get("analytics") or {}
    ).get("ip_salt")
    if salt:
        return str(salt)
    salt = secrets.token_hex(16)  # 32 hex chars
    await db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"settings.analytics.ip_salt": salt}},
    )
    return salt


def _hash_ip(ip: str, salt: str) -> str:
    if not ip:
        return "sha256:anon"
    h = hashlib.sha256(f"{ip}|{salt}".encode("utf-8")).hexdigest()
    return f"sha256:{h}"


def _client_ip(request: Request) -> str:
    """Extract the client IP honouring the ``X-Forwarded-For`` chain
    the K8s ingress attaches. Falls back to the direct peer."""
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        # Left-most entry is the original client.
        return fwd.split(",")[0].strip()
    peer = request.client.host if request.client else ""
    return peer or ""


def _truncate(s: Optional[str], cap: int) -> Optional[str]:
    if s is None:
        return None
    s = str(s)
    return s[:cap] if len(s) > cap else s


async def _rate_limit_check(session_id: str) -> None:
    """120 events / 60s per session_id. Raises 429 on limit.

    Mongo-backed sliding window: one document per session with a
    rolling list of event timestamps. TTL index (``expire_at``) purges
    idle sessions after the window closes.
    """
    now = datetime.now(timezone.utc)
    window_start = now.timestamp() - _RL_WINDOW_S
    row = await db[_RL_COLLECTION].find_one_and_update(
        {"session_id": session_id},
        {
            "$push": {"ts": now.timestamp()},
            "$set": {"expire_at": datetime.fromtimestamp(
                now.timestamp() + _RL_WINDOW_S * 4,
                tz=timezone.utc,
            )},
        },
        upsert=True,
        return_document=True,
    )
    ts = [t for t in (row.get("ts") or []) if t >= window_start]
    if len(ts) > _RL_MAX_EVENTS:
        oldest = min(ts)
        retry = int(_RL_WINDOW_S - (now.timestamp() - oldest)) + 1
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited",
                     "retry_after_seconds": max(1, retry)},
        )
    # Trim the ts list back to the window so it doesn't grow unbounded
    # across the TTL lifetime.
    if len(row.get("ts") or []) > len(ts):
        await db[_RL_COLLECTION].update_one(
            {"session_id": session_id},
            {"$set": {"ts": ts}},
        )


async def _ensure_indexes() -> None:
    """Create the read/rollup + rate-limit indexes idempotently.

    Called at first write instead of app startup so the collection
    lifecycle is self-contained inside this router.
    """
    try:
        await db[COLLECTION].create_index(
            [("tenant_id", 1), ("estimate_id", 1), ("created_at", -1)],
            name="ax_tenant_estimate_created",
        )
        await db[COLLECTION].create_index(
            [("tenant_id", 1), ("session_id", 1)],
            name="ax_tenant_session",
        )
        await db[COLLECTION].create_index(
            [("session_id", 1), ("estimate_id", 1), ("event_type", 1)],
            name="ax_session_estimate_type",
        )
        await db[_RL_COLLECTION].create_index(
            "expire_at", expireAfterSeconds=0,
            name="rl_expire_ttl",
        )
        await db[_RL_COLLECTION].create_index(
            "session_id", unique=True, name="rl_session_uniq",
        )
    except Exception as exc:  # pragma: no cover — index create races on cold-start
        logger.warning("[analytics_proposal] index create warning: %s", exc)


# ═════════════════════════════════════════════════════════════════════
# POST /analytics/proposal/{estimate_id}/event  — magic-link ingest
# ═════════════════════════════════════════════════════════════════════
class EventIn(BaseModel):
    token: str = Field(..., min_length=10)
    session_id: str = Field(..., min_length=8, max_length=_SESSION_ID_MAX_LEN)
    event_type: str
    page_index: Optional[int] = None
    page_key: Optional[str] = None
    button_id: Optional[str] = None
    duration_ms: Optional[int] = None
    referrer: Optional[str] = None


async def _parse_body(request: Request) -> Dict[str, Any]:
    """Accept both ``application/json`` and ``text/plain``.

    ``navigator.sendBeacon`` sends a Blob whose default type is
    ``text/plain`` — the customer viewer uses it for close/unload
    events so we have to parse the raw body ourselves.
    """
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "empty_body")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "invalid_json")


@router.post("/analytics/proposal/{estimate_id}/event")
async def ingest_event(estimate_id: str, request: Request):
    from routers.estimate_viewer import _verify_estimate_token
    body = await _parse_body(request)
    try:
        payload = EventIn(**body)
    except Exception as exc:
        raise HTTPException(422, f"invalid_payload: {exc}")

    if payload.event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(422, "invalid_event_type")

    tok_payload = _verify_estimate_token(payload.token)
    if tok_payload.get("eid") != estimate_id:
        # Token issued for a different estimate — refuse to log against
        # the URL-supplied one (prevents cross-estimate injection).
        raise HTTPException(404, "estimate_mismatch")

    tenant_id = tok_payload.get("tid") or ""
    # Confirm the estimate still exists on this tenant (guards against
    # cross-tenant leakage should the token JWT ever be misissued).
    est = await db.quotes.find_one(
        {"id": estimate_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1},
    )
    if not est:
        raise HTTPException(404, "estimate_not_found")

    # Rate limit BEFORE indexes so an attacker firing 10k/s doesn't
    # thrash the index-create path either.
    await _rate_limit_check(payload.session_id)
    await _ensure_indexes()

    # Deduplicate ``open`` per (session_id, estimate_id) so a page
    # refresh doesn't inflate unique-view counts. The idempotency
    # contract is: first ``open`` wins, subsequent ones are a no-op
    # that still returns 200.
    if payload.event_type == "open":
        prior_open = await db[COLLECTION].find_one(
            {
                "tenant_id": tenant_id,
                "estimate_id": estimate_id,
                "session_id": payload.session_id,
                "event_type": "open",
            },
            {"_id": 0, "id": 1},
        )
        if prior_open:
            return {"status": "ok", "deduped": True,
                     "id": prior_open.get("id")}

    salt = await _get_or_create_tenant_salt(tenant_id)
    ip_hash = _hash_ip(_client_ip(request), salt)

    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "estimate_id": estimate_id,
        "session_id": payload.session_id,
        "event_type": payload.event_type,
        "page_index": (
            int(payload.page_index)
            if payload.page_index is not None else None
        ),
        "page_key": _truncate(payload.page_key, _PAGE_KEY_MAX_LEN),
        "button_id": _truncate(payload.button_id, _BUTTON_ID_MAX_LEN),
        "duration_ms": (
            max(0, min(int(payload.duration_ms), _DURATION_MS_MAX))
            if payload.duration_ms is not None else None
        ),
        "user_agent": _truncate(
            request.headers.get("user-agent") or "",
            _UA_MAX_LEN,
        ),
        "ip_hash": ip_hash,
        "referrer": _truncate(payload.referrer, _REFERRER_MAX_LEN),
        "created_at": now_iso(),
    }
    await db[COLLECTION].insert_one(doc)
    return {"status": "ok", "id": doc["id"]}


# ═════════════════════════════════════════════════════════════════════
# Admin — GET /analytics/proposal/{estimate_id}/summary
# ═════════════════════════════════════════════════════════════════════
def _require_admin(user: Dict[str, Any]) -> None:
    role = str((user or {}).get("role") or "")
    if role not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_only")


async def _rollup_for_estimate(tenant_id: str, estimate_id: str) -> Dict[str, Any]:
    """Aggregate stats for a single estimate. All counts + averages
    computed server-side so the dashboard fetches one small JSON
    blob per drill-down."""
    q = {"tenant_id": tenant_id, "estimate_id": estimate_id}
    total = await db[COLLECTION].count_documents(q)
    if total == 0:
        return {
            "estimate_id": estimate_id,
            "total_events": 0,
            "opens": 0,
            "unique_sessions": 0,
            "clicks": 0,
            "clicks_by_button": {},
            "avg_pages_viewed": 0.0,
            "avg_session_duration_ms": 0.0,
            "page_views_by_key": {},
            "last_event_at": None,
        }

    opens = await db[COLLECTION].count_documents(
        {**q, "event_type": "open"},
    )
    clicks = await db[COLLECTION].count_documents(
        {**q, "event_type": "click"},
    )
    unique_sessions = len(await db[COLLECTION].distinct("session_id", q))

    # Clicks by button.
    clicks_by_button: Dict[str, int] = {}
    async for row in db[COLLECTION].aggregate([
        {"$match": {**q, "event_type": "click",
                     "button_id": {"$ne": None}}},
        {"$group": {"_id": "$button_id", "n": {"$sum": 1}}},
    ]):
        clicks_by_button[str(row["_id"])] = int(row["n"])

    # Page views by key.
    page_views_by_key: Dict[str, int] = {}
    async for row in db[COLLECTION].aggregate([
        {"$match": {**q, "event_type": "page_view",
                     "page_key": {"$ne": None}}},
        {"$group": {"_id": "$page_key", "n": {"$sum": 1}}},
    ]):
        page_views_by_key[str(row["_id"])] = int(row["n"])

    # Avg pages viewed per session + avg session duration.
    pv_pipe = [
        {"$match": {**q, "event_type": "page_view"}},
        {"$group": {
            "_id": "$session_id",
            "pages": {"$sum": 1},
            "duration_ms": {"$sum": "$duration_ms"},
        }},
    ]
    per_session = [row async for row in db[COLLECTION].aggregate(pv_pipe)]
    if per_session:
        avg_pages = sum(r["pages"] for r in per_session) / len(per_session)
        avg_dur = sum((r.get("duration_ms") or 0)
                      for r in per_session) / len(per_session)
    else:
        avg_pages = 0.0
        avg_dur = 0.0

    last = await db[COLLECTION].find_one(
        q, {"_id": 0, "created_at": 1},
        sort=[("created_at", -1)],
    )

    return {
        "estimate_id": estimate_id,
        "total_events": total,
        "opens": opens,
        "unique_sessions": unique_sessions,
        "clicks": clicks,
        "clicks_by_button": clicks_by_button,
        "avg_pages_viewed": round(avg_pages, 2),
        "avg_session_duration_ms": round(avg_dur, 1),
        "page_views_by_key": page_views_by_key,
        "last_event_at": (last or {}).get("created_at"),
    }


@router.get("/analytics/proposal/{estimate_id}/summary")
async def summary_endpoint(
    estimate_id: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    # Cross-tenant guard.
    est = await db.quotes.find_one(
        {"id": estimate_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "title": 1, "estimate_number": 1,
          "customer_id": 1, "sent_at": 1, "status": 1},
    )
    if not est:
        raise HTTPException(404, "estimate_not_found")
    rollup = await _rollup_for_estimate(tenant["id"], estimate_id)
    rollup["estimate"] = est
    return rollup


# ═════════════════════════════════════════════════════════════════════
# Admin — GET /analytics/proposal/{estimate_id}/events
# ═════════════════════════════════════════════════════════════════════
@router.get("/analytics/proposal/{estimate_id}/events")
async def events_endpoint(
    estimate_id: str,
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    q = {"tenant_id": tenant["id"], "estimate_id": estimate_id}
    rows = await db[COLLECTION].find(
        q, {"_id": 0},
    ).sort("created_at", -1).limit(limit).to_list(limit)
    return {"events": rows, "count": len(rows)}


# ═════════════════════════════════════════════════════════════════════
# Admin — GET /analytics/proposals/overview
# ═════════════════════════════════════════════════════════════════════
_DATE_RANGE_MAP = {
    "7d": 7, "30d": 30, "90d": 90, "all": None,
}


@router.get("/analytics/proposals/overview")
async def overview_endpoint(
    date_range: str = Query("30d"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    days = _DATE_RANGE_MAP.get(date_range)
    if date_range not in _DATE_RANGE_MAP:
        raise HTTPException(422, "invalid_date_range")

    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if days is not None:
        cutoff = (datetime.now(timezone.utc)
                   - _timedelta_days(days)).isoformat()
        q["created_at"] = {"$gte": cutoff}

    # Distinct estimates that have received at least one event.
    est_ids = await db[COLLECTION].distinct("estimate_id", q)
    if not est_ids:
        return {"date_range": date_range, "estimates": []}

    # Bulk-fetch estimate metadata once, index by id for the join.
    est_meta = {}
    async for e in db.quotes.find(
        {"id": {"$in": est_ids}, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "title": 1, "estimate_number": 1,
          "customer_id": 1, "sent_at": 1, "status": 1,
          "flipbook_enabled": 1},
    ):
        est_meta[e["id"]] = e

    # Fan out rollups (parallel would be nice but Motor's cursor
    # semantics make a serial loop simpler + fast enough for ≤ few
    # hundred estimates per tenant).
    out: List[Dict[str, Any]] = []
    for eid in est_ids:
        rollup = await _rollup_for_estimate(tenant["id"], eid)
        rollup["estimate"] = est_meta.get(eid) or {"id": eid}
        out.append(rollup)

    # Sort newest last-event first so the dashboard shows recent
    # activity at the top.
    out.sort(key=lambda r: r.get("last_event_at") or "", reverse=True)
    return {"date_range": date_range, "estimates": out}


def _timedelta_days(n: int):
    from datetime import timedelta
    return timedelta(days=n)
