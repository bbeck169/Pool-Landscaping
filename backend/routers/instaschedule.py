"""QuoteIQ Phase Q5 · InstaSchedule — Public self-book widget.

Public URL where prospects / existing customers self-book a service
appointment from live tenant availability. Mirrors InstaQuote's shape
(config → public → admin approval → converts to a real record) but
outputs a Job instead of a Deal + Estimate.

Design notes
------------
* Slot computation is deterministic and server-side. Public callers
  send ``date`` + ``service_type_id``; the server derives available
  slots from ``availability_rules`` (weekday windows, blackouts,
  min-notice, max-lead), then subtracts *both* pending bookings and
  scheduled jobs already sitting on that day.
* Booking is race-safe: we re-validate the requested slot inside the
  write path and 409 if capacity was consumed since the client fetched
  the slots list. Never overbook.
* Admin ``confirm`` creates the Job (bypasses HTTP; direct Mongo
  insert) + upserts / links the customer + assigns per
  ``route_integration.assign_strategy``. Idempotent by booking id
  (re-confirming a confirmed booking is a 409, not a duplicate job).
"""
from __future__ import annotations

import re
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field

from config import db, logger
from utils import require_admin, new_id, now_iso
from routers.tenants import get_current_tenant


router = APIRouter(tags=["InstaSchedule"])


# ─── Rate limit (in-memory, per IP) ────────────────────────────────────
#
# Separate from InstaQuote's counter so a hot public InstaQuote page
# doesn't lock a legitimate InstaSchedule booking on the same IP.

_RL_WINDOW_SECONDS = 10 * 60
_RL_MAX_HITS = 3
_rl_hits: Dict[str, deque] = {}


def _rl_allow(ip: str) -> bool:
    now = time.time()
    q = _rl_hits.setdefault(ip, deque())
    while q and now - q[0] > _RL_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _RL_MAX_HITS:
        return False
    q.append(now)
    return True


def _reset_rate_limit() -> None:
    _rl_hits.clear()


# ─── Weekday helpers ───────────────────────────────────────────────────

_DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_ALLOWED_ASSIGN = {"round_robin", "least_loaded", "admin_manual"}


def _parse_hhmm(s: str) -> int:
    """'HH:MM' → minutes-since-midnight. Raises on bad input."""
    if not re.match(r"^\d{1,2}:\d{2}$", s or ""):
        raise ValueError(f"bad HH:MM: {s!r}")
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _iso_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


# ─── Models ────────────────────────────────────────────────────────────

