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

import asyncio
import os
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
    customers_with_active_service,
)
from services.portal_magic_links import build_portal_home_url
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
    published document. Feb-2026 · Slice 2D — fires a non-blocking
    notification blast to affected customers.
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
    # Slice 2D — non-blocking blast. Wrapped in create_task so the
    # publish HTTP response returns immediately; every exception is
    # trapped inside :func:`_run_publish_blast` so Resend flakes can
    # never fail the endpoint.
    try:
        asyncio.create_task(
            _run_publish_blast(document=row, tenant=tenant),
        )
    except Exception as _e:  # pragma: no cover — belt-and-braces
        logger.warning(f"[slice-2d] blast task schedule failed: {_e}")
    return row


# ══════════════════════════════════════════════════════════════════════
# Feb-2026 · Slice 2D — Publish notification blast
# ══════════════════════════════════════════════════════════════════════
async def _run_publish_blast(
    *, document: Dict[str, Any], tenant: Dict[str, Any],
) -> None:
    """Enqueue one email per affected customer for a newly-published
    ToS document.  Idempotent via a document-scoped
    ``marketing_event_ledger`` row keyed ``tos_update:{doc_id}`` —
    the same upsert-first-then-dispatch pattern used by the door-
    hanger auto-send and the elevated-follow-up ledger.
    """
    try:
        doc_id = document.get("id")
        tenant_id = tenant.get("id")
        service_type = document.get("service_type")
        if not (doc_id and tenant_id and service_type in SERVICE_TYPES):
            return
        # Idempotency guard — try to insert the document-level ledger
        # row FIRST. Second publish of the same doc collides on the
        # unique compound index and the blast is skipped entirely.
        try:
            await db.marketing_event_ledger.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "event_key": f"tos_update:{doc_id}",
                "trigger_type": "tos_update",
                "correlation_id": doc_id,
                "processed_at": now_iso(),
                "meta": {"document_id": doc_id,
                         "service_type": service_type,
                         "version": int(document.get("version") or 1)},
            })
        except Exception as exc:
            if type(exc).__name__ == "DuplicateKeyError":
                logger.info(
                    f"[slice-2d] blast skipped — ledger key "
                    f"tos_update:{doc_id} already present"
                )
                return
            # Any other write failure — bail loudly but don't crash.
            logger.warning(f"[slice-2d] ledger insert failed: {exc}")
            return

        recipients = await customers_with_active_service(
            db, tenant_id, service_type,
        )
        for cust in recipients:
            await _blast_one_customer(
                document=document, tenant=tenant, cust=cust,
            )
    except Exception as e:
        logger.warning(f"[slice-2d] publish blast crashed: {e}")


def _resolve_public_base_url() -> str:
    from config import APP_PUBLIC_URL
    return APP_PUBLIC_URL or ""


def _tos_blast_html(*, doc, tenant, cust, cta_url) -> str:
    """Card-based, inline-styles-only email body reusing the visual
    system introduced by the door-hanger visual redesign (Slice 5).
    Copy is factual + non-alarming.
    """
    company = (tenant or {}).get("name") or "Pool & Landscaping of Vistancia"
    brand = (tenant or {}).get("brand_color") or "#1f2937"
    tenant_phone = (
        (tenant or {}).get("phone")
        or (tenant or {}).get("rc_sms_from_number")
        or "602-887-4400"
    )
    first = (
        (cust or {}).get("first_name")
        or (((cust or {}).get("name") or "").split(" ", 1)[0])
        or "Neighbor"
    )
    service_label = (
        "landscaping" if doc.get("service_type") == "landscaping" else "pool"
    )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="100%" style="border-collapse:collapse;'
        f'background:#F1F5F9;">'
        f'<tr><td align="center" style="padding:24px 12px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="640" style="border-collapse:collapse;'
        f'max-width:640px;font-family:Inter,Arial,sans-serif;color:#0F172A;">'
        f'<tr><td>'

        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="100%" style="border-collapse:collapse;'
        f'background:{brand};color:#FFFFFF;border-radius:12px;'
        f'margin:0 0 16px 0;">'
        f'<tr><td style="padding:24px;">'
        f'<div style="font-size:12px;letter-spacing:0.08em;'
        f'text-transform:uppercase;opacity:0.85;">Updated terms</div>'
        f'<div style="font-size:20px;font-weight:700;margin-top:4px;">'
        f'{company}</div>'
        f'</td></tr></table>'

        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" width="100%" style="border-collapse:collapse;'
        f'background:#FFFFFF;border:1px solid #E2E8F0;'
        f'border-radius:12px;margin:0 0 16px 0;">'
        f'<tr><td style="padding:20px;">'
        f'<p style="margin:0 0 8px;font-size:15px;">'
        f'Hi {first},</p>'
        f"<p style=\"margin:0 0 16px;font-size:14px;color:#334155;"
        f"line-height:1.5;\">"
        f"We've updated our Terms of Service for {service_label} "
        f"customers. Please review and accept the updated terms at "
        f"your next portal visit — this email is for your records; "
        f"the portal will prompt you when you sign in."
        f"</p>"
        f'<div style="text-align:center;margin:8px 0 4px;">'
        f'<a href="{cta_url}" '
        f'style="display:inline-block;background:{brand};'
        f'color:#FFFFFF;padding:12px 24px;border-radius:8px;'
        f'text-decoration:none;font-weight:600;font-size:14px;">'
        f'Review Updated Terms</a></div>'
        f'</td></tr></table>'

        f'<p style="font-size:13px;color:#334155;margin-top:24px;'
        f'text-align:center;">We appreciate your business<br/>'
        f'<b>{company}</b><br/>{tenant_phone}</p>'
        f'</td></tr></table></td></tr></table>'
    )


