"""Phase H6 · Feb-2026 — Monthly analytics rollup.

Single admin endpoint that aggregates four independent data
streams over a calendar month:

    1. Soshie moderation cost + decisions + cache-hit rate
       (``soshie_moderation_results``)
    2. Charge-template usage + revenue contribution
       (``charge_templates`` + ``jobs.charge_template_apply_count``)
    3. Drift-alert dispatches + clean heartbeats + worst day
       (``audit_events`` where ``event_type=data_integrity_digest``)
    4. Manual-post conversion rate — posts marked-posted ÷
       auto-approved manual-only drafts
       (``audit_events`` ``soshie_manual_mark_posted`` +
       ``soshie_moderation_results`` filtered to manual-only
       platforms via a join through ``ai_employee_actions``).

Non-goals (per H6 brief):
    * No auto-poll / real-time updates.
    * No previous-month comparison.
    * No per-customer PII exposure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin
from routers.tenants import get_current_tenant

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

router = APIRouter()

# Import the manual-only helper from H5.5 so the manual-conversion
# aggregation only counts platforms that H5.5 flipped to manual.
from services.soshie.autopilot_config import DEFAULT_CADENCE  # noqa: E402


_MANUAL_ONLY_PLATFORMS = [
    p for p, cfg in DEFAULT_CADENCE.items()
    if cfg.get("manual_only")
]


def _tenant_tz(tenant: Dict[str, Any]):
    tz_name = tenant.get("timezone") or "America/Phoenix"
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("America/Phoenix")


def _month_bounds(month: str, tenant: Dict[str, Any]) -> tuple[datetime, datetime]:
    """``month`` is ``YYYY-MM``. Returns half-open UTC bounds
    ``[start, end)`` covering the full calendar month in the
    tenant's local timezone. Legacy rows with ISO-string
    ``created_at`` compare cleanly against the ISO representation
    of these datetimes.
    """
    try:
        year, mo = month.split("-", 1)
        year_i = int(year)
        mo_i = int(mo)
        if not (1 <= mo_i <= 12):
            raise ValueError("month out of range")
    except (ValueError, AttributeError):
        raise HTTPException(
            400,
            {"detail": "invalid_month", "month": month,
             "hint": "format is YYYY-MM"},
        )
    tz = _tenant_tz(tenant)
    start_local = datetime(year_i, mo_i, 1, 0, 0, 0, tzinfo=tz)
    if mo_i == 12:
        end_local = datetime(year_i + 1, 1, 1, 0, 0, 0, tzinfo=tz)
    else:
        end_local = datetime(year_i, mo_i + 1, 1, 0, 0, 0, tzinfo=tz)
    return (start_local.astimezone(timezone.utc),
            end_local.astimezone(timezone.utc))


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ─── Soshie moderation rollup ─────────────────────────────────────
async def _soshie_moderation_rollup(
    tid: str, start_iso: str, end_iso: str,
) -> Dict[str, Any]:
    match = {"tenant_id": tid,
                "created_at": {"$gte": start_iso, "$lt": end_iso}}
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "calls_total": {"$sum": 1},
            "cost_estimate_usd": {"$sum": {"$ifNull": ["$cost_estimate_usd", 0]}},
            "cache_hits": {"$sum": {"$cond": [
                {"$eq": ["$from_cache", True]}, 1, 0,
            ]}},
            # Phase H7 · Feb-2026 — regex short-circuit counter.
            # Rows written by the ``regex-p1`` short-circuit
            # never spent a cent on the LLM. Surface the count
            # on the H6 dashboard so ops sees the savings.
            "regex_short_circuits": {"$sum": {"$cond": [
                {"$eq": ["$regex_short_circuit", True]}, 1, 0,
            ]}},
            "approve": {"$sum": {"$cond": [
                {"$eq": ["$decision", "approve"]}, 1, 0,
            ]}},
            "flag": {"$sum": {"$cond": [
                {"$eq": ["$decision", "flag"]}, 1, 0,
            ]}},
            "block": {"$sum": {"$cond": [
                {"$eq": ["$decision", "block"]}, 1, 0,
            ]}},
        }},
    ]
    rows = await db.soshie_moderation_results.aggregate(
        pipeline).to_list(1)
    r = rows[0] if rows else {"calls_total": 0, "cost_estimate_usd": 0,
                                  "cache_hits": 0,
                                  "regex_short_circuits": 0,
                                  "approve": 0,
                                  "flag": 0, "block": 0}
    total = int(r.get("calls_total") or 0)
    cost = float(r.get("cost_estimate_usd") or 0)
    return {
        "calls_total": total,
        "cost_estimate_usd": round(cost, 4),
        "decisions": {
            "approve": int(r.get("approve") or 0),
            "flag": int(r.get("flag") or 0),
            "block": int(r.get("block") or 0),
        },
        "cache_hit_rate": (
            round(int(r.get("cache_hits") or 0) / total, 4)
            if total else 0.0
        ),
        "avg_cost_per_call_usd": (
            round(cost / total, 6) if total else 0.0
        ),
        "regex_short_circuits": int(r.get("regex_short_circuits") or 0),
    }


async def _top_blocked_phrases(tid: str, start_iso: str, end_iso: str,
                                    ) -> List[Dict[str, Any]]:
    """Phase I2 · Feb-2026 — top 10 phrases that tripped the H7
    high-confidence regex short-circuit in the window."""
    pipe = [
        {"$match": {"tenant_id": tid,
                      "regex_short_circuit": True,
                      "created_at": {"$gte": start_iso, "$lt": end_iso}}},
        {"$unwind": "$regex_high_flags"},
        {"$group": {"_id": "$regex_high_flags.match",
                       "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    rows = await db.soshie_moderation_results.aggregate(pipe).to_list(10)
    return [{"phrase": (r.get("_id") or "")[:80],
                "count": int(r.get("count") or 0)}
              for r in rows if r.get("_id")]


# ─── Charge templates rollup ──────────────────────────────────────
async def _charge_templates_rollup(
    tid: str, start_iso: str, end_iso: str,
    prior_year_start_iso: Optional[str] = None,
    prior_year_end_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Templates: ``apply_count`` is a persistent counter, so we
    can't slice it by month. We use ``last_used_at`` as the
    "did this template contribute in the window" signal + fall
    back to per-line-item revenue via ``jobs.line_items.subtotal``
    filtered by ``jobs.charge_template_apply_count > 0`` and job
    ``updated_at`` in the month window.
    """
    tpls = await db.charge_templates.find(
        {"tenant_id": tid},
        {"_id": 0, "id": 1, "name": 1, "apply_count": 1,
         "created_at": 1, "last_used_at": 1},
    ).to_list(1000)
    total_templates = len(tpls)
    used_in_window = [
        t for t in tpls
        if t.get("last_used_at")
        and start_iso <= t.get("last_used_at") < end_iso
    ]
    total_applies = sum(int(t.get("apply_count") or 0)
                         for t in used_in_window)
    # Revenue contribution: sum ``line_items.subtotal`` on jobs
    # whose ``applied_from_template_id`` line-items point to
    # each top template, filtered to the month window on
    # ``jobs.updated_at``.
    top_sorted = sorted(
        used_in_window,
        key=lambda t: int(t.get("apply_count") or 0),
        reverse=True,
    )
    top_rows: List[Dict[str, Any]] = []
    for t in top_sorted[:3]:
        pipe = [
            {"$match": {"tenant_id": tid,
                          "updated_at": {"$gte": start_iso,
                                             "$lt": end_iso}}},
            {"$unwind": "$line_items"},
            {"$match": {
                "line_items.applied_from_template_id": t["id"],
            }},
            {"$group": {
                "_id": None,
                "revenue": {"$sum": {"$ifNull": [
                    "$line_items.subtotal", 0,
                ]}},
                "applies": {"$sum": 1},
            }},
        ]
        rows = await db.jobs.aggregate(pipe).to_list(1)
        rev = float(rows[0]["revenue"]) if rows else 0.0
        # Phase I2 · Feb-2026 — prior-year revenue for the same
        # template, same calendar month. Powers the YoY drop
        # badge; silently 0 when the caller doesn't request it
        # or when nothing was applied a year ago.
        prior_rev = 0.0
        if prior_year_start_iso and prior_year_end_iso:
            pipe_py = [
                {"$match": {"tenant_id": tid,
                              "updated_at": {"$gte": prior_year_start_iso,
                                                 "$lt": prior_year_end_iso}}},
                {"$unwind": "$line_items"},
                {"$match": {
                    "line_items.applied_from_template_id": t["id"],
                }},
                {"$group": {"_id": None, "revenue": {"$sum":
                    {"$ifNull": ["$line_items.subtotal", 0]}}}},
            ]
            py_rows = await db.jobs.aggregate(pipe_py).to_list(1)
            prior_rev = float(py_rows[0]["revenue"]) if py_rows else 0.0
        top_rows.append({
            "template_id": t["id"],
            "name": t.get("name") or "Unnamed",
            "apply_count": int(t.get("apply_count") or 0),
            "revenue_contribution_usd": round(rev, 2),
            "prior_year_revenue_usd": round(prior_rev, 2),
        })
    # Unused: templates whose ``last_used_at`` is missing OR older
    # than the window's start. Includes days_since_created.
    now = datetime.now(timezone.utc)
    unused: List[Dict[str, Any]] = []
    for t in tpls:
        lua = t.get("last_used_at")
        if not lua or lua < start_iso:
            created = t.get("created_at") or ""
            try:
                s = created[:-1] + "+00:00" if created.endswith(
                    "Z") else created
                cdt = datetime.fromisoformat(s) if s else now
                if cdt.tzinfo is None:
                    cdt = cdt.replace(tzinfo=timezone.utc)
                days = max(0, (now - cdt).days)
            except (ValueError, TypeError):
                days = 0
            unused.append({
                "template_id": t["id"],
                "name": t.get("name") or "Unnamed",
                "days_since_created": days,
            })
    unused.sort(key=lambda r: -r["days_since_created"])
    return {
        "total_templates": total_templates,
        "total_applies": total_applies,
        "top_templates": top_rows,
        "unused_templates": unused[:10],
    }


