"""MR0 · Feb-2026 — Public check-in submission.

Endpoint::

    POST /api/checkins/{checkin_id}/submit-public

Allows a technician (owner of the check-in) or an admin+ to submit a
checkin for admin moderation. The row lands in ``db.public_checkins``
in ``state='pending_review'``. Nothing is published until an admin
approves via ``/api/admin/moderation/public-checkins/{id}/approve``.

Body
----
``{ publish_to_website: bool, photo_license_ack: bool,
    description?: str, tags?: [str] }``

Both booleans must be true for a queue row to be created. Otherwise the
endpoint returns ``{ submitted: false, reason: "opt_out_or_no_license" }``
with a 200 status — the base check-in itself is untouched.

Once submitted, a second call for the same ``source_checkin_id`` returns
409 (double-submit prevention).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import db, logger
from services.coord_obfuscator import obfuscate_coords
from utils import get_current_user, new_id, now_iso

router = APIRouter()

_ADMIN_ROLES = {"admin", "super_admin", "manager"}


class SubmitPublicBody(BaseModel):
    publish_to_website: bool = False
    photo_license_ack: bool = False
    description: Optional[str] = None
    tags: Optional[List[str]] = None


async def _load_customer_address(customer_id: str | None) -> Dict[str, str]:
    if not customer_id:
        return {"street": "", "city": "", "state": "",
                "zip": "", "country": ""}
    cust = await db.customers.find_one(
        {"id": customer_id},
        {"_id": 0, "address_street": 1, "address_city": 1,
         "address_state": 1, "address_zip": 1, "address_country": 1,
         "address": 1, "city": 1, "state": 1, "zip": 1, "country": 1},
    )
    if not cust:
        return {"street": "", "city": "", "state": "",
                "zip": "", "country": ""}
    return {
        "street": cust.get("address_street") or cust.get("address") or "",
        "city": cust.get("address_city") or cust.get("city") or "",
        "state": cust.get("address_state") or cust.get("state") or "",
        "zip": cust.get("address_zip") or cust.get("zip") or "",
        "country": cust.get("address_country") or cust.get("country") or "US",
    }


async def _load_job_customer(job_id: str | None) -> Dict[str, Any]:
    """Given a job/workorder id, find the linked customer + tenant."""
    if not job_id:
        return {}
    # jobs collection first, then workorders.
    for coll_name in ("jobs", "workorders"):
        row = await db[coll_name].find_one(
            {"id": job_id},
            {"_id": 0, "id": 1, "tenant_id": 1, "customer_id": 1,
             "service_name": 1, "service_category": 1,
             "completed_at": 1, "closed_at": 1},
        )
        if row:
            return row
    return {}


async def _load_customer_geo(customer_id: str | None,
                              tenant_id: str) -> Dict[str, Any]:
    """Load coord + area_label fields off the customer for the map
    pin. Called as a FALLBACK when the check-in itself doesn't
    carry GPS coords (old rows, or admin-created check-ins)."""
    if not customer_id:
        return {}
    cust = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "latitude": 1, "longitude": 1,
         "address_city": 1, "address_state": 1,
         "city": 1, "state": 1, "property": 1},
    )
    return cust or {}


def _area_label_from_customer(cust: Dict[str, Any]) -> str:
    """Best-effort ``"City, ST"`` label for the public pin tooltip.
    Mirrors ``services.public_checkin_enqueue._area_label`` so the
    tech-submit path and auto-enqueue path emit the same field."""
    prop = cust.get("property") or {}
    city = (cust.get("address_city") or cust.get("city")
              or prop.get("city") or "")
    state = (cust.get("address_state") or cust.get("state")
               or prop.get("state") or "")
    city = str(city).strip()
    state = str(state).strip()
    if city and state:
        return f"{city}, {state}"
    return city or state or ""


def _month_year(iso_ts: str | None) -> str:
    """ISO ts → ``"Month YYYY"`` (never leaks specific day). Same
    shape as ``services.public_checkin_enqueue._month_year``."""
    if not iso_ts:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        return dt.strftime("%B %Y")
    except (ValueError, TypeError):
        return ""


@router.post("/checkins/{checkin_id}/submit-public",
              operation_id="publicCheckins.submit")
async def submit_public_checkin(
    checkin_id: str,
    body: SubmitPublicBody,
    caller: Dict[str, Any] = Depends(get_current_user),
):
    checkin = await db.checkins.find_one({"id": checkin_id}, {"_id": 0})
    if not checkin:
        raise HTTPException(404, {"error": "checkin_not_found"})

    caller_role = (caller.get("role") or "").lower()
    caller_id = caller.get("id")
    tech_id = checkin.get("technician_id") or checkin.get("user_id")
    if caller_role not in _ADMIN_ROLES and caller_id != tech_id:
        raise HTTPException(403, {"error": "forbidden"})

    if not body.publish_to_website or not body.photo_license_ack:
        return {"submitted": False, "reason": "opt_out_or_no_license"}

    # Enforce single queue row per source_checkin.
    existing = await db.public_checkins.find_one(
        {"source_checkin_id": checkin_id},
        {"_id": 0, "id": 1, "state": 1},
    )
    if existing:
        raise HTTPException(
            409,
            {"error": "already_submitted",
             "public_checkin_id": existing.get("id"),
             "state": existing.get("state")},
        )

    job = await _load_job_customer(
        checkin.get("job_id") or checkin.get("workorder_id"))
    tenant_id = (job.get("tenant_id")
                  or caller.get("tenant_id")
                  or checkin.get("tenant_id"))
    if not tenant_id:
        raise HTTPException(400, {"error": "missing_tenant"})

    raw_address = await _load_customer_address(job.get("customer_id"))
    # Fallback: any address stored on the checkin itself.
    if not raw_address["street"] and checkin.get("address"):
        addr = checkin["address"]
        if isinstance(addr, str):
            raw_address["street"] = addr
        elif isinstance(addr, dict):
            for src_key, dst_key in (
                ("street", "street"), ("city", "city"),
                ("state", "state"), ("zip", "zip"),
            ):
                if not raw_address[dst_key] and addr.get(src_key):
                    raw_address[dst_key] = addr[src_key]

    photos_src = (checkin.get("photos")
                   or checkin.get("photo_urls")
                   or [])
    photos: List[Dict[str, Any]] = []
    for i, p in enumerate(photos_src):
        if isinstance(p, str):
            photos.append({"id": new_id(), "url": p, "alt": None, "order": i})
        elif isinstance(p, dict) and p.get("url"):
            photos.append({
                "id": p.get("id") or new_id(),
                "url": p["url"],
                "alt": p.get("alt"),
                "order": p.get("order", i),
            })

    description = (body.description
                    or checkin.get("description")
                    or checkin.get("note")
                    or checkin.get("notes")
                    or "").strip()

    # Feb-2026 · Technician Check-In flow · Fix — resolve raw + public
    # coords for the public map pin. Priority: (1) GPS captured on
    # the check-in itself; (2) customer's geocoded coords as a
    # fallback (matches auto-enqueue behaviour). Same deterministic
    # obfuscator + seed as the auto-enqueue path so the pin lands
    # in the same spot regardless of which surface enqueued it.
    lat_raw = (checkin.get("latitude") if checkin.get("latitude") is not None
                else checkin.get("lat"))
    lng_raw = (checkin.get("longitude") if checkin.get("longitude") is not None
                else checkin.get("lng"))
    cust_geo: Dict[str, Any] = {}
    if (lat_raw is None or lng_raw is None) and job.get("customer_id"):
        cust_geo = await _load_customer_geo(job.get("customer_id"), tenant_id)
        if lat_raw is None:
            lat_raw = cust_geo.get("latitude")
        if lng_raw is None:
            lng_raw = cust_geo.get("longitude")
    lat_public, lng_public = obfuscate_coords(
        lat_raw, lng_raw, seed=str(checkin_id),
    )
    # Prefer the customer-derived label (matches auto-enqueue), fall
    # back to the raw_address dict we already loaded.
    area_label = _area_label_from_customer(cust_geo) or (
        f"{raw_address['city']}, {raw_address['state']}"
        if raw_address["city"] and raw_address["state"]
        else raw_address["city"] or raw_address["state"] or ""
    )
    completed_at = (job.get("completed_at")
                     or job.get("closed_at")
                     or checkin.get("checked_out_at")
                     or checkin.get("created_at")
                     or now_iso())

    row = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "source_checkin_id": checkin_id,
        "source_job_id": job.get("id"),
        "source": "tech",
        "submitted_by_user_id": caller_id,
        "submitted_at": now_iso(),
        "state": "pending_review",
        "photo_license_ack": True,
        "service_name": job.get("service_name") or "",
        "service_category": job.get("service_category"),
        "description": description,
        "tags": list(body.tags or []),
        "photos": photos,
        "raw_address": raw_address,
        "masked_address": None,
        # ── Map-specific fields (Feb-2026) ─────────────────────────
        "lat_raw": lat_raw,                  # admin view only
        "lng_raw": lng_raw,                  # admin view only
        "lat_public": lat_public,            # public map endpoint
        "lng_public": lng_public,
        "area_label": area_label,
        "completed_at": completed_at,
        "completed_at_month_year": _month_year(completed_at),
        "reviewed_by_user_id": None,
        "reviewed_at": None,
        "reviewer_notes": None,
        "approved_at": None,
        "approved_by_user_id": None,
        "unpublished_at": None,
        "unpublished_by_user_id": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.public_checkins.insert_one(row)

    # Feb-2026 · Technician Check-In flow — also flip the source
    # ``checkins`` record from ``draft`` → ``submitted`` so the mobile
    # Job-Detail screen can show "Submitted for review" instead of
    # letting the tech re-submit the same photos.
    try:
        await db.checkins.update_one(
            {"id": checkin_id},
            {"$set": {"status": "submitted",
                       "public_checkin_id": row["id"],
                       "submitted_at": now_iso()}},
        )
    except Exception as e:                                              # noqa: BLE001
        logger.warning("checkin status flip failed for %s: %s", checkin_id, e)

    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "event": "public_checkin_submitted",
            "email": caller.get("email"),
            "ip_address": None,
            "status": "success",
            "details": f"checkin={checkin_id} public_id={row['id']}",
            "tenant_id": tenant_id,
            "created_at": now_iso(),
        })
    except Exception as e:                                              # noqa: BLE001
        logger.warning("audit insert failed for public_checkin: %s", e)

    return {"submitted": True, "public_checkin_id": row["id"]}


async def ensure_public_checkins_indexes() -> None:
    """Called once on backend startup to guarantee the moderation
    queue has the compound + unique indexes it needs. Idempotent."""
    coll = db.public_checkins
    await coll.create_index([("tenant_id", 1), ("state", 1),
                              ("submitted_at", -1)],
                              name="tenant_state_submitted")
    await coll.create_index([("tenant_id", 1), ("source_checkin_id", 1)],
                              name="tenant_source_unique", unique=True)
