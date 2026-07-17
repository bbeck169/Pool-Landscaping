"""Phase 56.4 — Tech Job Request workflow.

Techs cannot create jobs directly (Phase 56.3.C RBAC). This router
gives them a formal request path that routes to admin approval,
creating a paper trail without unblocking creation.

Endpoints:
  POST   /api/job-requests               — any technician (or admin) can file
  GET    /api/job-requests?status=&mine= — techs see own; admins see all
  GET    /api/job-requests/{id}          — owner or admin
  PATCH  /api/job-requests/{id}          — admin only (status / reason / notes)
  POST   /api/job-requests/{id}/convert  — admin only, spawns a real job

Storage: `job_requests` collection, tenant-scoped.
"""
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from config import db, logger
from routers.tenants import get_current_tenant
from utils import now_iso, new_id, get_current_user, require_admin
from services.notifications import emit as notify_emit

router = APIRouter()


_STATUSES = {"pending", "approved", "rejected", "converted"}
_PRIORITIES = {"normal", "urgent"}


class JobRequestIn(BaseModel):
    customer_id: Optional[str] = None
    customer_name_hint: Optional[str] = ""
    customer_phone_hint: Optional[str] = ""
    address_hint: Optional[str] = ""
    service_type: Optional[str] = ""
    scheduled_preference: Optional[str] = "asap"   # asap | this_week | next_week | ISO date
    priority: Optional[str] = "normal"
    notes: Optional[str] = ""
    photos: Optional[List[str]] = []


class JobRequestPatch(BaseModel):
    status: Optional[str] = None
    rejection_reason: Optional[str] = None
    notes: Optional[str] = None


class JobRequestConvert(BaseModel):
    """Payload for admin approval-to-job conversion. Fields override the
    hints on the request when present, matching `JobIn` shape."""
    customer_id: str
    title: str
    service_type: str
    scheduled_date: str
    technician_id: Optional[str] = None
    price: Optional[float] = None
    address: Optional[str] = ""
    notes: Optional[str] = ""


def _is_admin(user: dict) -> bool:
    return (user.get("role") or "").lower() in ("admin", "super_admin")


def _sanitize_priority(v: Optional[str]) -> str:
    p = (v or "normal").strip().lower()
    return p if p in _PRIORITIES else "normal"