class ServiceTypeIn(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = ""
    duration_minutes: int = Field(default=60, ge=15, le=8 * 60)
    buffer_minutes: int = Field(default=0, ge=0, le=120)
    allow_public_book: bool = True
    restricted_to_existing_customer: bool = False
    requires_address: bool = False


class WeekdayWindowIn(BaseModel):
    start: str = Field(..., description="HH:MM 24-hour, tenant TZ.")
    end: str = Field(..., description="HH:MM 24-hour, tenant TZ.")


class AvailabilityRulesIn(BaseModel):
    timezone: str = "America/New_York"
    weekday_windows: Dict[str, List[WeekdayWindowIn]] = Field(default_factory=dict)
    blackout_dates: List[str] = Field(default_factory=list,
                                         description="YYYY-MM-DD list.")
    max_bookings_per_day: int = Field(default=20, ge=0, le=500)
    min_notice_hours: int = Field(default=4, ge=0, le=365 * 24)
    max_lead_days: int = Field(default=30, ge=1, le=365)


class RouteIntegrationIn(BaseModel):
    enabled: bool = False
    prefer_route_capacity: bool = False
    assign_strategy: str = Field(default="admin_manual")


class CollectFieldsIn(BaseModel):
    name: bool = True
    email: bool = True
    phone: bool = True
    address: bool = False
    notes: bool = False


class ConfigIn(BaseModel):
    slug: str = Field(..., min_length=2, max_length=80)
    headline: str = "Book your service."
    subheadline: Optional[str] = ""
    brand_color: Optional[str] = "#0284C7"
    logo_url: Optional[str] = None
    service_types: List[ServiceTypeIn] = Field(default_factory=list)
    availability_rules: AvailabilityRulesIn = Field(default_factory=AvailabilityRulesIn)
    route_integration: RouteIntegrationIn = Field(default_factory=RouteIntegrationIn)
    collect_fields: CollectFieldsIn = Field(default_factory=CollectFieldsIn)
    thank_you_html: Optional[str] = "Thanks — we'll be in touch shortly."
    success_redirect_url: Optional[str] = None
    notification_channels: List[str] = Field(default_factory=lambda: ["email"])
    active: bool = False


class ConfigPatch(BaseModel):
    headline: Optional[str] = None
    subheadline: Optional[str] = None
    brand_color: Optional[str] = None
    logo_url: Optional[str] = None
    service_types: Optional[List[ServiceTypeIn]] = None
    availability_rules: Optional[AvailabilityRulesIn] = None
    route_integration: Optional[RouteIntegrationIn] = None
    collect_fields: Optional[CollectFieldsIn] = None
    thank_you_html: Optional[str] = None
    success_redirect_url: Optional[str] = None
    notification_channels: Optional[List[str]] = None


class ContactIn(BaseModel):
    name: Optional[str] = ""
    email: Optional[EmailStr] = None
    phone: Optional[str] = ""
    address: Optional[str] = ""
    notes: Optional[str] = ""


class BookIn(BaseModel):
    """Public booking body.

    Canonical shape:
    * ``service_type_id`` — must map to a service_type on the active config.
    * ``requested_slot`` — ``{start_iso, end_iso}`` (server re-validates).
    * ``contact`` — subset per ``collect_fields``.
    * ``notes`` — optional job notes.
    * ``_hp`` — hidden honeypot input.
    """
    service_type_id: str
    requested_slot: Dict[str, str] = Field(
        ..., description="{'start_iso': ISO8601, 'end_iso': ISO8601}")
    contact: ContactIn
    notes: Optional[str] = ""
    customer_id: Optional[str] = Field(
        None, description="Optional — set to link an existing customer.")
    hp_field: Optional[str] = Field(default="", alias="_hp",
        description="Honeypot — must remain empty on the wire.")

    model_config = {"populate_by_name": True}


class BookingAckOut(BaseModel):
    """Canonical response for ``POST /public/instaschedule/{slug}/book``.

    Honeypot returns the same shape so spammers can't A/B the response.
    """
    id: str
    status: str = Field(..., description="Always 'pending' for the current flow.")
    service_type_id: str
    requested_slot: Dict[str, str]
    thank_you_html: str
    success_redirect_url: Optional[str] = None


class DeclineIn(BaseModel):
    reason: Optional[str] = ""
    notify_prospect: bool = False


# ─── Helpers ───────────────────────────────────────────────────────────

def _clean(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not d:
        return d
    out = dict(d)
    out.pop("_id", None)
    return out


def _normalize_ids(cfg: Dict[str, Any]) -> Dict[str, Any]:
    for item in cfg.get("service_types") or []:
        if not item.get("id"):
            item["id"] = new_id()
    return cfg


def _public_view(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Non-sensitive projection. Strips tenant_id, active state, and
    admin timestamps. Availability rules are exposed so the client
    knows which weekdays / blackouts to render as disabled."""
    return {
        "slug": cfg.get("slug"),
        "headline": cfg.get("headline") or "",
        "subheadline": cfg.get("subheadline") or "",
        "brand_color": cfg.get("brand_color") or "#0284C7",
        "logo_url": cfg.get("logo_url"),
        "service_types": [
            s for s in (cfg.get("service_types") or [])
            if s.get("allow_public_book")
        ],
        "availability_rules": {
            "timezone": (cfg.get("availability_rules") or {}).get("timezone") or "UTC",
            "weekday_windows": (cfg.get("availability_rules") or {}).get("weekday_windows") or {},
            "blackout_dates": (cfg.get("availability_rules") or {}).get("blackout_dates") or [],
            "min_notice_hours": (cfg.get("availability_rules") or {}).get("min_notice_hours") or 0,
            "max_lead_days": (cfg.get("availability_rules") or {}).get("max_lead_days") or 30,
        },
        "collect_fields": cfg.get("collect_fields") or {},
        "thank_you_html": cfg.get("thank_you_html") or "",
        "success_redirect_url": cfg.get("success_redirect_url"),
    }


async def _compute_slots(*, cfg: Dict[str, Any], service_type: Dict[str, Any],
                            target: date) -> List[Dict[str, Any]]:
    """Compute available slots for a given date + service_type.

    Rules applied in order:
    1. Target date must not be in the past.
    2. Target date must be within ``max_lead_days``.
    3. Blackout dates → empty.
    4. Weekday windows drive the base slot grid.
    5. Slots earlier than ``min_notice_hours`` from now are filtered.
    6. Existing pending bookings + scheduled jobs subtract capacity 1:1
       when they overlap the slot.
    7. Total bookings on the day capped by
       ``availability_rules.max_bookings_per_day``.
    """
    rules = cfg.get("availability_rules") or {}
    max_lead = int(rules.get("max_lead_days") or 30)
    min_notice_h = int(rules.get("min_notice_hours") or 0)
    max_per_day = int(rules.get("max_bookings_per_day") or 999)
    blackout = set(rules.get("blackout_dates") or [])
    windows = (rules.get("weekday_windows") or {}).get(_DOW[target.weekday()], [])

    today = datetime.now(timezone.utc).date()
    if target < today:
        return []
    if (target - today).days > max_lead:
        return []
    if target.strftime("%Y-%m-%d") in blackout:
        return []
    if not windows:
        return []

    duration = int(service_type.get("duration_minutes") or 60)
    buffer = int(service_type.get("buffer_minutes") or 0)
    step = duration + buffer

    slots: List[Dict[str, Any]] = []
    date_key = target.strftime("%Y-%m-%d")
    # Pre-load existing pending + confirmed bookings AND scheduled jobs
    # for the day so we can subtract capacity 1:1.
    existing = await db.instaschedule_bookings.find({
        "tenant_id": cfg["tenant_id"],
        "config_slug": cfg["slug"],
        "status": {"$in": ["pending", "confirmed"]},
        "requested_slot.date": date_key,
    }, {"requested_slot": 1, "_id": 0}).to_list(500)
    from utils import not_deleted_filter as _nd
    scheduled_jobs = await db.jobs.find({
        "tenant_id": cfg["tenant_id"],
        "scheduled_date": date_key,
        "status": {"$nin": ["cancelled", "completed"]},
        **_nd(),
    }, {"scheduled_start": 1, "_id": 0}).to_list(500)
    if len(existing) >= max_per_day:
        return []

    booked_starts = set()
    for e in existing:
        rs = e.get("requested_slot") or {}
        if rs.get("start_iso"):
            booked_starts.add(rs["start_iso"])
    for j in scheduled_jobs:
        st = j.get("scheduled_start")
        if st:
            booked_starts.add(st)

    now_utc = datetime.now(timezone.utc)
    earliest_allowed = now_utc + timedelta(hours=min_notice_h)

    for w in windows:
        try:
            start_min = _parse_hhmm(w["start"])
            end_min = _parse_hhmm(w["end"])
        except (ValueError, KeyError):
            continue
        cursor = start_min
        while cursor + duration <= end_min:
            slot_start = datetime.combine(target, datetime.min.time(),
                                            tzinfo=timezone.utc) \
                + timedelta(minutes=cursor)
            slot_end = slot_start + timedelta(minutes=duration)
            if slot_start >= earliest_allowed:
                start_iso = slot_start.strftime("%Y-%m-%dT%H:%M:%SZ")
                end_iso = slot_end.strftime("%Y-%m-%dT%H:%M:%SZ")
                if start_iso not in booked_starts:
                    slots.append({
                        "start_iso": start_iso,
                        "end_iso": end_iso,
                        "capacity_remaining": max(0,
                            max_per_day - len(existing) - len([s for s in slots
                                if s["start_iso"].startswith(date_key)])),
                    })
            cursor += step
    return slots


async def _fire_automation_event(tenant_id: str, event: str,
                                    payload: Dict[str, Any]) -> None:
    try:
        from services.automation_engine import emit
        await emit(event, payload, tenant_id, entity_kind="instaschedule",
                    entity_id=payload.get("booking_id", ""))
    except Exception as e:
        logger.warning(f"[instaschedule] automation event {event!r} failed: {e}")


# ═════════════════════════════════════════════════════════════════════
# Admin — Config CRUD
# ═════════════════════════════════════════════════════════════════════

@router.post("/instaschedule/rate-limit/reset")
async def reset_rl(user: dict = Depends(require_admin)):
    _reset_rate_limit()
    return {"ok": True}


@router.get("/instaschedule/configs")
async def list_configs(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    rows = await db.instaschedule_configs.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"count": len(rows), "configs": rows}


@router.post("/instaschedule/configs", status_code=201)
async def create_config(body: ConfigIn,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    slug = (body.slug or "").strip().lower()
    if await db.instaschedule_configs.find_one({"slug": slug}, {"_id": 0}):
        raise HTTPException(409, "slug already taken")
    if body.route_integration.assign_strategy not in _ALLOWED_ASSIGN:
        raise HTTPException(422,
            f"assign_strategy must be one of {sorted(_ALLOWED_ASSIGN)}")
    now = now_iso()
    doc = _normalize_ids({
        "id": new_id(), "tenant_id": tenant["id"], "slug": slug,
        "headline": body.headline, "subheadline": body.subheadline or "",
        "brand_color": body.brand_color, "logo_url": body.logo_url,
        "service_types": [s.model_dump() for s in body.service_types],
        "availability_rules": body.availability_rules.model_dump(),
        "route_integration": body.route_integration.model_dump(),
        "collect_fields": body.collect_fields.model_dump(),
        "thank_you_html": body.thank_you_html or "",
        "success_redirect_url": body.success_redirect_url,
        "notification_channels": body.notification_channels or ["email"],
        "active": bool(body.active),
        "created_at": now, "updated_at": now,
    })
    if doc["active"]:
        await db.instaschedule_configs.update_many(
            {"tenant_id": tenant["id"]}, {"$set": {"active": False}})
    await db.instaschedule_configs.insert_one(doc)
    return _clean(doc)


@router.get("/instaschedule/configs/{cid}")
async def get_config(cid: str,
                       user: dict = Depends(require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    row = await db.instaschedule_configs.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "config not found")
    return row


@router.patch("/instaschedule/configs/{cid}")
async def patch_config(cid: str, body: ConfigPatch,
                         user: dict = Depends(require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    row = await db.instaschedule_configs.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "config not found")
    updates = body.model_dump(exclude_none=True)
    for k in ("service_types",):
        if k in updates and isinstance(updates[k], list):
            updates[k] = [
                (v.model_dump() if hasattr(v, "model_dump") else v)
                for v in updates[k]
            ]
    for k in ("availability_rules", "route_integration", "collect_fields"):
        if k in updates and hasattr(updates[k], "model_dump"):
            updates[k] = updates[k].model_dump()
    updates["updated_at"] = now_iso()
    row.update(updates)
    row = _normalize_ids(row)
    await db.instaschedule_configs.update_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"$set": row})
    return _clean(row)


@router.delete("/instaschedule/configs/{cid}", status_code=204)
async def delete_config(cid: str,
                          user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    r = await db.instaschedule_configs.delete_one(
        {"id": cid, "tenant_id": tenant["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "config not found")
    return None


@router.post("/instaschedule/configs/{cid}/activate")
async def activate_config(cid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    row = await db.instaschedule_configs.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "config not found")
    await db.instaschedule_configs.update_many(
        {"tenant_id": tenant["id"]}, {"$set": {"active": False}})
    await db.instaschedule_configs.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"active": True, "updated_at": now_iso()}})
    return {"ok": True, "id": cid}


# ═════════════════════════════════════════════════════════════════════
# Admin — Bookings
# ═════════════════════════════════════════════════════════════════════

@router.get("/instaschedule/bookings")
async def list_bookings(user: dict = Depends(require_admin),
                          tenant: dict = Depends(get_current_tenant),
                          status: Optional[str] = Query(None),
                          from_date: Optional[str] = Query(None, alias="from"),
                          to_date: Optional[str] = Query(None, alias="to"),
                          limit: int = Query(50, ge=1, le=200),
                          cursor: Optional[str] = Query(None)):
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date:
            rng["$gte"] = from_date
        if to_date:
            rng["$lte"] = to_date
        q["requested_slot.date"] = rng
    if cursor:
        q["created_at"] = {"$lt": cursor}
    rows = await db.instaschedule_bookings.find(q, {"_id": 0}) \
        .sort("created_at", -1).to_list(limit)
    return {
        "count": len(rows),
        "bookings": rows,
        "next_cursor": rows[-1]["created_at"] if len(rows) == limit else None,
    }


@router.get("/instaschedule/bookings/{bid}")
async def get_booking(bid: str,
                        user: dict = Depends(require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    row = await db.instaschedule_bookings.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "booking not found")
    return row


async def _pick_technician(*, tenant_id: str,
                             strategy: str,
                             booking_date: str) -> Optional[Dict[str, Any]]:
    """Return the technician document to assign, or None for manual."""
    if strategy == "admin_manual":
        return None
    techs = await db.technicians.find(
        {"tenant_id": tenant_id, "active": {"$ne": False}},
        {"_id": 0}).to_list(200)
    if not techs:
        return None
    if strategy == "round_robin":
        # Rotate by day-of-year mod tech count. Deterministic + cheap.
        idx = int(datetime.strptime(booking_date, "%Y-%m-%d")
                    .timetuple().tm_yday) % len(techs)
        return techs[idx]
    if strategy == "least_loaded":
        counts = []
        for t in techs:
            n = await db.jobs.count_documents({
                "tenant_id": tenant_id,
                "technician_id": t["id"],
                "scheduled_date": booking_date,
                "status": {"$nin": ["cancelled", "completed"]},
            })
            counts.append((n, t))
        counts.sort(key=lambda x: (x[0], x[1].get("name") or ""))
        return counts[0][1] if counts else None
    return None


@router.post("/instaschedule/bookings/{bid}/confirm")
async def confirm_booking(bid: str,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    booking = await db.instaschedule_bookings.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not booking:
        raise HTTPException(404, "booking not found")
    if booking.get("status") == "confirmed":
        raise HTTPException(409, "already confirmed")
    if booking.get("status") in ("declined", "cancelled"):
        raise HTTPException(409, f"cannot confirm a {booking['status']} booking")
    cfg = await db.instaschedule_configs.find_one(
        {"slug": booking["config_slug"], "tenant_id": tenant["id"]},
        {"_id": 0})
    if not cfg:
        raise HTTPException(404, "config gone")
    st = next((s for s in (cfg.get("service_types") or [])
                if s.get("id") == booking["service_type_id"]), None)
    service_name = (st or {}).get("name") or "Service"

    # 1) Customer upsert. Prefer booking.customer_id if the prospect
    # linked their account; otherwise match by email → phone → create
    # a fresh lightweight customer row.
    contact = booking.get("contact") or {}
    email = (contact.get("email") or "").strip().lower() or None
    phone_norm = "".join(ch for ch in (contact.get("phone") or "")
                          if ch.isdigit() or ch == "+") or None
    now = now_iso()
    cust = None
    if booking.get("customer_id"):
        cust = await db.customers.find_one(
            {"id": booking["customer_id"], "tenant_id": tenant["id"]},
            {"_id": 0})
    if not cust and email:
        cust = await db.customers.find_one(
            {"tenant_id": tenant["id"], "email": email}, {"_id": 0})
    if not cust and not email and phone_norm:
        cust = await db.customers.find_one(
            {"tenant_id": tenant["id"], "phone": phone_norm}, {"_id": 0})
    inserted: List[tuple] = []
    if not cust:
        cust = {
            "id": new_id(), "tenant_id": tenant["id"],
            "name": contact.get("name") or "InstaSchedule Lead",
            "email": email, "phone": phone_norm,
            "address": contact.get("address") or "",
            "source": "instaschedule",
            "created_at": now, "updated_at": now,
        }
        await db.customers.insert_one(cust)
        inserted.append(("customers", {"id": cust["id"]}))

    # 2) Technician assignment per config strategy.
    booking_date = (booking.get("requested_slot") or {}).get("date") or ""
    strategy = ((cfg.get("route_integration") or {})
                 .get("assign_strategy") or "admin_manual")
    tech = None
    if (cfg.get("route_integration") or {}).get("enabled"):
        tech = await _pick_technician(tenant_id=tenant["id"],
                                        strategy=strategy,
                                        booking_date=booking_date)

    # 3) Job row.
    slot = booking.get("requested_slot") or {}
    job = {
        "id": new_id(), "tenant_id": tenant["id"],
        "customer_id": cust["id"], "customer_name": cust.get("name") or "",
        "title": f"{service_name} · InstaSchedule",
        "service_type": service_name,
        "scheduled_date": booking_date,
        "scheduled_start": slot.get("start_iso"),
        "scheduled_end": slot.get("end_iso"),
        "address": contact.get("address") or cust.get("address") or "",
        "notes": booking.get("notes") or contact.get("notes") or "",
        "price": 0.0, "photos": [], "status": "pending",
        "source": "instaschedule",
        "instaschedule_booking_id": bid,
        "technician_id": (tech or {}).get("id"),
        "technician_name": (tech or {}).get("name"),
        "created_at": now,
    }
    try:
        await db.jobs.insert_one(job)
        inserted.append(("jobs", {"id": job["id"]}))
    except Exception as e:
        for coll, filt in inserted:
            await db[coll].delete_one(filt)
        raise HTTPException(500, f"job creation failed: {e}")

    await db.instaschedule_bookings.update_one(
        {"id": bid, "tenant_id": tenant["id"]},
        {"$set": {"status": "confirmed",
                   "confirmed_at": now,
                   "confirmed_by": user.get("id"),
                   "computed_job_id": job["id"],
                   "computed_customer_id": cust["id"],
                   "assigned_user_id": (tech or {}).get("id")}})

    # Non-fatal: fire the confirmation event.
    await _fire_automation_event(tenant["id"], "instaschedule.confirmed", {
        "booking_id": bid, "job_id": job["id"],
        "customer_id": cust["id"], "scheduled_date": booking_date,
    })

    fresh = await db.instaschedule_bookings.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    return {
        "booking": _clean(fresh),
        "job_id": job["id"],
        "customer_id": cust["id"],
        "assigned_user_id": (tech or {}).get("id"),
    }


@router.post("/instaschedule/bookings/{bid}/decline")
async def decline_booking(bid: str, body: DeclineIn,
                            user: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    row = await db.instaschedule_bookings.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "booking not found")
    if row.get("status") in ("confirmed", "cancelled"):
        raise HTTPException(409, f"cannot decline a {row['status']} booking")
    await db.instaschedule_bookings.update_one(
        {"id": bid, "tenant_id": tenant["id"]},
        {"$set": {"status": "declined",
                   "decline_reason": body.reason or "",
                   "declined_at": now_iso(),
                   "declined_by": user.get("id")}})
    # Optional prospect notification — non-fatal.
    if body.notify_prospect:
        await _fire_automation_event(tenant["id"], "instaschedule.declined", {
            "booking_id": bid,
            "contact_email": ((row.get("contact") or {}).get("email") or ""),
            "reason": body.reason or "",
        })
    fresh = await db.instaschedule_bookings.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    return _clean(fresh)


@router.post("/instaschedule/bookings/{bid}/cancel")
async def cancel_booking(bid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    row = await db.instaschedule_bookings.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "booking not found")
    if row.get("status") == "cancelled":
        raise HTTPException(409, "already cancelled")
    now = now_iso()
    updates: Dict[str, Any] = {"status": "cancelled",
                                  "cancelled_at": now,
                                  "cancelled_by": user.get("id")}
    # Cascade: cancel the linked job so the schedule stays consistent.
    if row.get("computed_job_id"):
        await db.jobs.update_one(
            {"id": row["computed_job_id"], "tenant_id": tenant["id"]},
            {"$set": {"status": "cancelled", "cancelled_at": now}})
    await db.instaschedule_bookings.update_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"$set": updates})
    fresh = await db.instaschedule_bookings.find_one(
        {"id": bid, "tenant_id": tenant["id"]}, {"_id": 0})
    return _clean(fresh)


# ═════════════════════════════════════════════════════════════════════
# Public — Config + Slots + Book
# ═════════════════════════════════════════════════════════════════════

@router.get("/public/instaschedule/{slug}")
async def public_config(slug: str):
    row = await db.instaschedule_configs.find_one({"slug": slug, "active": True},
                                                     {"_id": 0})
    if not row:
        raise HTTPException(404, "not found")
    return _public_view(row)


@router.get("/public/instaschedule/{slug}/slots")
async def public_slots(slug: str,
                          service_type_id: str = Query(...),
                          date_str: str = Query(..., alias="date",
                                                  description="YYYY-MM-DD")):
    row = await db.instaschedule_configs.find_one({"slug": slug, "active": True},
                                                     {"_id": 0})
    if not row:
        raise HTTPException(404, "not found")
    try:
        target = _iso_date(date_str)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")
    st = next((s for s in (row.get("service_types") or [])
                if s.get("id") == service_type_id and s.get("allow_public_book")),
                None)
    if not st:
        raise HTTPException(404, "service_type not found or not bookable")
    slots = await _compute_slots(cfg=row, service_type=st, target=target)
    return {"date": date_str, "service_type_id": service_type_id,
             "slots": slots}


@router.post("/public/instaschedule/{slug}/book",
              status_code=201, response_model=BookingAckOut,
              description=(
                  "Public self-booking endpoint. NO auth.\n\n"
                  "Server re-validates the requested slot inside the "
                  "write path — races that consumed the slot after "
                  "the client fetched availability return **409 slot "
                  "unavailable**. Never overbook.\n\n"
                  "Rate-limit: 3 per IP per 10 min. Honeypot `_hp` "
                  "returns a real-shaped ack including the requested "
                  "slot echo without persisting."
              ))
async def public_book(slug: str, body: BookIn, request: Request):
    row = await db.instaschedule_configs.find_one({"slug": slug, "active": True},
                                                     {"_id": 0})
    if not row:
        raise HTTPException(404, "not found")

    # Honeypot: return real-shaped ack including the derived `date`
    # key on the slot echo so attackers can't A/B on subtle shape
    # differences vs the legit path. No DB write, no automation
    # event, no rate-limit slot spent.
    if getattr(body, "hp_field", None):
        hp_slot = dict(body.requested_slot or {})
        if hp_slot.get("start_iso") and "date" not in hp_slot:
            try:
                hp_dt = datetime.fromisoformat(
                    hp_slot["start_iso"].replace("Z", "+00:00"))
                hp_slot["date"] = hp_dt.date().strftime("%Y-%m-%d")
            except ValueError:
                pass
        return BookingAckOut(
            id=new_id(),
            status="pending",
            service_type_id=body.service_type_id,
            requested_slot=hp_slot,
            thank_you_html=row.get("thank_you_html") or "",
            success_redirect_url=row.get("success_redirect_url"),
        ).model_dump()

    # Rate limit.
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "unknown")
    if not _rl_allow(ip):
        raise HTTPException(429, "rate limit — try again in a few minutes")

    # Validate service_type.
    st = next((s for s in (row.get("service_types") or [])
                if s.get("id") == body.service_type_id
                    and s.get("allow_public_book")), None)
    if not st:
        raise HTTPException(404, "service_type not bookable")

    slot = body.requested_slot or {}
    start_iso = slot.get("start_iso") or ""
    end_iso = slot.get("end_iso") or ""
    if not (start_iso and end_iso):
        raise HTTPException(422, "requested_slot.start_iso + end_iso required")
    try:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "bad start_iso")
    target = start_dt.date()
    date_key = target.strftime("%Y-%m-%d")

    # Race guard: re-validate against the current slot set.
    live_slots = await _compute_slots(cfg=row, service_type=st, target=target)
    live_starts = {s["start_iso"] for s in live_slots}
    if start_iso not in live_starts:
        raise HTTPException(409, "slot unavailable — please pick another time")

    if st.get("restricted_to_existing_customer"):
        # Require either a linked customer_id OR an email that matches
        # an existing customer.
        email = (body.contact.email or "").strip().lower() or None
        existing = None
        if body.customer_id:
            existing = await db.customers.find_one(
                {"id": body.customer_id, "tenant_id": row["tenant_id"]},
                {"_id": 0})
        if not existing and email:
            existing = await db.customers.find_one(
                {"tenant_id": row["tenant_id"], "email": email}, {"_id": 0})
        if not existing:
            raise HTTPException(403,
                "this service is available to existing customers only")

    if st.get("requires_address") and not (body.contact.address or ""):
        raise HTTPException(422, "address is required for this service")

    now = now_iso()
    doc = {
        "id": new_id(), "tenant_id": row["tenant_id"],
        "config_slug": slug,
        "service_type_id": body.service_type_id,
        "requested_slot": {
            "date": date_key,
            "start_iso": start_iso,
            "end_iso": end_iso,
        },
        "contact": body.contact.model_dump(),
        "notes": body.notes or "",
        "customer_id": body.customer_id or None,
        "status": "pending",
        "computed_job_id": None,
        "computed_customer_id": None,
        "assigned_user_id": None,
        "source": "public",
        "ip": ip,
        "user_agent": (request.headers.get("user-agent") or "")[:512],
        "honey_pot_hit": False,
        "created_at": now,
    }
    await db.instaschedule_bookings.insert_one(doc)
    await _fire_automation_event(row["tenant_id"], "instaschedule.booked", {
        "booking_id": doc["id"],
        "config_slug": slug,
        "scheduled_date": date_key,
        "start_iso": start_iso,
        "contact_email": (body.contact.email or ""),
        "contact_name": (body.contact.name or ""),
    })
    # Unified notifications — new_lead ping to tenant admins.
    try:
        from services.notifications import enqueue_for_tenant_admins
        who = body.contact.name or body.contact.email or "New prospect"
        service_name = (st or {}).get("name") or "Service"
        await enqueue_for_tenant_admins(
            row["tenant_id"], "new_lead",
            title=f"New lead · {who}",
            body=f"InstaSchedule booking — {service_name} on {date_key}. Slug: {slug}.",
            source_ref={"kind": "instaschedule_booking", "id": doc["id"]},
            href=f"/instaschedule/bookings/{doc['id']}",
            priority="high",
        )
    except Exception as _e:
        logger.warning(f"[instaschedule] unified notify failed: {_e}")
    return BookingAckOut(
        id=doc["id"], status="pending",
        service_type_id=body.service_type_id,
        requested_slot=doc["requested_slot"],
        thank_you_html=row.get("thank_you_html") or "",
        success_redirect_url=row.get("success_redirect_url"),
    ).model_dump()
