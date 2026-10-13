"""P1 · Feb-2026 — Read-only mileage audit diagnostic endpoint.

Serves ``GET /api/admin/diagnostics/mileage-audit?user_id=...``
— a per-user, per-time-window snapshot that lets an admin
operator diagnose the "Steven Martinez shows 0.00 mi" symptom
against the live DB without needing shell / mongosh access.

Why
---
Two parallel GPS ping ingestion paths exist:

    * ``POST /api/workforce/location-ping`` → ``db.location_pings``
      (fields ``ts`` / ``lng``).  Fed by a foreground-only JS
      ``setInterval`` loop in mobile — pauses when the phone is
      locked.
    * ``POST /api/gps/pings``                → ``db.gps_pings``
      (fields ``captured_at`` / ``lon``).  Fed by an
      ``expo-task-manager`` background task that keeps collecting
      while the phone is locked.

The clock-out mileage calculator at
``routers/workforce._entry_mileage_miles`` currently reads
``location_pings`` only — if the mobile phone is locked during a
drive, the foreground loop stalls, zero pings land in the
collection the calculator reads, and ``mileage_miles`` lands at
``0.00``.

This endpoint surfaces the shape of ping flow + the resulting
``time_entries.mileage_miles`` row so the operator can confirm
the classification (D — calculator reads the wrong collection)
before kicking the Branch 1 backfill at
``POST /api/admin/mileage/backfill-recompute``.

Strictly read-only — no ``insert`` / ``update`` / ``delete``
paths.  Uses the backend's existing Motor client via ``config.db``.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import require_admin


router = APIRouter()


_AUDIT_SENTINEL_KINDS = frozenset({
    "auto_clockin_decision",
    # Add other known audit sentinel kinds here as they surface.
})


def _redact_mongo_host(url: Optional[str]) -> str:
    """Return host:port only — strip user/pass + path + query."""
    if not url:
        return ""
    try:
        split = urlsplit(url)
        netloc = split.netloc
        if "@" in netloc:
            netloc = netloc.rsplit("@", 1)[1]
        return netloc or ""
    except Exception:  # noqa: BLE001
        return ""


def _hour_bucket(iso_ts: str) -> Optional[str]:
    """Return ``YYYY-MM-DDTHH:00`` for an ISO timestamp or ``None``
    when the input is unparseable (defensive — we return the raw
    row count regardless)."""
    if not iso_ts:
        return None
    try:
        s = iso_ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")
    except Exception:  # noqa: BLE001
        return None


def _parse_window(start: Optional[str],
                   end: Optional[str]) -> Dict[str, str]:
    """Resolve the (start, end) window.  Default: last 7 days."""
    now = datetime.now(timezone.utc)
    end_dt = _parse_iso(end) or now
    start_dt = _parse_iso(start) or (end_dt - timedelta(days=7))
    if start_dt >= end_dt:
        raise HTTPException(
            400, {"error": "start_must_be_before_end"},
        )
    if (end_dt - start_dt) > timedelta(days=90):
        raise HTTPException(
            400, {"error": "window_too_large", "max_days": 90},
        )
    return {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        s = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001
        return None


async def _ping_hour_histogram(
    *, collection, user_id: str, tenant_id: str,
    start: str, end: str, ts_field: str,
    exclude_kinds: Optional[frozenset] = None,
) -> Dict[str, Any]:
    """Return ``{"total": N, "by_hour": [...], "audit_sentinel_count": N}``.

    Scans up to 10,000 pings per call — enough for a 7-day window
    at a 60-second ping cadence (~10,080 pings/week/tech max). If
    the collection is denser we cap to the first 10k and surface
    a ``truncated`` flag so the operator can shorten the window.
    """
    q = {"tenant_id": tenant_id, "user_id": user_id,
         ts_field: {"$gte": start, "$lt": end}}
    buckets: Dict[str, int] = {}
    audit_count = 0
    total = 0
    truncated = False
    cursor = collection.find(
        q, {"_id": 0, ts_field: 1, "kind": 1},
    ).sort(ts_field, 1)
    async for row in cursor:
        total += 1
        if total > 10_000:
            truncated = True
            break
        kind = row.get("kind")
        if exclude_kinds and kind in exclude_kinds:
            audit_count += 1
            continue
        bucket = _hour_bucket(row.get(ts_field))
        if bucket:
            buckets[bucket] = buckets.get(bucket, 0) + 1
    by_hour = [{"hour": h, "count": c}
                for h, c in sorted(buckets.items())]
    out = {"total": total, "by_hour": by_hour,
            "truncated": truncated}
    if exclude_kinds is not None:
        # Expose both the tracking total (excl. sentinels) and the
        # raw sentinel count so operators see both signals.
        out["total_tracking"] = total - audit_count
        out["audit_sentinel_count"] = audit_count
    return out


async def _shift_rows(
    *, user_id: str, tenant_id: str, start: str, end: str,
) -> List[Dict[str, Any]]:
    rows = await db.time_entries.find(
        {"tenant_id": tenant_id, "user_id": user_id,
         "clock_in_at": {"$gte": start, "$lt": end}},
        {"_id": 0, "id": 1, "clock_in_at": 1, "clock_out_at": 1,
         "mileage_miles": 1, "status": 1, "duration_minutes": 1},
    ).sort("clock_in_at", 1).to_list(200)
    return [
        {"entry_id": r.get("id"),
         "clock_in_at": r.get("clock_in_at"),
         "clock_out_at": r.get("clock_out_at"),
         "mileage_miles": r.get("mileage_miles") or 0,
         "status": r.get("status"),
         "duration_minutes": r.get("duration_minutes") or 0}
        for r in rows
    ]


def _classify(
    *, gps_total: int, loc_total_tracking: int,
    shifts: List[Dict[str, Any]],
) -> str:
    """Server-side classifier — operator doesn't have to interpret
    the raw counts."""
    closed_shifts = [s for s in shifts if s.get("clock_out_at")]
    if not shifts:
        return "no_shifts_in_window"
    if gps_total == 0 and loc_total_tracking == 0:
        return "likely_mobile_not_posting"
    any_zero_closed = any(
        (s.get("mileage_miles") or 0) == 0 for s in closed_shifts
    )
    all_closed_have_miles = (
        bool(closed_shifts)
        and all((s.get("mileage_miles") or 0) > 0
                for s in closed_shifts)
    )
    if (gps_total > 10 * max(loc_total_tracking, 1)
            and any_zero_closed):
        return "likely_calculator_reading_wrong_collection"
    if gps_total > 0 and all_closed_have_miles:
        return "preview_clean"
    return "unknown"


@router.get("/admin/diagnostics/mileage-audit")
async def mileage_audit(
    user_id: str = Query(..., description="Target user id."),
    start: Optional[str] = Query(
        None, description="ISO window start (default now - 7d)."),
    end: Optional[str] = Query(
        None, description="ISO window end (default now)."),
    _admin: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    """Read-only diagnostic for the mileage=0 symptom. Returns ping
    histograms + shift rows + a server-side classification hint.
    """
    user_row = await db.users.find_one(
        {"id": user_id},
        {"_id": 0, "id": 1, "name": 1, "email": 1,
         "role": 1, "tenant_id": 1},
    )
    if not user_row:
        raise HTTPException(404, {"error": "user_not_found",
                                     "user_id": user_id})
    tenant_id = user_row.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(500, {"error": "user_missing_tenant"})

    window = _parse_window(start, end)

    gps = await _ping_hour_histogram(
        collection=db.gps_pings, user_id=user_id,
        tenant_id=tenant_id,
        start=window["start"], end=window["end"],
        ts_field="captured_at",
    )
    loc = await _ping_hour_histogram(
        collection=db.location_pings, user_id=user_id,
        tenant_id=tenant_id,
        start=window["start"], end=window["end"],
        ts_field="ts",
        exclude_kinds=_AUDIT_SENTINEL_KINDS,
    )
    shifts = await _shift_rows(
        user_id=user_id, tenant_id=tenant_id,
        start=window["start"], end=window["end"],
    )
    hint = _classify(
        gps_total=gps["total"],
        loc_total_tracking=loc.get("total_tracking", 0),
        shifts=shifts,
    )

    return {
        "env": {
            "mongo_host_redacted": _redact_mongo_host(
                os.environ.get("MONGO_URL")),
            "db_name": os.environ.get("DB_NAME") or "",
            "app_env": os.environ.get("APP_ENV") or "",
        },
        "target": {
            "user_id": user_id,
            "user_name": user_row.get("name")
                or user_row.get("email") or "",
            "tenant_id": tenant_id,
            "start": window["start"],
            "end": window["end"],
        },
        "pings": {
            "gps_pings_total": gps["total"],
            "gps_pings_by_hour": gps["by_hour"],
            "gps_pings_truncated": gps["truncated"],
            "location_pings_total_tracking":
                loc.get("total_tracking", 0),
            "location_pings_by_hour": loc["by_hour"],
            "location_pings_audit_sentinel_count":
                loc.get("audit_sentinel_count", 0),
            "location_pings_truncated": loc["truncated"],
        },
        "shifts": shifts,
        "classification_hint": hint,
    }
