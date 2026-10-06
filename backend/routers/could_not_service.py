"""Feb-2026 · Phase 1 — Tech "Could Not Service" outcome + reasons CRUD.

Two closely-related surfaces live in this router:

    * ``GET/POST/PATCH/DELETE /api/settings/job-outcome-reasons`` —
      tenant-scoped preset list of "Could Not Service" reasons.
      Auto-hydrates 7 defaults on first GET so new tenants don't have
      to click "Seed defaults".
    * ``POST /api/jobs/{job_id}/could-not-service`` — flips a job to
      the new terminal-ish status ``could_not_service``, records the
      reason + notes + at least one attached photo, and fires the
      customer SMS via the same helper the OMW endpoint uses.

Reuses the existing comms gate, SMS adapter, and file store — no new
deps, no new backend infrastructure.
"""
from __future__ import annotations

import re
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from config import db, logger
from utils import now_iso, new_id, get_current_user
from routers.tenants import get_current_tenant


router = APIRouter()


_ALLOWED_TECH_ROLES = {"technician", "manager", "admin", "super_admin"}
_ALLOWED_ADMIN_ROLES = {"admin", "super_admin"}
_TEMPLATE_KEY = "job_could_not_service"


_DEFAULT_REASONS = [
    ("locked_out",           "Locked out"),
    ("no_water",             "No water / equipment off"),
    ("unsafe_conditions",    "Unsafe conditions"),
    ("weather",              "Weather"),
    ("customer_refused",     "Customer refused service"),
    ("equipment_failure",    "Equipment failure"),
    ("other",                "Other"),
]


def _slugify(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(label or "").lower()).strip("_")
    return s or new_id()[:8]


async def _hydrate_defaults(tenant_id: str):
    existing = await db.job_outcome_reasons.count_documents({"tenant_id": tenant_id})
    if existing:
        return
    now = now_iso()
    docs = [
        {"id": new_id(), "tenant_id": tenant_id, "key": k, "label": lbl,
         "sort_order": i, "is_default": True, "active": True,
         "created_at": now, "updated_at": now}
        for i, (k, lbl) in enumerate(_DEFAULT_REASONS)
    ]
    await db.job_outcome_reasons.insert_many(docs)


# ─── reasons CRUD ───────────────────────────────────────────────────
class ReasonIn(BaseModel):
    label: str
    sort_order: Optional[int] = None


class ReasonPatch(BaseModel):
    label: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


