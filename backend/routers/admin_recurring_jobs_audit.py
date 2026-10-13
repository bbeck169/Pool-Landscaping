"""P0 · Feb-2026 — Read-only recurring-jobs cadence audit endpoint.

Serves ``GET /api/admin/diagnostics/recurring-jobs-audit?date=YYYY-MM-DD``
— a read-only snapshot that lets an admin operator diagnose the
"active Tuesday templates but no jobs on the schedule" symptom
against the live DB without needing shell / mongosh access.

The endpoint:
  * Counts jobs on the target date (template-origin, both
    including and excluding soft-deleted; plus any-origin).
  * Counts active weekly templates under BOTH day-of-week
    conventions (Python ``weekday()`` Mon=0, and JS ``getDay()``
    Sun=0) so a convention mismatch between a writer and the
    materializer is instantly visible in the response.
  * Returns the ``last_generated_through`` cursor distribution
    under each convention.
  * Includes a per-template sample (first 20) that joins
    recently-generated job dates so Tue-vs-Wed landing is
    visible without extra queries.
  * Computes a short ``classification_hint`` string server-side
    so the operator doesn't have to interpret.

Strictly read-only — no ``insert`` / ``update`` / ``delete`` /
``find_one_and_update`` paths. Uses the backend's existing Motor
client via ``config.db``.
"""
from __future__ import annotations

import os
from datetime import date as _date
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin


router = APIRouter()


_WEEKDAY_NAMES = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}


def _redact_mongo_host(url: Optional[str]) -> str:
    """Return host:port only — strip user/pass + path + query."""
    if not url:
        return ""
    try:
        split = urlsplit(url)
        # ``netloc`` includes any ``user:pass@`` prefix; strip it.
        netloc = split.netloc
        if "@" in netloc:
            netloc = netloc.rsplit("@", 1)[1]
        return netloc or ""
    except Exception:  # noqa: BLE001
        return ""


def _classify(
    *,
    jobs_template_origin: int,
    python_match: int,
    js_match: int,
    cursors_python: List[Dict[str, Any]],
    target_date: str,
) -> str:
    """Server-side classification per the P0 ticket's 5 branches.

    Branch order matters — the convention-mismatch signal MUST
    win over ``preview_clean`` when ``js_match`` dwarfs
    ``python_match``, otherwise a prod with (e.g.) 2 correctly-
    convention Python matches ↔ 2 jobs AND 15 JS-convention
    mislabelled templates would mis-classify as "preview_clean"
    and hide the real smoking gun.
    """
    # Branch 2 FIRST — convention mismatch suspected (JS writer
    # vs Python materializer). Fires when the JS-convention
    # bucket is substantially larger than the Python bucket.
    if js_match > max(python_match * 2, 2):
        return "convention_mismatch_suspected"
    # Branch 1 — materializer healthy / preview-clean.
    if python_match > 0 and jobs_template_origin == python_match:
        return "preview_clean"
    # Shared predicate for branches 3 + 4 — significant under-
    # count relative to Python matches.
    under_counted = (
        python_match > 0
        and jobs_template_origin < python_match / 2
    )
    if under_counted:
        any_cursor_stuck = any(
            (r.get("_id") or "") < target_date
            for r in cursors_python
        )
        if any_cursor_stuck:
            return "cursor_stuck"
        all_cursors_advanced = all(
            (r.get("_id") or "") >= target_date
            for r in cursors_python
            if r.get("_id") is not None
        )
        if all_cursors_advanced:
            return "silent_materializer_failure"
    return "unknown"