# ─── Drift alerts rollup ──────────────────────────────────────────
async def _drift_alerts_rollup(
    tid: str, start_iso: str, end_iso: str,
) -> Dict[str, Any]:
    pipe = [
        {"$match": {
            "tenant_id": tid,
            "event_type": "data_integrity_digest",
            "timestamp": {"$gte": start_iso, "$lt": end_iso},
        }},
        {"$project": {
            "dispatched": "$payload.dispatched",
            "dangling_refs_total": "$payload.dangling_refs_total",
            "date": "$payload.date",
        }},
    ]
    rows = await db.audit_events.aggregate(pipe).to_list(1000)
    total = len(rows)
    dispatched = sum(1 for r in rows if r.get("dispatched"))
    with_drift = [r for r in rows
                     if (r.get("dangling_refs_total") or 0) > 0]
    worst = None
    for r in with_drift:
        d = int(r.get("dangling_refs_total") or 0)
        if worst is None or d > worst.get("dangling_refs_total", 0):
            worst = {"date": r.get("date"),
                        "dangling_refs_total": d}
    return {
        "dispatches_total": dispatched,
        "clean_heartbeats": total - len(with_drift),
        "dispatch_success_rate": (
            round(dispatched / total, 4) if total else 0.0
        ),
        "days_with_drift": len(with_drift),
        "worst_day": worst,
    }


