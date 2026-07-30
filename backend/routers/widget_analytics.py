"""MR3 · Feb-2026 — Public check-in widget analytics.

Endpoints
---------
* ``POST /api/public/widget/analytics/track``
    Public, no auth. Body: ``{widget_id, event_type, checkin_id?,
    session_id, referrer?}``. Rate-limited per (ip_hash, minute) at
    60/min. Returns 204.

* ``GET /api/widget/analytics/summary?range=7d|30d|90d``
    Tenant-scoped auth. Returns
    ``{range, impressions, clicks, ctr, top_checkins:[...]}``.

* ``GET /api/widget/analytics/timeseries?range=7d|30d|90d&granularity=day``
    Tenant-scoped auth. Daily buckets `[{date, impressions, clicks}]`.

Storage
-------
Events land in ``db.widget_analytics_events``:

    {tenant_id, widget_id, checkin_id?, event_type: impression|click,
     session_id, referrer, user_agent, ip_hash, ts}

``ip_hash = sha256((ip + tenant_id).encode()).hexdigest()`` — the raw
IP is never persisted anywhere.

Indexes are created lazily on first use:
    * ``(tenant_id, ts)`` for time-range scans.
    * ``(tenant_id, checkin_id, event_type)`` for top-checkins aggregation.
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user

router = APIRouter()

# ── Rate limit state (per-process, single-instance is fine) ─────────
_RATE_WINDOW_S = 60
_RATE_LIMIT = 60
_rate_buckets: Dict[str, Deque[float]] = defaultdict(deque)

# ── Range enum → timedelta helper ───────────────────────────────────
_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}

# ── Indexes are created once per process on first request ───────────
_indexes_ready = False


async def _ensure_indexes() -> None:
    """Idempotent index bootstrap. Called on the first request in each
    process; subsequent calls short-circuit on the module-level flag."""
    global _indexes_ready
    if _indexes_ready:
        return
    coll = db["widget_analytics_events"]
    await coll.create_index([("tenant_id", 1), ("ts", -1)])
    await coll.create_index([("tenant_id", 1), ("checkin_id", 1), ("event_type", 1)])
    _indexes_ready = True


# ── Helpers ─────────────────────────────────────────────────────────
def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip() or "?"
    return (request.client.host if request.client else "?")


def _ip_hash(raw_ip: str, tenant_id: str) -> str:
    """SHA-256 of (ip + tenant_id). Raw IPs never persisted."""
    return hashlib.sha256(f"{raw_ip}|{tenant_id}".encode("utf-8")).hexdigest()


def _rate_ok(bucket_key: str) -> bool:
    now = time.monotonic()
    q = _rate_buckets[bucket_key]
    while q and (now - q[0]) > _RATE_WINDOW_S:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        return False
    q.append(now)
    return True


async def _tenant_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    if not slug:
        return None
    return await db.tenants.find_one({"slug": slug}, {"_id": 0, "id": 1, "slug": 1, "name": 1})


def _range_window(range_str: str) -> datetime:
    days = _RANGE_DAYS.get(range_str)
    if days is None:
        raise HTTPException(status_code=400, detail="range must be 7d, 30d or 90d")
    return datetime.now(timezone.utc) - timedelta(days=days)


# ═══════════════════════ 1) Public track ═══════════════════════════
class TrackBody(BaseModel):
    widget_id: str = Field(..., min_length=1, max_length=64)
    event_type: str
    checkin_id: Optional[str] = None
    session_id: str = Field(..., min_length=6, max_length=64)
    referrer: Optional[str] = None


@router.options("/public/widget/analytics/track", include_in_schema=False)
async def track_options() -> Response:
    r = Response(status_code=204)
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "*"
    return r


@router.post("/public/widget/analytics/track",
              operation_id="widgetAnalytics.track",
              tags=["widget-analytics"])
async def track_event(body: TrackBody, request: Request) -> Response:
    """MR3 — record a widget impression/click event.

    Public, no auth. The widget_id is expected to be a tenant slug (the
    same value passed to <script data-tenant="..."> in the embed).
    Rows without a resolvable tenant are dropped silently (204) so a
    stale embed on a decommissioned tenant doesn't return errors.
    """
    if body.event_type not in ("impression", "click"):
        raise HTTPException(status_code=400, detail="event_type must be impression or click")

    tenant = await _tenant_by_slug(body.widget_id)
    if not tenant:
        # Silent 204 — decommissioned widget or misconfigured slug.
        return Response(status_code=204,
                        headers={"Access-Control-Allow-Origin": "*"})

    ip = _client_ip(request)
    ip_h = _ip_hash(ip, tenant["id"])

    # 60/min per (ip_hash) — very generous but blocks stuffing bots.
    if not _rate_ok(ip_h):
        return Response(status_code=204,
                        headers={"Access-Control-Allow-Origin": "*",
                                  "X-Widget-Analytics": "rate_limited"})

    await _ensure_indexes()
    doc: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "widget_id": body.widget_id,
        "checkin_id": body.checkin_id,
        "event_type": body.event_type,
        "session_id": body.session_id,
        "referrer": (body.referrer or "")[:512],
        "user_agent": (request.headers.get("user-agent") or "")[:256],
        "ip_hash": ip_h,
        "ts": datetime.now(timezone.utc),
    }
    await db.widget_analytics_events.insert_one(doc)
    return Response(status_code=204,
                    headers={"Access-Control-Allow-Origin": "*"})


# ═══════════════════════ 2) Admin summary ═══════════════════════════
@router.get("/widget/analytics/summary",
             operation_id="widgetAnalytics.summary",
             tags=["widget-analytics"])
async def analytics_summary(
    range: str = Query("7d"),
    caller: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    tenant_id = caller.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(status_code=403, detail="tenant scope required")
    await _ensure_indexes()
    since = _range_window(range)

    # Total impressions + clicks (single pipeline).
    totals_pipe = [
        {"$match": {"tenant_id": tenant_id, "ts": {"$gte": since}}},
        {"$group": {"_id": "$event_type", "n": {"$sum": 1}}},
    ]
    impressions, clicks = 0, 0
    async for row in db.widget_analytics_events.aggregate(totals_pipe):
        if row["_id"] == "impression":
            impressions = int(row["n"])
        elif row["_id"] == "click":
            clicks = int(row["n"])
    ctr = round((clicks / impressions), 4) if impressions else 0.0

    # Top 10 check-ins by clicks (with impressions + ctr).
    top_pipe: List[Dict[str, Any]] = [
        {"$match": {"tenant_id": tenant_id, "ts": {"$gte": since},
                    "checkin_id": {"$ne": None}}},
        {"$group": {"_id": {"checkin_id": "$checkin_id",
                             "event_type": "$event_type"},
                      "n": {"$sum": 1}}},
        {"$group": {"_id": "$_id.checkin_id",
                      "impressions": {
                          "$sum": {"$cond": [{"$eq": ["$_id.event_type", "impression"]},
                                              "$n", 0]}},
                      "clicks": {
                          "$sum": {"$cond": [{"$eq": ["$_id.event_type", "click"]},
                                              "$n", 0]}}}},
        {"$sort": {"clicks": -1, "impressions": -1}},
        {"$limit": 10},
    ]
    top_rows: List[Dict[str, Any]] = []
    async for row in db.widget_analytics_events.aggregate(top_pipe):
        top_rows.append({
            "checkin_id": row["_id"],
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
        })

    # Attach titles / service_name for the top check-ins.
    ids = [r["checkin_id"] for r in top_rows if r.get("checkin_id")]
    titles: Dict[str, str] = {}
    if ids:
        async for c in db.public_checkins.find(
                {"id": {"$in": ids}, "tenant_id": tenant_id},
                {"_id": 0, "id": 1, "service_name": 1, "title": 1}):
            titles[c["id"]] = (c.get("title") or c.get("service_name") or c["id"])
    for r in top_rows:
        r["title"] = titles.get(r["checkin_id"], r["checkin_id"])
        r["ctr"] = round((r["clicks"] / r["impressions"]), 4) if r["impressions"] else 0.0

    return {
        "range": range,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "top_checkins": top_rows,
    }


# ═══════════════════════ 3) Admin timeseries ════════════════════════
@router.get("/widget/analytics/timeseries",
             operation_id="widgetAnalytics.timeseries",
             tags=["widget-analytics"])
async def analytics_timeseries(
    range: str = Query("7d"),
    granularity: str = Query("day"),
    caller: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    tenant_id = caller.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(status_code=403, detail="tenant scope required")
    if granularity != "day":
        raise HTTPException(status_code=400, detail="only granularity=day is supported")
    await _ensure_indexes()

    since = _range_window(range)
    days = _RANGE_DAYS[range]

    pipe = [
        {"$match": {"tenant_id": tenant_id, "ts": {"$gte": since}}},
        {"$group": {"_id": {
            "d": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts",
                                      "timezone": "UTC"}},
            "event_type": "$event_type",
        }, "n": {"$sum": 1}}},
    ]
    buckets: Dict[str, Dict[str, int]] = {}
    async for row in db.widget_analytics_events.aggregate(pipe):
        date = row["_id"]["d"]
        ev = row["_id"]["event_type"]
        buckets.setdefault(date, {"impressions": 0, "clicks": 0})
        if ev == "impression":
            buckets[date]["impressions"] = int(row["n"])
        elif ev == "click":
            buckets[date]["clicks"] = int(row["n"])

    # Fill zero rows so the chart draws a continuous line.
    series: List[Dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()
    for i in range_(days):
        d = (today - timedelta(days=(days - 1 - i))).isoformat()
        b = buckets.get(d, {"impressions": 0, "clicks": 0})
        series.append({"date": d, "impressions": b["impressions"], "clicks": b["clicks"]})
    return {"range": range, "granularity": granularity, "series": series}


# Shadow of builtin `range` inside timeseries handler (kept because the
# query param is also called `range`).
def range_(n: int):  # pragma: no cover - trivial
    return range(n)
