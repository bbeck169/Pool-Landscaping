"""G2 · Feb-2026 — Batch stop-detection processor.

Cron-driven. Every ``interval`` minutes:

* For each tenant with ``gps_settings.enabled=true``:
    * For every currently-open shift AND every shift closed in the
      last hour, fetch the pings that are:
        - inside the batch window (``max(last_processed_at,
          shift.clock_in_at) → now``), AND
        - not already covered by an existing ``driver_stops`` row for
          the same user (dedup by time-range overlap).
    * Run ``detect_stops_for_user`` on the resulting ping list.
    * Insert the emitted stops into ``db.driver_stops``.
    * Update ``db.gps_stops_batch_meta`` per tenant.
* Log per-run summary.

Idempotent: pings falling inside an existing stop are excluded before
running the detector, so re-processing the same window emits nothing.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from config import db, logger
from services.gps_stop_detector import (
    Stop, StopParams, detect_stops_for_user,
)
from utils import new_id, now_iso


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _params_from(settings: Dict[str, Any]) -> StopParams:
    return StopParams(
        stop_radius_m=float(settings.get("stop_radius_m") or 75),
        stop_min_duration_s=int(settings.get("stop_min_duration_s") or 300),
        stop_gap_close_s=int(settings.get("stop_gap_close_s") or 120),
    )


async def _covered_ping_ids(tenant_id: str, user_id: str,
                              window_from: datetime,
                              window_to: datetime) -> set:
    """Return the ping IDs already recorded inside an existing stop
    for this user in the window. Only the ping_ids array is consulted."""
    covered: set = set()
    async for s in db.driver_stops.find(
        {
            "tenant_id": tenant_id, "user_id": user_id,
            "started_at": {"$lte": _iso(window_to)},
            "ended_at": {"$gte": _iso(window_from)},
        },
        {"_id": 0, "ping_ids": 1},
    ):
        for pid in s.get("ping_ids") or []:
            covered.add(pid)
    return covered


async def _process_shift_pings(
    tenant_id: str, user_id: str,
    window_from: datetime, window_to: datetime,
    params: StopParams,
) -> List[Stop]:
    covered = await _covered_ping_ids(tenant_id, user_id,
                                        window_from, window_to)

    q = {
        "tenant_id": tenant_id, "user_id": user_id,
        "captured_at": {
            "$gte": _iso(window_from),
            "$lte": _iso(window_to),
        },
    }
    raw: List[Dict[str, Any]] = []
    async for p in db.gps_pings.find(
        q,
        {"_id": 0, "id": 1, "lat": 1, "lon": 1, "captured_at": 1,
         "tenant_id": 1, "user_id": 1},
    ).sort("captured_at", 1):
        if p.get("id") and p["id"] in covered:
            continue
        raw.append(p)

    return detect_stops_for_user(raw, params,
                                    tenant_id=tenant_id, user_id=user_id)


async def _persist_stops(stops: List[Stop]) -> int:
    inserted = 0
    # G3 · Feb-2026 — best-effort reverse-geocode enrichment on new
    # stops. Cache-first; if MAPBOX_ACCESS_TOKEN is missing, the
    # reverse_geocode helper returns ``no_token`` without any network
    # call and the row lands with ``address_status="no_token"``.
    try:
        from services.reverse_geocoder import reverse_geocode
    except Exception:                                                    # noqa: BLE001
        reverse_geocode = None
    for s in stops:
        row = asdict(s)
        row["id"] = new_id()
        row["created_at"] = now_iso()
        if reverse_geocode is not None:
            try:
                r = await reverse_geocode(
                    row.get("center_lat"), row.get("center_lon"),
                    tenant_id=row.get("tenant_id") or "")
                row["address"] = r.get("address")
                row["address_status"] = r.get("status") or "pending"
                row["address_resolved_at"] = now_iso()
            except Exception:                                            # noqa: BLE001
                row["address"] = None
                row["address_status"] = "error"
                row["address_resolved_at"] = now_iso()
        else:
            row["address"] = None
            row["address_status"] = "pending"
        try:
            await db.driver_stops.insert_one(row)
            inserted += 1
        except Exception as e:                                          # noqa: BLE001
            logger.warning("[gps_stops] insert failed user=%s err=%s",
                            s.user_id, e)
    return inserted


async def _shifts_to_process(tenant_id: str, now: datetime):
    """Currently-open shifts, plus shifts that closed in the last hour."""
    cutoff = _iso(now - timedelta(hours=1))
    q = {
        "tenant_id": tenant_id,
        "$or": [
            {"clock_out_at": None},
            {"clock_out_at": {"$gte": cutoff}},
        ],
    }
    async for s in db.time_entries.find(
        q,
        {"_id": 0, "id": 1, "user_id": 1, "user_name": 1,
         "clock_in_at": 1, "clock_out_at": 1},
    ):
        yield s


async def process_tenant(tenant_id: str, settings: Dict[str, Any],
                          *, now: datetime | None = None) -> Dict[str, int]:
    now = now or datetime.now(timezone.utc)
    params = _params_from(settings)
    batch_window_min = int(settings.get("stop_batch_window_min") or 15)

    meta = await db.gps_stops_batch_meta.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}) or {}
    last_from = _parse_ts(meta.get("last_processed_ping_at")) or (
        now - timedelta(minutes=batch_window_min))

    users_processed = 0
    stops_emitted = 0
    seen_users: set = set()

    async for shift in _shifts_to_process(tenant_id, now):
        uid = shift.get("user_id")
        if not uid or uid in seen_users:
            continue
        seen_users.add(uid)

        shift_start = _parse_ts(shift.get("clock_in_at")) or last_from
        window_from = max(last_from, shift_start)
        # Constrain window to the tunable width regardless of last_from
        window_from = max(window_from,
                            now - timedelta(minutes=batch_window_min))
        window_to = now

        stops = await _process_shift_pings(
            tenant_id, uid, window_from, window_to, params)
        inserted = await _persist_stops(stops)
        stops_emitted += inserted
        users_processed += 1

    await db.gps_stops_batch_meta.update_one(
        {"tenant_id": tenant_id},
        {"$set": {"tenant_id": tenant_id,
                    "last_run_at": _iso(now),
                    "last_processed_ping_at": _iso(now)}},
        upsert=True,
    )

    logger.info(
        "[gps_stops] tenant=%s users_processed=%s stops_emitted=%s",
        tenant_id, users_processed, stops_emitted,
    )
    return {"users_processed": users_processed,
            "stops_emitted": stops_emitted}


async def run_gps_stops_batch(*, now: datetime | None = None) -> Dict[str, int]:
    """Cron entry point. Iterates every tenant with tracking enabled."""
    now = now or datetime.now(timezone.utc)
    totals = {"tenants": 0, "users_processed": 0, "stops_emitted": 0}
    async for s in db.gps_settings.find({"enabled": True}, {"_id": 0}):
        tenant_id = s.get("tenant_id")
        if not tenant_id:
            continue
        try:
            r = await process_tenant(tenant_id, s, now=now)
            totals["tenants"] += 1
            totals["users_processed"] += r["users_processed"]
            totals["stops_emitted"] += r["stops_emitted"]
        except Exception as e:                                          # noqa: BLE001
            logger.warning("[gps_stops] tenant=%s crashed: %s", tenant_id, e)
    return totals


async def rebuild_for_user(tenant_id: str, user_id: str,
                             *, from_dt: datetime, to_dt: datetime,
                             settings: Dict[str, Any] | None = None) -> int:
    """Delete stops in the [from_dt, to_dt] window for a specific user
    and re-run the detector against the pings in that window. Used by
    the admin rebuild endpoint."""
    settings = settings or await db.gps_settings.find_one(
        {"tenant_id": tenant_id}, {"_id": 0}) or {}
    params = _params_from(settings)

    # Wipe existing rows in the range.
    await db.driver_stops.delete_many({
        "tenant_id": tenant_id, "user_id": user_id,
        "started_at": {"$gte": _iso(from_dt), "$lte": _iso(to_dt)},
    })

    raw: List[Dict[str, Any]] = []
    async for p in db.gps_pings.find(
        {
            "tenant_id": tenant_id, "user_id": user_id,
            "captured_at": {
                "$gte": _iso(from_dt),
                "$lte": _iso(to_dt),
            },
        },
        {"_id": 0, "id": 1, "lat": 1, "lon": 1, "captured_at": 1,
         "tenant_id": 1, "user_id": 1},
    ).sort("captured_at", 1):
        raw.append(p)

    stops = detect_stops_for_user(raw, params,
                                    tenant_id=tenant_id, user_id=user_id)
    return await _persist_stops(stops)