@router.get("/admin/diagnostics/recurring-jobs-audit")
async def recurring_jobs_audit(
    date: Optional[str] = Query(
        None,
        description=(
            "Target date in ``YYYY-MM-DD`` format. "
            "Defaults to today (server TZ, same as the materializer uses)."
        ),
    ),
    user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """Read-only recurring-jobs cadence audit. See module docstring."""
    # ─── Parse + validate the target date ───────────────────────
    if date is None:
        target_dt = _date.today()
    else:
        try:
            target_dt = _date.fromisoformat(date)
        except Exception:
            raise HTTPException(
                400,
                "date must be ISO YYYY-MM-DD (e.g. 2026-10-13)",
            )
    target_iso = target_dt.isoformat()
    target_wd_py = target_dt.weekday()           # Mon=0 .. Sun=6
    target_wd_js = (target_wd_py + 1) % 7        # Sun=0 .. Sat=6

    # ─── Jobs on date ───────────────────────────────────────────
    jobs_tpl_not_deleted = await db.jobs.count_documents({
        "scheduled_date": target_iso,
        "recurring_template_id": {"$exists": True, "$ne": None},
        "deleted_at": {"$exists": False},
    })
    jobs_tpl_including_deleted = await db.jobs.count_documents({
        "scheduled_date": target_iso,
        "recurring_template_id": {"$exists": True, "$ne": None},
    })
    jobs_any_origin = await db.jobs.count_documents({
        "scheduled_date": target_iso,
    })

    # ─── Active-template counts per convention ──────────────────
    _active_filter_base: Dict[str, Any] = {
        "frequency": "weekly",
        "active": True,
        "is_active": True,
    }
    python_match = await db.recurring_job_templates.count_documents(
        {**_active_filter_base, "day_of_week": target_wd_py},
    )
    # Only count JS-convention match when it would be a DIFFERENT
    # day_of_week value than the Python one — otherwise the two
    # branches collide on days where the convention is the same
    # integer (not possible with Mon=0 vs Sun=0 but defensive).
    if target_wd_js != target_wd_py:
        js_match = await db.recurring_job_templates.count_documents(
            {**_active_filter_base, "day_of_week": target_wd_js},
        )
    else:
        js_match = python_match

    # ─── day_of_week distribution across weekly+active ──────────
    dow_dist: List[Dict[str, Any]] = []
    _dow_rows = {r["_id"]: r["n"] async for r in
                 db.recurring_job_templates.aggregate([
                     {"$match": _active_filter_base},
                     {"$group": {"_id": "$day_of_week",
                                  "n": {"$sum": 1}}},
                 ])}
    for dow in (0, 1, 2, 3, 4, 5, 6):
        dow_dist.append({"day_of_week": dow,
                         "count": int(_dow_rows.get(dow, 0))})
    # Null sentinel last.
    dow_dist.append({"day_of_week": None,
                     "count": int(_dow_rows.get(None, 0))})

    # ─── Cursor distribution per convention ─────────────────────
    async def _cursor_dist(dow_value: int) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        async for r in db.recurring_job_templates.aggregate([
            {"$match": {**_active_filter_base,
                           "day_of_week": dow_value}},
            {"$group": {"_id": "$last_generated_through",
                           "n": {"$sum": 1}}},
            {"$sort": {"_id": -1}},
        ]):
            rows.append(r)
        return rows

    cursors_python = await _cursor_dist(target_wd_py)
    cursors_js = (
        await _cursor_dist(target_wd_js)
        if target_wd_js != target_wd_py else cursors_python
    )

    # ─── Per-template sample (first 20 across both conventions) ─
    sample: List[Dict[str, Any]] = []
    sample_dow_candidates = [target_wd_py]
    if target_wd_js != target_wd_py:
        sample_dow_candidates.append(target_wd_js)
    async for t in db.recurring_job_templates.find(
        {
            **_active_filter_base,
            "day_of_week": {"$in": sample_dow_candidates},
        },
        {"_id": 0, "id": 1, "customer_name": 1,
          "day_of_week": 1, "last_generated_through": 1,
          "end_date": 1},
    ).limit(20):
        recent_dates: List[str] = []
        async for j in db.jobs.find(
            {"recurring_template_id": t.get("id")},
            {"_id": 0, "scheduled_date": 1},
        ).sort("scheduled_date", -1).limit(5):
            if j.get("scheduled_date"):
                recent_dates.append(j["scheduled_date"])
        recent_dates.reverse()  # chronological ascending
        sample.append({
            "id_prefix": (t.get("id") or "")[:8],
            "customer_name": t.get("customer_name"),
            "day_of_week": t.get("day_of_week"),
            "last_generated_through": t.get("last_generated_through"),
            "end_date": t.get("end_date"),
            "recent_job_dates": recent_dates,
        })

    classification = _classify(
        jobs_template_origin=jobs_tpl_not_deleted,
        python_match=python_match,
        js_match=js_match,
        cursors_python=cursors_python,
        target_date=target_iso,
    )

    # Normalize cursor-distribution shape to the response contract
    # ({last_generated_through, count} not {_id, n}).
    def _norm(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {"last_generated_through": r.get("_id"),
             "count": int(r.get("n") or 0)}
            for r in rows
        ]

    return {
        "env": {
            "mongo_host_redacted": _redact_mongo_host(
                os.environ.get("MONGO_URL"),
            ),
            "db_name": os.environ.get("DB_NAME"),
            "app_env": os.environ.get("APP_ENV"),
        },
        "target": {
            "date": target_iso,
            "weekday_name": _WEEKDAY_NAMES.get(target_wd_py, "?"),
            "day_of_week_python": target_wd_py,
            "day_of_week_js": target_wd_js,
        },
        "jobs_on_date": {
            "template_origin_not_deleted": jobs_tpl_not_deleted,
            "template_origin_including_deleted":
                jobs_tpl_including_deleted,
            "all_origins": jobs_any_origin,
        },
        "active_templates_by_convention": {
            "python_weekday_match": python_match,
            "js_getday_match": js_match,
        },
        "dow_distribution_weekly_active": dow_dist,
        "cursor_distribution": {
            "python_weekday_match": _norm(cursors_python),
            "js_getday_match": _norm(cursors_js),
        },
        "per_template_sample": sample,
        "classification_hint": classification,
    }