# ─── Manual-post conversion rollup ────────────────────────────────
async def _manual_conversion_rollup(
    tid: str, start_iso: str, end_iso: str,
) -> Dict[str, Any]:
    """Posts marked-posted (``audit_events.soshie_manual_mark_posted``)
    over ``ai_employee_actions.status=awaiting_manual`` generated in
    the same window. Both keyed by platform via
    ``manual_only_platform``.

    Generated total: rows in ``ai_employee_actions`` where
    ``manual_only_platform`` is set AND ``manual_ready_at`` OR
    ``created_at`` falls in the window.
    """
    gen_pipe = [
        {"$match": {
            "tenant_id": tid,
            "manual_only_platform": {"$in": _MANUAL_ONLY_PLATFORMS},
            "$or": [
                {"manual_ready_at": {"$gte": start_iso,
                                            "$lt": end_iso}},
                {"$and": [
                    {"manual_ready_at": {"$exists": False}},
                    {"created_at": {"$gte": start_iso,
                                        "$lt": end_iso}},
                ]},
            ],
        }},
        {"$group": {"_id": "$manual_only_platform",
                       "count": {"$sum": 1}}},
    ]
    gen_rows = await db.ai_employee_actions.aggregate(
        gen_pipe).to_list(50)
    gen_by = {r["_id"]: int(r["count"]) for r in gen_rows}
    # Marked-posted: audit events in the window.
    posted_pipe = [
        {"$match": {
            "tenant_id": tid,
            "event_type": "soshie_manual_mark_posted",
            "timestamp": {"$gte": start_iso, "$lt": end_iso},
        }},
        {"$group": {"_id": "$payload.platform",
                       "count": {"$sum": 1}}},
    ]
    posted_rows = await db.audit_events.aggregate(
        posted_pipe).to_list(50)
    posted_by = {r["_id"]: int(r["count"]) for r in posted_rows}
    platforms = sorted(
        set(gen_by.keys()) | set(posted_by.keys()) |
        set(_MANUAL_ONLY_PLATFORMS),
    )
    by_platform: List[Dict[str, Any]] = []
    total_gen = 0
    total_post = 0
    for p in platforms:
        g = gen_by.get(p, 0)
        m = posted_by.get(p, 0)
        total_gen += g
        total_post += m
        # Only include rows with any activity so the UI stays
        # focused on movers; downstream frontend can still render
        # the aggregate.
        if g == 0 and m == 0:
            continue
        by_platform.append({
            "platform": p,
            "generated": g,
            "marked_posted": m,
            "conversion_rate": (
                round(m / g, 4) if g else 0.0
            ),
        })
    by_platform.sort(key=lambda r: -r["conversion_rate"])
    return {
        "posts_generated_total": total_gen,
        "posts_marked_posted_total": total_post,
        "conversion_rate": (
            round(total_post / total_gen, 4) if total_gen else 0.0
        ),
        "by_platform": by_platform,
    }


