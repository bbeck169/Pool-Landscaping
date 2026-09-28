"""SO-A · Feb-2026 — top-level recommendation orchestrator.

Called by :mod:`routers.schedule_ai` after RBAC + rate-limit gates.
Loads eligible techs, computes best insertion per tech, ranks, and
synthesises DISPATCH plain-English lines.

Never mutates state.  A single ``ai_employee_actions`` audit row is
written by the router AFTER this helper returns — the algorithm
itself is pure read.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import logger
from services.fleet.eta import compute_eta as _fleet_compute_eta
from services.schedule_optimizer.detour import (
    Stop, best_insertion, score_from_detour,
)
from services.schedule_optimizer.origin import resolve_origin
from services.schedule_optimizer.persona import synthesize_plain_english
from services.tenant_ai_rules.gate import _within_working_hours
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant


def _db():
    """Lazy DB accessor so test fixtures can monkeypatch
    ``config.db`` and have it seen inside this module."""
    from config import db
    return db

MAX_SUGGESTIONS_HARD_CAP = 5
DISPATCH_EMPLOYEE_KEY = "dispatch"
REASSIGN_ACTION_KEY = "dispatch.reassign"


def _coords(obj: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    for lat_key, lng_key in (("latitude", "longitude"),
                              ("site_lat", "site_lng"),
                              ("lat", "lng")):
        lat, lng = obj.get(lat_key), obj.get(lng_key)
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)
    return None


def _resolve_apply_mode(rules: Dict[str, Any],
                          master_on: bool) -> str:
    """One-click when master is ON, dispatch enabled, and allowlist
    marks ``dispatch.reassign`` = auto.  Otherwise queued."""
    if not master_on:
        return "queued_for_approval"
    emp_on = bool((rules.get("employee_enable_disable") or {}).get(
        DISPATCH_EMPLOYEE_KEY, False))
    if not emp_on:
        return "queued_for_approval"
    mode = (rules.get("auto_action_allowlist") or {}).get(REASSIGN_ACTION_KEY)
    return "one_click" if mode == "auto" else "queued_for_approval"


async def _load_target_job(
    *, tenant_id: str, job_id: str,
) -> Optional[Dict[str, Any]]:
    return await _db().jobs.find_one(
        {"tenant_id": tenant_id, "id": job_id,
          "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    )


async def _load_route_for_tech(
    *, tenant_id: str, tech_id: str, target_date: str,
) -> List[Dict[str, Any]]:
    """Return the tech's jobs on ``target_date`` ordered by
    ``route_index`` asc (nulls sorted last).  Matches the ordering
    convention in :mod:`routers.jobs`.
    """
    cursor = _db().jobs.find(
        {"tenant_id": tenant_id,
          "technician_id": tech_id,
          "scheduled_date": target_date,
          "$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    )
    rows: List[Dict[str, Any]] = []
    if hasattr(cursor, "to_list"):
        rows = await cursor.to_list(500)
    else:
        async for r in cursor:                                     # pragma: no cover
            rows.append(r)
    # route_index None → sort last (∞).
    def _ri(job: Dict[str, Any]) -> float:
        v = job.get("route_index")
        return float(v) if isinstance(v, (int, float)) else float("inf")
    rows.sort(key=lambda j: (_ri(j),
                                str(j.get("scheduled_start") or ""),
                                str(j.get("created_at") or "")))
    return rows


async def _load_eligible_tech_docs(
    *, tenant_id: str, only_ids: Optional[List[str]],
) -> List[Dict[str, Any]]:
    """Load technician user docs.  If ``only_ids`` is set, restrict
    to those; otherwise pull every user with ``role in {"technician",
    "tech"}`` in the tenant.
    """
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if only_ids:
        q["id"] = {"$in": only_ids}
    else:
        q["role"] = {"$in": ["technician", "tech"]}
    cursor = _db().users.find(q, {"_id": 0})
    docs: List[Dict[str, Any]] = []
    if hasattr(cursor, "to_list"):
        docs = await cursor.to_list(500)
    else:
        async for r in cursor:                                     # pragma: no cover
            docs.append(r)
    return docs


async def _fleet_membership_map(*, tenant_id: str) -> Dict[str, bool]:
    cursor = _db().fleet_membership.find(
        {"tenant_id": tenant_id}, {"_id": 0, "tech_user_id": 1, "in_fleet": 1},
    )
    out: Dict[str, bool] = {}
    if hasattr(cursor, "to_list"):
        rows = await cursor.to_list(500)
    else:
        rows = []
        async for r in cursor:                                     # pragma: no cover
            rows.append(r)
    for r in rows:
        out[r.get("tech_user_id")] = bool(r.get("in_fleet"))
    return out


async def generate_recommendations(
    *, tenant_id: str, job_id: str, target_date: str,
    eligible_technician_ids: Optional[List[str]],
    max_suggestions: int,
    now_utc: Optional[datetime] = None,
    eta_fn=None,
) -> Dict[str, Any]:
    """Full orchestration.  See router docstring for response shape."""
    now = now_utc or datetime.now(timezone.utc)
    cap = max(1, min(int(max_suggestions or 3), MAX_SUGGESTIONS_HARD_CAP))
    eta_callable = eta_fn or _fleet_compute_eta

    # 1) Load target job.
    target_job = await _load_target_job(tenant_id=tenant_id, job_id=job_id)
    if target_job is None:
        return {
            "error_code": "target_job_not_found",
            "message": "Target job not visible under this tenant.",
        }
    target_coords = _coords(target_job)
    if target_coords is None:
        return {
            "error_code": "target_job_missing_coords",
            "message": (
                "Target job has no lat/lng — cannot compute a detour. "
                "Geocode the customer address first."
            ),
        }
    target_stop = Stop(job_id=target_job["id"],
                        lat=target_coords[0], lng=target_coords[1])

    # 2) Resolve tenant rules (fresh, not from cache — this is a
    #    proactive scheduling surface, admins expect live values).
    resolved = await resolve_rules_for_tenant(tenant_id, use_cache=True)
    rules = resolved.get("rules") or {}
    master_on = bool(resolved.get("master_ai_send_live_comms"))
    apply_mode = _resolve_apply_mode(rules, master_on)
    dispatch_enabled = master_on and bool(
        (rules.get("employee_enable_disable") or {}).get(
            DISPATCH_EMPLOYEE_KEY, False),
    )

    # 3) Load candidate techs.
    tech_docs = await _load_eligible_tech_docs(
        tenant_id=tenant_id, only_ids=eligible_technician_ids,
    )
    fleet_map = await _fleet_membership_map(tenant_id=tenant_id)

    unavailable: List[Dict[str, Any]] = []
    origin_source_map: Dict[str, Dict[str, Any]] = {}
    per_tech_results: List[Dict[str, Any]] = []

    # 4) Iterate techs.
    for t in tech_docs:
        tid = t.get("id")
        if not tid:
            continue
        in_fleet = fleet_map.get(tid, False)

        route = await _load_route_for_tech(
            tenant_id=tenant_id, tech_id=tid, target_date=target_date,
        )
        # Exclude techs with no route on target_date (per brief §3.1).
        if not route:
            unavailable.append({"technician_id": tid,
                                 "reason": "no_route_on_date"})
            continue

        # Origin cascade.
        origin_res = await resolve_origin(
            db=_db(), tenant_id=tenant_id, tech_user_id=tid,
            ordered_stops_today=route, now_utc=now,
        )
        if origin_res.lat is None:
            unavailable.append({"technician_id": tid,
                                 "reason": "origin_unresolvable"})
            continue
        origin_source_map[tid] = {
            "source": origin_res.source, "detail": origin_res.detail,
            "in_fleet": in_fleet,
        }

        # Build ordered stops.
        stops: List[Stop] = []
        for j in route:
            c = _coords(j)
            if c is None:
                continue
            stops.append(Stop(job_id=j["id"], lat=c[0], lng=c[1]))
        if not stops:
            unavailable.append({"technician_id": tid,
                                 "reason": "route_missing_coords"})
            continue

        # Working-hours gate (per brief §4).  Rule scope is
        # tenant-wide; we exclude techs whose insertion falls
        # outside the window.  ``_within_working_hours`` returns
        # ``(within: bool, reason: str)``.
        wh = rules.get("working_hours") or {}
        within, _wh_reason = _within_working_hours(wh, now)
        if not within:
            unavailable.append({"technician_id": tid,
                                 "reason": "outside_working_hours"})
            continue

        # Best insertion for this tech.
        try:
            best = await best_insertion(
                origin=(origin_res.lat, origin_res.lng),
                existing_stops=stops, target=target_stop,
                eta_fn=eta_callable,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.warning(
                "[so-a] best_insertion failed tenant=%s tech=%s err=%s",
                tenant_id, tid, exc,
            )
            unavailable.append({"technician_id": tid,
                                 "reason": "compute_error"})
            continue

        per_tech_results.append({
            "technician_id": tid,
            "technician_name": (
                t.get("name") or t.get("display_name") or tid
            ),
            "route_len": len(stops),
            "insertion_index": best.insertion_index,
            "detour_minutes": round(best.detour_seconds / 60.0, 2),
            "detour_miles": round(best.detour_meters / 1609.344, 2),
            "baseline_route_minutes": round(
                best.baseline_seconds / 60.0, 2),
            "with_insertion_route_minutes": round(
                best.with_insertion_seconds / 60.0, 2),
            "score": score_from_detour(best.detour_seconds),
            "provider_used": best.provider_used,
        })

    # 5) Rank ascending by detour.
    per_tech_results.sort(key=lambda r: r["detour_minutes"])
    top = per_tech_results[:cap]

    # 6) DISPATCH persona plain-English.
    persona_items = [
        {"tech_name": r["technician_name"],
          "insertion_index": r["insertion_index"],
          "detour_minutes": r["detour_minutes"],
          "detour_miles": r["detour_miles"],
          "route_len": r["route_len"]}
        for r in top
    ]
    persona_result = await synthesize_plain_english(
        tenant_id=tenant_id, resolved_rules=rules,
        items=persona_items, enabled=dispatch_enabled,
    )
    if not master_on:
        # Master off — force the deterministic template regardless
        # of the enabled flag (belt+braces).
        persona_result = {
            "lines": [_tmpl(r) for r in top],
            "source": "template_fallback_master_off",
            "llm_ms": 0,
        }

    for r, line, rank in zip(top, persona_result["lines"], range(1, len(top) + 1)):
        r["plain_english"] = line
        r["rank"] = rank

    # 7) Response shape.
    dominant_provider = "crowflies"
    if top:
        # Take the most common provider across the top results.
        counts: Dict[str, int] = {}
        for r in top:
            counts[r["provider_used"]] = counts.get(
                r["provider_used"], 0) + 1
        dominant_provider = max(counts.items(),
                                    key=lambda kv: kv[1])[0]

    return {
        "job_id": job_id,
        "target_date": target_date,
        "apply_mode": apply_mode,
        "dispatch_employee_enabled": dispatch_enabled,
        "master_switch_on": master_on,
        "plain_english_source": persona_result["source"],
        "suggestions": top,
        "unavailable_technicians": unavailable,
        "origin_source_map": origin_source_map,
        "provider_used": dominant_provider,
        "generated_at": now.isoformat(),
    }


def _tmpl(row: Dict[str, Any]) -> str:
    from services.schedule_optimizer.persona import template_line
    return template_line(
        tech_name=row["technician_name"],
        insertion_index=row["insertion_index"],
        detour_minutes=row["detour_minutes"],
        detour_miles=row["detour_miles"],
    )


__all__ = [
    "generate_recommendations", "MAX_SUGGESTIONS_HARD_CAP",
    "DISPATCH_EMPLOYEE_KEY", "REASSIGN_ACTION_KEY",
]