@router.get("/settings/job-outcome-reasons")
async def list_reasons(include_inactive: bool = False,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_TECH_ROLES:
        raise HTTPException(403, "role not permitted")
    # Feb-2026 · Only admins may fetch inactive reasons (admin settings panel).
    if include_inactive and role not in _ALLOWED_ADMIN_ROLES:
        include_inactive = False
    tid = tenant["id"]
    await _hydrate_defaults(tid)
    q: dict = {"tenant_id": tid}
    if not include_inactive:
        q["active"] = True
    rows = await db.job_outcome_reasons.find(
        q, {"_id": 0},
    ).sort("sort_order", 1).to_list(200)
    return {"reasons": rows}


@router.post("/settings/job-outcome-reasons")
async def create_reason(body: ReasonIn,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ADMIN_ROLES:
        raise HTTPException(403, "admin only")
    tid = tenant["id"]
    await _hydrate_defaults(tid)
    label = (body.label or "").strip()
    if not label:
        raise HTTPException(422, "label required")
    key = _slugify(label)
    if await db.job_outcome_reasons.find_one({"tenant_id": tid, "key": key}):
        raise HTTPException(409, "reason with this label already exists")
    order = body.sort_order
    if order is None:
        max_row = await db.job_outcome_reasons.find(
            {"tenant_id": tid}, {"_id": 0, "sort_order": 1},
        ).sort("sort_order", -1).limit(1).to_list(1)
        order = ((max_row[0]["sort_order"] + 1) if max_row else 0)
    now = now_iso()
    doc = {"id": new_id(), "tenant_id": tid, "key": key, "label": label,
           "sort_order": int(order), "is_default": False, "active": True,
           "created_at": now, "updated_at": now}
    await db.job_outcome_reasons.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


@router.patch("/settings/job-outcome-reasons/{rid}")
async def patch_reason(rid: str, body: ReasonPatch,
                         user: dict = Depends(get_current_user),
                         tenant: dict = Depends(get_current_tenant)):
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ADMIN_ROLES:
        raise HTTPException(403, "admin only")
    tid = tenant["id"]
    r = await db.job_outcome_reasons.find_one(
        {"id": rid, "tenant_id": tid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "reason not found")
    upd = {"updated_at": now_iso()}
    if body.label is not None:
        upd["label"] = body.label.strip()
    if body.sort_order is not None:
        upd["sort_order"] = int(body.sort_order)
    if body.active is not None:
        upd["active"] = bool(body.active)
    await db.job_outcome_reasons.update_one(
        {"id": rid, "tenant_id": tid}, {"$set": upd})
    r.update(upd)
    return r


@router.delete("/settings/job-outcome-reasons/{rid}")
async def delete_reason(rid: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_ADMIN_ROLES:
        raise HTTPException(403, "admin only")
    tid = tenant["id"]
    r = await db.job_outcome_reasons.find_one(
        {"id": rid, "tenant_id": tid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "reason not found")
    if r.get("is_default"):
        raise HTTPException(400, "cannot hard-delete a seeded default; toggle active=false instead")
    await db.job_outcome_reasons.delete_one({"id": rid, "tenant_id": tid})
    return {"deleted": True}


# ─── could-not-service endpoint ────────────────────────────────────
class CouldNotServiceBody(BaseModel):
    reason_id: str
    reason_notes: Optional[str] = None
    photo_file_ids: List[str] = Field(default_factory=list)


def _first_name(rec: dict, fallback_key: str = "name") -> str:
    first = (rec.get("first_name") or "").strip()
    if first:
        return first
    full = (rec.get(fallback_key) or "").strip()
    return full.split(" ", 1)[0] if full else ""


def _company_name(tenant: dict) -> str:
    return (tenant.get("company_name") or tenant.get("name") or "").strip()


def _render_body(customer_first: str, tech_first: str, company: str,
                  reason_label: str) -> str:
    return (
        f"Hi {customer_first}, this is {tech_first} from {company}. "
        f"We attempted service today but couldn't complete it — reason: "
        f"{reason_label}. We'll be in touch to reschedule. "
        f"Reply STOP to opt out."
    )


@router.post("/jobs/{job_id}/could-not-service")
async def could_not_service(
    job_id: str,
    body: CouldNotServiceBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = (user.get("role") or "").lower()
    if role not in _ALLOWED_TECH_ROLES:
        raise HTTPException(403, "role not permitted")
    tid = tenant["id"]

    job = await db.jobs.find_one({"id": job_id, "tenant_id": tid}, {"_id": 0, "photos.data": 0})
    if not job:
        raise HTTPException(404, "job not found")
    current_status = str(job.get("status") or "").lower()
    if current_status in ("completed", "canceled", "cancelled"):
        raise HTTPException(409, f"job is already {current_status}")

    reason = await db.job_outcome_reasons.find_one(
        {"id": body.reason_id, "tenant_id": tid}, {"_id": 0})
    if not reason:
        raise HTTPException(422, "reason not found")
    if not reason.get("active", True):
        raise HTTPException(422, "reason is inactive")

    if not body.photo_file_ids:
        raise HTTPException(422, "at least one photo is required")
    # Verify each attached file id exists for this tenant.
    found = await db.files.count_documents(
        {"id": {"$in": body.photo_file_ids}, "tenant_id": tid})
    if found != len(body.photo_file_ids):
        raise HTTPException(422, "one or more photo_file_ids are invalid")

    now = now_iso()
    upd = {
        "status": "could_not_service",
        "outcome_reason_id": body.reason_id,
        "outcome_reason_notes": (body.reason_notes or "").strip() or None,
        "outcome_photo_file_ids": body.photo_file_ids,
        "outcome_recorded_by_user_id": user.get("id"),
        "outcome_recorded_at": now,
        "updated_at": now,
    }
    await db.jobs.update_one({"id": job_id, "tenant_id": tid}, {"$set": upd})

    # Reason label for SMS body (special-case "other").
    if reason.get("key") == "other":
        notes = (body.reason_notes or "").strip()
        reason_label = (notes.split("\n", 1)[0][:60] if notes else "unable to complete")
    else:
        reason_label = reason.get("label") or "unable to complete"

    cust = await db.customers.find_one(
        {"id": job.get("customer_id"), "tenant_id": tid}, {"_id": 0}) or {}
    tech = await db.users.find_one(
        {"$or": [
            {"id": job.get("technician_id") or job.get("tech_user_id"), "tenant_id": tid},
            {"technician_id": job.get("technician_id"), "tenant_id": tid},
        ]}, {"_id": 0}) or {}

    sms_result = {"sent": False, "reason": None, "communication_id": None}
    if cust.get("is_demo_account") is not True and (cust.get("blocked")
                                                     or cust.get("is_blocked")):
        sms_result["reason"] = "customer_blocked"
    elif cust.get("sms_opt_in") is False:
        sms_result["reason"] = "sms_opt_in_false"
    else:
        phone = (cust.get("phone")
                 or (cust.get("mobiles") or [{}])[0].get("number_e164"))
        if not phone:
            sms_result["reason"] = "no_phone"
        else:
            from services.comms.gate import is_comm_allowed
            allowed = await is_comm_allowed(
                recipient_identifier=phone, comm_type="sms",
                tenant_id=tid, provider="ringcentral",
                trigger_action="job_could_not_service",
            )
            if not allowed:
                sms_result["reason"] = "outbound_disabled"
            else:
                # SMS-RECIPIENT-FIX · Feb-2026 — customer-facing deny-list
                # guardrail; keeps workforce/tenant-owned numbers off the
                # could-not-service outcome SMS even if the customer
                # record is contaminated. Matches the
                # ``on_my_way.py:321-333`` precedent.
                from services.comms_hardening.deny_list import (
                    strip_admin_owned_recipients,
                )
                _kept, _stripped = await strip_admin_owned_recipients(
                    tenant_id=tid, kind="customer_facing", channel="sms",
                    recipients=[phone],
                    context={"trigger": "could_not_service",
                              "job_id": job_id,
                              "customer_id": cust.get("id")},
                )
                if _stripped:
                    logger.warning(
                        "[could_not_service] denied_admin_owned_recipient "
                        "tenant=%s job=%s customer=%s phone=%s",
                        tid, job_id, cust.get("id"), phone,
                    )
                    sms_result["reason"] = "denied_admin_owned_recipient"
                else:
                    phone = _kept[0] if _kept else phone
                    sms_body = _render_body(
                        customer_first=_first_name(cust) or "there",
                        tech_first=_first_name(tech) or "your technician",
                        company=_company_name(tenant) or "our team",
                        reason_label=reason_label,
                    )
                    from services.comms_sms_adapter import send_sms
                    from services.comms_env_guard import CommsContext
                    result = await send_sms(tid, phone, sms_body,
                                            context=CommsContext.SYSTEM)
                    status = result.get("status")
                    if status == "failed":
                        sms_result["reason"] = "send_failed"
                    else:
                        comm_id = new_id()
                        await db.communications.insert_one({
                            "id": comm_id, "tenant_id": tid,
                            "customer_id": cust.get("id"), "job_id": job_id,
                            "channel": "sms", "direction": "outbound",
                            "template_key": _TEMPLATE_KEY, "body": sms_body,
                            "to": phone, "sent_by_user_id": user.get("id"),
                            "sent_at": now,
                            "status": "sent" if status in ("sent", "mocked") else "queued",
                            "provider_message_id": result.get("provider_id"),
                        })
                        sms_result = {"sent": True, "reason": None,
                                        "communication_id": comm_id}

    logger.info(
        "[could_not_service] tenant=%s job=%s user=%s reason_key=%s sms=%s",
        tid, job_id, user.get("id"), reason.get("key"), sms_result,
    )
    fresh_job = await db.jobs.find_one({"id": job_id, "tenant_id": tid}, {"_id": 0, "photos.data": 0})
    return {
        "status": "could_not_service",
        "job": fresh_job,
        "sms_result": sms_result,
    }
