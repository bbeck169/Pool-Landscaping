"""Phase 16C — Tech Today Schedule endpoint.

Returns a chronologically ordered list of items for *the current user, today*:
  - jobs assigned to them scheduled for today
  - time_entries (shifts) they opened today (from Phase 16A)
  - break intervals inside those shifts

Also emits `route_legs` between consecutive jobs so the client can hydrate
driving time/distance via the Google Distance Matrix JS API. If a
`distance_matrix_cache` entry already exists for a leg, we hydrate it
server-side so the client can skip the Distance Matrix call.

Endpoints (all tenant-scoped)
-----------------------------
* GET  /api/schedule/today
* POST /api/schedule/route-leg    (client-provided distance/duration cache write)
* POST /api/schedule/reschedule   (Feb-2026 · admin drag-and-drop reschedule)
"""
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from config import db, logger
from utils import now_iso, get_current_user, new_id
from routers.tenants import get_current_tenant

router = APIRouter()


DEFAULT_TZ = "America/Phoenix"  # Pool & Landscaping HQ, no DST → consistent


def _today_bounds_utc(tz_name: str, date_str: Optional[str] = None) -> tuple:
    """Return (start_iso, end_iso) UTC ISO strings covering the requested day
    (or *today* in the given tz when date_str is None). Simplified: bucket by
    UTC midnight ±14h so we safely catch every reasonable tz. Client filters
    again in local tz when rendering."""
    if date_str:
        try:
            anchor = datetime.fromisoformat(date_str + "T12:00:00+00:00")
        except Exception:
            anchor = datetime.now(timezone.utc)
    else:
        anchor = datetime.now(timezone.utc)
    start = (anchor - timedelta(hours=14)).replace(microsecond=0)
    end = (anchor + timedelta(hours=14)).replace(microsecond=0)
    return start.isoformat(), end.isoformat()


def _cache_key(from_lat, from_lng, to_lat, to_lng):
    return f"{round(from_lat, 4)},{round(from_lng, 4)}|{round(to_lat, 4)},{round(to_lng, 4)}"


# ═══════════════════════════════════════════════════════════════════
# Phase R1.1 · Feb-2026 — Schedule 500 · technician_id mismatch hotfix.
# ═══════════════════════════════════════════════════════════════════
# Some tenants carry ``jobs.technician_id`` values keyed in either the
# ``technicians.id`` space (canonical) OR the legacy ``users.id`` space
# (pre-K42 seed) OR a "ghost" id that no longer resolves in either
# collection (tech deleted / re-provisioned).  Any caller that assumed
# a single id space + a live technician doc could 500 with
# ``AttributeError`` on a subsequent ``.get(...)`` off ``None``.
#
# This helper resolves BOTH id spaces AND returns an empty set when
# nothing is live for the tenant.  Callers use ``in`` for the Safe
# Check (``if tid and tid not in live: skip + WARN``) so a bogus ref
# never crashes the endpoint.
# ═══════════════════════════════════════════════════════════════════
async def _live_technician_id_space(tenant_id: str) -> set:
    """Return the union of every live technician identifier for
    ``tenant_id`` across BOTH id spaces:

    * ``technicians.id``  — canonical (K42+ writes)
    * ``technicians.user_id`` — back-ref shape (legacy seed)
    * ``users.id`` where ``role`` in {technician, tech, owner, admin,
      manager, super_admin}  — legacy jobs that stamped
      ``technician_id = user.id``
    * ``users.technician_id``   — the JWT claim shape

    Deleted / soft-deleted rows are excluded on both collections so
    a Safe Check on this set catches stale assignments cleanly.
    """
    ids: set = set()
    async for row in db.technicians.find(
        {"tenant_id": tenant_id, "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ]},
        {"_id": 0, "id": 1, "user_id": 1},
    ):
        if row.get("id"):
            ids.add(row["id"])
        if row.get("user_id"):
            ids.add(row["user_id"])
    async for row in db.users.find(
        {"tenant_id": tenant_id, "role": {"$in": [
            "technician", "tech", "owner", "admin", "manager", "super_admin",
        ]}, "$or": [
            {"deleted_at": None},
            {"deleted_at": {"$exists": False}},
        ]},
        {"_id": 0, "id": 1, "technician_id": 1},
    ):
        if row.get("id"):
            ids.add(row["id"])
        if row.get("technician_id"):
            ids.add(row["technician_id"])
    return ids


async def _resolve_tech_display(tenant_id: str,
                                 tid: Optional[str]) -> Optional[str]:
    """Resolve ``tid`` to a display name across BOTH id spaces.
    Returns ``None`` (never raises) when the id is null or does not
    match any live tech / user in the tenant. Callers that received
    ``None`` should render "Unassigned" and NEVER crash.
    """
    if not tid:
        return None
    # 1 · users.id (legacy jobs stamped technician_id = user.id).
    u = await db.users.find_one(
        {"tenant_id": tenant_id, "id": tid},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1},
    )
    if u:
        nm = (u.get("name") or "").strip()
        if not nm:
            nm = f"{u.get('first_name','')} {u.get('last_name','')}".strip()
        if nm:
            return nm
    # 2 · users.technician_id (JWT claim shape).
    u = await db.users.find_one(
        {"tenant_id": tenant_id, "technician_id": tid},
        {"_id": 0, "name": 1, "first_name": 1, "last_name": 1},
    )
    if u:
        nm = (u.get("name") or "").strip()
        if not nm:
            nm = f"{u.get('first_name','')} {u.get('last_name','')}".strip()
        if nm:
            return nm
    # 3 · technicians.id (canonical K42+ write).
    t = await db.technicians.find_one(
        {"tenant_id": tenant_id, "id": tid},
        {"_id": 0, "name": 1},
    )
    if t and (t.get("name") or "").strip():
        return t["name"].strip()
    # 4 · technicians.user_id (back-ref shape).
    t = await db.technicians.find_one(
        {"tenant_id": tenant_id, "user_id": tid},
        {"_id": 0, "name": 1},
    )
    if t and (t.get("name") or "").strip():
        return t["name"].strip()
    return None


