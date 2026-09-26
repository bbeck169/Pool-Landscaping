"""Feb-2026 · C1 · Chemical Application records (regulatory log).

Tracks every field-recorded chemical spray with the who / what / where /
when / weather + REI (Restricted-Entry Interval) unlock timestamp so
the customer's property is not re-entered before the label period
expires.  Separate from ``routers/chemicals.py`` which handles the
chemical *catalog* (pricebook items with ``category='Chemical'``) and
AI dosing recommendations — this router owns application *records*
(regulatory log entries), a distinct concept.

Endpoints
─────────
  * POST   /chemical-applications              — tech + admin create
  * GET    /chemical-applications              — filtered list, tech + admin
  * GET    /chemical-applications/{app_id}     — single fetch, tech + admin
  * GET    /chemical-applications/{app_id}/rei-status  — REI countdown
  * PATCH  /chemical-applications/{app_id}     — admin only (regulatory sensitivity)
  * DELETE /chemical-applications/{app_id}     — admin only

Cross-tenant hardening on ``customer_id`` mirrors ``measurements.py``
from ``9ecc749d3`` — the referenced customer MUST live in the caller's
tenant or the write is rejected 403.

Server auto-fields (un-spoofable — ``ChemicalApplicationIn`` does not
declare them so any client-supplied ``technician_id`` / ``tenant_id`` /
``license_number`` / ``rei_unlock_at`` in the JSON body is silently
stripped by Pydantic):
  * ``tenant_id``          — from the caller's tenant dep
  * ``technician_id``      — from ``current_user.id``
  * ``technician_name``    — from ``current_user.name``
  * ``license_number``     — snapshot of ``user.applicator_license_number``
                              at write time; frozen even if the user
                              later changes their license number, so the
                              regulatory record reflects reality at the
                              moment of spray
  * ``created_at``         / ``updated_at``  — UTC ISO-8601 strings
  * ``rei_unlock_at``      — computed as
                              ``application_date + start_time + rei_hours``
                              in UTC ISO-8601
"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from config import db
from utils import new_id, now_iso, require_admin
from routers.tenants import get_current_tenant
from routers.pool_calculators import require_tech_or_above

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════
# Pydantic input model
# ═══════════════════════════════════════════════════════════════════
class ChemicalApplicationIn(BaseModel):
    # When ─────────────────────────────────────────────────────────
    application_date: date
    start_time: time
    stop_time: time

    # Where ─────────────────────────────────────────────────────────
    customer_id: str
    property_address: Optional[str] = None

    # Weather ───────────────────────────────────────────────────────
    temp_f: Optional[float] = None
    humidity_pct: Optional[float] = None
    wind_mph: Optional[float] = None
    wind_direction: Optional[str] = None
    weather_source: Optional[Literal["manual", "openweather"]] = "manual"
    weather_fetched_at: Optional[datetime] = None

    # Chemical details ──────────────────────────────────────────────
    chemical_name: str
    area_treated_sqft: float
    amount_sprayed_gal: float
    concentrate_oz: float

    # Regulatory ────────────────────────────────────────────────────
    target_pest: str
    rei_hours: float

    # Attachments (photo uploader — populated in C4; C1 accepts [])
    attachments: List[dict] = Field(default_factory=list)

    # Free-form
    notes: Optional[str] = None

    # ── field validators ─────────────────────────────────────────
    @field_validator("chemical_name", "target_pest")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip()

    @field_validator("area_treated_sqft")
    @classmethod
    def _area_positive(cls, v: float) -> float:
        if v is None or v <= 0:
            raise ValueError("area_treated_sqft must be > 0")
        return float(v)

    @field_validator("amount_sprayed_gal", "concentrate_oz", "rei_hours")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v is None or v < 0:
            raise ValueError("must be >= 0")
        return float(v)


class ChemicalApplicationPatch(BaseModel):
    """Admin-only patch — every field optional; validators run only
    on fields the caller explicitly sends."""
    application_date: Optional[date] = None
    start_time: Optional[time] = None
    stop_time: Optional[time] = None
    property_address: Optional[str] = None
    temp_f: Optional[float] = None
    humidity_pct: Optional[float] = None
    wind_mph: Optional[float] = None
    wind_direction: Optional[str] = None
    weather_source: Optional[Literal["manual", "openweather"]] = None
    weather_fetched_at: Optional[datetime] = None
    chemical_name: Optional[str] = None
    area_treated_sqft: Optional[float] = None
    amount_sprayed_gal: Optional[float] = None
    concentrate_oz: Optional[float] = None
    target_pest: Optional[str] = None
    rei_hours: Optional[float] = None
    attachments: Optional[List[dict]] = None
    notes: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════
async def _assert_owns_customer(cid: str, tenant_id: str) -> None:
    """Mirror the guard in ``routers/measurements.py`` — the
    customer_id must exist in this tenant.  A tech in tenant A must
    not be able to log an application against tenant B's customer,
    even by directly hitting the API."""
    hit = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    if not hit:
        raise HTTPException(
            status_code=403,
            detail="customer_id not found in caller tenant",
        )


def _compute_rei_unlock_at(app_date: date, start: time,
                              rei_hours: float) -> str:
    """Combine ``application_date`` + ``start_time`` at UTC, add
    ``rei_hours``, return ISO-8601.  The regulatory contract is
    "no re-entry until at least ``rei_hours`` after application
    start", so we lock the countdown to ``start_time`` (not stop)."""
    naive = datetime.combine(app_date, start)
    aware = naive.replace(tzinfo=timezone.utc)
    unlocked = aware + timedelta(hours=float(rei_hours or 0))
    return unlocked.isoformat()


