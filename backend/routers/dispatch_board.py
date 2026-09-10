"""Phase 17 · Feb-2026 — Dispatch Board (Google Maps + Directions).

Full-fat implementation once the frontend rewrite landed:

* ``GET  /api/dispatch/board`` — pins for geocoded customers, filtered
  by ``day`` / ``tech_user_id`` / ``route_type`` / ``global`` toggle,
  plus the ordered stop sequence persisted for that (day, tech) pair,
  plus a ``tech_load`` strip enriched with the tech's display color.
* ``POST /api/dispatch/board/optimize`` — calls Google Directions
  with ``optimize:true`` and returns the reordered customer IDs +
  encoded polyline + total distance/duration + savings vs. the
  originally-submitted order.
* ``POST /api/dispatch/board/apply-order`` — persists a
  ``dispatch_route_orders`` doc keyed by
  ``(tenant_id, day, tech_user_id)`` so the next board load picks
  up the drag-reordered sequence.
* ``POST /api/admin/customers/geocode-backfill`` — idempotent,
  admin-only. Iterates every non-deleted customer with a
  ``service_address`` and skips rows already geocoded within
  30 days. Sleeps 100 ms between calls to stay under Google's
  50-QPS burst ceiling.

RBAC: admin + super_admin. Manager reads permitted so operations
managers can see the board without super-admin. Techs never see
this page — the ``/dispatch`` route is ``AdminOnly`` on the
frontend and the endpoints below re-enforce role on the backend.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Header, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user
from utils import not_deleted_filter as _nd
from routers.tenants import get_current_tenant

router = APIRouter()

_READ_ROLES = {"admin", "super_admin", "manager"}
_ADMIN_ROLES = {"admin", "super_admin"}

_PALETTE = ["#4F46E5", "#059669", "#DB2777", "#D97706", "#0891B2",
             "#7C3AED", "#DC2626", "#65A30D", "#0284C7", "#EA580C"]

# Crew/department fallback palette (Phase 17 pin-color modes).
# We don't have a first-class `crews` collection yet; the frontend
# color-by-crew mode uses the tech's `department` for grouping.
_CREW_PALETTE = {
    "pool":         {"label": "Pool",        "color": "#0ea5e9"},
    "landscaping":  {"label": "Landscaping", "color": "#16a34a"},
    "landscape":    {"label": "Landscaping", "color": "#16a34a"},
    "repairs":      {"label": "Repairs",     "color": "#f59e0b"},
    "repair":       {"label": "Repairs",     "color": "#f59e0b"},
}
_CREW_OTHER = {"label": "Other", "color": "#64748b"}


def _crew_from_department(dept: Optional[str]) -> Dict[str, str]:
    key = (dept or "").strip().lower()
    return _CREW_PALETTE.get(key, _CREW_OTHER)


def _require_read(user: dict):
    if user.get("role") not in _READ_ROLES:
        raise HTTPException(403, "Dispatch board is admin/manager only")


def _require_admin(user: dict):
    if user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin only")


def _hash_color(seed: str) -> str:
    h = sum(ord(c) for c in (seed or "")) % len(_PALETTE)
    return _PALETTE[h]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═════════════════════════════════════════════════════════════════
# GET /api/dispatch/board
# ═════════════════════════════════════════════════════════════════
@router.get("/dispatch/board", tags=["dispatch"],
             operation_id="dispatchBoard.get")
async def get_board(
    day: str = Query("all"),
    tech_user_id: Optional[str] = Query(None),
    route_type: str = Query("all"),
    global_view: bool = Query(False, alias="global"),
    date: Optional[str] = Query(None, description=(
        "Feb-2026 · Concrete calendar date (YYYY-MM-DD). When present "
        "AND the customer-denorm path yields empty route_stops, the "
        "endpoint falls back to db.jobs for that (tenant, tech, date). "
        "Read-only — never mutates dispatch_route_orders or customer "
        "denorm fields.")),
    if_none_match: Optional[str] = Header(
        default=None, alias="If-None-Match",
        description=(
            "Feb-2026 · Live-Tech-Map Phase 1 (Q8) — conditional GET "
            "support. When the caller's cached ETag matches the "
            "current board hash the endpoint returns 304 Not Modified "
            "with an empty body. Reduces the 30 s dispatch poll cost "
            "on quiet boards.")),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_read(user)
    day_norm = (day or "all").lower()
    q: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "service_lat": {"$exists": True, "$ne": None},
    }
    # Non-global filters — respect service_days / assigned_tech_ids
    # denormalized by customer_categories.recompute_customer_denorm.
    # NOTE: tech_user_id filter is applied POST-override (see below)
    # so customers shifted IN to the current tech via a route override
    # still surface on the board.
    if not global_view:
        if day_norm and day_norm != "all":
            q["service_days"] = day_norm
        if route_type and route_type != "all":
            q["$or"] = [
                {"category_ids": route_type},
                {"tags": {"$regex": f"(?i){route_type}"}},
            ]

    customers = await db.customers.find(q, {
        "_id": 0, "id": 1, "name": 1, "service_address": 1,
        "service_lat": 1, "service_lng": 1, "tags": 1,
        "category_ids": 1, "service_days": 1, "assigned_tech_ids": 1,
    }).to_list(2000)

    # Phase 17 · Route Assignment Overrides — apply active overrides
    # BEFORE building the pin list so shifted stops move to the target
    # tech's board and disappear from the source tech's board. This
    # also stamps ``override_source_tech_id`` on each shifted customer
    # so the frontend can render the "← Brian B. (until Sat)" tag.
    from services.route_reassign import apply_overrides_to_customers
    await apply_overrides_to_customers(tenant["id"], customers)

    # Post-override tech filter — if the caller filtered to a tech,
    # the override may have shifted customers IN (target) or OUT
    # (source). Redo the check now that assigned_tech_ids reflect
    # effective ownership.
    if not global_view and tech_user_id:
        customers = [c for c in customers
                     if tech_user_id in (c.get("assigned_tech_ids") or [])]

    # Preload tech directory so we can decorate every pin with the
    # tech color + department (for the pin-color modes).
    all_tech_ids = set()
    for c in customers:
        for tid in (c.get("assigned_tech_ids") or []):
            all_tech_ids.add(tid)
        src = c.get("override_source_tech_id")
        if src:
            all_tech_ids.add(src)
    tech_directory: Dict[str, Dict[str, Any]] = {}
    if all_tech_ids:
        async for u in db.users.find(
            {"id": {"$in": list(all_tech_ids)}},
            {"_id": 0, "id": 1, "name": 1, "display_color_hex": 1, "department": 1},
        ):
            tech_directory[u["id"]] = {
                "name": u.get("name") or u["id"],
                "color_hex": u.get("display_color_hex") or _hash_color(u["id"]),
                "department": u.get("department"),
            }

    pins = []
    for c in customers:
        first_tech = (c.get("assigned_tech_ids") or [None])[0]
        tech_info = tech_directory.get(first_tech) if first_tech else None
        tech_color_hex = (tech_info or {}).get("color_hex")
        crew = _crew_from_department((tech_info or {}).get("department"))
        pins.append({
            "customer_id": c["id"],
            "name": c.get("name") or "",
            "address": c.get("service_address") or "",
            "lat": c["service_lat"], "lng": c["service_lng"],
            "tags": c.get("tags") or [],
            "category_ids": c.get("category_ids") or [],
            "service_days": c.get("service_days") or [],
            "assigned_tech_ids": c.get("assigned_tech_ids") or [],
            "is_scheduled_this_day": bool(
                day_norm != "all" and day_norm in (c.get("service_days") or [])
            ),
            # Phase 17 · pin-color-mode fields.
            "tech_color_hex": tech_color_hex,
            "crew_label": crew["label"],
            "crew_color_hex": crew["color"],
            "service_day": (c.get("service_days") or [None])[0],
            # Phase 17 · route-reassignment override tags.
            "override_source_tech_id": c.get("override_source_tech_id"),
            "override_id": c.get("override_id"),
            "override_end_at": c.get("override_end_at"),
        })

    # Tech load — count pins assigned per tech within the current filter.
    tech_load: Dict[str, Dict[str, Any]] = {}
    for p in pins:
        for tid in p["assigned_tech_ids"]:
            if tid not in tech_load:
                tech_load[tid] = {"tech_user_id": tid, "count": 0, "drops": []}
            tech_load[tid]["count"] += 1
            tech_load[tid]["drops"].append(p["customer_id"])

    tech_ids = list(tech_load.keys())
    if tech_ids:
        for tid in tech_ids:
            info = tech_directory.get(tid)
            if info:
                tech_load[tid]["name"] = info["name"]
                tech_load[tid]["color_hex"] = info["color_hex"]
        # Backfill any tech not in the pre-loaded directory (edge
        # case: pin has an assigned tech that was deleted).
        missing = [tid for tid in tech_ids if "color_hex" not in tech_load[tid]]
        if missing:
            async for u in db.users.find(
                {"id": {"$in": missing}},
                {"_id": 0, "id": 1, "name": 1, "display_color_hex": 1},
            ):
                tech_load[u["id"]]["name"] = u.get("name") or u["id"]
                tech_load[u["id"]]["color_hex"] = (
                    u.get("display_color_hex") or _hash_color(u["id"])
                )

    # Route stops — fetch the persisted (day, tech) ordered sequence
    # so the "Route Details" drag list picks up prior work + so the
    # optimize endpoint can compute a savings delta.
    route_stops: List[Dict[str, Any]] = []
    if day_norm != "all" and tech_user_id:
        order_doc = await db.dispatch_route_orders.find_one(
            {"tenant_id": tenant["id"], "day": day_norm,
              "tech_user_id": tech_user_id},
            {"_id": 0},
        )
        ordered_ids: List[str] = (order_doc or {}).get("ordered_customer_ids") or []
        if ordered_ids:
            by_id = {p["customer_id"]: p for p in pins}
            for cid in ordered_ids:
                p = by_id.get(cid)
                if p:
                    route_stops.append({
                        "customer_id": p["customer_id"],
                        "name": p["name"], "address": p["address"],
                        "lat": p["lat"], "lng": p["lng"],
                        "tech_color_hex": p["tech_color_hex"],
                        "crew_label": p["crew_label"],
                        "crew_color_hex": p["crew_color_hex"],
                        "service_day": p["service_day"],
                        "override_source_tech_id": p["override_source_tech_id"],
                    })
        else:
            # No saved order yet — surface every pin assigned to this
            # tech on this day so the drag list is populated on first
            # visit.
            for p in pins:
                if p["is_scheduled_this_day"] and tech_user_id in p["assigned_tech_ids"]:
                    route_stops.append({
                        "customer_id": p["customer_id"],
                        "name": p["name"], "address": p["address"],
                        "lat": p["lat"], "lng": p["lng"],
                        "tech_color_hex": p["tech_color_hex"],
                        "crew_label": p["crew_label"],
                        "crew_color_hex": p["crew_color_hex"],
                        "service_day": p["service_day"],
                        "override_source_tech_id": p["override_source_tech_id"],
                    })

    # ─── Unrouted customers ─────────────────────────────────────
    # Active customers who are NOT on the current day/tech route.
    # In global view, unrouted = "no recurring service day" — the
    # truly unassigned. Everywhere else, unrouted = "active + not in
    # route_stops for the current filter". Geocoded rows carry
    # lat/lng so they can render as gray hollow pins on the map;
    # non-geocoded rows still appear in the sidebar list.
    routed_ids = {p["customer_id"] for p in pins}
    unrouted_q: Dict[str, Any] = {
        "tenant_id": tenant["id"],
        "$or": [
            {"is_active": {"$ne": False}},
            {"is_active": {"$exists": False}},
        ],
    }
    if global_view:
        unrouted_q["$and"] = [{
            "$or": [
                {"service_days": {"$exists": False}},
                {"service_days": {"$size": 0}},
            ],
        }]
    unrouted_docs = await db.customers.find(unrouted_q, {
        "_id": 0, "id": 1, "name": 1, "service_address": 1,
        "service_lat": 1, "service_lng": 1, "tags": 1,
        "category_ids": 1, "service_days": 1, "assigned_tech_ids": 1,
        "last_serviced_at": 1,
    }).to_list(3000)

    unrouted_customers: List[Dict[str, Any]] = []
    for c in unrouted_docs:
        if c["id"] in routed_ids:
            continue
        days = c.get("service_days") or []
        techs = c.get("assigned_tech_ids") or []
        if not days:
            reason = "no_service_day"
        elif not techs:
            reason = "no_tech_assigned"
        else:
            # Has a day + tech but not on the current filter.
            reason = "not_on_this_day"
        unrouted_customers.append({
            "customer_id": c["id"],
            "name": c.get("name") or "",
            "address": c.get("service_address") or "",
            "lat": c.get("service_lat"),
            "lng": c.get("service_lng"),
            "category_ids": c.get("category_ids") or [],
            "tags": c.get("tags") or [],
            "service_days": days,
            "assigned_tech_ids": techs,
            "last_serviced_at": c.get("last_serviced_at"),
            "reason": reason,
        })

    # Feb-2026 · jobs fallback — when the customer-denorm path
    # yielded nothing (no dispatch_route_orders row AND no pins
    # matched the day/tech filter) AND the caller supplied a
    # concrete ``date``, hydrate ``route_stops`` from ``db.jobs``.
    # Read-only: no writes to dispatch_route_orders or customer
    # denorm fields. Multi-tenant safe (query is tenant-scoped).
    fallback_from_jobs = False
    if (not route_stops) and date and tech_user_id:
        import re as _re
        date_prefix = _re.escape(date)
        job_q: Dict[str, Any] = {
            "tenant_id": tenant["id"],
            "scheduled_date": {"$regex": f"^{date_prefix}"},
            "$or": [
                {"tech_user_id": tech_user_id},
                {"assigned_to": tech_user_id},
                {"technician_id": tech_user_id},
            ],
        }
        job_q = {**job_q, **_nd()}
        jobs = await db.jobs.find(
            job_q,
            {"_id": 0, "id": 1, "customer_id": 1, "customer_name": 1,
             "title": 1, "service_type": 1, "address": 1, "status": 1,
             "route_index": 1, "scheduled_start": 1, "scheduled_date": 1},
        ).sort([("route_index", 1), ("scheduled_start", 1)]).to_list(500)

        if jobs:
            fallback_from_jobs = True
            # Batch-fetch customers for name + coords in one round-trip.
            needed = {j.get("customer_id") for j in jobs if j.get("customer_id")}
            cmap: Dict[str, Dict[str, Any]] = {}
            if needed:
                async for c in db.customers.find(
                    {"id": {"$in": list(needed)}, "tenant_id": tenant["id"]},
                    {"_id": 0, "id": 1, "name": 1, "billing_name": 1,
                     "service_address": 1, "service_lat": 1, "service_lng": 1},
                ):
                    cmap[c["id"]] = c

            # Reset pins so the map + tech_load reflect the fallback
            # set. Skip customers we didn't just look up so we don't
            # bleed unrelated pins in.
            pins = []
            for j in jobs:
                cust = cmap.get(j.get("customer_id"))
                display_name = (
                    (j.get("customer_name") or "").strip()
                    or ((cust or {}).get("name") or "").strip()
                    or ((cust or {}).get("billing_name") or "").strip()
                    or ((cust or {}).get("service_address") or "").strip()
                    or (j.get("address") or "").strip()
                    or "(no customer)"
                )
                svc_addr = (
                    (cust or {}).get("service_address")
                    or j.get("address") or ""
                )
                lat = (cust or {}).get("service_lat")
                lng = (cust or {}).get("service_lng")
                route_stops.append({
                    "job_id": j.get("id"),
                    "customer_id": j.get("customer_id"),
                    "name": display_name,
                    "customer_display_name": display_name,
                    "service_address": svc_addr,
                    "address": svc_addr,
                    "lat": lat, "lng": lng,
                    "route_index": j.get("route_index"),
                    "service_type": j.get("service_type"),
                    "title": j.get("title"),
                    "status": j.get("status"),
                    "not_geocoded": lat is None or lng is None,
                    "tech_color_hex": None,
                    "crew_label": None,
                    "crew_color_hex": None,
                    "service_day": day_norm,
                    "override_source_tech_id": None,
                    "source": "jobs_fallback",
                })
                # Emit a pin ONLY when geocoded. Non-geocoded stops
                # still show on the sidebar list via ``route_stops``.
                if lat is not None and lng is not None:
                    pins.append({
                        "customer_id": j.get("customer_id"),
                        "name": display_name,
                        "address": svc_addr,
                        "lat": lat, "lng": lng,
                        "tags": [], "category_ids": [],
                        "service_days": [day_norm] if day_norm != "all" else [],
                        "assigned_tech_ids": [tech_user_id],
                        "is_scheduled_this_day": True,
                        "tech_color_hex": None,
                        "crew_label": None,
                        "crew_color_hex": None,
                        "service_day": day_norm,
                        "override_source_tech_id": None,
                        "override_id": None,
                        "override_end_at": None,
                        "source": "jobs_fallback",
                    })

            # Refresh tech_load for the fallback tech.
            tech_load = {tech_user_id: {
                "tech_user_id": tech_user_id,
                "name": None, "color_hex": _hash_color(tech_user_id or ""),
                "count": len(route_stops),
            }}
            u = await db.users.find_one(
                {"id": tech_user_id, "tenant_id": tenant["id"]},
                {"_id": 0, "name": 1, "display_color_hex": 1},
            )
            if u:
                tech_load[tech_user_id]["name"] = u.get("name") or tech_user_id
                tech_load[tech_user_id]["color_hex"] = (
                    u.get("display_color_hex") or tech_load[tech_user_id]["color_hex"]
                )
            # Rebuild routed_ids so unrouted computation reflects the
            # new pins set (below).
            routed_ids = {p["customer_id"] for p in pins}

    payload = {
        "pins": pins,
        "route_stops": route_stops,
        "tech_load": list(tech_load.values()) if isinstance(tech_load, dict) else tech_load,
        "unrouted_customers": unrouted_customers,
        "suggested_optimization": None,
        "polyline": None,
        "global_view": global_view,
        "day": day_norm,
        "date": date,
        "tech_user_id": tech_user_id,
        "source": "jobs_fallback" if fallback_from_jobs else "denorm",
    }
    # Feb-2026 · Live-Tech-Map Phase 1 (Q8) — ETag / If-None-Match.
    # Hash the serialized payload; return 304 if the caller's
    # cached tag matches. ``sort_keys=True`` + ``default=str`` guard
    # against key-order jitter and stray datetime/ObjectId objects
    # in the pin list.
    try:
        canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        etag = '"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16] + '"'
    except Exception:  # noqa: BLE001
        # Hash failure must never break the endpoint — fall through
        # to a plain 200 without ETag rather than 500.
        return payload
    if if_none_match and if_none_match == etag:
        # 304 body MUST be empty per RFC 7232.
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(content=payload, headers={"ETag": etag})


# ═════════════════════════════════════════════════════════════════
# POST /api/dispatch/board/optimize
# ═════════════════════════════════════════════════════════════════
class OptimizeRequest(BaseModel):
    day: str
    tech_user_id: str
    stop_customer_ids: List[str]
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None


@router.post("/dispatch/board/optimize", tags=["dispatch"],
              operation_id="dispatchBoard.optimize")
async def optimize_board(
    body: OptimizeRequest,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    if not body.stop_customer_ids:
        raise HTTPException(400, "stop_customer_ids required")
    if len(body.stop_customer_ids) < 2:
        raise HTTPException(400, "Need at least 2 stops to optimize")

    docs = await db.customers.find(
        {"tenant_id": tenant["id"], "id": {"$in": body.stop_customer_ids},
          "service_lat": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "service_lat": 1,
          "service_lng": 1, "service_address": 1},
    ).to_list(1000)
    by_id = {d["id"]: d for d in docs}
    ordered_docs = [by_id[cid] for cid in body.stop_customer_ids if cid in by_id]
    if len(ordered_docs) < 2:
        raise HTTPException(400, "At least 2 stops must be geocoded")

    # Origin defaults to the first stop when caller didn't pass a depot.
    if body.start_lat is not None and body.start_lng is not None:
        origin: Tuple[float, float] = (body.start_lat, body.start_lng)
        waypoints = [(d["service_lat"], d["service_lng"]) for d in ordered_docs]
    else:
        origin = (ordered_docs[0]["service_lat"], ordered_docs[0]["service_lng"])
        waypoints = [(d["service_lat"], d["service_lng"]) for d in ordered_docs[1:]]

    # Import late to avoid pulling httpx into cold-start callers that
    # never hit the optimizer.
    from services.google_maps.directions import optimize_route  # noqa: WPS433

    # 1) Baseline order (as caller sent) — total drive time.
    # Chunk 3 · Feb-2026 — thread tenant_id so BYO Maps + monthly cap
    # fire when ``MAPS_BYO_ENABLED=true``. Behavior unchanged when off.
    baseline = await optimize_route(origin, waypoints, tenant_id=tenant["id"])
    # Google gives us the reorder plus an OVERVIEW polyline. The
    # frontend also wants the "before" total, so we call again with
    # the caller's order pinned. Cheap because both hit the same 30-
    # day billing tier and each request is bounded to <= 25 stops
    # (Directions API limit).
    baseline_pinned = await _directions_no_optimize(
        origin, waypoints, tenant_id=tenant["id"],
    )

    if not baseline:
        raise HTTPException(502, "Google Directions failed — check API key + quota")

    # ordered_indices refers to the ``waypoints`` list only (i.e. skips
    # the origin). If we shifted the first stop to be the origin,
    # reconstruct the full 0-based customer index list.
    if body.start_lat is not None and body.start_lng is not None:
        ordered_customer_ids = [ordered_docs[i]["id"] for i in baseline["ordered_indices"]]
    else:
        ordered_customer_ids = [ordered_docs[0]["id"]] + [
            ordered_docs[i + 1]["id"] for i in baseline["ordered_indices"]
        ]

    total_duration_min = round(baseline["total_duration_s"] / 60.0, 1)
    total_distance_mi = round(baseline["total_distance_m"] * 0.000621371, 2)

    savings_min = None
    savings_pct = None
    if baseline_pinned and baseline_pinned["total_duration_s"] > 0:
        savings_s = baseline_pinned["total_duration_s"] - baseline["total_duration_s"]
        savings_min = round(max(0.0, savings_s) / 60.0, 1)
        savings_pct = round(
            100.0 * max(0.0, savings_s) / baseline_pinned["total_duration_s"], 1,
        )

    return {
        "ordered_customer_ids": ordered_customer_ids,
        "polyline": baseline["polyline"],
        "total_distance_mi": total_distance_mi,
        "total_duration_min": total_duration_min,
        "savings_min": savings_min,
        "savings_pct": savings_pct,
    }


async def _directions_no_optimize(origin: Tuple[float, float],
                                    waypoints: List[Tuple[float, float]],
                                    tenant_id: Optional[str] = None):
    """Compute the caller's baseline drive time (no reordering) so
    the optimize endpoint can report a savings delta. Delegates to
    the Routes API v2 wrapper; never raises.

    Chunk 3 · Feb-2026 — ``tenant_id`` threaded so the underlying
    call routes through the BYO Maps dispatcher when the flag is on."""
    from services.google_maps.directions import compute_route_no_optimize
    res = await compute_route_no_optimize(
        origin, waypoints, tenant_id=tenant_id,
    )
    if not res:
        return None
    return {
        "total_distance_m": res["total_distance_m"],
        "total_duration_s": res["total_duration_s"],
    }


# ═════════════════════════════════════════════════════════════════
# POST /api/dispatch/board/apply-order
# ═════════════════════════════════════════════════════════════════
class ApplyOrderRequest(BaseModel):
    day: str
    tech_user_id: str
    ordered_customer_ids: List[str]


@router.post("/dispatch/board/apply-order", tags=["dispatch"],
              operation_id="dispatchBoard.applyOrder")
async def apply_order(
    body: ApplyOrderRequest,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    day = (body.day or "").lower()
    if not day or day == "all":
        raise HTTPException(400, "day must be a specific weekday")
    if not body.tech_user_id:
        raise HTTPException(400, "tech_user_id is required")
    await db.dispatch_route_orders.update_one(
        {"tenant_id": tenant["id"], "day": day,
          "tech_user_id": body.tech_user_id},
        {"$set": {
            "tenant_id": tenant["id"], "day": day,
            "tech_user_id": body.tech_user_id,
            "ordered_customer_ids": list(body.ordered_customer_ids),
            "updated_at": _now_iso(),
            "updated_by": user.get("id"),
        }},
        upsert=True,
    )
    return {"ok": True, "count": len(body.ordered_customer_ids)}


# ═════════════════════════════════════════════════════════════════
# POST /api/admin/customers/geocode-backfill
#
# Feb-2026 · Follow-up — Now accepts ``?dry_run=true`` for a scan-
# only pass (counts what WOULD be geocoded without hitting Google or
# writing to the customer doc). Also exposed under the canonical
# ``/admin/migrations/backfill-customer-geocodes`` alias so future
# callers use the migration-family naming convention. Both routes
# call the same handler.
# ═════════════════════════════════════════════════════════════════
@router.post("/admin/customers/geocode-backfill", tags=["dispatch"],
              operation_id="admin.customersGeocodeBackfill")
@router.post("/admin/migrations/backfill-customer-geocodes",
             tags=["dispatch"],
             operation_id="admin.migrations.backfillCustomerGeocodes")
async def geocode_backfill(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    limit: int = Query(500, ge=1, le=5000),
    dry_run: bool = Query(
        False,
        description="Feb-2026 · When true, report which customers WOULD be geocoded without hitting Google or writing to the customer doc. Non-idempotency risk: none.",
    ),
):
    _require_admin(user)
    from services.google_maps.geocoding import geocode_and_persist_customer
    # Legacy customers persist ``service_address`` as a structured
    # dict (``{street, city, state, zip}``) — the P37b flattener is
    # the canonical read-side normalizer.
    from services.google_maps.geocoding import _flatten_addr

    processed = geocoded = skipped = failed = 0
    would_geocode: List[str] = []
    async for c in db.customers.find(
        {"tenant_id": tenant["id"],
          "$or": [{"is_deleted": {"$ne": True}}, {"is_deleted": {"$exists": False}}]},
        {"_id": 0, "id": 1, "service_address": 1, "geocoded_at": 1,
         "latitude": 1, "longitude": 1},
    ):
        if processed >= limit:
            break
        processed += 1
        if not _flatten_addr(c.get("service_address")).strip():
            skipped += 1
            continue
        if dry_run:
            # Mirror the ``geocode_and_persist_customer`` skip-if-fresh
            # heuristic (30-day cache) so the dry-run count matches
            # what a live run would actually process.
            if c.get("geocoded_at"):
                try:
                    g = datetime.fromisoformat(
                        c["geocoded_at"].replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - g).days < 30:
                        skipped += 1
                        continue
                except Exception:
                    pass
            would_geocode.append(c["id"])
            geocoded += 1
            continue
        try:
            did = await geocode_and_persist_customer(c["id"], tenant["id"])
            if did:
                geocoded += 1
            else:
                skipped += 1
        except Exception as exc:
            logger.warning("[geocode-backfill] %s: %s", c.get("id"), exc)
            failed += 1
        await asyncio.sleep(0.1)  # ~10 QPS

    payload = {"processed": processed, "geocoded": geocoded,
               "skipped": skipped, "failed": failed,
               "dry_run": bool(dry_run)}
    if dry_run:
        payload["would_geocode"] = would_geocode
    return payload


# ═════════════════════════════════════════════════════════════════
# POST /api/dispatch/suggest-route  (Phase 17 · Smart Suggestions)
# ═════════════════════════════════════════════════════════════════
class _SuggestConstraints(BaseModel):
    allowed_days: Optional[List[str]] = None
    preferred_tech_user_ids: Optional[List[str]] = None
    max_added_minutes: Optional[float] = None


class SuggestRequest(BaseModel):
    customer_ids: List[str]
    constraints: Optional[_SuggestConstraints] = None


@router.post("/dispatch/suggest-route", tags=["dispatch"],
              operation_id="dispatchBoard.suggestRoute")
async def suggest_route(
    body: SuggestRequest,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_admin(user)
    if not body.customer_ids:
        raise HTTPException(400, "customer_ids required")
    constraints = body.constraints or _SuggestConstraints()
    max_added_min = constraints.max_added_minutes if constraints.max_added_minutes is not None else 25.0
    max_added_s = float(max_added_min) * 60.0

    from services.route_suggest import (
        build_candidate_day_routes, suggest_for_customer,
    )

    # Preload the customers + tech directory once.
    docs = await db.customers.find(
        {"tenant_id": tenant["id"], "id": {"$in": body.customer_ids}},
        {"_id": 0, "id": 1, "name": 1, "service_lat": 1, "service_lng": 1,
          "category_ids": 1, "service_days": 1, "assigned_tech_ids": 1},
    ).to_list(500)

    tech_directory: Dict[str, Dict[str, Any]] = {}
    async for u in db.users.find(
        {"tenant_id": tenant["id"], "role": "technician"},
        {"_id": 0, "id": 1, "name": 1, "display_color_hex": 1, "department": 1},
    ):
        tech_directory[u["id"]] = {
            "name": u.get("name") or u["id"],
            "color_hex": u.get("display_color_hex") or _hash_color(u["id"]),
            "department": u.get("department"),
        }

    routes = await build_candidate_day_routes(
        tenant["id"],
        allowed_days=constraints.allowed_days,
        preferred_techs=constraints.preferred_tech_user_ids,
    )

    results = []
    for c in docs:
        res = await suggest_for_customer(
            tenant["id"], c, routes, tech_directory, max_added_s,
        )
        results.append(res)
    return {"items": results, "total": len(results)}


async def geocode_backfill_all_tenants_boot() -> None:
    """Fire-and-forget on boot. Iterates every tenant so first-load
    of ``/dispatch`` has pins to render. Sleeps 150 ms between calls
    to stay well under Google's per-second cap even when several
    tenants boot together."""
    from services.google_maps.geocoding import geocode_and_persist_customer
    async for t in db.tenants.find({}, {"_id": 0, "id": 1, "slug": 1}):
        async for c in db.customers.find(
            {"tenant_id": t["id"],
              "service_address": {"$exists": True, "$ne": ""}},
            {"_id": 0, "id": 1},
        ):
            try:
                await geocode_and_persist_customer(c["id"], t["id"])
                await asyncio.sleep(0.15)
            except Exception:
                pass
        logger.info("[phase17] geocode boot pass complete for tenant=%s", t.get("slug"))
