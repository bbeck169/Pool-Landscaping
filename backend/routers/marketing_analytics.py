"""Feb-2026 · Marketing Slice M7 — Campaign / Sequence / Review-Request
analytics.

Read-only across every marketing collection.  Nothing here writes.
Aggregations are computed on the fly and cached in-process for 5
minutes per (tenant_id, endpoint, args) tuple to blunt dashboard
refresh storms.  Cache is a simple dict — a real system would swap
this for Redis; the codebase target is small enough today.

Windows (7d / 30d / 90d / all) are applied on ``sent_at`` for
deliveries and ``requested_at`` for review requests, and on
``created_at`` / ``enrolled_at`` for enrolments.  Any missing engagement
event (opened / clicked / replied) surfaces as ``0`` rather than
crashing — real events plug in whenever live providers land.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin
from routers.tenants import get_current_tenant

router = APIRouter(prefix="/marketing/analytics")

_CACHE_TTL_SECONDS = 300
_CACHE: Dict[Tuple, Tuple[float, Any]] = {}


def _window_since(window: str) -> Optional[datetime]:
    now = datetime.now(timezone.utc)
    return {
        "7d":  now - timedelta(days=7),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
        "all": None,
    }.get(window, now - timedelta(days=30))


def _cached(key: Tuple, compute):
    """5-minute per-key cache.  ``compute`` is an ``async`` no-arg
    callable returning the computed payload."""
    async def inner():
        now = time.time()
        hit = _CACHE.get(key)
        if hit and (now - hit[0]) < _CACHE_TTL_SECONDS:
            payload = dict(hit[1])
            payload["_cache"] = "hit"
            return payload
        result = await compute()
        _CACHE[key] = (now, result)
        payload = dict(result)
        payload["_cache"] = "miss"
        return payload
    return inner


def _pct(numerator: int, denominator: int) -> Optional[float]:
    return round(100.0 * numerator / denominator, 1) if denominator else None


# ═══════════════════════════════════════════════════════════════════════
# Overview
# ═══════════════════════════════════════════════════════════════════════
@router.get("/overview")
async def get_overview(
    window: str = Query("30d"),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if window not in ("7d", "30d", "90d", "all"):
        raise HTTPException(422, "window must be 7d|30d|90d|all")

    async def _compute():
        return await _compute_overview(tenant["id"], window)

    return await _cached(("overview", tenant["id"], window), _compute)()


async def _compute_overview(tenant_id: str, window: str) -> Dict[str, Any]:
    since = _window_since(window)
    since_iso = since.isoformat() if since else None

    # ── Campaigns rollup ───────────────────────────────────────────
    camp_q: Dict[str, Any] = {"tenant_id": tenant_id}
    if since_iso:
        camp_q["created_at"] = {"$gte": since_iso}
    camp_agg = {
        "total_sent": 0, "active": 0, "delivered": 0,
        "opened": 0, "clicked": 0, "converted": 0,
    }
    async for c in db.marketing_campaigns.find(camp_q, {"_id": 0}):
        camp_agg["total_sent"] += 1
        if c.get("status") in ("running", "scheduled", "sending"):
            camp_agg["active"] += 1
        stats = c.get("stats") or {}
        for k in ("delivered", "opened", "clicked", "converted"):
            camp_agg[k] += int(stats.get(k) or 0)

    # ── Sequences rollup ───────────────────────────────────────────
    enrol_q: Dict[str, Any] = {"tenant_id": tenant_id}
    if since_iso:
        enrol_q["enrolled_at"] = {"$gte": since_iso}
    total_enr = active_enr = completed_enr = halted_enr = 0
    completion_durations_hours: List[float] = []
    async for e in db.marketing_drip_enrolments.find(enrol_q, {"_id": 0}):
        total_enr += 1
        status = e.get("status")
        if status == "active":       active_enr += 1
        elif status == "completed":  completed_enr += 1
        elif status == "halted":     halted_enr += 1
        # Rough completion time: last history send - enrolled_at
        if status == "completed":
            hist = e.get("history") or []
            if hist:
                try:
                    ended = datetime.fromisoformat(hist[-1]["sent_at"])
                    started = datetime.fromisoformat(e["enrolled_at"])
                    completion_durations_hours.append(
                        (ended - started).total_seconds() / 3600.0,
                    )
                except Exception:
                    pass
    avg_completion = None
    if completion_durations_hours:
        avg_completion = round(
            sum(completion_durations_hours) / len(completion_durations_hours), 2,
        )
    seq_agg = {
        "total_enrolments": total_enr, "active": active_enr,
        "completed": completed_enr, "halted": halted_enr,
        "avg_completion_hours": avg_completion,
    }

    # ── Review requests funnel ─────────────────────────────────────
    rr_q: Dict[str, Any] = {"tenant_id": tenant_id}
    if since_iso:
        rr_q["requested_at"] = {"$gte": since_iso}
    rr_agg = {"queued": 0, "sent": 0, "opened": 0, "reviewed": 0,
              "expired": 0, "failed": 0, "total": 0}
    ratings: List[int] = []
    async for r in db.marketing_review_requests.find(rr_q, {"_id": 0}):
        rr_agg["total"] += 1
        s = r.get("status") or "queued"
        rr_agg[s] = rr_agg.get(s, 0) + 1
        if r.get("review_rating"):
            ratings.append(int(r["review_rating"]))
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    rr_summary = {
        "queued": rr_agg["queued"],
        "sent": rr_agg["sent"],
        "opened": rr_agg["opened"],
        "reviewed": rr_agg["reviewed"],
        "expired": rr_agg["expired"],
        "failed": rr_agg["failed"],
        "total": rr_agg["total"],
        "avg_rating": avg_rating,
        "review_rate_pct": _pct(rr_agg["reviewed"], rr_agg["total"]),
    }

    # ── Top sequences (by enrolment volume) ────────────────────────
    top_sequences = await _top_sequences(tenant_id, since_iso)
    top_campaigns = await _top_campaigns(tenant_id, since_iso)

    # ── Daily trend (last N days) — deliveries + opens (via review
    # requests + drip enrolments' history + campaign stats.opens by
    # day if the campaign engine records it; falls back to deliveries
    # only when opens aren't tracked yet).
    trend = await _daily_trend(tenant_id, window)

    return {
        "window": window,
        "campaigns": camp_agg,
        "sequences": seq_agg,
        "review_requests": rr_summary,
        "top_sequences": top_sequences,
        "top_campaigns": top_campaigns,
        "trend": trend,
    }


async def _top_sequences(tenant_id: str, since_iso: Optional[str]) -> List[Dict[str, Any]]:
    """Top 5 sequences by enrolment count within the window."""
    match: Dict[str, Any] = {"tenant_id": tenant_id}
    if since_iso:
        match["enrolled_at"] = {"$gte": since_iso}
    pipe = [
        {"$match": match},
        {"$group": {
            "_id": "$sequence_id",
            "enrolments": {"$sum": 1},
            "completed": {
                "$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]},
            },
        }},
        {"$sort": {"enrolments": -1}},
        {"$limit": 5},
    ]
    rows = await db.marketing_drip_enrolments.aggregate(pipe).to_list(5)
    if not rows:
        return []
    ids = [r["_id"] for r in rows]
    name_map: Dict[str, str] = {}
    async for s in db.marketing_sequences.find(
        {"id": {"$in": ids}, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1},
    ):
        name_map[s["id"]] = s["name"]
    return [{
        "id": r["_id"],
        "name": name_map.get(r["_id"], "(deleted)"),
        "enrolments": r["enrolments"],
        "completion_rate": _pct(r["completed"], r["enrolments"]),
    } for r in rows]


async def _top_campaigns(tenant_id: str, since_iso: Optional[str]) -> List[Dict[str, Any]]:
    """Top 5 campaigns by delivered count within the window."""
    match: Dict[str, Any] = {"tenant_id": tenant_id}
    if since_iso:
        match["created_at"] = {"$gte": since_iso}
    rows: List[Dict[str, Any]] = []
    async for c in db.marketing_campaigns.find(match, {"_id": 0}):
        stats = c.get("stats") or {}
        delivered = int(stats.get("delivered") or 0)
        opened = int(stats.get("opened") or 0)
        rows.append({
            "id": c["id"],
            "name": c.get("name") or "(untitled)",
            "delivered": delivered,
            "opened": opened,
            "open_rate_pct": _pct(opened, delivered),
        })
    rows.sort(key=lambda r: r["delivered"], reverse=True)
    return rows[:5]


async def _daily_trend(tenant_id: str, window: str) -> List[Dict[str, Any]]:
    """Simple day-by-day rollup of deliveries + review request outcomes."""
    days = {"7d": 7, "30d": 30, "90d": 90, "all": 30}[window]
    now = datetime.now(timezone.utc)
    days_index = [(now.date() - timedelta(days=i)).isoformat()
                    for i in range(days)]
    days_index.reverse()
    # Deliveries by day (marketing_deliveries.sent_at).
    since_iso = (now - timedelta(days=days)).isoformat()
    delivery_by_day: Dict[str, int] = {d: 0 for d in days_index}
    async for d in db.marketing_deliveries.find(
        {"tenant_id": tenant_id, "sent_at": {"$gte": since_iso}},
        {"_id": 0, "sent_at": 1},
    ):
        d_day = str(d.get("sent_at") or "")[:10]
        if d_day in delivery_by_day:
            delivery_by_day[d_day] += 1
    # Conversions per day = review_requests flipped to ``reviewed``.
    conversion_by_day: Dict[str, int] = {d: 0 for d in days_index}
    async for r in db.marketing_review_requests.find(
        {"tenant_id": tenant_id, "status": "reviewed",
         "reviewed_at": {"$gte": since_iso}},
        {"_id": 0, "reviewed_at": 1},
    ):
        d_day = str(r.get("reviewed_at") or "")[:10]
        if d_day in conversion_by_day:
            conversion_by_day[d_day] += 1
    # Opens per day: review request opened_at (proxy — real open
    # events wire in cleanly when live provider events land).
    opens_by_day: Dict[str, int] = {d: 0 for d in days_index}
    async for r in db.marketing_review_requests.find(
        {"tenant_id": tenant_id, "opened_at": {"$gte": since_iso}},
        {"_id": 0, "opened_at": 1},
    ):
        d_day = str(r.get("opened_at") or "")[:10]
        if d_day in opens_by_day:
            opens_by_day[d_day] += 1
    return [{
        "date": d,
        "deliveries": delivery_by_day[d],
        "opens": opens_by_day[d],
        "conversions": conversion_by_day[d],
    } for d in days_index]


# ═══════════════════════════════════════════════════════════════════════
# Per-campaign
# ═══════════════════════════════════════════════════════════════════════
@router.get("/campaigns/{campaign_id}")
async def get_campaign_analytics(
    campaign_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    c = await db.marketing_campaigns.find_one(
        {"id": campaign_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not c:
        raise HTTPException(404, "Campaign not found")
    stats = c.get("stats") or {}
    delivered = int(stats.get("delivered") or 0)
    opened = int(stats.get("opened") or 0)
    clicked = int(stats.get("clicked") or 0)
    replied = int(stats.get("replied") or 0)
    unsubbed = int(stats.get("unsubscribed") or 0)
    converted = int(stats.get("converted") or 0)
    return {
        "id": c["id"], "name": c.get("name"),
        "channel": c.get("channel"),
        "status": c.get("status"),
        "created_at": c.get("created_at"),
        "counts": {
            "delivered": delivered, "opened": opened, "clicked": clicked,
            "replied": replied, "unsubscribed": unsubbed, "converted": converted,
        },
        "rates": {
            "open_rate_pct": _pct(opened, delivered),
            "click_rate_pct": _pct(clicked, delivered),
            "reply_rate_pct": _pct(replied, delivered),
            "unsubscribe_rate_pct": _pct(unsubbed, delivered),
            "conversion_rate_pct": _pct(converted, delivered),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# Per-sequence
# ═══════════════════════════════════════════════════════════════════════
@router.get("/sequences/{sequence_id}")
async def get_sequence_analytics(
    sequence_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    seq = await db.marketing_sequences.find_one(
        {"id": sequence_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not seq:
        raise HTTPException(404, "Sequence not found")
    steps = seq.get("steps") or []
    step_reached = [0] * (len(steps) + 1)   # +1 for "completed all"
    active = completed = halted = 0
    async for e in db.marketing_drip_enrolments.find(
        {"sequence_id": sequence_id, "tenant_id": tenant["id"]},
        {"_id": 0, "status": 1, "current_step": 1, "history": 1},
    ):
        status = e.get("status")
        if status == "active":       active += 1
        elif status == "completed":  completed += 1
        elif status == "halted":     halted += 1
        # ``current_step`` points to the NEXT step index — so
        # ``history`` length = fired step count.
        fired = len(e.get("history") or [])
        for i in range(min(fired + 1, len(step_reached))):
            step_reached[i] += 1
    total = active + completed + halted
    funnel = [{
        "step_index": i,
        "reached": step_reached[i],
        "rate_from_start_pct": _pct(step_reached[i], step_reached[0] or 1)
                                if step_reached[0] else None,
    } for i in range(len(step_reached))]
    return {
        "id": seq["id"], "name": seq["name"],
        "trigger_type": seq.get("trigger_type"),
        "step_count": len(steps),
        "counts": {"total": total, "active": active,
                    "completed": completed, "halted": halted},
        "funnel": funnel,
    }


# ═══════════════════════════════════════════════════════════════════════
# Review-request funnel
# ═══════════════════════════════════════════════════════════════════════
@router.get("/review-requests")
async def get_review_request_analytics(
    window: str = Query("30d"),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if window not in ("7d", "30d", "90d", "all"):
        raise HTTPException(422, "window must be 7d|30d|90d|all")
    since = _window_since(window)
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if since:
        q["requested_at"] = {"$gte": since.isoformat()}
    counts = {"queued": 0, "sent": 0, "opened": 0,
              "reviewed": 0, "expired": 0, "failed": 0}
    ratings: List[int] = []
    async for r in db.marketing_review_requests.find(q, {"_id": 0}):
        s = r.get("status") or "queued"
        counts[s] = counts.get(s, 0) + 1
        if r.get("review_rating"):
            ratings.append(int(r["review_rating"]))
    total = sum(counts.values())
    # Funnel: queued(all) → sent(sent+opened+reviewed+expired) →
    # opened(opened+reviewed) → reviewed(reviewed).
    reached_sent   = counts["sent"] + counts["opened"] + counts["reviewed"] + counts["expired"]
    reached_opened = counts["opened"] + counts["reviewed"]
    reached_rev    = counts["reviewed"]
    return {
        "window": window,
        "counts": counts,
        "total": total,
        "funnel": [
            {"stage": "queued",   "count": total,          "rate_pct": _pct(total, total)},
            {"stage": "sent",     "count": reached_sent,   "rate_pct": _pct(reached_sent,   total)},
            {"stage": "opened",   "count": reached_opened, "rate_pct": _pct(reached_opened, total)},
            {"stage": "reviewed", "count": reached_rev,    "rate_pct": _pct(reached_rev,    total)},
        ],
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "review_rate_pct": _pct(reached_rev, total),
    }


# ═══════════════════════════════════════════════════════════════════════
# Testing hook — clears the in-process cache
# ═══════════════════════════════════════════════════════════════════════
@router.post("/_cache/clear")
async def clear_analytics_cache(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Admin-only.  Clears every cached rollup for THIS tenant.  Meant
    for test hygiene and dashboard "refresh" buttons — never called on
    a hot path."""
    global _CACHE
    _CACHE = {k: v for k, v in _CACHE.items() if k[1] != tenant["id"]}
    return {"ok": True, "remaining_entries": len(_CACHE)}


def _clear_cache_for_tests() -> None:  # pragma: no cover — used from tests
    _CACHE.clear()
