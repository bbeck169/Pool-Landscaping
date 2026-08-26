"""Feb-2026 · Optimize Route (tech→admin approval flow) — algorithm helpers.

Pure functions, no DB access. Consumed by ``routers/route_optimization_approval.py``.

Design notes
------------
* Distance model:  Haversine great-circle in **miles**  (the mobile spec
  surfaces "miles saved" to the tech; internal storage keeps miles).
* Time model:      distance / 30 mph  +  2 minutes per stop-to-stop
                   transition (settle-in cost).
* Reshuffle rule:  jobs whose ``status`` is completed / could_not_service
                   / skipped / cancelled are **pinned** to their current
                   route_index. Only the reshufflable jobs get reordered
                   by nearest-neighbor from the supplied start point.
* No-op guard:     when the proposed order == the current order the
                   caller must interpret ``miles_saved == 0`` as "no
                   suggestion needed" and hide the pill.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Optional

# Statuses whose route_index is preserved on reorder.
PINNED_STATUSES = {"completed", "could_not_service", "skipped", "canceled", "cancelled"}

# Constants — externalised so tests can pin them.
AVG_SPEED_MPH = 30.0
TRANSITION_PENALTY_MIN = 2.0
EARTH_RADIUS_MILES = 3958.7613

# Feb-2026 · Google Routes API v2 hard waypoint cap. Optimizer requests
# with more intermediates than this must be rejected at the router
# layer (see spec: 400 with a friendly split-the-day message). Applies
# ONLY to reshufflable stops — pinned statuses don't count toward the
# cap because they never go through the Directions call.
GOOGLE_DIRECTIONS_MAX_WAYPOINTS = 25


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in statute miles."""
    la1, la2 = math.radians(lat1), math.radians(lat2)
    dla = math.radians(lat2 - lat1)
    dlo = math.radians(lng2 - lng1)
    a = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _tour_distance_miles(start: tuple[float, float] | None,
                         points_in_order: list[dict[str, Any]]) -> float:
    """Sum-of-legs from ``start`` (if given) through each point in order.

    ``points_in_order`` items must carry ``lat`` and ``lng`` keys.
    """
    if not points_in_order:
        return 0.0
    total = 0.0
    if start is not None:
        first = points_in_order[0]
        total += haversine_miles(start[0], start[1], first["lat"], first["lng"])
    for i in range(1, len(points_in_order)):
        a = points_in_order[i - 1]
        b = points_in_order[i]
        total += haversine_miles(a["lat"], a["lng"], b["lat"], b["lng"])
    return total


def _time_from_distance_min(miles: float, num_transitions: int) -> float:
    """Convert leg-total miles + transition count into an estimated minute total."""
    if miles <= 0 and num_transitions <= 0:
        return 0.0
    drive_min = (miles / AVG_SPEED_MPH) * 60.0
    settle_min = max(0, num_transitions) * TRANSITION_PENALTY_MIN
    return drive_min + settle_min


