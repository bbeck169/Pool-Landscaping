"""Phase G3 · Feb-2026 — GPS Route + reverse-geocode backfill.

Two admin+/manager endpoints:

* ``GET /api/gps/route`` — full route data for a user in a range
  (stops + downsampled pings). Powers the Driver Activity map panel.
* ``POST /api/admin/gps/reverse-geocode/backfill`` — bulk hydrate
  ``driver_stops.address`` for rows currently in ``address_status
  in {None, "pending", "error"}``. Honours ``dry_run`` and
  ``max_calls`` guardrails.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db, logger
from services.reverse_geocoder import (
    ensure_indexes as _ensure_geocoder_indexes,
    mapbox_token_configured, reverse_geocode,
)
from utils import get_current_user, now_iso

router = APIRouter()

_MOD_ROLES = {"admin", "super_admin", "manager"}
_MAX_PINGS = 500
_MAX_WINDOW_DAYS = 31


def _require_mod(user: Dict[str, Any]) -> None:
    if (user or {}).get("role") not in _MOD_ROLES:
        raise HTTPException(403, {"error": "forbidden"})


def _tenant_or_400(user: Dict[str, Any]) -> str:
    tid = (user or {}).get("tenant_id") or ""
    if not tid:
        raise HTTPException(400, {"error": "missing_tenant"})
    return tid


def _parse_iso(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


# ═══════════════════════ GET /gps/route ═══════════════════════════

@router.get("/gps/route", operation_id="gps.route")
async def get_route(
    user_id: str = Query(..., min_length=1),
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    q_customer: Optional[str] = Query(None),
    q_address: Optional[str] = Query(None),
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    try:
        from_dt = _parse_iso(from_)
        to_dt = _parse_iso(to)
    except Exception:
        raise HTTPException(400, {"error": "invalid_datetime"})
    if to_dt <= from_dt:
        raise HTTPException(400, {"error": "invalid_range"})
    if (to_dt - from_dt).days > _MAX_WINDOW_DAYS:
        raise HTTPException(400, {"error": "range_too_large",
                                    "max_days": _MAX_WINDOW_DAYS})

    # Stops (already may carry address/address_status from batch enrichment).
    stops: List[Dict[str, Any]] = []
    async for s in db.driver_stops.find(
            {"tenant_id": tenant_id, "user_id": user_id,
              "started_at": {"$gte": from_.replace("Z", "+00:00"),
                              "$lte": to.replace("Z", "+00:00")}},
            {"_id": 0}).sort("started_at", 1):
        stops.append(s)

    # G5b addendum · Feb-2026 — hydrate attributed_customer_name on
    # every stop (one round-trip). Missing/deleted customers → null.
    cust_ids = list({s.get("attributed_customer_id") for s in stops
                     if s.get("attributed_customer_id")})
    if cust_ids:
        cust_map: Dict[str, str] = {}
        async for c in db.customers.find(
                {"tenant_id": tenant_id, "id": {"$in": cust_ids}},
                {"_id": 0, "id": 1, "name": 1}):
            cust_map[c["id"]] = c.get("name") or ""
        for s in stops:
            cid = s.get("attributed_customer_id")
            s["attributed_customer_name"] = cust_map.get(cid) if cid else None
    else:
        for s in stops:
            s["attributed_customer_name"] = None

    # G5b addendum #2 · Feb-2026 — post-hydration search filters. Only
    # the stops list is filtered — pings are not (they're the raw
    # signal, and downsampling already happens above). Empty filter =
    # no-op. Case-insensitive substring; regex chars escaped.
    import re
    if q_customer:
        pat = re.compile(re.escape(q_customer), re.IGNORECASE)
        stops = [s for s in stops
                 if pat.search(s.get("attributed_customer_name") or "")]
    if q_address:
        pat = re.compile(re.escape(q_address), re.IGNORECASE)
        stops = [s for s in stops
                 if pat.search((s.get("address") or {}).get("formatted") or "")]

    # Pings — count first, then downsample if we need to.
    q_pings = {"tenant_id": tenant_id, "user_id": user_id,
                 "captured_at": {"$gte": from_.replace("Z", "+00:00"),
                                  "$lte": to.replace("Z", "+00:00")}}
    total_pings = await db.gps_pings.count_documents(q_pings)
    step = 1
    if total_pings > _MAX_PINGS:
        # Server-side "every Nth row" downsample so we don't ship
        # every ping across a wide range.
        step = (total_pings // _MAX_PINGS) + 1
    pings: List[Dict[str, Any]] = []
    i = 0
    async for p in db.gps_pings.find(
            q_pings, {"_id": 0, "lat": 1, "lon": 1, "captured_at": 1}
            ).sort("captured_at", 1):
        if i % step == 0:
            pings.append({
                "lat": float(p["lat"]),
                "lon": float(p["lon"]),
                "captured_at": p.get("captured_at"),
            })
        i += 1
        if len(pings) >= _MAX_PINGS:
            break

    # Best-effort user_name lookup (does not error if missing).
    user_name = ""
    u = await db.users.find_one(
        {"id": user_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1, "email": 1})
    if u:
        user_name = u.get("name") or u.get("email") or ""

    return {
        "user_id": user_id,
        "user_name": user_name,
        "from": from_,
        "to": to,
        "stops": stops,
        "pings": pings,
        "pings_total": total_pings,
        "pings_downsample_step": step,
        "mapbox_token_configured": mapbox_token_configured(),
    }


# ═══════════════════════ POST reverse-geocode/backfill ═════════════

class BackfillBody(BaseModel):
    dry_run: bool = True
    scope: Literal["stops", "pings", "both"] = "stops"
    max_calls: int = Field(100, ge=1, le=1000)


@router.post("/admin/gps/reverse-geocode/backfill",
              operation_id="gps.reverseGeocodeBackfill")
async def reverse_geocode_backfill(
    body: BackfillBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    _require_mod(caller)
    tenant_id = _tenant_or_400(caller)
    await _ensure_geocoder_indexes()

    # Common query for pending stops. Old rows may lack these fields
    # entirely, so we accept null / missing / "pending" / "error".
    q_stops = {
        "tenant_id": tenant_id,
        "$or": [
            {"address_status": {"$in": [None, "pending", "error"]}},
            {"address_status": {"$exists": False}},
        ],
    }
    pending_stops_count = await db.driver_stops.count_documents(q_stops)

    if body.dry_run:
        return {
            "dry_run": True,
            "scope": body.scope,
            "pending_stops": pending_stops_count,
            "mapbox_token_configured": mapbox_token_configured(),
        }

    if not mapbox_token_configured():
        return {"status": "no_token", "processed": 0, "resolved": 0,
                "errors": 0, "pending_stops": pending_stops_count,
                "mapbox_token_configured": False,
                "message":
                    "MAPBOX_ACCESS_TOKEN is empty — backfill skipped."}

    processed = 0
    resolved = 0
    errors = 0
    if body.scope in ("stops", "both"):
        cursor = db.driver_stops.find(
            q_stops, {"_id": 0, "id": 1, "center_lat": 1,
                        "center_lon": 1}).limit(body.max_calls)
        async for s in cursor:
            if processed >= body.max_calls:
                break
            processed += 1
            r = await reverse_geocode(
                s.get("center_lat"), s.get("center_lon"),
                tenant_id=tenant_id)
            update = {
                "address": r.get("address"),
                "address_status": r.get("status"),
                "address_resolved_at": now_iso(),
            }
            try:
                await db.driver_stops.update_one(
                    {"id": s["id"], "tenant_id": tenant_id},
                    {"$set": update})
                if r.get("status") == "resolved":
                    resolved += 1
                else:
                    errors += 1
            except Exception as e:                                     # noqa: BLE001
                logger.warning("[gps_route.backfill] stop=%s err=%s",
                                s.get("id"), e)
                errors += 1

    return {
        "status": "ok",
        "processed": processed,
        "resolved": resolved,
        "errors": errors,
        "pending_stops_remaining": max(0, pending_stops_count - processed),
        "mapbox_token_configured": True,
    }