async def _blast_one_customer(
    *, document: Dict[str, Any], tenant: Dict[str, Any],
    cust: Dict[str, Any],
) -> None:
    """Send (or skip + log) the ToS-update email for one customer.
    Every branch writes a ``marketing_deliveries`` row so we can
    diff sent vs skipped vs failed after the fact.
    """
    doc_id = document.get("id")
    cid = cust.get("id")
    tenant_id = tenant.get("id")
    email = (cust or {}).get("email")

    def _delivery(status: str, reason: Optional[str] = None,
                    provider_response_id: Optional[str] = None) -> Dict[str, Any]:
        return {
            "id": new_id(),
            "tenant_id": tenant_id,
            "customer_id": cid,
            "trigger_entity": {"kind": "tos_document", "id": doc_id},
            "trigger_type": "tos_update",
            "event_key": f"tos_update:{doc_id}:{cid}",
            "channel": "email",
            "to": email,
            "status": status,  # ``sent`` / ``skipped`` / ``failed``
            "skip_reason": reason,
            "provider_status": provider_response_id and "sent" or None,
            "provider_response_id": provider_response_id,
            "created_at": now_iso(),
        }

    # Skip rules.
    if not email:
        await db.marketing_deliveries.insert_one(
            _delivery("skipped", reason="no_email"),
        )
        return
    if cust.get("unsubscribed"):
        await db.marketing_deliveries.insert_one(
            _delivery("skipped", reason="unsubscribed"),
        )
        return
    if cust.get("do_not_contact"):
        await db.marketing_deliveries.insert_one(
            _delivery("skipped", reason="do_not_contact"),
        )
        return

    # Compose + send.
    base = _resolve_public_base_url()
    try:
        cta_url = (
            build_portal_home_url(base, cid, tenant_id)
            if base else ""
        )
    except Exception as _mint_exc:
        logger.warning(f"[slice-2d] portal_home token mint failed: {_mint_exc}")
        cta_url = ""
    subject = (
        f"Updated Terms of Service — "
        f"{(tenant or {}).get('name') or 'Pool & Landscaping'}"
    )
    html = _tos_blast_html(
        doc=document, tenant=tenant, cust=cust, cta_url=cta_url,
    )
    try:
        from services.email import resend_adapter
        result = await resend_adapter.send(
            to=email, subject=subject, html=html,
            sender=(tenant or {}).get("settings", {}).get("email_sender"),
        )
        provider_id = (
            (result or {}).get("id") or (result or {}).get("provider_id")
        )
        await db.marketing_deliveries.insert_one(
            _delivery("sent", provider_response_id=provider_id),
        )
    except Exception as exc:
        logger.warning(
            f"[slice-2d] Resend failed for cust={cid} doc={doc_id}: {exc}"
        )
        row = _delivery("failed", reason=str(exc)[:200])
        row["provider_status"] = "failed"
        await db.marketing_deliveries.insert_one(row)


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
