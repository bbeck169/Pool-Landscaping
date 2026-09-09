"""Phase 20A.1 · Route optimization for a tech's daily job list.

Nearest-neighbor Haversine ordering, cached per-day per-user, ready to be
upgraded to Google Directions/Distance-Matrix later without changing the
public contract. Emits a `route_optimized` WS event so the schedule UI can
reorder cards without a manual reload.

Feb-2026 · Slice 4 (MP1.6) — stops with ``property_id`` set now route on
the property's coords + address instead of the customer default. See
``services.stop_geo.resolve_stop_geo``.
"""
import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, new_id, get_current_user
from utils import not_deleted_filter as _nd
from routers.tenants import get_current_tenant
from services.stop_geo import resolve_stop_geo
from services.route_optimizer import (
    GOOGLE_DIRECTIONS_MAX_WAYPOINTS,
    try_google_directions_optimize,
    zip_cluster_swap_pass,
)

# Reuse the existing Haversine + settings helpers.
from routers.workforce import _haversine_m, _settings  # type: ignore

router = APIRouter()


class OptimizeIn(BaseModel):
    date: Optional[str] = None      # YYYY-MM-DD (defaults today)
    start_lat: Optional[float] = None
    start_lng: Optional[float] = None


def _waypoints_hash(job_ids: List[str], start_lat, start_lng) -> str:
    payload = "|".join(sorted(job_ids)) + f"|{start_lat}|{start_lng}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _estimate_duration_s(distance_m: float) -> int:
    """~35 km/h neighborhood-average driving. Good enough for card badges."""
    if distance_m <= 0:
        return 0
    return int(distance_m / (35 * 1000 / 3600))