# ─── Endpoint ─────────────────────────────────────────────────────
@router.get("/admin/analytics/monthly")
async def analytics_monthly(
    month: Optional[str] = Query(
        None,
        description=(
            "``YYYY-MM``. Default: current month in the tenant's "
            "timezone. Unknown/invalid values 400."
        ),
    ),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    """Phase H6 · Feb-2026 — Four-stream monthly rollup for the
    admin analytics dashboard."""
    if not month:
        tz = _tenant_tz(tenant)
        month = datetime.now(tz).strftime("%Y-%m")
    start, end = _month_bounds(month, tenant)
    start_iso = _iso(start)
    end_iso = _iso(end)
    # Phase I2 · Feb-2026 — prior-year bounds for the H6 YoY badge.
    try:
        py_year, py_mo = month.split("-", 1)
        py_month = f"{int(py_year) - 1:04d}-{py_mo}"
        py_start, py_end = _month_bounds(py_month, tenant)
        py_start_iso = _iso(py_start)
        py_end_iso = _iso(py_end)
    except Exception:  # noqa: BLE001
        py_start_iso = None
        py_end_iso = None
    tid = tenant["id"]
    soshie = await _soshie_moderation_rollup(tid, start_iso, end_iso)
    # Attach the Phase I2 top-blocked-phrases table.
    soshie["top_blocked_phrases"] = await _top_blocked_phrases(
        tid, start_iso, end_iso,
    )
    templates = await _charge_templates_rollup(
        tid, start_iso, end_iso,
        prior_year_start_iso=py_start_iso,
        prior_year_end_iso=py_end_iso,
    )
    drift = await _drift_alerts_rollup(tid, start_iso, end_iso)
    manual = await _manual_conversion_rollup(tid, start_iso, end_iso)
    return {
        "tenant_id": tid,
        "month": month,
        "month_start": start_iso,
        "month_end": end_iso,
        "soshie_moderation": soshie,
        "charge_templates": templates,
        "drift_alerts": drift,
        "soshie_manual_conversion": manual,
    }