@router.get("/schedule/today")
async def schedule_today(request: Request,
                         date: Optional[str] = None,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    """Return the tech's timeline for `date` (YYYY-MM-DD) or today when omitted.
    Alias `/schedule/day` accepts the same query.

    Feb-2026 · Task 5 perf instrumentation — the handler pushes
    phase timings into ``request.state.timings`` so the
    ``ServerTimingMiddleware`` in ``server.py`` emits them under the
    ``Server-Timing`` response header.  Fields:

      * ``crews;dur=X``   — my_crew_ids prefetch (tenant scan).
      * ``jobs;dur=X``    — main jobs query (tech + crew visibility).
      * ``custs;dur=X``   — bulk gate-code/notes prefetch.
      * ``entries;dur=X`` — time entries prefetch.
      * ``legs;dur=X``    — batched distance_matrix_cache lookup.

    Any prod slowness now surfaces the culprit phase in DevTools
    without a code deploy.
    """
    import time as _t
    _timings = request.state.timings if hasattr(request.state, "timings") else []
    tid = tenant["id"]
    # Feb-2026 · Timezone Finalization — read the canonical
    # ``tenant.timezone`` (top-level) instead of the legacy
    # ``tenant.settings.tz`` path (which was never populated by the
    # canonical PATCH /api/tenants/mine/settings write path). This
    # closes the "``/schedule/today`` always thinks the tenant lives
    # in America/Phoenix" bug that surfaced for every non-Vistancia
    # tenant.
    from services.tenant_helpers import get_tenant_timezone_name
    tz_name = get_tenant_timezone_name(tenant)
    start_iso, end_iso = _today_bounds_utc(tz_name, date)
    if date:
        # Validate strict YYYY-MM-DD
        try:
            requested = datetime.strptime(date, "%Y-%m-%d").date().isoformat()
        except Exception:
            requested = datetime.now(timezone.utc).date().isoformat()
    else:
        requested = datetime.now(timezone.utc).date().isoformat()
    today_yyyymmdd = requested

    # Feb-2026 · Crew Phase A · widen the tech-visibility filter so any
    # tech who's a member of a crew ALSO sees that crew's jobs on
    # their personal ``/schedule/today``. ``crew.tech_ids`` is
    # populated with the caller's ``user_id`` (see
    # ``routers/ops.py::create_crew``), so the crew clause below
    # queries with ``user["id"]``.
    #
    # Feb-2026 · P2→P0 · Identity-mismatch hotfix. Legacy jobs are
    # stamped with ``technician_id = user.id``; post-``bulk-reassign``
    # (jobs.py::_lookup_tech_user :: canonical_tech_id) jobs are
    # stamped with ``technician_id = user.technician_id``. Real
    # tenants have BOTH shapes co-existing. The prior code queried
    # only ``user.id`` and hid every job on the newer shape — techs
    # would see a partial or empty schedule. Union BOTH ids so we
    # don't hide legitimate jobs. Same defensive posture as
    # ``service_reports.py::_authorize_report``.
    #
    # Phase P9-A · Feb-2026 — Technician Visibility Jail (Option B).
    # Fail-closed ONLY when the technician session carries NO
    # resolvable identity (both ``user.id`` and ``user.technician_id``
    # empty). Otherwise scope over the FULL union so legacy shapes
    # (jobs stamped ``technician_id = user.id``) still surface for
    # R1.1 crew visibility. Silent 200 + WARN — never 403 (never
    # reveal that the caller is a tech in a broken state).
    _tech_ids = list(filter(None, [user.get("id"), user.get("technician_id")]))
    _role = (user.get("role") or "").lower()
    if _role == "technician" and not _tech_ids:
        logger.warning(
            "[p9.jail] technician with no resolvable identity — "
            "fail-closed. tenant_id=%s endpoint=schedule_today",
            tid,
        )
        return {
            "date": today_yyyymmdd,
            "tz": tz_name,
            "items": [],
            "route_legs": [],
            "summary": {
                "job_count": 0,
                "job_count_repair": 0,
                "job_count_service": 0,
                "scheduled_hours": 0.0,
                "hours_logged_today": 0.0,
                "miles_logged_today": 0.0,
                "clocked_in": False,
                "open_entry_id": None,
            },
        }
    tech_or_clauses: list = [
        {"assigned_technician_id": {"$in": _tech_ids}},
        {"technician_id": {"$in": _tech_ids}},
        {"assigned_to": {"$in": _tech_ids}},
    ]
    # Feb-2026 · P2→P0 · Same identity-union treatment for the crew
    # prefetch — ``crews.tech_ids`` is written with ``user.id`` today
    # (via ``ops.py::create_crew``) but the field has legacy rows
    # from a prior seed migration that stored ``technicians.id``.
    # Match either so no crew memberships are silently skipped.
    #
    # CREW-SCHEDULE-FANOUT · Feb-2026 — the crew branch was widened
    # from a single ``{crew_id: {$in: [...]}}`` to per-crew branches
    # each carrying the current user's own ``member_added_at`` floor
    # so a tech just added to a crew doesn't retroactively see
    # historical jobs they weren't on the crew for.  Floor is a
    # ``YYYY-MM-DD`` date-prefix (``added_at[:10]``) so bare-date and
    # ISO-datetime ``scheduled_date`` values both lex-compare
    # correctly against ``$gte``.  Fallback floor when the migration
    # hasn't yet run / a legacy crew lacks the map = ``crew.created_at``
    # (best-effort; same semantics as the backfill script).
    _t_crews = _t.perf_counter()
    my_crew_ids: list = []
    async for _c in db.crews.find(
        {"tenant_id": tid, "tech_ids": {"$in": _tech_ids}},
        {"_id": 0, "id": 1, "member_added_at": 1, "created_at": 1},
    ):
        _added_at = None
        _mam = _c.get("member_added_at") or {}
        for _tid_var in _tech_ids:
            if _mam.get(_tid_var):
                _added_at = _mam[_tid_var]
                break
        if not _added_at:
            _added_at = _c.get("created_at")
        _floor = str(_added_at or "")[:10]  # YYYY-MM-DD prefix
        tech_or_clauses.append({
            "crew_id": _c["id"],
            # Guard the ``$gte`` so an un-migrated crew with no
            # ``created_at`` (shouldn't happen but defense-in-depth)
            # falls back to "match any date", preserving the pre-ship
            # visibility semantics.
            **({"scheduled_date": {"$gte": _floor}} if _floor else {}),
        })
        my_crew_ids.append(_c["id"])
    _timings.append(f"crews;dur={(_t.perf_counter()-_t_crews)*1000:.1f}")
    # Feb-2026 · Crew Phase A · $and-compose the tech-visibility $or
    # with ``not_deleted_filter()``'s own $or (soft-delete predicate).
    # Prior code did ``{**job_q, **_nd()}`` where Python dict-spread
    # silently overwrote the tech-visibility $or with the soft-delete
    # $or — collapsing the tech scoping and returning every non-
    # deleted job in the tenant to every caller. Discovered while
    # shipping Phase A; the fix is required for the crew clause to
    # have any effect at all.
    from utils import not_deleted_filter as _nd
    job_q = {
        "tenant_id": tid,
        "$and": [
            {"$or": tech_or_clauses},
            _nd(),
        ],
        "scheduled_date": {"$gte": start_iso, "$lte": end_iso},
    }
    # Feb-2026 · route-order read-path fix — sort by
    # ``scheduled_date`` first, then by the admin-assigned
    # ``route_index`` (written by ``POST /api/jobs/reorder``).
    # Fallback to Mongo's natural insertion order for untouched days
    # via ``created_at`` as the tertiary key.
    # Feb-2026 · Crew Phase A · ``job_q`` already carries the
    # soft-delete predicate composed under $and above — do NOT
    # dict-spread ``_nd()`` in again (that's what caused the
    # tech-visibility leak this ship fixed).
    _t_jobs = _t.perf_counter()
    jobs = await db.jobs.find(job_q, {"_id": 0, "photos.data": 0}).sort(
        [("scheduled_date", 1), ("route_index", 1), ("created_at", 1)]
    ).to_list(200)
    _timings.append(f"jobs;dur={(_t.perf_counter()-_t_jobs)*1000:.1f}")

    # Phase 16C follow-up · fetch customer gate codes + notes for the tech.
    _t_custs = _t.perf_counter()
    cids = list({j.get("customer_id") for j in jobs if j.get("customer_id")})
    cust_map: dict = {}
    if cids:
        for c in await db.customers.find(
            {"id": {"$in": cids}, "tenant_id": tid},
            # Phase P26 · Feb-2026 — added service_lat/service_lng to
            # the projection so the coord-fallback resolver below can
            # rescue jobs whose own ``site_lat`` / ``lat`` /
            # ``latitude`` fields are null but the linked customer
            # has geocoded coords. Preview data shows ~1,031 of 1,527
            # jobs missing own coords are rescuable via this fallback.
            {"_id": 0, "id": 1, "gate_code": 1, "notes": 1, "access_notes": 1,
              "service_notes": 1,
              "service_lat": 1, "service_lng": 1},
        ).to_list(500):
            cust_map[c["id"]] = c
    _timings.append(f"custs;dur={(_t.perf_counter()-_t_custs)*1000:.1f}")

    # Time entries + break intervals for *today* (by user).
    _t_entries = _t.perf_counter()
    entries = await db.time_entries.find(
        {"tenant_id": tid, "user_id": user["id"],
         "clock_in_at": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0},
    ).sort("clock_in_at", 1).to_list(50)
    _timings.append(f"entries;dur={(_t.perf_counter()-_t_entries)*1000:.1f}")

    items: list = []
    # Phase R1.1 · Feb-2026 — Safe Check.  Build the tenant's live
    # technician id-space ONCE (both technicians + users id spaces)
    # so a bogus ``jobs.technician_id`` never crashes the projection.
    # ``None`` / missing ``technician_id`` is FINE — those jobs
    # matched the visibility filter via ``assigned_technician_id``,
    # ``assigned_to``, or crew membership and represent unassigned
    # work that the caller still needs to see.  We only skip when a
    # ``technician_id`` IS set but doesn't resolve.
    _live_tech_space = await _live_technician_id_space(tid)
    _skipped_bad_tech: int = 0
    for j in jobs:
        # Phase R1.1 · Safe Check — skip jobs whose ``technician_id``
        # points at a ghost identity in this tenant.  WARN once per
        # skipped row with enough context that the F2 data-repair
        # scan can find + heal them.
        _job_tid = j.get("technician_id")
        if _job_tid and _job_tid not in _live_tech_space:
            _skipped_bad_tech += 1
            logger.warning(
                "[schedule/today] skipped job with dangling technician_id "
                "job_id=%s tenant_id=%s technician_id=%s",
                j.get("id"), tid, _job_tid,
            )
            continue
        cust = cust_map.get(j.get("customer_id")) or {}
        job_notes_raw = "\n".join(filter(None, [j.get("notes"), j.get("internal_notes")]))
        # Feb-2026 service-notes ship + tester fix — inject the note
        # matching this job's service type. Try ``service_type`` first,
        # then ``job_type`` (legacy schema alias), then the resolver's
        # tech-specialty fallback. Substring match handles values like
        # "Weekly Pool Service".
        from routers.customers import _resolve_service_note
        stype_for_resolver = j.get("service_type") or j.get("job_type")
        service_note = _resolve_service_note(
            cust, stype_for_resolver, user,
        )
        # Phase P26 · Feb-2026 — coord fallback: prefer the job's
        # own coords, fall back to the linked customer's
        # ``service_lat`` / ``service_lng``, and stamp
        # ``coord_source`` on the response so the schedule map can
        # debug why a specific pin is (or isn't) plotted. NEVER
        # mutates the underlying job doc; this is a
        # serialization-time enrichment only.
        from services.geo_resolver import resolve_job_coordinates
        _lat, _lng, _cs = resolve_job_coordinates(j, cust_map)
        # CREW-SCHEDULE-FANOUT · Feb-2026 — tag ``_crew_role`` so the
        # client can render "Crew lead" vs "Crew member" badges. A
        # job is "direct" when any of the ``JOB_TECH_FIELDS`` holds a
        # value in the caller's identity union (overlay wins per the
        # ticket's Q6 dedupe gate); otherwise the caller reached the
        # job only via the crew ``$or`` branch above and is a
        # "member".  Non-tech callers (admin / dispatcher) get
        # ``_crew_role = None`` so the FE suppresses the badge.
        from services.tech_id_resolver import JOB_TECH_FIELDS as _JTF
        _crew_role = None
        if _role == "technician":
            _tid_set = set(_tech_ids)
            if any(j.get(_f) in _tid_set for _f in _JTF):
                _crew_role = "direct"
            elif j.get("crew_id") in set(my_crew_ids):
                _crew_role = "member"
        items.append({
            "type": "job",
            "id": j.get("id"),
            "title": j.get("title") or j.get("service_type") or "Job",
            "service_type": j.get("service_type") or j.get("job_type") or j.get("title") or "Service",
            "job_type": j.get("job_type") or j.get("service_type"),
            "crew_id": j.get("crew_id"),
            "_crew_role": _crew_role,
            # Feb 2026 · work-class dimension surfaced on each item so
            # the frontend can render Repair badges + drive the summary
            # split. Legacy jobs without the field read as "service"
            # via ``infer_work_class`` — never null.
            "work_class": (
                "repair" if (j.get("work_class") == "repair") else "service"
            ),
            "customer_name": j.get("customer_name"),
            "customer_id": j.get("customer_id"),
            "address": j.get("address") or j.get("site_address"),
            "city": j.get("city"),
            "state": j.get("state"),
            "zip": j.get("zip"),
            # Phase P26 · Feb-2026 — resolved coords (job → customer
            # fallback → null). ``coord_source`` is a debug/audit
            # field the FE map layer can log when a pin's origin is
            # ambiguous; future analytics can count fallback rate.
            "lat": _lat,
            "lng": _lng,
            "coord_source": _cs,
            "scheduled_start": j.get("scheduled_date") or j.get("scheduled_start"),
            "scheduled_end": j.get("scheduled_end"),
            "status": j.get("status"),
            "priority": j.get("priority"),
            "gate_code": cust.get("gate_code") or None,
            "access_notes": cust.get("access_notes") or None,
            "customer_notes": cust.get("notes") or None,
            "job_notes": job_notes_raw or None,
            "service_note": service_note,
            # Feb-2026 · route-order read-path fix — expose the
            # admin-assigned ``route_index`` in the tech's day view
            # payload so the client can visually surface + trust the
            # server-side sort.  Null on tech-days the admin hasn't
            # touched yet.
            "route_index": j.get("route_index"),
        })

    for e in entries:
        items.append({
            "type": "shift",
            "entry_id": e.get("id"),
            "job_id": e.get("job_id"),
            "job_title": e.get("job_title"),
            "clock_in_at": e.get("clock_in_at"),
            "clock_out_at": e.get("clock_out_at"),
            "out_of_geofence": bool(e.get("out_of_geofence")),
            "status": e.get("status"),
        })
        for b in (e.get("breaks") or []):
            items.append({
                "type": "break",
                "entry_id": e.get("id"),
                "start": b.get("start"),
                "end": b.get("end"),
            })

    # Feb-2026 · route-order read-path fix — primary sort key is
    # the admin-assigned ``route_index`` (writes from ``POST
    # /api/jobs/reorder``).  Missing / null values sink to the
    # bottom (via ``999999`` sentinel) so untouched tech-days keep
    # their prior time-based ordering.  Secondary key is the
    # existing time-based sort so shifts/breaks + route legs stay
    # deterministic.
    def _sort_key(it):
        ri = it.get("route_index")
        primary = ri if isinstance(ri, int) else 999999
        secondary = (it.get("scheduled_start") or it.get("clock_in_at")
                     or it.get("start") or "")
        return (primary, secondary)
    items.sort(key=_sort_key)

    # Route legs between consecutive jobs with coords.
    # Feb-2026 · Task 5 perf — replace the O(N) sequential
    # ``find_one`` loop with a single batched ``find({key: {$in: [...]}})``.
    # On a schedule with 15 jobs the old code fired 14 sequential
    # Mongo round-trips (100–700 ms on a remote cluster); the new
    # path fires 1.  Query semantics + response shape are byte-
    # for-byte identical (verified by
    # ``tests/test_schedule_today_leg_cache_batched.py``).
    coord_jobs = [it for it in items if it["type"] == "job"
                                       and it.get("lat") is not None
                                       and it.get("lng") is not None]
    legs = []
    leg_pairs = list(zip(coord_jobs, coord_jobs[1:]))
    leg_keys = [_cache_key(a["lat"], a["lng"], b["lat"], b["lng"])
                 for a, b in leg_pairs]
    cache_by_key: dict = {}
    _t_legs = _t.perf_counter()
    if leg_keys:
        async for row in db.distance_matrix_cache.find(
            {"key": {"$in": leg_keys}},
            {"_id": 0, "key": 1, "distance_meters": 1, "duration_seconds": 1},
        ):
            cache_by_key[row["key"]] = row
    _timings.append(f"legs;dur={(_t.perf_counter()-_t_legs)*1000:.1f}")
    for (a, b), leg_key in zip(leg_pairs, leg_keys):
        cached = cache_by_key.get(leg_key)
        legs.append({
            "from_job_id": a["id"],
            "to_job_id": b["id"],
            "from_lat": a["lat"], "from_lng": a["lng"],
            "to_lat": b["lat"], "to_lng": b["lng"],
            "distance_meters": (cached or {}).get("distance_meters"),
            "duration_seconds": (cached or {}).get("duration_seconds"),
            "cached": bool(cached),
        })

    # Summary
    total_hours = sum(
        (e.get("duration_minutes") or 0) for e in entries
    ) / 60.0
    total_miles = sum((e.get("mileage_miles") or 0) for e in entries)
    scheduled_hours = 0.0
    for j in jobs:
        s = j.get("scheduled_date") or j.get("scheduled_start")
        eend = j.get("scheduled_end")
        if s and eend:
            try:
                ds = datetime.fromisoformat(s.replace("Z", "+00:00"))
                de = datetime.fromisoformat(eend.replace("Z", "+00:00"))
                scheduled_hours += max(0, (de - ds).total_seconds() / 3600.0)
            except Exception:
                pass
    open_shift = next((e for e in entries if not e.get("clock_out_at")), None)

    return {
        "date": today_yyyymmdd,
        "tz": tz_name,
        "items": items,
        "route_legs": legs,
        "summary": {
            "job_count": len(coord_jobs) + sum(1 for it in items
                                                if it["type"] == "job"
                                                and (it.get("lat") is None)),
            # Feb 2026 · Work-class counter split. ``job_count`` above
            # stays as the historical total for backward compat.
            # ``job_count_repair`` counts items with an explicit
            # ``"repair"`` work_class; ``job_count_service`` is the
            # complement (any missing/legacy work_class reads as
            # service, so total − repair = service).
            "job_count_repair": sum(
                1 for it in items
                if it["type"] == "job" and it.get("work_class") == "repair"
            ),
            "job_count_service": sum(
                1 for it in items
                if it["type"] == "job" and it.get("work_class") != "repair"
            ),
            "scheduled_hours": round(scheduled_hours, 2),
            "hours_logged_today": round(total_hours, 2),
            "miles_logged_today": round(total_miles, 2),
            "clocked_in": bool(open_shift),
            "open_entry_id": open_shift and open_shift.get("id"),
        },
    }


# ─── Route-leg cache write (client posts back after Distance Matrix call) ──
class LegIn(BaseModel):
    from_lat: float
    from_lng: float
    to_lat: float
    to_lng: float
    distance_meters: float
    duration_seconds: float


class RouteLegCacheReq(BaseModel):
    legs: List[LegIn]


@router.post("/schedule/route-leg")
async def cache_route_legs(body: RouteLegCacheReq,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    written = 0
    for l in body.legs:
        key = _cache_key(l.from_lat, l.from_lng, l.to_lat, l.to_lng)
        await db.distance_matrix_cache.update_one(
            {"key": key},
            {"$set": {
                "key": key,
                "tenant_id": tenant["id"],   # last-writer tenant for auditing
                "from_lat": l.from_lat, "from_lng": l.from_lng,
                "to_lat": l.to_lat, "to_lng": l.to_lng,
                "distance_meters": l.distance_meters,
                "duration_seconds": l.duration_seconds,
                "updated_at": now_iso(),
                "mode": "driving",
            }},
            upsert=True,
        )
        written += 1
    return {"ok": True, "written": written}


@router.get("/schedule/day")
async def schedule_day(date: Optional[str] = None,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    """Alias for `/schedule/today?date=…` — cleaner URL when browsing history."""
    return await schedule_today(date=date, user=user, tenant=tenant)


# ══════════════════════════════════════════════════════════════════
# Feb-2026 · Enhancement 1 — Drag-and-drop reschedule + auto-notify
# ══════════════════════════════════════════════════════════════════
class RescheduleRequest(BaseModel):
    job_id: str
    new_start_at: str       # ISO datetime OR YYYY-MM-DD
    new_end_at: Optional[str] = None
    new_tech_user_id: Optional[str] = None
    dry_run: bool = False   # if true, don't persist — just return the
                              # notification preview so the confirmation
                              # modal can render it before commit.


def _tenant_tz(tenant: dict) -> str:
    return (tenant or {}).get("timezone") or DEFAULT_TZ


def _format_local(iso_or_date: str, tz_name: str) -> str:
    """Render an ISO datetime OR YYYY-MM-DD string in the tenant tz."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_name or "America/Phoenix")
    except Exception:
        tz = timezone.utc
    s = (iso_or_date or "").strip()
    if not s:
        return ""
    try:
        # Date-only rows land as "YYYY-MM-DD"; give them the noon
        # anchor so the label reads sanely.
        if len(s) == 10 and s.count("-") == 2:
            dt = datetime.fromisoformat(s + "T12:00:00+00:00")
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return s
    local = dt.astimezone(tz)
    return local.strftime("%a %b %-d, %Y %-I:%M %p")


async def _resolve_service_name(job: dict) -> str:
    """Merge tag `{{SERVICE_NAME}}` resolver — pulls from the job's
    service_template.name (or the recurring template name) with a
    friendly fallback."""
    st = job.get("service_template") or {}
    if isinstance(st, dict) and st.get("name"):
        return st["name"]
    tpl_id = job.get("recurring_template_id") or job.get("template_id")
    if tpl_id:
        try:
            row = await db.recurring_job_templates.find_one(
                {"id": tpl_id}, {"_id": 0, "service_type": 1, "name": 1},
            )
            if row and (row.get("name") or row.get("service_type")):
                return row.get("name") or row["service_type"]
        except Exception:
            pass
    return (job.get("service_type") or job.get("title") or "your service")


@router.post("/schedule/reschedule",
              operation_id="schedule.reschedule")
async def reschedule_job(body: RescheduleRequest,
                           user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    """Admin drag-and-drop reschedule.

    Updates the ``jobs`` doc (``scheduled_start_at``, ``scheduled_end_at``,
    optionally ``technician_id``), appends a ``job_history`` entry, then
    fires — best-effort, wrapped in try/except so the reschedule never
    rolls back — an email via Resend + SMS via RingCentral to the
    customer. Both writes land in ``marketing_deliveries`` with
    ``trigger_entity.kind == "job_rescheduled"`` so the Communications
    Log timeline surfaces them.
    """
    if (user or {}).get("role") not in {"admin", "super_admin", "manager"}:
        raise HTTPException(403, "Admin/manager only")
    job = await db.jobs.find_one(
        {"id": body.job_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not job:
        raise HTTPException(404, "Job not found")

    old_start = job.get("scheduled_start_at") or job.get("scheduled_date")
    old_end = job.get("scheduled_end_at")
    old_tech = job.get("technician_id")

    tz = _tenant_tz(tenant)
    customer = None
    cid = job.get("customer_id")
    if cid:
        customer = await db.customers.find_one(
            {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
        )
    service_name = await _resolve_service_name(job)
    old_dt_label = _format_local(old_start, tz)
    new_dt_label = _format_local(body.new_start_at, tz)

    preview = {
        "job_id": job["id"],
        "customer_id": cid,
        "customer_name": (customer or {}).get("name") or "",
        "customer_first_name": (customer or {}).get("first_name") or "",
        "customer_email": (customer or {}).get("email"),
        "customer_phone": (customer or {}).get("phone"),
        "service_name": service_name,
        "old_datetime": old_dt_label,
        "new_datetime": new_dt_label,
        "tech_name": None,
    }
    tech_id = body.new_tech_user_id or old_tech
    # Phase R1.1 · Feb-2026 — Safe Check.  Resolve the tech display
    # name across BOTH id spaces (users AND technicians) and within
    # the tenant scope so a legacy ``users.id``-shaped ``tech_id``,
    # a canonical ``technicians.id``, or a JWT-claim
    # ``users.technician_id`` all render correctly.  A ghost id
    # simply leaves ``preview["tech_name"]`` as ``None`` — the
    # reschedule still proceeds, we just log a WARN so the F2 data-
    # repair scan surfaces the corrupt row.  Previous code did
    # ``db.users.find_one({"id": tech_id})`` (no tenant filter, one
    # id space) which either 500-ed on ``AttributeError`` further
    # down OR silently rendered the wrong tenant's tech name.
    if tech_id:
        display = await _resolve_tech_display(tenant["id"], tech_id)
        if display:
            preview["tech_name"] = display
        else:
            logger.warning(
                "[schedule/reschedule] tech_id did not resolve in tenant "
                "tech_id=%s tenant_id=%s job_id=%s",
                tech_id, tenant["id"], job["id"],
            )
            preview["tech_name"] = None

    if body.dry_run:
        return {"ok": True, "dry_run": True, "preview": preview}

    # ── Persist reschedule ──────────────────────────────────
    update = {
        "scheduled_start_at": body.new_start_at,
    }
    # Keep the legacy YYYY-MM-DD field in sync so list filters still work.
    date_prefix = body.new_start_at[:10] if body.new_start_at else None
    if date_prefix and len(date_prefix) == 10:
        update["scheduled_date"] = date_prefix
    if body.new_end_at:
        update["scheduled_end_at"] = body.new_end_at
    if body.new_tech_user_id:
        update["technician_id"] = body.new_tech_user_id

    history_entry = {
        "event": "rescheduled",
        "from": {"scheduled_start_at": old_start,
                  "scheduled_end_at": old_end,
                  "technician_id": old_tech},
        "to": {"scheduled_start_at": body.new_start_at,
                "scheduled_end_at": body.new_end_at,
                "technician_id": body.new_tech_user_id or old_tech},
        "by": user.get("id"),
        "at": now_iso(),
    }
    await db.jobs.update_one(
        {"id": job["id"], "tenant_id": tenant["id"]},
        {"$set": update, "$push": {"job_history": history_entry}},
    )

    # ── Best-effort customer notifications ───────────────────
    sent_email = False; sent_sms = False
    trigger_id = new_id()
    company_name = (tenant.get("name") or "your service team")
    email_ctx = {
        "customer_first_name": preview["customer_first_name"],
        "service_name": service_name,
        "old_datetime": old_dt_label,
        "new_datetime": new_dt_label,
        "tech_name": preview["tech_name"] or "your tech",
        "company_name": company_name,
    }
    sms_body = (
        f"Hi {preview['customer_first_name'] or 'there'}, your "
        f"{service_name} has been rescheduled from {old_dt_label} to "
        f"{new_dt_label}. Reply STOP to opt out."
    )

    # Feb-2026 · Multi-Contact Phase 2 · fan-out (automation).
    # Reschedule notifications are side-effects of admin action but
    # the customer sees them as automated appointment updates —
    # muted customers should not receive these.
    from services.customer_multi_contact import (
        active_email_recipients, active_phone_recipients, log_mute_suppressed,
    )
    _email_recipients = active_email_recipients(customer, context="automation") if customer else []
    if not _email_recipients and customer and customer.get("automations_muted"):
        await log_mute_suppressed(
            tenant_id=tenant["id"], customer_id=cid,
            channel="email", cluster="schedule_reschedule_email",
            context="automation",
        )
    for _addr in _email_recipients:
        try:
            from services.comms_email_adapter import send_email
            subject = f"Your {service_name} has been rescheduled"
            html = (
                f"<p>Hi {email_ctx['customer_first_name'] or 'there'},</p>"
                f"<p>Your <strong>{service_name}</strong> has been "
                f"rescheduled from <strong>{old_dt_label}</strong> to "
                f"<strong>{new_dt_label}</strong>.</p>"
                f"<p>Assigned tech: {email_ctx['tech_name']}.</p>"
                f"<p>— {company_name}</p>"
            )
            import asyncio as _a
            res = await _a.wait_for(send_email(
                tenant_id=tenant["id"], to_email=_addr,
                subject=subject, html=html, from_name=company_name,
            ), timeout=8.0)
            _sent = (res or {}).get("status") in ("sent", "sent_no_provider_id")
            if _sent:
                sent_email = True
        except Exception as exc:
            logger.warning(f"[reschedule] email failed for {_addr}: {exc}")
            _sent = False
        await db.marketing_deliveries.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "email", "kind": "transactional",
            "recipient": _addr,
            "subject": f"Your {service_name} has been rescheduled",
            "body": None,
            "trigger_entity": {"kind": "job_rescheduled",
                                "id": job["id"], "job_id": job["id"]},
            "trigger_id": trigger_id,
            "delivered": _sent,
            "created_at": now_iso(),
            "fanned_out": True,
            "fanout_recipient_count": len(_email_recipients),
        })

    _phone_recipients = active_phone_recipients(customer, context="automation") if customer else []
    if not _phone_recipients and customer and customer.get("automations_muted"):
        await log_mute_suppressed(
            tenant_id=tenant["id"], customer_id=cid,
            channel="sms", cluster="schedule_reschedule_sms",
            context="automation",
        )
    for _num in _phone_recipients:
        try:
            from services.comms_sms_adapter import send_sms
            import asyncio as _a
            res = await _a.wait_for(send_sms(
                tenant_id=tenant["id"], to_phone=_num,
                body=sms_body,
            ), timeout=8.0)
            _sent = bool(res and (res.get("status") in ("sent", "queued")))
            if _sent:
                sent_sms = True
        except Exception as exc:
            logger.warning(f"[reschedule] sms failed for {_num}: {exc}")
            _sent = False
        await db.marketing_deliveries.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "sms", "kind": "transactional",
            "recipient": _num,
            "subject": None, "body": sms_body,
            "trigger_entity": {"kind": "job_rescheduled",
                                "id": job["id"], "job_id": job["id"]},
            "trigger_id": trigger_id,
            "delivered": _sent,
            "created_at": now_iso(),
            "fanned_out": True,
            "fanout_recipient_count": len(_phone_recipients),
        })

    return {"ok": True, "preview": preview,
             "sent_email": sent_email, "sent_sms": sent_sms,
             "job_id": job["id"]}




# ═══════════════════════════════════════════════════════════════════
# Feb-2026 Enhancement — pending-unassigned-stale admin nudge.
#
# Counts jobs in the caller's tenant that are:
#   * ``status="pending"``
#   * missing both ``technician_id`` AND ``crew_id``
#   * ``created_at`` older than ``days`` (default 7)
#
# The `/schedule` page renders a dismissible banner when the count
# is > 0 so dispatchers see stale unassigned work before it rots.
# Complements F2's ``unassigned_pending_jobs`` scan (which is a
# super-admin data-repair tool) with an admin-visible nudge.
# ═══════════════════════════════════════════════════════════════════
_STALE_MIN_DAYS = 1
_STALE_MAX_DAYS = 90


@router.get("/schedule/unassigned-pending-stale",
              operation_id="schedule.unassignedPendingStaleCount")
async def get_unassigned_pending_stale_count(
    days: int = 7,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Return the count of pending jobs unassigned for > ``days`` days.

    Admin / manager / super_admin only. Techs do not see the nudge
    (dispatch is not their responsibility).
    """
    if user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Admin/manager access required")
    if days < _STALE_MIN_DAYS or days > _STALE_MAX_DAYS:
        raise HTTPException(400, {"code": "INVALID_DAYS",
                                    "min": _STALE_MIN_DAYS,
                                    "max": _STALE_MAX_DAYS})

    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()
    query = {
        "tenant_id": tenant["id"],
        "status": "pending",
        "created_at": {"$lt": cutoff},
        # Missing OR null on BOTH assignment fields — a job with a
        # crew or a technician is not "unassigned" for this purpose.
        "$and": [
            {"$or": [{"technician_id": None},
                        {"technician_id": {"$exists": False}}]},
            {"$or": [{"crew_id": None},
                        {"crew_id": {"$exists": False}}]},
            # Skip soft-deleted jobs — those are already off the
            # dispatch board.
            {"$or": [{"deleted_at": None},
                        {"deleted_at": {"$exists": False}}]},
        ],
    }
    count = await db.jobs.count_documents(query)
    return {"count": count, "days": days, "cutoff": cutoff}
