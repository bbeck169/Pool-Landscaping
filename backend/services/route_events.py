"""Phase 10 · Feb-2026 — Sub-item F: Route optimize / insert event log.

Append-only event log written by Phase 3 (`POST /dispatch/route/apply`)
and Phase 4 (`POST /dispatch/route/insert`) on success, plus the weekly
savings aggregator that powers the Dispatch Board KPI strip.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(d: date) -> str:
    return d.isoformat()


async def log_event(*, tenant_id: str, kind: str, tech_user_id: str,
                       route_date: str, savings_km: float,
                       stop_count: int, added_distance_km: Optional[float] = None,
                       executed_by: str = "") -> None:
    """Fire-and-forget log. Failures never bubble up — the caller has
    already committed the optimize/insert."""
    try:
        doc = {"tenant_id": tenant_id,
                "event_id": f"rte_{uuid.uuid4().hex[:16]}",
                "kind": kind, "tech_user_id": tech_user_id,
                "route_date": route_date,
                "savings_km": round(float(savings_km or 0.0), 3),
                "stop_count": int(stop_count or 0),
                "executed_at": _now(), "executed_by": executed_by or ""}
        if added_distance_km is not None:
            doc["added_distance_km"] = round(float(added_distance_km), 3)
        await db.route_optimize_events.insert_one(doc)
    except Exception:
        pass


def _range_bounds(range_: str) -> (date, date):
    today = datetime.now(timezone.utc).date()
    if range_ == "30d":
        return today - timedelta(days=29), today
    return today - timedelta(days=6), today  # default 7d


async def weekly_summary(*, tenant_id: str, range_: str = "7d",
                            top_n: int = 5) -> Dict[str, Any]:
    period_start, period_end = _range_bounds(range_)
    lo = period_start.isoformat() + "T00:00:00+00:00"
    hi = period_end.isoformat() + "T23:59:59+00:00"

    total_savings = 0.0
    opt_events = 0; ins_events = 0
    per_day_map: Dict[str, Dict[str, float]] = {}
    per_tech: Dict[str, Dict[str, Any]] = {}
    tech_ids: List[str] = []
    async for e in db.route_optimize_events.find(
            {"tenant_id": tenant_id, "executed_at": {"$gte": lo, "$lte": hi}},
            {"_id": 0}):
        s = float(e.get("savings_km") or 0.0)
        total_savings += s
        if e.get("kind") == "insert":
            ins_events += 1
        else:
            opt_events += 1
        day_bucket = (e.get("executed_at") or "")[:10]
        d = per_day_map.setdefault(day_bucket, {"savings_km": 0.0, "event_count": 0})
        d["savings_km"] += s; d["event_count"] += 1
        tid = e.get("tech_user_id") or ""
        t = per_tech.setdefault(tid, {"tech_user_id": tid,
                                          "savings_km": 0.0, "event_count": 0})
        t["savings_km"] += s; t["event_count"] += 1
        if tid and tid not in tech_ids:
            tech_ids.append(tid)

    # Backfill per-day zeros to render a clean sparkline.
    per_day: List[Dict[str, Any]] = []
    cursor_d = period_start
    while cursor_d <= period_end:
        k = cursor_d.isoformat()
        row = per_day_map.get(k) or {"savings_km": 0.0, "event_count": 0}
        per_day.append({"date": k,
                          "savings_km": round(row["savings_km"], 3),
                          "event_count": int(row["event_count"])})
        cursor_d += timedelta(days=1)

    # Resolve tech names.
    name_map: Dict[str, str] = {}
    if tech_ids:
        async for u in db.users.find(
                {"tenant_id": tenant_id, "id": {"$in": tech_ids}},
                {"_id": 0, "id": 1, "name": 1, "full_name": 1, "email": 1}):
            name_map[u["id"]] = (u.get("full_name") or u.get("name")
                                    or (u.get("email") or "").split("@")[0]
                                    or u["id"])
    top_techs = sorted(per_tech.values(),
                          key=lambda x: x["savings_km"], reverse=True)[:int(top_n)]
    for t in top_techs:
        t["name"] = name_map.get(t["tech_user_id"], t["tech_user_id"])
        t["savings_km"] = round(t["savings_km"], 3)

    return {"range": range_ if range_ in ("7d", "30d") else "7d",
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "total_savings_km": round(total_savings, 3),
            "total_optimize_events": opt_events,
            "total_insert_events": ins_events,
            "per_day": per_day, "top_techs": top_techs}