@router.post("/schedule/optimize-route")
async def optimize_route(
    body: OptimizeIn = OptimizeIn(),
    user_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Optimize the driving order for a tech's today (or `date`) job list.

    Response contract (canonical — every branch returns the same shape;
    tests in ``test_route_optimization_google_directions.py`` and
    ``test_route_optimizer_response_contract.py`` lock this down):

      * ``ordered_job_ids: list[str]`` — planned traversal order.
      * ``total_distance_m: float`` — meters. 0 when <2 stops.
      * ``total_duration_s: int``   — seconds. 0 when <2 stops.
      * ``legs: list[dict]``        — pairwise legs (``from_job_id``,
                                       ``to_job_id``, ``distance_m``,
                                       ``duration_s``, ``polyline``).
      * ``cached: bool``            — true on cache hit.
      * ``algorithm: str``          — one of ``"trivial"``,
                                       ``"directions_v2+orion_bias"``,
                                       ``"haversine_fallback"``.
      * ``warnings: list[str]``     — ORION heuristic notes on the
                                       Google path; a Haversine
                                       fallback message on failure
                                       (transport-layer OR zero-legs
                                       degenerate-route guard).

    ``algorithm`` mapping:
      * ``"trivial"`` — <2 geocoded stops.
      * ``"directions_v2+orion_bias"`` — Google returned a route with
                                     positive leg distances AND the
                                     ORION zip-cluster pass ran to
                                     completion (with or without
                                     appended warnings). This is the
                                     canonical Google-success badge
                                     for this endpoint. The legacy
                                     ``"google_directions"`` value
                                     is retired — every Google-
                                     success response on the schedule
                                     endpoint runs the ORION pass, so
                                     the badge is always composite.
      * ``"haversine_fallback"`` — Google unavailable / errored OR
                                     Google returned a degenerate
                                     all-zero-legs route (guarded
                                     via a diagnostic WARN log +
                                     Haversine fallback so the
                                     endpoint never silently ships
                                     zero-distance data). The
                                     ``warnings`` list carries the
                                     specific reason.
    """
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    # Feb-2026 HOTFIX (live user report) — the Optimize Route bulk
    # action is a dispatcher / planner tool. Technicians must not
    # invoke it, even though they can PATCH their own jobs. This is
    # defense-in-depth alongside the FE hide of the toolbar button.
    if (user.get("role") or "").lower() == "technician":
        raise HTTPException(
            403,
            "Optimize Route is a dispatcher action — technicians cannot "
            "invoke it. Ask your dispatcher to reorder the day.",
        )
    # Only admins can override which user to optimize for.
    target_uid = user["id"]
    if user_id and user.get("role") in ("admin", "super_admin"):
        target_uid = user_id
    elif user_id and user_id != user["id"]:
        raise HTTPException(403, "Cannot optimize another user's route")

    # Hard cross-tenant guard: if the caller is planning for someone else,
    # that user must exist and belong to the caller's current tenant.
    if target_uid != user["id"]:
        other = await db.users.find_one({"id": target_uid},
                                        {"_id": 0, "id": 1, "tenant_id": 1})
        if not other:
            raise HTTPException(404, "user_id not found")
        if other.get("tenant_id") != tenant["id"]:
            raise HTTPException(403, "user_id not in current tenant")

    date_str = body.date or datetime.now(timezone.utc).date().isoformat()
    day_start = f"{date_str}T00:00:00+00:00"
    day_end   = f"{date_str}T23:59:59+00:00"

    # Load the target user's assigned jobs for the day.
    target_user = await db.users.find_one({"id": target_uid, "tenant_id": tenant["id"]},
                                          {"_id": 0})
    tech_id = (target_user or {}).get("technician_id") or target_uid
    query = {
        "tenant_id": tenant["id"],
        "$or": [
            {"technician_id": target_uid},
            {"technician_id": tech_id},
            {"assigned_technician_id": target_uid},
        ],
        "status": {"$nin": ["completed", "cancelled"]},
        "scheduled_start": {"$gte": day_start, "$lte": day_end},
    }
    query = {**query, **_nd()}
    jobs = await db.jobs.find(query, {"_id": 0}).to_list(100)
    # Feb-2026 · Slice 4 (MP1.6) — resolve every stop through the
    # shared stop-geo resolver so a job with ``property_id`` set uses
    # the property's coords (lazy-geocoding the property once when
    # its geocode cache is cold). The resolved coords land back on
    # the working job dict as ``site_lat/site_lng`` so the existing
    # nearest-neighbour loop below (which reads those keys) is
    # unchanged. Also cache ``address_source`` so the WS payload can
    # surface it for the UI.
    for j in jobs:
        geo = await resolve_stop_geo(j, tenant["id"], geocode_if_missing=True)
        if geo.get("lat") is not None and geo.get("lng") is not None:
            j["site_lat"] = geo["lat"]
            j["site_lng"] = geo["lng"]
        j["address_source"] = geo.get("address_source", "customer")
        if geo.get("address"):
            j["stop_address"] = geo["address"]
    jobs_with_geo = [
        j for j in jobs
        if (j.get("site_lat") is not None or j.get("lat") is not None)
        and (j.get("site_lng") is not None or j.get("lng") is not None)
    ]
    if len(jobs_with_geo) < 2:
        return {
            "ordered_job_ids": [j["id"] for j in jobs_with_geo],
            "total_distance_m": 0, "total_duration_s": 0,
            "legs": [], "cached": False, "algorithm": "trivial",
            "warnings": ["Need at least 2 stops to optimize."],
        }

    # Feb-2026 · Google Routes API v2 hard cap. Beyond 25 intermediates
    # the modern Routes API rejects the request; per spec we return a
    # clean 400 with a friendly message instead of silently degrading.
    if len(jobs_with_geo) > GOOGLE_DIRECTIONS_MAX_WAYPOINTS:
        raise HTTPException(
            400,
            {
                "code": "too_many_stops",
                "max_waypoints": GOOGLE_DIRECTIONS_MAX_WAYPOINTS,
                "actual": len(jobs_with_geo),
                "message": (
                    f"Route optimization supports up to "
                    f"{GOOGLE_DIRECTIONS_MAX_WAYPOINTS} stops per day — "
                    f"this day has {len(jobs_with_geo)}. Split the day "
                    f"or reduce the stop count to try again."
                ),
            },
        )

    job_ids = [j["id"] for j in jobs_with_geo]
    whash = _waypoints_hash(job_ids, body.start_lat, body.start_lng)
    cached = await db.route_optimizations.find_one(
        {"tenant_id": tenant["id"], "user_id": target_uid,
         "date": date_str, "waypoints_hash": whash},
        {"_id": 0},
    )
    if cached:
        cached["cached"] = True
        return cached

    # Feb-2026 · Try Google Routes API v2 first. Returns None on any
    # failure (network / quota / missing key / >25 waypoints already
    # guarded above); we then fall through to the pure-Python Haversine
    # nearest-neighbor loop below. The savings chip on the client stays
    # correct in both branches because it computes savings vs its own
    # baseline (Haversine of original order) rather than trusting the
    # server's total_distance_m as the "before" number.
    google_waypoints = [
        {
            "id": j["id"],
            "lat": j.get("site_lat") if j.get("site_lat") is not None else j.get("lat"),
            "lng": j.get("site_lng") if j.get("site_lng") is not None else j.get("lng"),
        }
        for j in jobs_with_geo
    ]
    google_start_lat = body.start_lat if body.start_lat is not None else google_waypoints[0]["lat"]
    google_start_lng = body.start_lng if body.start_lng is not None else google_waypoints[0]["lng"]
    google = None
    if google_start_lat is not None and google_start_lng is not None:
        google = await try_google_directions_optimize(
            start_lat=float(google_start_lat),
            start_lng=float(google_start_lng),
            waypoints=google_waypoints,
            tenant_id=tenant["id"],
        )

    if google is not None:
        by_id = {j["id"]: j for j in jobs_with_geo}
        ordered = [by_id[wp["id"]] for wp in google["ordered_waypoints"]
                    if wp["id"] in by_id]
        # Feb-2026 · ORION-inspired zip-cluster tiebreaker (Phase A).
        # Applied ONLY over the reshufflable subset Google returned
        # (pinned stops are handled elsewhere in this codebase's
        # approval-flow router; ``/schedule/optimize-route`` is
        # already reshufflable-only per the earlier ``status`` filter).
        # Never blocks the response — warnings are surfaced verbatim.
        orion_warnings: list = []
        _start_lat = float(google_start_lat)
        _start_lng = float(google_start_lng)
        for j in ordered:
            if j.get("site_lat") is not None: j["lat"] = j.get("site_lat")
            if j.get("site_lng") is not None: j["lng"] = j.get("site_lng")
        try:
            ordered, orion_warnings = zip_cluster_swap_pass(
                ordered=ordered,
                start_lat=_start_lat,
                start_lng=_start_lng,
            )
        except Exception as exc:                                # noqa: BLE001
            orion_warnings = [f"zip_cluster_tiebreaker error: {exc}"]
        legs: list = []
        for i in range(1, len(ordered)):
            leg_google = google["legs"][i - 1] if i - 1 < len(google["legs"]) else {}
            legs.append({
                "from_job_id": ordered[i - 1]["id"],
                "to_job_id": ordered[i]["id"],
                "distance_m": int(leg_google.get("distance_m") or 0),
                "duration_s": int(leg_google.get("duration_s") or 0),
                "polyline": None,
            })

        # Feb-2026 · P1 · Zero-distance leg guard. Google Routes API
        # v2 sometimes returns a "successful" 200 that describes a
        # degenerate route — every leg is 0m/0s (e.g. all waypoints
        # collapsed onto the same coord because ``resolve_stop_geo``
        # attached them all to a shared property, or a silent quota
        # / API-enable failure surfaces as an empty-leg response).
        # If we cache that we'd silently ship zero-distance routes to
        # techs. Detect and fall through to the Haversine block
        # below so ``total_distance_m`` is at least a crow-fly
        # estimate; append a client-facing warning so the Reorder
        # modal renders the yellow banner.
        google_total_m = int(google.get("total_distance_m") or 0)
        legs_total_m  = sum((l.get("distance_m") or 0) for l in legs)
        if legs and (legs_total_m == 0 and google_total_m == 0):
            # Redacted diagnostic — the ``google`` dict never carries
            # the API key (the wrapper strips it before returning),
            # but we still redact defensively in case the shape
            # changes upstream.
            _safe_google = {k: v for k, v in google.items()
                             if k not in ("api_key", "authorization")}
            try:
                logger.warning(
                    "[optimize-route] Google Directions returned zero-distance "
                    "legs — tenant=%s user=%s date=%s stops=%d ordered=%s "
                    "google_payload=%s. Falling back to Haversine.",
                    tenant["id"], target_uid, date_str, len(ordered),
                    [j["id"] for j in ordered],
                    _safe_google,
                )
            except Exception:
                pass
            # Signal the fallback branch below to badge + warn.
            _zero_legs_reason = (
                "Google Directions returned zero-distance legs — falling "
                "back to Haversine (drive-time estimate unavailable)."
            )
        else:
            out = {
                "ordered_job_ids": [j["id"] for j in ordered],
                "total_distance_m": int(google["total_distance_m"]),
                "total_duration_s": int(google["total_duration_s"]),
                "legs": legs,
                "cached": False,
                # Feb-2026 · P1 · Canonical Google-path badge. The
                # legacy ``"google_directions"`` value was retired —
                # the schedule endpoint always runs the ORION zip-
                # cluster pass, so every Google-success response
                # carries the composite badge (whether or not ORION
                # emitted a warning). See docstring above + the
                # response-contract test suite.
                "algorithm": "directions_v2+orion_bias",
                # Feb-2026 · P0-frontend contract — surface every ORION
                # heuristic warning + any transport-layer note so the
                # client can render a yellow banner in the Reorder modal.
                "warnings": orion_warnings,
                "date": date_str,
                "waypoints_hash": whash,
                "tenant_id": tenant["id"],
                "user_id": target_uid,
                "computed_at": now_iso(),
            }
            await db.route_optimizations.insert_one(dict(out))
            try:
                from routers.realtime import bus
                await bus.broadcast(target_uid, {
                    "type": "route_optimized",
                    "payload": {"ordered_job_ids": out["ordered_job_ids"],
                                "total_distance_m": out["total_distance_m"]},
                })
            except Exception as e:
                logger.warning(f"WS notify (route_optimized) failed: {e}")
            return out
    else:
        _zero_legs_reason = None  # Google unavailable / errored.

    # Nearest-neighbor from the start (or first job).
    start = (body.start_lat, body.start_lng) if body.start_lat and body.start_lng else None
    remaining = list(jobs_with_geo)
    ordered: list = []
    legs: list = []
    total_m = 0.0
    prev_lat, prev_lng = start if start else (None, None)
    while remaining:
        if prev_lat is None:
            nxt = remaining[0]
        else:
            nxt = min(remaining, key=lambda j: _haversine_m(
                prev_lat, prev_lng,
                j.get("site_lat") or j.get("lat"),
                j.get("site_lng") or j.get("lng"),
            ))
            d = _haversine_m(
                prev_lat, prev_lng,
                nxt.get("site_lat") or nxt.get("lat"),
                nxt.get("site_lng") or nxt.get("lng"),
            )
            legs.append({
                "from_job_id": ordered[-1]["id"] if ordered else None,
                "to_job_id": nxt["id"],
                "distance_m": round(d, 1),
                "duration_s": _estimate_duration_s(d),
                "polyline": None,
            })
            total_m += d
        ordered.append(nxt)
        prev_lat = nxt.get("site_lat") or nxt.get("lat")
        prev_lng = nxt.get("site_lng") or nxt.get("lng")
        remaining.remove(nxt)

    out = {
        "ordered_job_ids": [j["id"] for j in ordered],
        "total_distance_m": round(total_m, 1),
        "total_duration_s": _estimate_duration_s(total_m),
        "legs": legs,
        "cached": False,
        "algorithm": "haversine_fallback",
        # Feb-2026 · Optimize Route contract — signal to the client
        # that Google was unavailable so the modal can render the
        # "Directions unavailable — review manually" warning banner.
        # P1 · The zero-legs guard emits a more specific message so
        # operators can distinguish "Google unreachable" from "Google
        # returned a degenerate route" (usually a shared-property /
        # geocode collapse). Both trigger the same yellow banner.
        "warnings": [
            _zero_legs_reason
            if _zero_legs_reason
            else "Directions unavailable — using Haversine fallback. "
                 "Review order manually."
        ],
        "date": date_str,
        "waypoints_hash": whash,
        "tenant_id": tenant["id"],
        "user_id": target_uid,
        "computed_at": now_iso(),
    }
    await db.route_optimizations.insert_one(dict(out))
    # WS notify — best-effort.
    try:
        from routers.realtime import bus
        await bus.broadcast(target_uid, {
            "type": "route_optimized",
            "payload": {"ordered_job_ids": out["ordered_job_ids"],
                        "total_distance_m": out["total_distance_m"]},
        })
    except Exception as e:
        logger.warning(f"WS notify (route_optimized) failed: {e}")
    return out


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 4 (MP1.6) — Route stops read endpoint
# ═══════════════════════════════════════════════════════════════════════
@router.get("/routes/{tech_id}/stops")
async def get_route_stops(
    tech_id: str,
    date: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """List a tech's route stops for a date, resolved property-first.

    Each stop's ``address`` + ``lat`` + ``lng`` come from the
    property doc when ``property_id`` is set (falling back to the
    customer-scoped coords otherwise). ``address_source`` is
    ``"property"`` or ``"customer"`` for debuggability.

    Admin can query any tech in the tenant; a tech can only query
    themselves; customers are 403'd (unchanged with the optimizer).
    """
    if user.get("role") == "customer":
        raise HTTPException(403, "Not allowed")
    if user.get("role") not in ("admin", "super_admin"):
        # A technician can only fetch their own route stops. Both the
        # ``id`` (user row) and ``technician_id`` (technicians table)
        # forms are accepted so older seeds still resolve.
        if tech_id not in (user.get("id"), user.get("technician_id")):
            raise HTTPException(403, "Cannot read another user's route")

    date_str = date or datetime.now(timezone.utc).date().isoformat()
    day_start = f"{date_str}T00:00:00+00:00"
    day_end = f"{date_str}T23:59:59+00:00"

    # Load the tech row so we can match either user_id or technician_id
    # on the jobs collection (mirrors ``optimize_route``).
    # Feb-2026 · Routes enrichment — also read ``name`` and
    # ``display_color_hex`` in the same round-trip so the UI can show
    # the tech's name + color chip without an N+1 fetch.
    tech_user = await db.users.find_one(
        {"id": tech_id, "tenant_id": tenant["id"]},
        {"_id": 0, "id": 1, "technician_id": 1,
         "name": 1, "display_color_hex": 1},
    ) or {}
    # Feb-2026 · Routes enrichment · tech-id fragmentation fallback.
    # ``/api/technicians`` surfaces the ``technicians`` collection id,
    # which may differ from the ``users`` row id for the same human.
    # When ``users`` misses on ``tech_id``, look up the technicians
    # collection so ``tech_name`` + ``tech_color_hex`` still populate
    # (the durable fix is in ``/app/memory/known_issues.md``).
    if not tech_user:
        tech_row = await db.technicians.find_one(
            {"id": tech_id, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "user_id": 1,
             "name": 1, "display_color_hex": 1},
        ) or {}
        if tech_row:
            tech_user = {
                "id": tech_row.get("user_id") or tech_row.get("id"),
                "technician_id": tech_row.get("id"),
                "name": tech_row.get("name"),
                "display_color_hex": tech_row.get("display_color_hex"),
            }
    tid = tech_user.get("technician_id") or tech_id
    # ``user_side_id`` is the ``users`` row id when we resolved from
    # ``technicians`` — jobs seeded against either id must match.
    user_side_id = tech_user.get("id") or tech_id

    q = {
        "tenant_id": tenant["id"],
        "$or": [
            {"technician_id": tech_id},
            {"technician_id": tid},
            {"technician_id": user_side_id},
            {"assigned_technician_id": tech_id},
            {"assigned_technician_id": user_side_id},
        ],
        "status": {"$nin": ["completed", "cancelled"]},
        # Feb-2026 · Routes enrichment · match jobs stored with
        # either the ``scheduled_start`` datetime (post-optimizer)
        # or the flat ``scheduled_date`` ISO string (legacy seeds +
        # recurring-generator writes). Without this the enrichment
        # endpoint silently drops any job that never hit the
        # optimizer, which is most of them.
        "$and": [{
            "$or": [
                {"scheduled_start": {"$gte": day_start, "$lte": day_end}},
                {"scheduled_date": date_str},
            ],
        }],
    }
    q = {**q, **_nd()}
    jobs = await db.jobs.find(q, {"_id": 0}).sort(
        [("route_order", 1), ("scheduled_start", 1)]
    ).to_list(200)

    # Feb-2026 · Ops Routes fix — batch-fetch customers for every
    # job that has a ``customer_id`` but empty ``customer_name`` on
    # the job doc. Avoids the N+1 per stop AND makes the display
    # name fallback authoritative (name → billing_name → display_name
    # → service_address → "(no customer)"). The address fallback now
    # lives on the display-name chain explicitly, not conflated with
    # a title-typed fallback that hides real customer identity.
    needy_cids = {j.get("customer_id") for j in jobs
                  if j.get("customer_id")
                     and not (j.get("customer_name") or "").strip()}
    cust_map: Dict[str, dict] = {}
    if needy_cids:
        async for c in db.customers.find(
            {"id": {"$in": list(needy_cids)}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "billing_name": 1,
             "display_name": 1, "service_address": 1},
        ):
            cust_map[c["id"]] = c

    stops: List[dict] = []
    for j in jobs:
        geo = await resolve_stop_geo(j, tenant["id"], geocode_if_missing=False)
        # Prefer the denormalised name on the job. When missing, look
        # up the customer doc (batched above) and walk the name
        # chain. Address is the LAST resort — "(no customer)" is the
        # ultimate fallback so the UI never leaks "Weekly Pool Service"
        # into the primary line.
        name_on_job = (j.get("customer_name") or "").strip()
        cust = cust_map.get(j.get("customer_id")) if not name_on_job else None
        display_name = (
            name_on_job
            or ((cust or {}).get("name") or "").strip()
            or ((cust or {}).get("billing_name") or "").strip()
            or ((cust or {}).get("display_name") or "").strip()
            or ((cust or {}).get("service_address") or "").strip()
            or (geo.get("address") or "").strip()
            or "(no customer)"
        )
        stops.append({
            "job_id": j.get("id"),
            "title": j.get("title"),
            "service_type": j.get("service_type") or j.get("job_type"),
            "customer_id": j.get("customer_id"),
            "customer_name": j.get("customer_name") or (
                (cust or {}).get("name")
                or (cust or {}).get("billing_name")
                or (cust or {}).get("display_name")
                or None
            ),
            "customer_display_name": display_name,
            "billing_name": (cust or {}).get("billing_name") or None,
            "service_address": (cust or {}).get("service_address") or None,
            "property_id": j.get("property_id"),
            "property_label": j.get("property_label"),
            "scheduled_start": j.get("scheduled_start"),
            "scheduled_end": j.get("scheduled_end"),
            "status": j.get("status"),
            "route_order": j.get("route_order"),
            "address": geo.get("address"),
            "lat": geo.get("lat"),
            "lng": geo.get("lng"),
            "address_source": geo.get("address_source"),
        })

    return {
        "tech_id": tech_id,
        "tech_name": tech_user.get("name"),
        "tech_color_hex": tech_user.get("display_color_hex"),
        "date": date_str,
        "count": len(stops),
        "stops": stops,
    }
