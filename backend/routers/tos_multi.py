"""Feb-2026 · Slice 2A — Multi-ToS Backend Foundation router.

Endpoint surface
----------------
Admin (admin OR super_admin — enforced via ``get_current_user`` role
check inside each handler):

* ``GET  /admin/tos-documents``              — list, filterable by
  ``service_type`` / ``status`` / ``version``.
* ``POST /admin/tos-documents``              — create new draft.
* ``GET  /admin/tos-documents/{doc_id}``     — read one.
* ``PUT  /admin/tos-documents/{doc_id}``     — update draft (rejects
  updates on ``published`` / ``superseded`` — legal audit invariant).
* ``POST /admin/tos-documents/{doc_id}/publish`` — draft → published,
  atomically supersedes the prior published row for
  ``(tenant, service_type)``.

Customer (authenticated as ``role=customer``):

* ``GET  /customer-portal/onboarding-state`` — extends the legacy
  onboarding-state shape with a ``pending_tos`` array of documents
  the customer still needs to accept (ordered pool → landscaping).
* ``POST /customer-portal/tos/{document_id}/accept`` — stamps an
  ``tos_acceptances`` row + updates the customer's embedded
  ``tos_status.{service_type}`` map.

Notes
-----
* HTML is sanitized SERVER-SIDE via :func:`services.tos_service.sanitize_html`
  before being written to Mongo. Client-side sanitization is treated
  as untrusted per the scope-guard requirement.
* Every admin write goes through :func:`services.tos_service.next_version_for`
  so ``version`` is monotonically increasing per (tenant, service_type).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from config import db, logger
from services.tos_service import (
    SERVICE_TYPES,
    DOC_STATUSES,
    sanitize_html,
    compute_pending_tos_for_customer,
    record_customer_acceptance,
    publish_document,
    next_version_for,
)
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant


router = APIRouter(tags=["Multi-ToS"])


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "admin_or_super_admin_required")


def _require_customer(user: Dict[str, Any]) -> str:
    if user.get("role") != "customer":
        raise HTTPException(403, "customer_only")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(400, "user_missing_customer_id")
    return cid


# ══════════════════════════════════════════════════════════════════════
# Admin CRUD
# ══════════════════════════════════════════════════════════════════════
class TosDocCreate(BaseModel):
    service_type: str = Field(..., description="'pool' or 'landscaping'")
    title: str = ""
    content_html: str = ""
    content_json: Optional[Dict[str, Any]] = None
    effective_date: Optional[str] = None


class TosDocUpdate(BaseModel):
    title: Optional[str] = None
    content_html: Optional[str] = None
    content_json: Optional[Dict[str, Any]] = None
    effective_date: Optional[str] = None


def _dto(d: Dict[str, Any]) -> Dict[str, Any]:
    d = {**(d or {})}
    d.pop("_id", None)
    return d


@router.get("/admin/tos-documents")
async def list_tos_documents(
    service_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    version: Optional[int] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    q: Dict[str, Any] = {"tenant_id": tenant["id"]}
    if service_type:
        if service_type not in SERVICE_TYPES:
            raise HTTPException(400, "invalid_service_type")
        q["service_type"] = service_type
    if status:
        if status not in DOC_STATUSES:
            raise HTTPException(400, "invalid_status")
        q["status"] = status
    if version is not None:
        q["version"] = int(version)
    rows = await db.tos_documents.find(q, {"_id": 0}).sort(
        [("service_type", 1), ("version", -1)],
    ).to_list(length=500)
    return {"count": len(rows), "documents": rows}


@router.post("/admin/tos-documents")
async def create_tos_document(
    body: TosDocCreate,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    if body.service_type not in SERVICE_TYPES:
        raise HTTPException(400, "invalid_service_type")
    clean_html = sanitize_html(body.content_html)
    version = await next_version_for(db, tenant["id"], body.service_type)
    row = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "service_type": body.service_type,
        "version": version,
        "status": "draft",
        "title": (body.title or "").strip(),
        "content_html": clean_html,
        "content_json": body.content_json,
        "effective_date": body.effective_date,
        "created_at": now_iso(),
        "created_by": user.get("id"),
        "published_at": None,
        "published_by": None,
        "superseded_at": None,
    }
    await db.tos_documents.insert_one(row)
    return _dto(row)

@router.get("/admin/tos-documents/{doc_id}")
async def get_tos_document(
    doc_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    row = await db.tos_documents.find_one(
        {"id": doc_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "document_not_found")
    return row


@router.put("/admin/tos-documents/{doc_id}")
async def update_tos_document(
    doc_id: str,
    body: TosDocUpdate,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Edit a *draft*. Published + superseded documents are
    immutable — the workflow is: clone → new draft → publish, which
    increments the version and preserves the audit trail.
    """
    _require_admin(user)
    row = await db.tos_documents.find_one(
        {"id": doc_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "document_not_found")
    if row.get("status") != "draft":
        raise HTTPException(
            409, "only_draft_documents_are_editable",
        )
    patch: Dict[str, Any] = {"updated_at": now_iso()}
    if body.title is not None:
        patch["title"] = body.title.strip()
    if body.content_html is not None:
        patch["content_html"] = sanitize_html(body.content_html)
    if body.content_json is not None:
        patch["content_json"] = body.content_json
    if body.effective_date is not None:
        patch["effective_date"] = body.effective_date
    await db.tos_documents.update_one(
        {"id": doc_id, "tenant_id": tenant["id"]},
        {"$set": patch},
    )
    fresh = await db.tos_documents.find_one(
        {"id": doc_id, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    return fresh or row


@router.post("/admin/tos-documents/{doc_id}/publish")
async def publish_tos_document(
    doc_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Promote draft → published. Prior published row is atomically
    superseded (never deleted). Idempotent when called on an already-
    published document.
    """
    _require_admin(user)
    try:
        row = await publish_document(
            db, tenant_id=tenant["id"], document_id=doc_id,
            actor_id=user.get("id"),
        )
    except ValueError as e:
        code = str(e)
        status = 404 if code == "document_not_found" else 409
        raise HTTPException(status, code)
    return row


# ══════════════════════════════════════════════════════════════════════
# Customer portal
# ══════════════════════════════════════════════════════════════════════
@router.get("/customer-portal/onboarding-state")
async def get_customer_onboarding_state(
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Returns the shape ``OnboardingGate`` needs to sequence the
    first-login flow: tutorial completion flag + pending ToS list.
    """
    cid = _require_customer(user)
    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    ) or {}
    pending = await compute_pending_tos_for_customer(
        db, tenant["id"], customer,
    )
    return {
        "customer_id": cid,
        "tutorial_completed": bool(customer.get("tutorial_completed")),
        "pending_tos": pending,
        "tos_status": customer.get("tos_status") or {},
    }


class AcceptIn(BaseModel):
    pass  # body currently unused — reserved for future ``signature``


@router.post("/customer-portal/tos/{document_id}/accept")
async def customer_accept_tos(
    document_id: str,
    request: Request,
    _body: Optional[AcceptIn] = None,
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    cid = _require_customer(user)
    ip = (
        request.headers.get("x-forwarded-for")
        or (request.client.host if request.client else None)
    )
    ua = request.headers.get("user-agent")
    try:
        row = await record_customer_acceptance(
            db, tenant_id=tenant["id"], customer_id=cid,
            document_id=document_id, ip=ip, ua=ua,
        )
    except ValueError as e:
        code = str(e)
        status_code = 404 if code == "document_not_found" else 409
        raise HTTPException(status_code, code)

    # Recompute pending so the client can decide whether to unmount
    # the modal or advance to the next entry.
    customer = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    ) or {}
    pending = await compute_pending_tos_for_customer(
        db, tenant["id"], customer,
    )
    return {
        "ok": True,
        "acceptance": row,
        "pending_tos": pending,
    }
