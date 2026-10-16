"""P0-GEOCODE-LEAK-C2 · TD-62 (Feb-2026).

Admin-only diagnostics endpoint exposing a 7-day (default) rollup of
``db.geocode_call_log``:

  * ``GET /admin/diagnostics/geocode-usage?days=<1-90>``

Super-admins see all tenants; regular admins see their own tenant.
All aggregations run on the server via Mongo ``$match`` + ``$group``
+ ``$sort`` + ``$limit`` so a 90-day window is tractable.  The
response powers the Phase 3 fix decisions by giving the operator
ground truth on:

  * ``by_trigger_reason`` — which call-site paths dominate the spend.
  * ``by_outcome``        — hit vs skipped_cached vs error ratios.
  * ``top_10_addresses_by_count`` — pathologically-hot addresses to
    sentinel-guard.
  * ``backend_vs_user_percent_split`` — operator-visible spend split
    (BACKEND = ``{boot_sweep, admin_backfill, csv_import, manual_regeocode}``;
    USER = everything else).

Deferred FE wire-up to C4; the C2 endpoint is callable from
``curl`` / Postman today.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from utils import require_admin
from config import db
from services.google_maps.geocode_trigger import is_backend_trigger


router = APIRouter()


_MAX_DAYS = 90
_DEFAULT_DAYS = 7
_TOP_N_ADDRESSES = 10


def _tenant_match_clause(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a Mongo ``$match`` sub-clause scoping the aggregation
    to the caller's tenant.  Super-admins see all tenants and
    receive ``None`` (no scoping)."""
    role = (user or {}).get("role") or ""
    if role == "super_admin":
        return None
    tid = (user or {}).get("tenant_id")
    if not tid:
        # Non-super-admin WITHOUT tenant_id → return a match that
        # yields zero rows so we never leak cross-tenant data.
        return {"tenant_id": "__no_tenant__"}
    return {"tenant_id": tid}


@router.get("/admin/diagnostics/geocode-usage")
async def geocode_usage_rollup(
    days: int = Query(_DEFAULT_DAYS, ge=1, le=_MAX_DAYS),
    user: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Return a rollup of ``db.geocode_call_log`` across the last
    ``days`` days (default 7, max 90).  Admin-gated + tenant-scoped
    (super-admins see all tenants)."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    match_stage: Dict[str, Any] = {"called_at": {"$gte": window_start}}
    scope = _tenant_match_clause(user)
    if scope:
        match_stage.update(scope)

    # ─── Total + unique counts ─────────────────────────────────
    total_calls = await db.geocode_call_log.count_documents(match_stage)
    distinct_addrs = await db.geocode_call_log.distinct(
        "address_hash", match_stage,
    )
    unique_addresses = len([h for h in distinct_addrs if h])

    # ─── by_trigger_reason ─────────────────────────────────────
    by_trigger: Dict[str, int] = {}
    async for row in db.geocode_call_log.aggregate([
        {"$match": match_stage},
        {"$group": {"_id": "$trigger_reason", "n": {"$sum": 1}}},
    ]):
        key = row.get("_id") or "unknown"
        by_trigger[key] = int(row.get("n") or 0)

    # ─── by_outcome ────────────────────────────────────────────
    by_outcome: Dict[str, int] = {}
    async for row in db.geocode_call_log.aggregate([
        {"$match": match_stage},
        {"$group": {"_id": "$outcome", "n": {"$sum": 1}}},
    ]):
        key = row.get("_id") or "unknown"
        by_outcome[key] = int(row.get("n") or 0)

    # ─── Top 10 addresses by count + their dominant trigger ────
    top_pipeline: List[Dict[str, Any]] = [
        {"$match": {**match_stage, "address_hash": {"$ne": ""}}},
        {"$group": {
            "_id": "$address_hash",
            "count": {"$sum": 1},
            "sample_address": {"$first": "$address"},
            "triggers": {"$push": "$trigger_reason"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": _TOP_N_ADDRESSES},
    ]
    top_10: List[Dict[str, Any]] = []
    async for row in db.geocode_call_log.aggregate(top_pipeline):
        triggers = row.get("triggers") or []
        top_trigger = None
        if triggers:
            counts: Dict[str, int] = {}
            for t in triggers:
                counts[t] = counts.get(t, 0) + 1
            top_trigger = max(counts.items(), key=lambda kv: kv[1])[0]
        top_10.append({
            "address": row.get("sample_address") or "",
            "address_hash": row.get("_id") or "",
            "count": int(row.get("count") or 0),
            "top_trigger_reason": top_trigger or "unknown",
        })

    # ─── BACKEND vs USER percent split ─────────────────────────
    backend_n = 0
    user_n = 0
    for trig, n in by_trigger.items():
        if is_backend_trigger(trig):
            backend_n += n
        else:
            user_n += n
    denom = backend_n + user_n or 1
    backend_pct = round(100.0 * backend_n / denom, 2)
    user_pct = round(100.0 * user_n / denom, 2)

    return {
        "window_days": days,
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "total_calls": total_calls,
        "unique_addresses": unique_addresses,
        "by_trigger_reason": by_trigger,
        "by_outcome": by_outcome,
        "top_10_addresses_by_count": top_10,
        "backend_vs_user_percent_split": {
            "backend_pct": backend_pct,
            "user_pct": user_pct,
            "backend_n": backend_n,
            "user_n": user_n,
        },
        "generated_at": now.isoformat(),
        "tenant_scoped": scope is not None,
    }
