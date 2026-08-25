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

from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/schedule/today")
async def schedule_today(date: Optional[str] = None,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    """Return the tech's timeline for `date` (YYYY-MM-DD) or today when omitted.
    Alias `/schedule/day` accepts the same query."""
    tid = tenant["id"]
    tz_name = (tenant.get("settings") or {}).get("tz") or DEFAULT_TZ
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
    # ``routers/ops.py::create_crew``), so we query with
    # ``user["id"]``. The identity-mismatch between this endpoint
    # (``user.id``) and ``jobs.py::scope_jobs_query``
    # (``user.technician_id``) is a pre-existing P2 — parked, not
    # touched here.
    tech_or_clauses: list = [
        {"assigned_technician_id": user["id"]},
        {"technician_id": user["id"]},
        {"assigned_to": user["id"]},
    ]
    my_crew_ids = [
        c["id"] async for c in db.crews.find(
            {"tenant_id": tid, "tech_ids": user["id"]},
            {"_id": 0, "id": 1},
        )
    ]
    # Guardrail — only add the crew clause when the list is non-empty.
    # ``$in: []`` would emit an always-false branch that Mongo still
    # has to plan; skip entirely instead.
    if my_crew_ids:
        tech_or_clauses.append({"crew_id": {"$in": my_crew_ids}})
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
    jobs = await db.jobs.find(job_q, {"_id": 0}).sort(
        [("scheduled_date", 1), ("route_index", 1), ("created_at", 1)]
    ).to_list(200)

    # Phase 16C follow-up · fetch customer gate codes + notes for the tech.
    cids = list({j.get("customer_id") for j in jobs if j.get("customer_id")})
    cust_map: dict = {}
    if cids:
        for c in await db.customers.find(
            {"id": {"$in": cids}, "tenant_id": tid},
            {"_id": 0, "id": 1, "gate_code": 1, "notes": 1, "access_notes": 1,
              "service_notes": 1},
        ).to_list(500):
            cust_map[c["id"]] = c

    # Time entries + break intervals for *today* (by user).
    entries = await db.time_entries.find(
        {"tenant_id": tid, "user_id": user["id"],
         "clock_in_at": {"$gte": start_iso, "$lte": end_iso}},
        {"_id": 0},
    ).sort("clock_in_at", 1).to_list(50)

    items: list = []
    for j in jobs:
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
        items.append({
            "type": "job",
            "id": j.get("id"),
            "title": j.get("title") or j.get("service_type") or "Job",
            "service_type": j.get("service_type") or j.get("job_type") or j.get("title") or "Service",
            "job_type": j.get("job_type") or j.get("service_type"),
            "customer_name": j.get("customer_name"),
            "customer_id": j.get("customer_id"),
            "address": j.get("address") or j.get("site_address"),
            "city": j.get("city"),
            "state": j.get("state"),
            "zip": j.get("zip"),
            "lat": j.get("site_lat") or j.get("lat"),
            "lng": j.get("site_lng") or j.get("lng"),
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

    # Route legs between consecutive jobs with coords
    coord_jobs = [it for it in items if it["type"] == "job"
                                       and it.get("lat") is not None
                                       and it.get("lng") is not None]
    legs = []
    for a, b in zip(coord_jobs, coord_jobs[1:]):
        leg_key = _cache_key(a["lat"], a["lng"], b["lat"], b["lng"])
        cached = await db.distance_matrix_cache.find_one(
            {"key": leg_key}, {"_id": 0}
        )
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
    if tech_id:
        t = await db.users.find_one({"id": tech_id}, {"_id": 0, "name": 1})
        if t:
            preview["tech_name"] = t.get("name") or tech_id

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

    if customer and customer.get("email"):
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
                tenant_id=tenant["id"], to_email=customer["email"],
                subject=subject, html=html, from_name=company_name,
            ), timeout=8.0)
            sent_email = (res or {}).get("status") in ("sent", "sent_no_provider_id")
        except Exception as exc:
            logger.warning(f"[reschedule] email failed: {exc}")
        await db.marketing_deliveries.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "email", "kind": "transactional",
            "recipient": customer["email"],
            "subject": f"Your {service_name} has been rescheduled",
            "body": None,
            "trigger_entity": {"kind": "job_rescheduled",
                                "id": job["id"], "job_id": job["id"]},
            "trigger_id": trigger_id,
            "delivered": sent_email,
            "created_at": now_iso(),
        })

    if customer and customer.get("phone"):
        try:
            from services.comms_sms_adapter import send_sms
            import asyncio as _a
            res = await _a.wait_for(send_sms(
                tenant_id=tenant["id"], to_phone=customer["phone"],
                body=sms_body,
            ), timeout=8.0)
            sent_sms = bool(res and (res.get("status") in ("sent", "queued")))
        except Exception as exc:
            logger.warning(f"[reschedule] sms failed: {exc}")
        await db.marketing_deliveries.insert_one({
            "id": new_id(), "tenant_id": tenant["id"],
            "customer_id": cid,
            "channel": "sms", "kind": "transactional",
            "recipient": customer["phone"],
            "subject": None, "body": sms_body,
            "trigger_entity": {"kind": "job_rescheduled",
                                "id": job["id"], "job_id": job["id"]},
            "trigger_id": trigger_id,
            "delivered": sent_sms,
            "created_at": now_iso(),
        })

    return {"ok": True, "preview": preview,
             "sent_email": sent_email, "sent_sms": sent_sms,
             "job_id": job["id"]}