def nearest_neighbor_order(start: tuple[float, float],
                            points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``points`` reordered by greedy nearest-neighbor from ``start``.

    Each point must have ``lat`` and ``lng`` keys. Returns a NEW list; the
    input is not mutated. ``sequence`` is added to each row (0-based).
    """
    if not points:
        return []
    remaining = list(points)
    tour: list[dict[str, Any]] = []
    cur_lat, cur_lng = start
    while remaining:
        idx = min(
            range(len(remaining)),
            key=lambda i: haversine_miles(cur_lat, cur_lng,
                                            remaining[i]["lat"], remaining[i]["lng"]),
        )
        nxt = remaining.pop(idx)
        tour.append({**nxt, "sequence": len(tour)})
        cur_lat, cur_lng = nxt["lat"], nxt["lng"]
    return tour


def split_pinned_reshufflable(jobs: Iterable[dict[str, Any]]) -> tuple[list, list]:
    """Partition jobs into (pinned, reshufflable) by status.

    Preserves the input order within each partition (caller should have
    already sorted the list by ``route_index``).
    """
    pinned, reshuf = [], []
    for j in jobs:
        status = (j.get("status") or "").lower()
        if status in PINNED_STATUSES:
            pinned.append(j)
        else:
            reshuf.append(j)
    return pinned, reshuf


def merge_pinned_into_slots(pinned_by_index: dict[int, dict[str, Any]],
                             reshufflable_new_order: list[dict[str, Any]],
                             slot_count: int) -> list[dict[str, Any]]:
    """Interleave pinned jobs back at their original slot positions.

    ``pinned_by_index`` — {original_route_index: job_dict}
    ``reshufflable_new_order`` — list in NN order (no route_index yet)
    Returns a list of ``slot_count`` items in final order; ``route_index``
    on each item equals its position in the returned list.
    """
    out: list[dict[str, Any] | None] = [None] * slot_count
    for idx, job in pinned_by_index.items():
        if 0 <= idx < slot_count:
            out[idx] = {**job, "route_index": idx}
    cursor = 0
    for job in reshufflable_new_order:
        while cursor < slot_count and out[cursor] is not None:
            cursor += 1
        if cursor >= slot_count:
            break
        out[cursor] = {**job, "route_index": cursor}
        cursor += 1
    return [j for j in out if j is not None]


def compute_optimization(*, current_order_jobs: list[dict[str, Any]],
                          start_lat: float, start_lng: float
                          ) -> dict[str, Any]:
    """End-to-end preview computation.

    Input
    -----
    * ``current_order_jobs`` — list of job dicts sorted by their current
      route_index. Each must carry: id, status, lat, lng.
    * ``start_lat`` / ``start_lng`` — origin (tech's current GPS or the
      first pending stop's coords as fallback).

    Output
    -----
    * ``proposed_order`` — [job_id, ...] in the new order
    * ``miles_saved`` — >= 0
    * ``minutes_saved`` — >= 0
    * ``stops_affected`` — count of reshufflable jobs whose slot changed
    * ``pinned_ids`` — ids that stayed pinned
    * ``no_change`` — True when the proposal equals the current order
    """
    # Filter to jobs with resolvable coords; drop the rest silently.
    with_coords = [
        j for j in current_order_jobs
        if isinstance(j.get("lat"), (int, float))
        and isinstance(j.get("lng"), (int, float))
    ]
    pinned, reshuf = split_pinned_reshufflable(with_coords)
    slot_count = len(with_coords)
    if slot_count == 0 or len(reshuf) < 2:
        return {
            "proposed_order": [j["id"] for j in with_coords],
            "miles_saved": 0.0,
            "minutes_saved": 0.0,
            "stops_affected": 0,
            "pinned_ids": [j["id"] for j in pinned],
            "no_change": True,
        }

    # Original leg-total: [start → jobs in their current route_index order].
    current_miles = _tour_distance_miles((start_lat, start_lng), with_coords)

    # Nearest-neighbor over the reshufflable subset, from start.
    new_reshuf_order = nearest_neighbor_order((start_lat, start_lng), reshuf)

    # Reinsert pinned jobs at their original slot positions.
    original_indexes: dict[int, dict[str, Any]] = {}
    for job in with_coords:
        original_indexes[with_coords.index(job)] = job  # slot 0..N-1
    # Rebuild pinned_by_index by scanning ``with_coords`` order.
    pinned_by_index: dict[int, dict[str, Any]] = {}
    for i, job in enumerate(with_coords):
        if (job.get("status") or "").lower() in PINNED_STATUSES:
            pinned_by_index[i] = job

    final = merge_pinned_into_slots(pinned_by_index, new_reshuf_order, slot_count)
    new_miles = _tour_distance_miles((start_lat, start_lng), final)

    miles_saved = max(0.0, current_miles - new_miles)
    # transitions = number of legs; identical count for both orderings.
    transitions = max(0, len(with_coords) - 1)
    minutes_saved = max(
        0.0,
        _time_from_distance_min(current_miles, transitions)
        - _time_from_distance_min(new_miles, transitions),
    )

    proposed_ids = [j["id"] for j in final]
    current_ids = [j["id"] for j in with_coords]
    no_change = proposed_ids == current_ids

    # stops_affected — reshufflable slots whose id shifted between orderings.
    stops_affected = 0
    for pos, (cur, nxt) in enumerate(zip(current_ids, proposed_ids)):
        if cur != nxt:
            stops_affected += 1

    return {
        "proposed_order": proposed_ids,
        "miles_saved": round(miles_saved, 3),
        "minutes_saved": round(minutes_saved, 2),
        "stops_affected": stops_affected,
        "pinned_ids": [j["id"] for j in pinned],
        "no_change": no_change,
    }


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · Google Routes API v2 optimizer path.
#
# Shared helper for BOTH router surfaces:
#   * routers/route_optimization.py      (/api/schedule/optimize-route)
#   * routers/route_optimization_approval.py::preview
#
# Never raises. On any failure (empty input, >25 waypoints, HTTP error,
# missing API key, malformed response) returns None so the caller can
# fall back to the pure-Python Haversine implementation. Callers are
# expected to badge the response ``algorithm: "google_directions"`` on
# success, ``algorithm: "haversine_fallback"`` on None-return.
# ═══════════════════════════════════════════════════════════════════════
async def try_google_directions_optimize(
    *,
    start_lat: float,
    start_lng: float,
    waypoints: list[dict[str, Any]],
    dest_lat: Optional[float] = None,
    dest_lng: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Attempt a Google Routes API v2 optimize call.

    ``waypoints`` — list of dicts each carrying ``lat``/``lng`` (already
    coord-filtered by caller). Order in the input is the CURRENT order;
    the Google response's ``ordered_indices`` reorders them.

    Returns:
      * ``None`` — anything went wrong. Caller should fall back to
        Haversine and badge ``algorithm: "haversine_fallback"``.
      * ``{ordered_waypoints, total_distance_m, total_duration_s,
        total_miles, total_minutes, polyline, ordered_indices, legs}``
        — Google succeeded.
    """
    if not waypoints:
        return None
    if len(waypoints) > GOOGLE_DIRECTIONS_MAX_WAYPOINTS:
        return None
    try:
        from services.google_maps.directions import optimize_route as _google
    except Exception:
        return None
    coords = []
    for p in waypoints:
        la, lo = p.get("lat"), p.get("lng")
        if not isinstance(la, (int, float)) or not isinstance(lo, (int, float)):
            return None
        coords.append((float(la), float(lo)))
    try:
        origin = (float(start_lat), float(start_lng))
    except (TypeError, ValueError):
        return None
    dest = None
    if dest_lat is not None and dest_lng is not None:
        try:
            dest = (float(dest_lat), float(dest_lng))
        except (TypeError, ValueError):
            dest = None
    result = await _google(origin, coords, destination=dest)
    if not result:
        return None
    ordered_indices = result.get("ordered_indices") or list(range(len(waypoints)))
    ordered_wps = [waypoints[i] for i in ordered_indices if 0 <= i < len(waypoints)]
    if len(ordered_wps) != len(waypoints):
        # Google returned an index list that doesn't cover every input.
        # Bail — Haversine fallback is safer than a truncated route.
        return None
    total_m = int(result.get("total_distance_m") or 0)
    total_s = int(result.get("total_duration_s") or 0)
    return {
        "ordered_waypoints": ordered_wps,
        "ordered_indices": ordered_indices,
        "total_distance_m": total_m,
        "total_duration_s": total_s,
        # Convenience conversions for the approval-flow response shape.
        "total_miles": total_m / 1609.344,
        "total_minutes": total_s / 60.0,
        "polyline": result.get("polyline") or "",
        "legs": result.get("legs") or [],
    }


async def compute_optimization_v2(
    *,
    current_order_jobs: list[dict[str, Any]],
    start_lat: float,
    start_lng: float,
) -> dict[str, Any]:
    """Google-Directions-first version of :func:`compute_optimization`.

    Same input contract, same output shape — PLUS an ``algorithm``
    field: ``"google_directions"`` when the Google call succeeded,
    ``"haversine_fallback"`` when it fell through.

    Preserves the pinned-status protocol: completed / skipped / canceled
    / could_not_service stops keep their original slot; only reshufflable
    stops go through Google.
    """
    # Coord filter — mirrors compute_optimization for parity.
    with_coords = [
        j for j in current_order_jobs
        if isinstance(j.get("lat"), (int, float))
        and isinstance(j.get("lng"), (int, float))
    ]
    _pinned, reshuf = split_pinned_reshufflable(with_coords)
    # Trivial case — the sync fallback handles empty / <2 reshufflable.
    if len(reshuf) < 2:
        base = compute_optimization(
            current_order_jobs=current_order_jobs,
            start_lat=start_lat, start_lng=start_lng,
        )
        base["algorithm"] = "haversine_fallback"
        return base

    google = await try_google_directions_optimize(
        start_lat=start_lat, start_lng=start_lng,
        waypoints=reshuf,
    )
    if google is None:
        base = compute_optimization(
            current_order_jobs=current_order_jobs,
            start_lat=start_lat, start_lng=start_lng,
        )
        base["algorithm"] = "haversine_fallback"
        return base

    # Reinterleave pinned stops back at their original slots — same
    # protocol as compute_optimization.
    slot_count = len(with_coords)
    pinned_by_index: dict[int, dict[str, Any]] = {}
    for i, job in enumerate(with_coords):
        if (job.get("status") or "").lower() in PINNED_STATUSES:
            pinned_by_index[i] = job
    final = merge_pinned_into_slots(pinned_by_index, google["ordered_waypoints"], slot_count)

    # Savings — compute BOTH sides via Haversine so the units are
    # comparable. Google's ``total_distance_m`` is REAL road distance,
    # which will almost always exceed the Haversine crow-fly total even
    # after optimal ordering — mixing units would clamp miles_saved to
    # 0.0 on virtually every request and 422 the downstream /request
    # endpoint. The client-side savings chip only needs directional
    # accuracy, and Haversine-vs-Haversine on current vs proposed
    # ordering preserves that.
    current_miles = _tour_distance_miles((start_lat, start_lng), with_coords)
    new_miles = _tour_distance_miles((start_lat, start_lng), final)
    miles_saved = max(0.0, current_miles - new_miles)
    transitions = max(0, len(with_coords) - 1)
    current_minutes = _time_from_distance_min(current_miles, transitions)
    new_minutes = _time_from_distance_min(new_miles, transitions)
    minutes_saved = max(0.0, current_minutes - new_minutes)

    proposed_ids = [j["id"] for j in final]
    current_ids = [j["id"] for j in with_coords]
    no_change = proposed_ids == current_ids
    stops_affected = sum(1 for a, b in zip(current_ids, proposed_ids) if a != b)

    return {
        "proposed_order": proposed_ids,
        "miles_saved": round(miles_saved, 3),
        "minutes_saved": round(minutes_saved, 2),
        "stops_affected": stops_affected,
        "pinned_ids": [j["id"] for j in _pinned],
        "no_change": no_change,
        "algorithm": "google_directions",
    }


# ═══════════════════════════════════════════════════════════════════════
# Feb-2026 · ORION-inspired post-processing biases.
#
# Applied AFTER Google Routes API v2 returns an optimal order. Each
# heuristic is a swap-based local search that runs at most one pass
# over the ordered waypoints — it never re-solves the TSP.
#
# Heuristics shipped in Phase A:
#   * ``zip_cluster_swap_pass`` — nudge same-zip stops adjacent when a
#     swap doesn't blow the total-distance budget.
#
# Deferred to Phase B (see SHIPPED note):
#   * Right-turn preference — requires ``routes.legs.steps.navigation
#     Instruction`` in the field mask (billed extra by Google). Not
#     worth the incremental cost until Phase A ships and we validate
#     the base is stable.
#   * Contiguous-street bonus — low-signal in dense urban routes.
# ═══════════════════════════════════════════════════════════════════════

# Feb-2026 · ZIP tiebreaker budget. The swap is applied only when
# the Haversine delta (proposed vs base ordering) stays within this
# fraction of the base total. 2% mirrors UPS's published ORION
# tolerance for zip-cluster continuity vs pure-duration.
ZIP_CLUSTER_TIEBREAKER_BUDGET = 0.02


def _extract_zip(job: dict[str, Any]) -> Optional[str]:
    """Pull a ZIP / postal-code from a job dict.

    Tries (in order):
      1. Explicit ``zip`` key.
      2. ``postal_code`` key.
      3. ``address`` string — parse trailing digits (US ZIP shape).
    """
    for k in ("zip", "postal_code", "zipcode"):
        v = job.get(k)
        if v:
            return str(v).strip()[:5] or None
    addr = job.get("address") or job.get("stop_address") or ""
    if not addr:
        return None
    import re as _re
    m = _re.search(r"(\d{5})(?:-\d{4})?\s*$", str(addr))
    if m:
        return m.group(1)
    return None


def zip_cluster_swap_pass(
    *,
    ordered: list[dict[str, Any]],
    start_lat: float,
    start_lng: float,
    budget: float = ZIP_CLUSTER_TIEBREAKER_BUDGET,
) -> tuple[list[dict[str, Any]], list[str]]:
    """One-pass swap search that keeps same-zip stops adjacent when
    doing so doesn't inflate the total Haversine leg-distance by
    more than ``budget`` (default 2%).

    Contract:
      * Input ``ordered`` — already-optimized list from Google
        (or Haversine fallback). Each item must carry ``lat`` +
        ``lng``; ``zip`` / ``postal_code`` / ``address`` optional.
      * Returns ``(new_ordered, warnings)`` — ``new_ordered`` is a
        NEW list; input is not mutated. ``warnings`` accumulates
        any diagnostics (e.g. "zip data missing on N stops — skipped").

    No-op when: <3 stops, no ZIP data on any stop, or every swap
    would blow the budget.
    """
    warnings: list[str] = []
    if len(ordered) < 3:
        return list(ordered), warnings

    zips = [_extract_zip(j) for j in ordered]
    has_zip = sum(1 for z in zips if z)
    if has_zip < 2:
        warnings.append(
            "zip_cluster_tiebreaker skipped — no ZIP data available",
        )
        return list(ordered), warnings

    base_total = _tour_distance_miles((start_lat, start_lng), ordered)
    budget_miles = base_total * budget

    working = list(ordered)
    working_zips = list(zips)

    swaps_applied = 0
    # Scan for adjacent pairs A,B,C where A and C share a zip but B
    # doesn't — a swap of B and C would put A and C adjacent.
    i = 0
    while i < len(working) - 2:
        za, zb, zc = working_zips[i], working_zips[i + 1], working_zips[i + 2]
        if za and zc and za == zc and zb != za:
            # Candidate swap: swap positions (i+1) and (i+2).
            candidate = list(working)
            candidate[i + 1], candidate[i + 2] = candidate[i + 2], candidate[i + 1]
            new_total = _tour_distance_miles((start_lat, start_lng), candidate)
            if new_total <= base_total + budget_miles:
                working = candidate
                working_zips[i + 1], working_zips[i + 2] = (
                    working_zips[i + 2], working_zips[i + 1]
                )
                swaps_applied += 1
        i += 1

    if swaps_applied:
        warnings.append(
            f"zip_cluster_tiebreaker applied {swaps_applied} swap(s)",
        )
    return working, warnings