@router.post("/job-requests")
async def create_job_request(body: JobRequestIn,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    role = (user.get("role") or "").lower()
    if role not in ("technician", "admin", "super_admin"):
        raise HTTPException(403, "Only technicians and admins may file job requests")

    doc = body.dict()
    # Tech-supplied fields never dictate lifecycle — status locked, reviewer null.
    doc.update({
        "id": new_id(),
        "tenant_id": tenant["id"],
        "requested_by_user_id": user["id"],
        "requested_by_name": user.get("name") or user.get("email") or "Tech",
        "priority": _sanitize_priority(doc.get("priority")),
        "status": "pending",
        "created_at": now_iso(),
        "reviewed_at": None,
        "reviewed_by_user_id": None,
        "converted_job_id": None,
        "rejection_reason": None,
    })
    await db.job_requests.insert_one(doc)
    doc.pop("_id", None)

    # Notify all admin + super_admin.
    try:
        admins = await db.users.find(
            {"tenant_id": tenant["id"], "role": {"$in": ["admin", "super_admin"]}},
            {"_id": 0, "id": 1},
        ).to_list(200)
        aids = [a["id"] for a in admins if a.get("id")]
        if aids:
            hint = doc.get("customer_name_hint") or doc.get("address_hint") or "field opportunity"
            await notify_emit(
                aids, kind="system_alert",
                title=f"New job request from {doc['requested_by_name']}",
                body=f"{doc['service_type'] or 'Job'} — {hint}",
                href=f"/admin/job-requests?id={doc['id']}",
                tenant_id=tenant["id"], audience="internal",
                source_ref={"kind": "job_request", "id": doc["id"]},
            )
    except Exception:
        pass
    return doc


@router.get("/job-requests")
async def list_job_requests(status: Optional[str] = None,
                             mine: Optional[bool] = None,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    q: dict = {"tenant_id": tenant["id"]}
    role = (user.get("role") or "").lower()
    if role == "customer":
        raise HTTPException(403, "Not authorized")
    # Techs are always scoped to their own requests, regardless of `mine`.
    if role == "technician":
        q["requested_by_user_id"] = user["id"]
    elif mine:
        q["requested_by_user_id"] = user["id"]
    if status:
        if status not in _STATUSES:
            raise HTTPException(400, f"status must be one of: {sorted(_STATUSES)}")
        q["status"] = status
    rows = await db.job_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return rows


@router.get("/job-requests/{req_id}")
async def get_job_request(req_id: str,
                           user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    doc = await db.job_requests.find_one({"id": req_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job request not found")
    if not _is_admin(user) and doc.get("requested_by_user_id") != user.get("id"):
        raise HTTPException(403, "Not authorized")
    return doc


@router.patch("/job-requests/{req_id}")
async def update_job_request(req_id: str, body: JobRequestPatch,
                              user: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    doc = await db.job_requests.find_one({"id": req_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job request not found")

    updates: dict = {}
    if body.status is not None:
        if body.status not in _STATUSES:
            raise HTTPException(400, f"status must be one of: {sorted(_STATUSES)}")
        # 'converted' is only set by the convert endpoint.
        if body.status == "converted":
            raise HTTPException(400, "Use POST /job-requests/{id}/convert to convert")
        updates["status"] = body.status
    if body.rejection_reason is not None:
        updates["rejection_reason"] = body.rejection_reason
    if body.notes is not None:
        updates["notes"] = body.notes
    if not updates:
        return {"ok": True, "unchanged": True}
    updates["reviewed_at"] = now_iso()
    updates["reviewed_by_user_id"] = user.get("id")

    await db.job_requests.update_one(
        {"id": req_id, "tenant_id": tenant["id"]}, {"$set": updates}
    )

    # Notify the requesting tech on approval/rejection.
    try:
        st = updates.get("status")
        if st in ("approved", "rejected"):
            title = "Job request approved" if st == "approved" else "Job request rejected"
            body_txt = (
                f"Your request was approved and will be scheduled soon."
                if st == "approved"
                else f"Your request was rejected. Reason: {updates.get('rejection_reason') or 'See admin notes.'}"
            )
            await notify_emit(
                [doc["requested_by_user_id"]], kind="system_alert",
                title=title, body=body_txt,
                href=f"/job-requests/{req_id}",
                tenant_id=tenant["id"], audience="internal",
                source_ref={"kind": "job_request", "id": req_id},
            )
    except Exception:
        pass

    doc2 = await db.job_requests.find_one({"id": req_id, "tenant_id": tenant["id"]}, {"_id": 0})
    return doc2


@router.post("/job-requests/{req_id}/convert")
async def convert_job_request(req_id: str, body: JobRequestConvert,
                                user: dict = Depends(require_admin),
                                tenant: dict = Depends(get_current_tenant)):
    """Admin approval-to-job — spawns a real job from the request.
    Uses the same insert-shape as `POST /api/jobs` to keep behavior
    consistent (customer_name backfill, tech name lookup, auto-assign
    hook). Sets `status: "converted"` + `converted_job_id` on the
    request atomically."""
    doc = await db.job_requests.find_one({"id": req_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Job request not found")
    if doc.get("status") == "converted":
        raise HTTPException(409, "Job request already converted")

    customer = await db.customers.find_one(
        {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not customer:
        raise HTTPException(400, "Customer not found")

    tech_name = None
    tech_avatar = ""
    if body.technician_id:
        tech = await db.technicians.find_one(
            {"id": body.technician_id, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        tech_name = tech["name"] if tech else None
        tech_avatar = (tech.get("avatar") if tech else "") or ""

    job_id = new_id()
    job_doc = {
        "id": job_id,
        "tenant_id": tenant["id"],
        "customer_id": body.customer_id,
        "customer_name": customer.get("name"),
        "title": body.title,
        "service_type": body.service_type,
        "scheduled_date": body.scheduled_date,
        "technician_id": body.technician_id,
        "technician_name": tech_name,
        "technician_avatar": tech_avatar,
        "price": body.price,
        "address": body.address or customer.get("address", ""),
        "notes": body.notes or doc.get("notes") or "",
        "status": "pending",
        "photos": doc.get("photos") or [],
        "created_at": now_iso(),
        "source": "job_request",
        "source_ref_id": req_id,
    }
    await db.jobs.insert_one(job_doc)
    job_doc.pop("_id", None)

    await db.job_requests.update_one(
        {"id": req_id, "tenant_id": tenant["id"]},
        {"$set": {
            "status": "converted",
            "converted_job_id": job_id,
            "reviewed_at": now_iso(),
            "reviewed_by_user_id": user.get("id"),
        }},
    )

    # Notify the requesting tech.
    try:
        await notify_emit(
            [doc["requested_by_user_id"]], kind="system_alert",
            title="Job request converted",
            body=f"Your request has been scheduled as a job on {body.scheduled_date}.",
            href=f"/jobs/{job_id}",
            tenant_id=tenant["id"], audience="internal",
            source_ref={"kind": "job_request_converted", "id": req_id},
        )
    except Exception:
        pass

    return {"ok": True, "job": job_doc, "request_id": req_id}