def _shape_output(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


def _rei_status(doc: dict) -> dict:
    """REI countdown snapshot at the moment of the request."""
    unlock_iso = doc.get("rei_unlock_at")
    if not unlock_iso:
        return {
            "rei_hours": doc.get("rei_hours", 0),
            "rei_unlock_at": None,
            "is_locked": False,
            "hours_remaining": 0.0,
        }
    unlock_dt = datetime.fromisoformat(unlock_iso)
    now = datetime.now(timezone.utc)
    delta_hours = (unlock_dt - now).total_seconds() / 3600.0
    return {
        "rei_hours": doc.get("rei_hours", 0),
        "rei_unlock_at": unlock_iso,
        "is_locked": delta_hours > 0,
        "hours_remaining": max(0.0, round(delta_hours, 4)),
    }


# ═══════════════════════════════════════════════════════════════════
# POST — create (tech + admin)
# ═══════════════════════════════════════════════════════════════════
@router.post("/chemical-applications")
async def create_chemical_application(
    body: ChemicalApplicationIn,
    user: dict = Depends(require_tech_or_above),
    tenant: dict = Depends(get_current_tenant),
):
    await _assert_owns_customer(body.customer_id, tenant["id"])

    now = now_iso()
    rei_unlock_at = _compute_rei_unlock_at(
        body.application_date, body.start_time, body.rei_hours,
    )

    doc = {
        "id": new_id(),
        # Server-attached — un-spoofable (client keys stripped by Pydantic).
        "tenant_id":       tenant["id"],
        "technician_id":   user["id"],
        "technician_name": user.get("name", ""),
        "license_number":  user.get("applicator_license_number") or None,
        "created_at":      now,
        "updated_at":      now,
        "rei_unlock_at":   rei_unlock_at,
        # Wire fields (ISO-normalised for date / time so Mongo can sort).
        "application_date":    body.application_date.isoformat(),
        "start_time":          body.start_time.isoformat(),
        "stop_time":           body.stop_time.isoformat(),
        "customer_id":         body.customer_id,
        "property_address":    body.property_address,
        "temp_f":              body.temp_f,
        "humidity_pct":        body.humidity_pct,
        "wind_mph":            body.wind_mph,
        "wind_direction":      body.wind_direction,
        "weather_source":      body.weather_source,
        "weather_fetched_at":  (body.weather_fetched_at.isoformat()
                                 if body.weather_fetched_at else None),
        "chemical_name":       body.chemical_name,
        "area_treated_sqft":   body.area_treated_sqft,
        "amount_sprayed_gal":  body.amount_sprayed_gal,
        "concentrate_oz":      body.concentrate_oz,
        "target_pest":         body.target_pest,
        "rei_hours":           body.rei_hours,
        "attachments":         body.attachments,
        "notes":               body.notes,
    }
    await db.chemical_applications.insert_one(doc)
    return _shape_output(doc)


# ═══════════════════════════════════════════════════════════════════
# GET — filtered list (tech + admin)
# ═══════════════════════════════════════════════════════════════════
@router.get("/chemical-applications")
async def list_chemical_applications(
    customer_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    technician_id: Optional[str] = Query(None),
    target_pest: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    cursor: Optional[str] = Query(None),
    user: dict = Depends(require_tech_or_above),
    tenant: dict = Depends(get_current_tenant),
):
    q: dict = {"tenant_id": tenant["id"]}
    if customer_id:
        q["customer_id"] = customer_id
    if technician_id:
        q["technician_id"] = technician_id
    if target_pest:
        # Partial match — case-insensitive substring on ``target_pest``.
        import re as _re
        q["target_pest"] = {"$regex": _re.escape(target_pest),
                              "$options": "i"}
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["application_date"] = rng
    if cursor:
        q["_id_lt_cursor"] = cursor  # unused hint — cursor uses created_at
        q["created_at"] = {"$lt": cursor}
        q.pop("_id_lt_cursor", None)

    docs = await (db.chemical_applications
                    .find(q, {"_id": 0})
                    .sort([("application_date", -1), ("start_time", -1)])
                    .limit(limit)
                    .to_list(limit))
    next_cursor = docs[-1]["created_at"] if len(docs) == limit else None
    return {"items": docs, "next_cursor": next_cursor}


# ═══════════════════════════════════════════════════════════════════
# GET one · tenant-scoped
# ═══════════════════════════════════════════════════════════════════
@router.get("/chemical-applications/{app_id}")
async def get_chemical_application(
    app_id: str,
    user: dict = Depends(require_tech_or_above),
    tenant: dict = Depends(get_current_tenant),
):
    doc = await db.chemical_applications.find_one(
        {"id": app_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "chemical application not found")
    return _shape_output(doc)


# ═══════════════════════════════════════════════════════════════════
# GET /rei-status · countdown badge feed for C3 list page
# ═══════════════════════════════════════════════════════════════════
@router.get("/chemical-applications/{app_id}/rei-status")
async def rei_status(
    app_id: str,
    user: dict = Depends(require_tech_or_above),
    tenant: dict = Depends(get_current_tenant),
):
    doc = await db.chemical_applications.find_one(
        {"id": app_id, "tenant_id": tenant["id"]},
        {"_id": 0, "rei_hours": 1, "rei_unlock_at": 1},
    )
    if not doc:
        raise HTTPException(404, "chemical application not found")
    return _rei_status(doc)


# ═══════════════════════════════════════════════════════════════════
# PATCH · admin-only (regulatory sensitivity)
# ═══════════════════════════════════════════════════════════════════
@router.patch("/chemical-applications/{app_id}")
async def patch_chemical_application(
    app_id: str,
    body: ChemicalApplicationPatch,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    doc = await db.chemical_applications.find_one(
        {"id": app_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "chemical application not found")

    # Build the update dict only from fields the caller explicitly sent.
    payload = body.model_dump(exclude_unset=True)
    updates: dict = {}
    for key, val in payload.items():
        if key == "application_date" and val is not None:
            updates[key] = val.isoformat()
        elif key in ("start_time", "stop_time") and val is not None:
            updates[key] = val.isoformat()
        elif key == "weather_fetched_at" and val is not None:
            updates[key] = val.isoformat()
        else:
            updates[key] = val

    # Regulatory-sensitive value validation on any writable numeric field.
    if "area_treated_sqft" in updates and (updates["area_treated_sqft"] is None
                                            or updates["area_treated_sqft"] <= 0):
        raise HTTPException(422, "area_treated_sqft must be > 0")
    for k in ("amount_sprayed_gal", "concentrate_oz", "rei_hours"):
        if k in updates and updates[k] is not None and updates[k] < 0:
            raise HTTPException(422, f"{k} must be >= 0")

    # Recompute rei_unlock_at when any input to it changes.
    if any(k in updates for k in ("application_date", "start_time", "rei_hours")):
        new_date = (date.fromisoformat(updates["application_date"])
                    if "application_date" in updates
                    else date.fromisoformat(doc["application_date"]))
        new_start = (time.fromisoformat(updates["start_time"])
                     if "start_time" in updates
                     else time.fromisoformat(doc["start_time"]))
        new_hours = (updates["rei_hours"] if "rei_hours" in updates
                     else doc["rei_hours"])
        updates["rei_unlock_at"] = _compute_rei_unlock_at(
            new_date, new_start, new_hours,
        )

    updates["updated_at"] = now_iso()
    await db.chemical_applications.update_one(
        {"id": app_id, "tenant_id": tenant["id"]}, {"$set": updates},
    )
    fresh = await db.chemical_applications.find_one(
        {"id": app_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    return _shape_output(fresh)


# ═══════════════════════════════════════════════════════════════════
# DELETE · admin-only
# ═══════════════════════════════════════════════════════════════════
@router.delete("/chemical-applications/{app_id}")
async def delete_chemical_application(
    app_id: str,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    res = await db.chemical_applications.delete_one(
        {"id": app_id, "tenant_id": tenant["id"]},
    )
    if res.deleted_count == 0:
        raise HTTPException(404, "chemical application not found")
    return {"ok": True}
