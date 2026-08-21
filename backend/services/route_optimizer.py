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
from typing import Any, Iterable

# Statuses whose route_index is preserved on reorder.
PINNED_STATUSES = {"completed", "could_not_service", "skipped", "canceled", "cancelled"}

# Constants — externalised so tests can pin them.
AVG_SPEED_MPH = 30.0
TRANSITION_PENALTY_MIN = 2.0
EARTH_RADIUS_MILES = 3958.7613


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
