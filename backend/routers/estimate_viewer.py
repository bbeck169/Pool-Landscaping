"""Feb 2026 · Slice R — Estimate Viewer aggregator + Accept/Decline + PDF.

Feb 2026 · Outcome C rename — Canonical paths moved to ``/quotes/{qid}/*``
because the underlying resource lives in ``db.quotes``. The old
``/estimates/{eid}/*`` paths are preserved as ``deprecated=True``
aliases pointing to the same handlers; response shape unchanged
(``estimate_id``, ``estimate_number`` fields retained for backward
compat). Slated for removal one release cycle after Feb 2026.

Endpoints (canonical + deprecated alias each):
    GET  /api/quotes/{qid}/full            — role-projected viewer payload
         (alias) /api/estimates/{qid}/full [deprecated]
    POST /api/quotes/{qid}/accept          — admin or portal customer
         (alias) /api/estimates/{qid}/accept [deprecated]
    POST /api/quotes/{qid}/decline         — same
         (alias) /api/estimates/{qid}/decline [deprecated]
    POST /api/quotes/{qid}/request-changes — same
         (alias) /api/estimates/{qid}/request-changes [deprecated]
    GET  /api/quotes/{qid}/magic-link      — admin issues token URL
         (alias) /api/estimates/{qid}/magic-link [deprecated]
    GET  /api/portal/quotes/via-token       — public, reads by JWT
         (alias) /api/portal/estimates/via-token [deprecated]
    POST /api/portal/quotes/via-token/accept
         (alias) /api/portal/estimates/via-token/accept [deprecated]
    POST /api/portal/quotes/via-token/decline
         (alias) /api/portal/estimates/via-token/decline [deprecated]
    POST /api/portal/quotes/via-token/request-changes
         (alias) /api/portal/estimates/via-token/request-changes [deprecated]
    GET  /api/quotes/{qid}/pdf              — ReportLab
         (alias) /api/estimates/{qid}/pdf [deprecated]

RBAC & pricing invariants (locked):
    * Technician role   → 403 on everything
    * Customer role     → own estimate only, admin-only columns/rows stripped
    * Magic-link viewer → treated as ``customer`` projection
    * Admin/super_admin → full detail with margin + BH fields

Customer projection strips these fields from line_items:
    calc, m_rate, bh, t_bh, t_b_cost, margin_pct
and from totals:
    estimated_profit, total_b_hrs, total_b_hrs_revenue
Server-side projection is the security boundary; the frontend is a hint.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from config import db, logger, JWT_SECRET, JWT_ALGO, APP_PUBLIC_URL
from utils import get_current_user, now_iso, new_id
from routers.tenants import get_current_tenant
from routers.invoice_viewer import _resolve_logo_path
from routers.invoice_viewer import (
    _fmt_addr, _load_company, _load_customer,
)
# Feb-2026 · Interactive Flipbook Estimate Viewer — reuse the HMAC
# signed-download helper already used by the SMS attachment surface
# so anonymous customer <img> tags can load flipbook backgrounds
# without an Authorization header.
from routers.marketing_media import _signed_download_url

router = APIRouter()

TOKEN_SUB = "est"
MAGIC_LINK_TTL_DAYS = 30

_CUSTOMER_LINE_HIDDEN = ("calc", "m_rate", "bh", "t_bh", "t_b_cost",
                          "margin_pct", "cost_rate", "unit_price", "cost",
                          # Pricebook × Profit-Reporting Phase 1 (Feb-2026) —
                          # PB1 write-once cost snapshots + admin-only flags
                          # MUST NEVER surface on customer-facing payloads.
                          # Enforced-at-boundary; the item modal only ever
                          # sets these for admin surfaces (see items.py).
                          "wholesale_price_snapshot",
                          "labor_cost_snapshot",
                          "retail_price_snapshot",
                          "overridden_price",
                          "pricebook_writeback",
                          "wholesale_price",
                          "labor_cost",
                          "labor_cost_default",
                          # Feb-2026 · Pricebook × Profit-Reporting Phase 2 —
                          # per-line admin cost/category overrides. Same
                          # posture as Phase 1 cost snapshots: NEVER leak to
                          # customer-facing payloads (magic-link viewer,
                          # portal, PDF, email). Effective values are
                          # computed admin-side; the customer only ever
                          # sees ``unit_price × quantity``.
                          "wholesale_cost_override",
                          "labor_cost_override",
                          "income_category_id_override",
                          "service_category_id_override")
_CUSTOMER_TOTAL_HIDDEN = ("estimated_profit", "total_b_hrs",
                          "total_b_hrs_revenue")


def _is_admin(user: Optional[dict]) -> bool:
    return bool(user) and user.get("role") in ("admin", "super_admin")


def _project_line_items_for_customer(items: List[dict]) -> List[dict]:
    out = []
    for li in items:
        row = {k: v for k, v in li.items() if k not in _CUSTOMER_LINE_HIDDEN}
        # Ensure a display-safe subset — Description, Qty/Hr, Visits, line total.
        out.append(row)
    return out


def _project_totals_for_customer(totals: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in totals.items() if k not in _CUSTOMER_TOTAL_HIDDEN}


async def _load_estimate(qid: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    return await db.quotes.find_one(
        {"id": qid, "tenant_id": tenant_id,
         "doc_type": {"$in": ["quote", "estimate"]}},
        {"_id": 0},
    )


def _compute_totals(est: dict) -> Dict[str, Any]:
    subtotal = float(est.get("subtotal") or 0)
    tax = float(est.get("tax") or 0)
    total = float(est.get("total") or 0)
    amount_paid = float(est.get("amount_paid") or 0)
    # Admin-only aggregates. Fall back to zeros if the extended fields
    # aren't populated on the doc (older estimates).
    est_profit = float(est.get("estimated_profit") or 0)
    total_bhrs = float(est.get("total_b_hrs") or 0)
    total_bhrs_rev = float(est.get("total_b_hrs_revenue") or 0)
    # Feb-2026 · Phase A · Customer per-line decline — surface the
    # original/adjusted totals block that the customer viewer uses
    # for the strike-through summary. Numbers come from the shared
    # helper so the frontend never disagrees with the server.
    from services.quotes.totals import recompute_customer_adjusted_totals
    adj = recompute_customer_adjusted_totals(est)
    return {
        "subtotal": round(subtotal, 2),
        "taxes": round(tax, 2),
        "amount_paid": round(amount_paid, 2),
        "total_estimated_cost": round(total, 2),
        "estimated_profit": round(est_profit, 2),
        "total_b_hrs": round(total_bhrs, 2),
        "total_b_hrs_revenue": round(total_bhrs_rev, 2),
        # Adjusted-total block (Phase A) — always present so the
        # frontend renders the strike-through only when
        # ``has_declined_lines`` is true.
        "original_subtotal": adj["original_subtotal"],
        "original_discount_value": adj["original_discount_value"],
        "original_tax": adj["original_tax"],
        "original_total": adj["original_total"],
        "adjusted_subtotal": adj["adjusted_subtotal"],
        "adjusted_discount_value": adj["adjusted_discount_value"],
        "adjusted_tax": adj["adjusted_tax"],
        "adjusted_total": adj["adjusted_total"],
        "has_declined_lines": adj["has_declined_lines"],
        "declined_line_count": adj["declined_line_count"],
    }


async def _build_payload(est: dict, tenant: dict, *,
                          as_customer: bool,
                          magic_token: Optional[str] = None,
                          url_base: Optional[str] = None,
                          ) -> Dict[str, Any]:
    company = await _load_company(tenant["id"])
    bill_to = await _load_customer(est.get("customer_id"), tenant["id"])
    property_address = est.get("property_address")
    if est.get("property_id") and not property_address:
        p = await db.properties.find_one(
            {"id": est["property_id"], "tenant_id": tenant["id"]},
            {"_id": 0, "address": 1},
        )
        if p:
            property_address = _fmt_addr(p.get("address"))
    if not property_address:
        property_address = bill_to.get("address")

    line_items = est.get("line_items") or []
    totals = _compute_totals(est)
    if as_customer:
        line_items = _project_line_items_for_customer(line_items)
        totals = _project_totals_for_customer(totals)

    # Phase K79 · Feb-2026 — Grouped customer-facing view. Populated on
    # every payload so admin previews can render it too; the surface
    # picks itemized vs grouped based on ``customer_group_display``.
    # long_description is stripped by the helper (contract-tested in
    # test_k79_group_lines_helper.py).
    from services.quotes.customer_view import build_customer_view_payload
    svc_cats: List[Dict[str, Any]] = await db.service_categories.find(
        {"tenant_id": tenant["id"], "is_archived": False},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    customer_view = build_customer_view_payload(est, svc_cats)

    # Feb-2026 · Phase C — expose the tenant-scoped signature gate +
    # the doc's current signature_status so both the auth'd + magic-
    # link customer surfaces can render the disabled-Approve hint
    # without a second fetch. Admin surfaces read the same block for
    # audit/UX consistency.
    require_signature_before_approve = bool(
        tenant.get("require_signature_before_approve", False),
    )
    signature_status = str(est.get("signature_status") or "").lower() or None

    # Feb-2026 · Public Quote Attachments — surface tenant-scoped
    # ``invoice_attachment``-purposed files that are linked to this
    # quote to the customer viewer. Only populated when a
    # ``magic_token`` is supplied so the download URL is signed +
    # scoped to THIS quote via the same JWT the viewer already
    # trusts. The auth'd admin surface keeps using the pre-existing
    # ``/api/files/*`` router directly (unchanged).
    attachments: List[Dict[str, Any]] = []
    if magic_token:
        # ``linked_entity_type=="invoice"`` is the unified label the
        # existing ``InvoiceAttachments`` component uses for BOTH
        # invoices AND quotes/estimates (see
        # frontend/src/components/quotes/InvoiceAttachments.jsx line
        # 8). Purpose stays "invoice_attachment". Not-deleted is
        # ``is_deleted != True`` (matches missing OR false) to align
        # with routers/files.py conventions.
        _base = (url_base or APP_PUBLIC_URL or "").rstrip("/")
        _rows = await db.files.find(
            {
                "tenant_id": tenant["id"],
                "linked_entity_type": "invoice",
                "linked_entity_id": est.get("id"),
                "purpose": "invoice_attachment",
                "is_deleted": {"$ne": True},
            },
            {
                "_id": 0, "id": 1, "original_filename": 1,
                "content_type": 1, "size": 1, "created_at": 1,
            },
        ).sort("created_at", -1).to_list(500)
        for r in _rows:
            _fid = r.get("id")
            if not _fid:
                continue
            _rel = (
                f"/api/portal/quotes/via-token/files/{_fid}"
                f"?token={magic_token}"
            )
            attachments.append({
                "id": _fid,
                "filename": r.get("original_filename") or _fid,
                "content_type": (
                    r.get("content_type") or "application/octet-stream"
                ),
                "size": int(r.get("size") or 0),
                "url": f"{_base}{_rel}" if _base else _rel,
            })

    return {
        "estimate_id": est.get("id"),
        "status": est.get("status") or "draft",
        "decision": est.get("decision") or None,
        "accepted_at": est.get("accepted_at"),
        "declined_at": est.get("declined_at"),
        "decline_reason": est.get("decline_reason"),
        "sent_at": est.get("sent_at"),
        "sent_via": est.get("sent_via"),  # e.g., "email" | "sms"
        "expires_at": est.get("expires_at"),
        "company": company,
        "bill_to": bill_to,
        "property_address": property_address,
        "header": {
            "customer_number": bill_to.get("customer_number"),
            "estimate_number": (
                est.get("estimate_number") or est.get("number")
                or (est.get("id") or "")[:8].upper()
            ),
            "estimate_date": (est.get("issued_at") or est.get("created_at") or "")[:10],
            "expiration_date": (est.get("expires_at") or "")[:10] if est.get("expires_at") else None,
        },
        "title": est.get("title") or "",
        "line_items": line_items,
        "totals": totals,
        "notes": (est.get("notes") or "").strip() or None,
        # Feb-2026 · Task 6 — Terms & Conditions surfacing for the
        # customer viewer. Doc-level ``terms`` is normalised (empty
        # string collapses to None) and exposed on both auth'd + magic-
        # link payloads so <DocTermsSection> renders on every estimate
        # / quote surface. Invoices EXCLUDE this field per product lock.
        "terms_and_conditions": (est.get("terms") or "").strip() or None,
        "as_customer": as_customer,
        # K79 grouped preview — always included so the admin toolbar's
        # "Preview customer view" can render without a second call.
        "customer_view": customer_view,
        # BUG FIX · Feb-2026 — top-level ``customer_group_display`` must
        # match what ``EstimateView.jsx:373`` reads. Pre-fix, this field
        # was ONLY nested under ``customer_view.customer_group_display``,
        # so the frontend read ``data.customer_group_display`` as
        # ``undefined`` and fell through its "undefined → grouped"
        # legacy fallback, which meant the customer page always
        # rendered grouped on ``/e/e/{token}`` regardless of the admin's
        # toggle. Emits the raw stored value verbatim: ``bool`` when
        # the admin flipped the toggle, ``None`` for legacy pre-K79
        # quotes (frontend treats null/undefined → grouped so legacy
        # behaviour is preserved).
        "customer_group_display": est.get("customer_group_display"),
        # Phase C · Feb-2026 — signature gate surface fields.
        "signature_status": signature_status,
        "require_signature_before_approve": require_signature_before_approve,
        # Feb-2026 · Public Quote Attachments — token-scoped download
        # URLs for the customer viewer. Empty list on auth'd admin
        # payloads (where ``magic_token`` isn't threaded in).
        "attachments": attachments,
        # Feb-2026 · Interactive Flipbook Estimate Viewer — surface
        # the two per-estimate opt-in fields to BOTH admin previews
        # and the magic-link customer viewer. ``EstimateView.jsx``
        # branches on ``flipbook_enabled`` to swap the render mode.
        # ``flipbook_background_ids`` is exposed as-is for admin /
        # UI use; ``flipbook_background_urls`` carries the pre-signed
        # HMAC download URL (``?tid=&sig=``) for each ID so the
        # anonymous customer ``<img>`` tags can load the assets
        # without an ``Authorization`` header (same trust model as
        # the SMS attachment surface — see
        # ``routers/marketing_media._signed_download_url``).
        "flipbook_enabled": bool(est.get("flipbook_enabled") or False),
        "flipbook_background_ids": list(est.get("flipbook_background_ids") or []),
        "flipbook_background_urls": [
            _signed_download_url(tenant["id"], str(_mid))
            for _mid in (est.get("flipbook_background_ids") or [])
            if _mid
        ],
    }


# ══════════════════════════════════════════════════════════════════
# GET /quotes/{qid}/full   (canonical)
# GET /estimates/{qid}/full  (deprecated alias)
# ══════════════════════════════════════════════════════════════════
@router.get("/quotes/{qid}/full")
@router.get("/estimates/{qid}/full", deprecated=True)
async def get_estimate_full(qid: str,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    est = await _load_estimate(qid, tenant["id"])
    if not est:
        raise HTTPException(404, "Estimate not found")
    if role == "customer":
        if est.get("customer_id") != user.get("customer_id"):
            raise HTTPException(404, "Estimate not found")
    return await _build_payload(est, tenant, as_customer=(role == "customer"))


# ══════════════════════════════════════════════════════════════════
# Accept / decline / request changes (authenticated)
# ══════════════════════════════════════════════════════════════════
class DeclineIn(BaseModel):
    reason: Optional[str] = None


class RequestChangesIn(BaseModel):
    message: str


async def _authorised_estimate(qid: str, user: dict,
                                tenant: dict) -> Dict[str, Any]:
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    est = await _load_estimate(qid, tenant["id"])
    if not est:
        raise HTTPException(404, "Estimate not found")
    if role == "customer" and est.get("customer_id") != user.get("customer_id"):
        raise HTTPException(404, "Estimate not found")
    return est


# Feb-2026 · Phase C — signature-before-approve gate.
# Raises 400 with ``error_code=signature_required`` when the tenant
# has ``require_signature_before_approve=true`` AND the estimate is
# not yet signed. Idempotent for already-accepted docs (callers
# short-circuit before hitting this check).
async def _phase_c_assert_signature_gate(
    est: dict, tenant_id: str,
) -> None:
    tenant = await db.tenants.find_one(
        {"id": tenant_id},
        {"_id": 0, "require_signature_before_approve": 1},
    ) or {}
    if not bool(tenant.get("require_signature_before_approve", False)):
        return
    if str(est.get("signature_status") or "").lower() == "signed":
        return
    raise HTTPException(
        status_code=400,
        detail={
            "error_code": "signature_required",
            "message": (
                "This estimate requires a customer signature "
                "before it can be approved."
            ),
        },
    )


async def _notify_admins(tenant_id: str, kind: str,
                           title: str, body: str, href: str) -> None:
    try:
        rows = await db.users.find(
            {"tenant_id": tenant_id, "role": {"$in": ["admin", "super_admin"]}},
            {"_id": 0, "id": 1},
        ).to_list(50)
        from services.notifications import emit as _emit
        await _emit([r["id"] for r in rows], kind=kind, title=title, body=body,
                    href=href, tenant_id=tenant_id)
    except Exception as exc:  # pragma: no cover
        logger.warning("[slice-r] admin bell emit failed: %s", exc)


# Feb-2026 · Phase B — wire the email + SMS fanout for top-level
# approve / decline. Kept as a thin wrapper so the 4 endpoints below
# stay short and readable. Loads the fresh tenant doc so the toggle
# (``notify_admin_on_decline``) reflects the latest admin state, and
# the fresh estimate doc so the templates carry the final total /
# decline_reason.
async def _notify_admins_email_sms(*, tenant_id: str, doc_id: str,
                                     event: str,
                                     actor_id: Optional[str]) -> None:
    try:
        tenant = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
        doc = await db.quotes.find_one({"id": doc_id, "tenant_id": tenant_id},
                                         {"_id": 0}) or {}
        origin = _public_frontend_origin()
        from services.quote_notifications import notify_quote_decision
        await notify_quote_decision(
            tenant=tenant, doc=doc, event=event,
            actor_id=actor_id, frontend_origin=origin,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[phase-b] email/sms fanout failed: %s", exc)


def _public_frontend_origin() -> str:
    """Absolute base URL for admin deep-links. Kept env-driven so
    email/SMS bodies never leak preview-only hostnames when the app
    is running in prod."""
    import os
    return (
        os.environ.get("PUBLIC_FRONTEND_ORIGIN")
        or os.environ.get("REACT_APP_BACKEND_URL")
        or ""
    ).rstrip("/")


async def _mark_accepted(est: dict, tenant_id: str, actor_id: str) -> None:
    upd = {
        "status": "accepted",
        "decision": "accepted",
        "accepted_at": now_iso(),
        "accepted_by": actor_id,
    }
    await db.quotes.update_one(
        {"id": est["id"], "tenant_id": tenant_id}, {"$set": upd},
    )
    # Slice O.2 companion · fire the ``estimate_accepted`` drip event
    # into any active matching sequence. Best-effort — never breaks the
    # accept response.
    try:
        from services.marketing.drip_events import on_event as _drip_on_event
        await _drip_on_event(
            trigger_type="estimate_accepted",
            tenant_id=tenant_id,
            customer_id=est.get("customer_id"),
            meta={"estimate_id": est.get("id"),
                   "actor_id": actor_id},
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[slice-r] estimate_accepted drip fanout failed: %s", exc)
    # Feb 2026 · Phase 1 Custom Trigger Builder — emit ``estimate_signed``.
    # Correlation key = estimate id so replays dedupe.
    try:
        from services.marketing.event_dispatcher import emit_event
        await emit_event(
            event="estimate_signed",
            tenant_id=tenant_id,
            entity_id=est.get("id"),
            customer_id=est.get("customer_id"),
            payload_extras={"estimate": est, "actor_id": actor_id,
                              "correlation_id": est.get("id")},
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[phase1] estimate_signed emit failed: %s", exc)


async def _mark_declined(est: dict, tenant_id: str,
                          actor_id: str, reason: Optional[str]) -> None:
    upd = {
        "status": "declined",
        "decision": "declined",
        "declined_at": now_iso(),
        "declined_by": actor_id,
        "decline_reason": (reason or "").strip() or None,
    }
    await db.quotes.update_one(
        {"id": est["id"], "tenant_id": tenant_id}, {"$set": upd},
    )


async def _mark_changes_requested(est: dict, tenant_id: str,
                                    actor_id: str, message: str) -> None:
    upd = {
        "status": "changes_requested",
        "decision": "changes_requested",
        "changes_requested_at": now_iso(),
        "changes_requested_by": actor_id,
        "changes_requested_message": message.strip(),
    }
    await db.quotes.update_one(
        {"id": est["id"], "tenant_id": tenant_id}, {"$set": upd},
    )


@router.post("/quotes/{qid}/accept")
@router.post("/estimates/{qid}/accept", deprecated=True)
async def accept_estimate(qid: str,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    est = await _authorised_estimate(qid, user, tenant)
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    # Feb-2026 · Phase C — signature-before-approve gate (tenant opt-in).
    await _phase_c_assert_signature_gate(est, tenant["id"])
    await _mark_accepted(est, tenant["id"], user.get("id"))
    await _notify_admins(
        tenant["id"], kind="quote_accepted",
        title=f"Estimate accepted by {est.get('customer_name') or 'customer'}",
        body=f"Estimate #{(est.get('id') or '')[:8]} was accepted.",
        href=f"/estimates/{qid}",
    )
    # Feb-2026 · Phase B — email + SMS fanout in addition to bell.
    await _notify_admins_email_sms(
        tenant_id=tenant["id"], doc_id=qid,
        event="quote_accepted", actor_id=user.get("id"),
    )
    return await _build_payload(
        await _load_estimate(qid, tenant["id"]), tenant,
        as_customer=(user.get("role") == "customer"),
    )


@router.post("/quotes/{qid}/decline")
@router.post("/estimates/{qid}/decline", deprecated=True)
async def decline_estimate(qid: str, body: DeclineIn,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    est = await _authorised_estimate(qid, user, tenant)
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_declined(est, tenant["id"], user.get("id"), body.reason)
    await _notify_admins(
        tenant["id"], kind="quote_declined",
        title=f"Estimate declined by {est.get('customer_name') or 'customer'}",
        body=(body.reason or "No reason given")[:200],
        href=f"/estimates/{qid}",
    )
    # Feb-2026 · Phase B — email + SMS fanout (gated on tenant toggle).
    await _notify_admins_email_sms(
        tenant_id=tenant["id"], doc_id=qid,
        event="quote_declined", actor_id=user.get("id"),
    )
    return await _build_payload(
        await _load_estimate(qid, tenant["id"]), tenant,
        as_customer=(user.get("role") == "customer"),
    )


@router.post("/quotes/{qid}/request-changes")
@router.post("/estimates/{qid}/request-changes", deprecated=True)
async def request_changes(qid: str, body: RequestChangesIn,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    est = await _authorised_estimate(qid, user, tenant)
    if not (body.message or "").strip():
        raise HTTPException(422, "message is required")
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_changes_requested(est, tenant["id"], user.get("id"), body.message)
    await _notify_admins(
        tenant["id"], kind="quote_change_requested",
        title=f"Estimate change request from {est.get('customer_name') or 'customer'}",
        body=body.message[:200],
        href=f"/estimates/{qid}",
    )
    return await _build_payload(
        await _load_estimate(qid, tenant["id"]), tenant,
        as_customer=(user.get("role") == "customer"),
    )


# ══════════════════════════════════════════════════════════════════
# Magic-link tokens (public path)
# ══════════════════════════════════════════════════════════════════
def _sign_estimate_token(
    qid: str, cid: str, tenant_id: str,
    *,
    recipient_kind: Optional[str] = None,
    recipient_id: Optional[str] = None,
) -> str:
    """Phase 2 · Feb-2026 — hybrid payload (customer / lead / legacy)."""
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": TOKEN_SUB,
        "eid": qid,
        "tid": tenant_id,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(days=MAGIC_LINK_TTL_DAYS),
    }
    rk = (recipient_kind or "").strip().lower()
    if rk == "lead":
        payload["rid"] = recipient_id or ""
        payload["rtype"] = "lead"
    elif rk == "customer":
        payload["cid"] = recipient_id or cid or ""
        payload["rid"] = recipient_id or cid or ""
        payload["rtype"] = "customer"
    else:
        payload["cid"] = cid or ""
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _verify_estimate_token(tok: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Estimate link expired")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid estimate link")
    if payload.get("sub") != TOKEN_SUB:
        raise HTTPException(401, "Invalid estimate link")
    return payload


@router.get("/quotes/{qid}/magic-link")
@router.get("/estimates/{qid}/magic-link", deprecated=True)
async def issue_magic_link(qid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    est = await _load_estimate(qid, tenant["id"])
    if not est:
        raise HTTPException(404, "Estimate not found")
    cid = est.get("customer_id") or ""
    tok = _sign_estimate_token(qid, cid, tenant["id"])
    return {"token": tok, "url": f"/e/estimate?token={tok}",
             "expires_in_days": MAGIC_LINK_TTL_DAYS}


async def _load_est_from_token(tok: str) -> Dict[str, Any]:
    """Phase 2 · Feb-2026 — hybrid verification."""
    payload = _verify_estimate_token(tok)
    est = await db.quotes.find_one(
        {"id": payload["eid"], "tenant_id": payload["tid"]}, {"_id": 0},
    )
    if not est:
        raise HTTPException(401, "Invalid estimate link")
    tok_rtype = payload.get("rtype")
    tok_rid = payload.get("rid")
    tok_cid = payload.get("cid")
    if tok_rtype or tok_rid:
        est_rtype = (est.get("recipient_type") or "").strip().lower()
        est_rid = est.get("recipient_id") or ""
        if not est_rtype and est.get("customer_id"):
            est_rtype = "customer"
            est_rid = est.get("customer_id") or ""
        if tok_rtype != est_rtype or tok_rid != est_rid:
            raise HTTPException(401, "Invalid estimate link")
    else:
        if est.get("customer_id") != tok_cid:
            raise HTTPException(401, "Invalid estimate link")
    tenant = await db.tenants.find_one({"id": payload["tid"]}, {"_id": 0})
    if not tenant:
        raise HTTPException(401, "Invalid estimate link")
    return {"est": est, "tenant": tenant, "cid": tok_cid or tok_rid or ""}


@router.get("/portal/quotes/via-token")
@router.get("/portal/estimates/via-token", deprecated=True)
async def view_estimate_via_token(
    request: Request,
    token: str = Query(...),
    src: Optional[str] = Query(
        None,
        description=(
            "QV-service · Feb-2026 — Optional send-channel "
            "attribution: 'email' | 'sms' | 'portal' | 'link'. "
            "Anything unknown normalises to 'link'. Backwards-"
            "compatible: omitted callers still see the payload; "
            "they just attribute as 'link'."
        ),
    ),
):
    ctx = await _load_est_from_token(token)
    payload = await _build_payload(
        ctx["est"], ctx["tenant"], as_customer=True,
        magic_token=token, url_base=_resolve_url_base(request),
    )
    # QV-service · Feb-2026 — fire-and-forget view stamp.
    # ``record_quote_view`` swallows Mongo failures internally so
    # the customer's page render is never blocked on it. The
    # ``doc_type`` filter inside the tracker guarantees this
    # tokenized route can never accidentally stamp an invoice
    # (tokens issued for invoices never resolve here anyway — the
    # collection is shared but ``doc_type`` on the doc gates the
    # denorm update).
    try:
        from services.quote_view_tracker import record_quote_view
        ua = request.headers.get("user-agent")
        ip = (request.client.host
                if request.client is not None else None)
        await record_quote_view(
            quote_id=ctx["est"]["id"],
            tenant_id=ctx["tenant"]["id"],
            source=src,
            user_agent=ua, ip=ip,
        )
    except Exception:  # pragma: no cover — defensive
        pass
    return payload


def _resolve_url_base(request: Request) -> str:
    """Resolve the absolute URL prefix used to render tokenised
    attachment download links inside the magic-link viewer payload.

    Prefers ``APP_PUBLIC_URL`` (production canonical host); falls back
    to ``<scheme>://<host>`` reconstructed from the incoming ``Request``
    so local + preview environments stay self-consistent even when the
    env var isn't set. Returns an empty string if neither is
    resolvable — the payload then emits a relative URL and the
    customer's browser fills in the origin.
    """
    if APP_PUBLIC_URL:
        return APP_PUBLIC_URL
    try:
        base = str(request.base_url).rstrip("/")
        return base
    except Exception:  # noqa: BLE001
        return ""


# ══════════════════════════════════════════════════════════════════
# GET /portal/quotes/via-token/files/{file_id}?token=…
#   — public token-scoped download for attachments linked to the
#     quote referenced by the magic-link JWT. Auth path forks the
#     SAME ``_verify_estimate_token`` helper the viewer uses so
#     tokens minted for one quote can never surface files for
#     another quote / tenant.
# ══════════════════════════════════════════════════════════════════
@router.get("/portal/quotes/via-token/files/{file_id}")
async def download_attachment_via_token(
    file_id: str,
    token: Optional[str] = None,
):
    from services.file_storage import (
        StorageError, get_object, is_storage_configured,
    )

    # Feb-2026 · Uniform 401 for missing/empty token — the route sits
    # alongside other portal auth surfaces, so a missing credential
    # must land as 401 (not FastAPI's default 422 for required
    # query params). ``_load_est_from_token`` handles invalid /
    # expired / wrong-``sub`` tokens with 401 downstream.
    if not token:
        raise HTTPException(status_code=401, detail="missing_token")

    # 401 — invalid/expired/missing token. ``_load_est_from_token``
    # already normalises the various JWT failures into a 401 and
    # confirms the token's ``eid``/``tid``/``cid`` triple matches an
    # existing quote.
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    tenant = ctx["tenant"]

    doc = await db.files.find_one({"id": file_id})
    # 404 — no such file record (or it's on a different tenant we
    # don't want to leak the existence of).
    if not doc:
        raise HTTPException(404, detail="not_found")
    # 410 — file was soft-deleted (existed but no longer available).
    if doc.get("is_deleted"):
        raise HTTPException(410, detail="deleted")
    # 403 — tenant / entity mismatch. Return 403 (not 404) so the
    # customer-facing UI can distinguish "wrong token for this file"
    # from "file gone entirely".
    if doc.get("tenant_id") != tenant["id"]:
        raise HTTPException(403, detail="forbidden")
    if (
        doc.get("linked_entity_type") != "invoice"
        or doc.get("linked_entity_id") != est.get("id")
        or doc.get("purpose") != "invoice_attachment"
    ):
        raise HTTPException(403, detail="forbidden")

    if not is_storage_configured():
        raise HTTPException(503, detail={
            "code": "STORAGE_UNAVAILABLE",
            "message": "File storage is not configured on this server.",
        })

    try:
        data, ct = get_object(doc["storage_path"])
    except StorageError as e:
        logger.warning("[VIA-TOKEN FILES] get_object failed: %s", e)
        raise HTTPException(502, detail={
            "code": "STORAGE_READ_FAILED",
            "message": str(e),
        })

    filename = doc.get("original_filename") or file_id
    # ``attachment`` disposition (spec) — the customer explicitly
    # clicked "Download", not embedded in an <img>/<iframe>. Filename
    # is escaped for RFC-6266 safety.
    _safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
    return Response(
        content=data,
        media_type=(
            doc.get("content_type") or ct or "application/octet-stream"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{_safe}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/portal/quotes/via-token/accept")
@router.post("/portal/estimates/via-token/accept", deprecated=True)
async def accept_via_token(token: str = Query(...)):
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    # Feb-2026 · Phase C — signature-before-approve gate.
    await _phase_c_assert_signature_gate(est, ctx["tenant"]["id"])
    await _mark_accepted(est, ctx["tenant"]["id"], f"token:{ctx['cid']}")
    await _notify_admins(
        ctx["tenant"]["id"], kind="quote_accepted",
        title="Estimate accepted via link",
        body=f"Estimate #{(est.get('id') or '')[:8]} accepted via magic link.",
        href=f"/estimates/{est['id']}",
    )
    # Feb-2026 · Phase B — email + SMS fanout for magic-link accepts.
    await _notify_admins_email_sms(
        tenant_id=ctx["tenant"]["id"], doc_id=est["id"],
        event="quote_accepted", actor_id=f"token:{ctx['cid']}",
    )
    return await _build_payload(
        await db.quotes.find_one({"id": est["id"]}, {"_id": 0}),
        ctx["tenant"], as_customer=True,
    )


@router.post("/portal/quotes/via-token/decline")
@router.post("/portal/estimates/via-token/decline", deprecated=True)
async def decline_via_token(body: DeclineIn, token: str = Query(...)):
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_declined(est, ctx["tenant"]["id"], f"token:{ctx['cid']}", body.reason)
    await _notify_admins(
        ctx["tenant"]["id"], kind="quote_declined",
        title="Estimate declined via link",
        body=(body.reason or "No reason given")[:200],
        href=f"/estimates/{est['id']}",
    )
    # Feb-2026 · Phase B — email + SMS fanout (gated on tenant toggle).
    await _notify_admins_email_sms(
        tenant_id=ctx["tenant"]["id"], doc_id=est["id"],
        event="quote_declined", actor_id=f"token:{ctx['cid']}",
    )
    return await _build_payload(
        await db.quotes.find_one({"id": est["id"]}, {"_id": 0}),
        ctx["tenant"], as_customer=True,
    )


@router.post("/portal/quotes/via-token/request-changes")
@router.post("/portal/estimates/via-token/request-changes", deprecated=True)
async def changes_via_token(body: RequestChangesIn, token: str = Query(...)):
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    if not (body.message or "").strip():
        raise HTTPException(422, "message is required")
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_changes_requested(
        est, ctx["tenant"]["id"], f"token:{ctx['cid']}", body.message,
    )
    await _notify_admins(
        ctx["tenant"]["id"], kind="quote_change_requested",
        title="Estimate change request via link",
        body=body.message[:200],
        href=f"/estimates/{est['id']}",
    )
    return await _build_payload(
        await db.quotes.find_one({"id": est["id"]}, {"_id": 0}),
        ctx["tenant"], as_customer=True,
    )


# ══════════════════════════════════════════════════════════════════
# Feb-2026 · Phase A · Customer per-line-item decline + top-level
# approve/decline (path-based token endpoints)
#
# The pre-existing accept/decline endpoints (query-string token) at
# ``/portal/quotes/via-token/{accept,decline,request-changes}`` stay
# in place for back-compat. The four endpoints below are the Phase A
# API surface used by the customer portal for the new decline UX:
#
#   POST /api/portal/quotes/via-token/{token}/line-items/{index}/decline
#   POST /api/portal/quotes/via-token/{token}/line-items/{index}/undecline
#   POST /api/portal/quotes/via-token/{token}/approve
#   POST /api/portal/quotes/via-token/{token}/decline
#
# Rules:
#   1. Idempotent: repeating the same action on an already-in-state doc
#      returns 200 with the current state, never 4xx. Line-item decline
#      of an already-declined row is a no-op; approve of an already-
#      accepted doc likewise.
#   2. Approve / top-level decline are only actionable when
#      ``status ∈ {'sent', 'viewed'}``. Otherwise 409 with a
#      machine-readable ``error_code``.
#   3. Line-item decline / undecline honor the same
#      ``status ∈ {'sent', 'viewed'}`` gate so an already-decided doc
#      can't be mutated by the customer.
#   4. Notifications are NOT wired in Phase A. Phase B will consume
#      the emitted ``quote_accepted`` / ``quote_declined`` events.
#   5. Totals recomputation runs on every mutation via
#      ``services.quotes.totals.recompute_customer_adjusted_totals``.
# ══════════════════════════════════════════════════════════════════
_PHASE_A_ACTIONABLE_STATUSES = {"sent", "viewed"}
_PHASE_A_TERMINAL_DECISIONS = {"accepted", "declined"}


class _PhaseALineDeclineIn(BaseModel):
    reason: Optional[str] = None


class _PhaseATopLevelDeclineIn(BaseModel):
    reason: Optional[str] = None


# In-memory rate limiter (Phase A minimum viable — replace with a
# Redis-backed limiter when we get one). Key = ``(token_hash, bucket)``,
# value = list of timestamps within the window. Two buckets:
#   * ``"line"`` → 30 requests / 5 min per token
#   * ``"decision"`` → 5 requests / 5 min per token
# The limiter is process-local — sufficient for single-worker preview;
# multi-worker prod will multiply the effective limit which is fine
# for Phase A.
import time as _time_mod
from hashlib import sha256 as _sha256

_PHASE_A_RATE_BUCKETS: Dict[str, List[float]] = {}
_PHASE_A_RATE_LIMITS = {
    "line": (30, 300.0),
    "decision": (5, 300.0),
    # Feb-2026 · Decline-per-group ship — magic-link group decline /
    # restore. Slightly tighter than the per-line bucket because a
    # single group action can touch many lines. Admin routes are
    # JWT-gated and don't share this limiter.
    "group": (10, 300.0),
}


def _phase_a_rate_gate(token: str, bucket: str) -> None:
    """Raise 429 when the token has burned through its rate budget."""
    max_hits, window = _PHASE_A_RATE_LIMITS[bucket]
    key = f"{bucket}:{_sha256(token.encode()).hexdigest()[:16]}"
    now = _time_mod.monotonic()
    hits = [t for t in _PHASE_A_RATE_BUCKETS.get(key, []) if now - t < window]
    if len(hits) >= max_hits:
        raise HTTPException(
            status_code=429,
            detail={"error_code": "rate_limited",
                     "message": f"Too many requests. Wait a few seconds."},
        )
    hits.append(now)
    _PHASE_A_RATE_BUCKETS[key] = hits


async def _phase_a_recompute_and_persist(est: dict, tenant_id: str) -> None:
    """Recompute the ``original_*`` / ``adjusted_*`` totals block and
    persist it onto the quote row. Mutates ``est`` in place with the
    new fields so callers can pass it to ``_build_payload`` without
    a second Mongo read."""
    from services.quotes.totals import recompute_customer_adjusted_totals
    block = recompute_customer_adjusted_totals(est)
    est.update(block)
    await db.quotes.update_one(
        {"id": est["id"], "tenant_id": tenant_id},
        {"$set": block},
    )


def _phase_a_assert_actionable(est: dict) -> None:
    """Gate mutations to the ``sent`` / ``viewed`` window."""
    if est.get("decision") in _PHASE_A_TERMINAL_DECISIONS:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "already_finalized",
                     "message": "This estimate is already finalized."},
        )
    status = str(est.get("status") or "").lower()
    if status not in _PHASE_A_ACTIONABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "not_actionable",
                     "status": status,
                     "message": (
                         "Estimate can only be acted on while it's in "
                         "'sent' or 'viewed' state."
                     )},
        )


@router.post("/portal/quotes/via-token/{token}/line-items/{index}/decline")
async def phase_a_decline_line_item(
    token: str, index: int,
    body: Optional[_PhaseALineDeclineIn] = None,
):
    _phase_a_rate_gate(token, "line")
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    _phase_a_assert_actionable(est)
    line_items = list(est.get("line_items") or [])
    if index < 0 or index >= len(line_items):
        raise HTTPException(
            status_code=404,
            detail={"error_code": "line_index_out_of_range",
                     "index": index,
                     "count": len(line_items),
                     "message": "Line item does not exist."},
        )
    reason = (getattr(body, "reason", None) or "").strip()[:200] if body else ""
    row = line_items[index]
    # Idempotent — already declined stays declined; refresh reason if provided.
    row["customer_status"] = "declined"
    row["customer_declined_at"] = now_iso()
    if reason:
        row["customer_decline_reason"] = reason
    line_items[index] = row
    est["line_items"] = line_items
    await db.quotes.update_one(
        {"id": est["id"], "tenant_id": ctx["tenant"]["id"]},
        {"$set": {"line_items": line_items}},
    )
    await _phase_a_recompute_and_persist(est, ctx["tenant"]["id"])
    return await _build_payload(est, ctx["tenant"], as_customer=True)


@router.post("/portal/quotes/via-token/{token}/line-items/{index}/undecline")
async def phase_a_undecline_line_item(token: str, index: int):
    _phase_a_rate_gate(token, "line")
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    _phase_a_assert_actionable(est)
    line_items = list(est.get("line_items") or [])
    if index < 0 or index >= len(line_items):
        raise HTTPException(
            status_code=404,
            detail={"error_code": "line_index_out_of_range",
                     "index": index,
                     "count": len(line_items),
                     "message": "Line item does not exist."},
        )
    row = line_items[index]
    # Idempotent — already pending stays pending.
    row["customer_status"] = "pending"
    row["customer_declined_at"] = None
    row["customer_decline_reason"] = None
    line_items[index] = row
    est["line_items"] = line_items
    await db.quotes.update_one(
        {"id": est["id"], "tenant_id": ctx["tenant"]["id"]},
        {"$set": {"line_items": line_items}},
    )
    await _phase_a_recompute_and_persist(est, ctx["tenant"]["id"])
    return await _build_payload(est, ctx["tenant"], as_customer=True)


@router.post("/portal/quotes/via-token/{token}/approve")
async def phase_a_approve_via_token(token: str):
    _phase_a_rate_gate(token, "decision")
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    # Idempotent: if already accepted, return current state (200).
    if est.get("decision") == "accepted":
        return await _build_payload(est, ctx["tenant"], as_customer=True)
    _phase_a_assert_actionable(est)
    # Feb-2026 · Phase C — signature-before-approve gate.
    await _phase_c_assert_signature_gate(est, ctx["tenant"]["id"])
    await _mark_accepted(est, ctx["tenant"]["id"], f"token:{ctx['cid']}")
    # Refresh + recompute so the response reflects the accepted state
    # AND the adjusted-total block (in case the customer had declined
    # some lines before approving).
    est_fresh = await db.quotes.find_one(
        {"id": est["id"], "tenant_id": ctx["tenant"]["id"]}, {"_id": 0},
    )
    await _phase_a_recompute_and_persist(est_fresh, ctx["tenant"]["id"])
    # Feb-2026 · Phase B — bell fanout + email + SMS. Approve always
    # notifies (no gate).
    await _notify_admins(
        ctx["tenant"]["id"], kind="quote_accepted",
        title="Estimate approved via portal",
        body=f"Estimate #{(est.get('id') or '')[:8]} approved via portal.",
        href=f"/estimates/{est['id']}",
    )
    await _notify_admins_email_sms(
        tenant_id=ctx["tenant"]["id"], doc_id=est["id"],
        event="quote_accepted", actor_id=f"token:{ctx['cid']}",
    )
    return await _build_payload(est_fresh, ctx["tenant"], as_customer=True)


@router.post("/portal/quotes/via-token/{token}/decline")
async def phase_a_decline_via_token(
    token: str,
    body: Optional[_PhaseATopLevelDeclineIn] = None,
):
    _phase_a_rate_gate(token, "decision")
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    # Idempotent: if already declined, return current state (200).
    if est.get("decision") == "declined":
        return await _build_payload(est, ctx["tenant"], as_customer=True)
    _phase_a_assert_actionable(est)
    reason = (getattr(body, "reason", None) or "").strip()[:200] if body else ""
    await _mark_declined(est, ctx["tenant"]["id"], f"token:{ctx['cid']}", reason)
    est_fresh = await db.quotes.find_one(
        {"id": est["id"], "tenant_id": ctx["tenant"]["id"]}, {"_id": 0},
    )
    await _phase_a_recompute_and_persist(est_fresh, ctx["tenant"]["id"])
    # Feb-2026 · Phase B — bell fanout + email + SMS (gated on the
    # tenant's ``notify_admin_on_decline`` flag inside the helper).
    await _notify_admins(
        ctx["tenant"]["id"], kind="quote_declined",
        title="Estimate declined via portal",
        body=(reason or "No reason given")[:200],
        href=f"/estimates/{est['id']}",
    )
    await _notify_admins_email_sms(
        tenant_id=ctx["tenant"]["id"], doc_id=est["id"],
        event="quote_declined", actor_id=f"token:{ctx['cid']}",
    )
    return await _build_payload(est_fresh, ctx["tenant"], as_customer=True)


# ══════════════════════════════════════════════════════════════════
# Feb-2026 · Customer decline-per-group on Quotes
#
# Ships four PATCH routes that let the customer (magic-link) or an
# admin (JWT) toggle the ``customer_status`` on every line item that
# belongs to a specific service-category group in one call:
#
#   PATCH /api/portal/quotes/via-token/{token}/groups/{group_key}/decline
#   PATCH /api/portal/quotes/via-token/{token}/groups/{group_key}/undecline
#   PATCH /api/quotes/{qid}/groups/{group_key}/decline
#   PATCH /api/quotes/{qid}/groups/{group_key}/undecline
#
# The group is ephemeral (see ``services/quotes/customer_view.py``);
# ``group_key`` == ``service_category_id`` for real categories, or the
# ``"__other__"`` sentinel for lines without a category. The mutation
# lives on the underlying line items — no new schema on the group.
#
# See /app/memory/FEATURE_QUOTE_DECLINE_PER_GROUP.md.
# ══════════════════════════════════════════════════════════════════
_GROUP_OTHER_KEY = "__other__"


class _GroupDeclineIn(BaseModel):
    reason: Optional[str] = None


def _resolve_group_line_indices(line_items: List[dict],
                                  group_key: str) -> List[int]:
    """Return the indices of ``line_items`` whose service-category id
    matches ``group_key``. The ``__other__`` sentinel captures rows
    with a missing/blank ``service_category_id``.
    """
    out: List[int] = []
    for i, li in enumerate(line_items):
        raw = li.get("service_category_id")
        cat = raw if isinstance(raw, str) and raw.strip() else _GROUP_OTHER_KEY
        if cat == group_key:
            out.append(i)
    return out


async def _write_group_decline_audit(*, event: str, tenant_id: str,
                                        quote_id: str, group_key: str,
                                        actor_id: str, source: str,
                                        line_count: int,
                                        reason: Optional[str]) -> None:
    """Best-effort audit row. Never breaks the mutation on failure."""
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "event": event,
            "tenant_id": tenant_id,
            "quote_id": quote_id,
            "group_key": group_key,
            "actor_id": actor_id,
            "source": source,
            "at": now_iso(),
            "line_count": line_count,
            "reason": reason,
        })
    except Exception as exc:  # pragma: no cover
        logger.warning("group_decline_audit_write_failed: %s", exc)


async def _apply_group_decline(*, est: dict, tenant_id: str,
                                 group_key: str, actor_id: str,
                                 decline: bool,
                                 reason: Optional[str]) -> int:
    """Flip ``customer_status`` on every line in ``group_key``.

    Returns the affected line count. Raises 404 when no line in the
    quote belongs to ``group_key`` — protects against typos and stale
    frontend keys after a category was renamed / removed.
    """
    line_items = list(est.get("line_items") or [])
    indices = _resolve_group_line_indices(line_items, group_key)
    if not indices:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "group_not_found",
                     "group_key": group_key,
                     "message": "No line items belong to this group."},
        )
    stamped_at = now_iso()
    clean_reason = (reason or "").strip()[:200] if decline else None
    for i in indices:
        row = line_items[i]
        if decline:
            row["customer_status"] = "declined"
            row["customer_declined_at"] = stamped_at
            row["customer_declined_by"] = actor_id
            if clean_reason:
                row["customer_decline_reason"] = clean_reason
        else:
            row["customer_status"] = "pending"
            row["customer_declined_at"] = None
            row["customer_declined_by"] = None
            row["customer_decline_reason"] = None
        line_items[i] = row
    est["line_items"] = line_items
    await db.quotes.update_one(
        {"id": est["id"], "tenant_id": tenant_id},
        {"$set": {"line_items": line_items}},
    )
    await _phase_a_recompute_and_persist(est, tenant_id)
    return len(indices)


@router.patch("/portal/quotes/via-token/{token}/groups/{group_key}/decline")
async def customer_group_decline_via_token(
    token: str, group_key: str,
    body: Optional[_GroupDeclineIn] = None,
):
    _phase_a_rate_gate(token, "group")
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    _phase_a_assert_actionable(est)
    actor_id = f"token:{ctx['cid']}"
    reason = getattr(body, "reason", None) if body else None
    count = await _apply_group_decline(
        est=est, tenant_id=ctx["tenant"]["id"], group_key=group_key,
        actor_id=actor_id, decline=True, reason=reason,
    )
    await _write_group_decline_audit(
        event="quote.group_declined", tenant_id=ctx["tenant"]["id"],
        quote_id=est["id"], group_key=group_key,
        actor_id=actor_id, source="portal_token",
        line_count=count,
        reason=(reason or "").strip()[:200] if reason else None,
    )
    return await _build_payload(est, ctx["tenant"], as_customer=True)


@router.patch("/portal/quotes/via-token/{token}/groups/{group_key}/undecline")
async def customer_group_undecline_via_token(token: str, group_key: str):
    _phase_a_rate_gate(token, "group")
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    _phase_a_assert_actionable(est)
    actor_id = f"token:{ctx['cid']}"
    count = await _apply_group_decline(
        est=est, tenant_id=ctx["tenant"]["id"], group_key=group_key,
        actor_id=actor_id, decline=False, reason=None,
    )
    await _write_group_decline_audit(
        event="quote.group_restored", tenant_id=ctx["tenant"]["id"],
        quote_id=est["id"], group_key=group_key,
        actor_id=actor_id, source="portal_token",
        line_count=count, reason=None,
    )
    return await _build_payload(est, ctx["tenant"], as_customer=True)


@router.patch("/quotes/{qid}/groups/{group_key}/decline")
async def admin_group_decline(
    qid: str, group_key: str,
    body: Optional[_GroupDeclineIn] = None,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    est = await _load_estimate(qid, tenant["id"])
    if not est:
        raise HTTPException(404, "Quote not found")
    _phase_a_assert_actionable(est)
    actor_id = user.get("id") or ""
    reason = getattr(body, "reason", None) if body else None
    count = await _apply_group_decline(
        est=est, tenant_id=tenant["id"], group_key=group_key,
        actor_id=actor_id, decline=True, reason=reason,
    )
    await _write_group_decline_audit(
        event="quote.group_declined", tenant_id=tenant["id"],
        quote_id=est["id"], group_key=group_key,
        actor_id=actor_id, source="admin_ui",
        line_count=count,
        reason=(reason or "").strip()[:200] if reason else None,
    )
    return await _build_payload(est, tenant, as_customer=False)


@router.patch("/quotes/{qid}/groups/{group_key}/undecline")
async def admin_group_undecline(
    qid: str, group_key: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    est = await _load_estimate(qid, tenant["id"])
    if not est:
        raise HTTPException(404, "Quote not found")
    _phase_a_assert_actionable(est)
    actor_id = user.get("id") or ""
    count = await _apply_group_decline(
        est=est, tenant_id=tenant["id"], group_key=group_key,
        actor_id=actor_id, decline=False, reason=None,
    )
    await _write_group_decline_audit(
        event="quote.group_restored", tenant_id=tenant["id"],
        quote_id=est["id"], group_key=group_key,
        actor_id=actor_id, source="admin_ui",
        line_count=count, reason=None,
    )
    return await _build_payload(est, tenant, as_customer=False)






# ══════════════════════════════════════════════════════════════════
# Phase K79 · Feb-2026 — Grouped customer-facing view endpoint.
# Single aggregation helper (services.quotes.customer_view) powers:
#   * this authenticated admin/customer preview endpoint
#   * the magic-link public variant below
#   * the embedded ``customer_view`` block inside ``_build_payload``
#   * the customer-facing PDF fork in ``estimate_pdf``
# ══════════════════════════════════════════════════════════════════
@router.get("/quotes/{qid}/customer-view")
async def quote_customer_view(qid: str,
                                user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    """Return the grouped customer-facing payload for a quote (auth).

    When ``customer_group_display`` is False the payload still returns
    (with ``groups=[…]``) so the caller can decide to render itemized
    vs grouped. Truth of "which mode to render" is
    ``payload.customer_group_display``.
    """
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    est = await _load_estimate(qid, tenant["id"])
    if not est:
        raise HTTPException(404, "Quote not found")
    if role == "customer" and est.get("customer_id") != user.get("customer_id"):
        raise HTTPException(404, "Quote not found")
    return await _build_customer_view_only(est, tenant)


@router.get("/portal/quotes/via-token/customer-view")
async def quote_customer_view_via_token(token: str = Query(...)):
    """Return the grouped customer-facing payload via magic-link.

    Same signing/verification path as
    ``GET /api/portal/quotes/via-token``.
    """
    ctx = await _load_est_from_token(token)
    return await _build_customer_view_only(ctx["est"], ctx["tenant"])


async def _build_customer_view_only(est: dict, tenant: dict) -> Dict[str, Any]:
    """Return ONLY the grouped customer-view payload (no admin fields).

    Deliberately narrow surface — safe to expose via magic-link.
    Uses :func:`services.quotes.customer_view.build_customer_view_payload`
    which enforces the ``long_description``-scrubbed contract.
    """
    from services.quotes.customer_view import build_customer_view_payload
    svc_cats = await db.service_categories.find(
        {"tenant_id": tenant["id"], "is_archived": False},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    cv = build_customer_view_payload(est, svc_cats)
    cv["quote_id"] = est.get("id")
    cv["title"] = est.get("title") or ""
    return cv


# ══════════════════════════════════════════════════════════════════
# PDF
# ══════════════════════════════════════════════════════════════════
# Feb-2026 · Cleanup Dispatch A · Item 2 — the ``/quotes/{qid}/pdf``
# decorator was previously registered here as well. Route-order made
# it dead code (``routers/quotes.py::quote_or_invoice_pdf`` wins
# because ``quotes`` is included in server.py before ``estimate_viewer``).
# The remaining ``/estimates/{qid}/pdf`` decorator below is the
# deprecated legacy alias — still reachable and intentional.
# See /app/memory/CLEANUP_DISPATCH_A.md.
@router.get("/estimates/{qid}/pdf", deprecated=True)
async def estimate_pdf(qid: str,
                        internal: bool = False,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    """Render an estimate PDF.

    Phase K79 · Feb-2026 — When the quote has ``customer_group_display``
    on AND the caller is a customer (or an admin who omitted
    ``?internal=1``), the PDF renders the grouped view. Admins can
    always fetch the fully-itemized "Internal PDF" with ``?internal=1``.
    """
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    est = await _load_estimate(qid, tenant["id"])
    if not est:
        raise HTTPException(404, "Estimate not found")
    if role == "customer" and est.get("customer_id") != user.get("customer_id"):
        raise HTTPException(404, "Estimate not found")
    is_customer_view = (role == "customer") or (not internal)
    payload = await _build_payload(est, tenant, as_customer=is_customer_view)

    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rlcolors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
        Image,
    )
    styles = getSampleStyleSheet()
    big = ParagraphStyle("big", parent=styles["Title"], alignment=1, fontSize=28)
    label_r = ParagraphStyle("labelr", parent=styles["Normal"], alignment=2,
                              fontSize=9, textColor=rlcolors.grey)
    value_r = ParagraphStyle("valuer", parent=styles["Normal"], alignment=2,
                              fontSize=10, fontName="Helvetica-Bold")
    buf = BytesIO()
    pdf = SimpleDocTemplate(
        buf, pagesize=letter,
        title=f"Estimate {payload['header']['estimate_number']}",
        leftMargin=0.5 * inch, rightMargin=0.5 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
    )
    story = []

    # ── Brand logo (Phase 34 · Feb 2026) ────────────────────────
    # Per-tenant override wins; falls back to the shared brand logo
    # bundled with the frontend so every generated estimate PDF
    # matches the invoice + login + email surfaces.
    logo_path = _resolve_logo_path(tenant)
    if logo_path:
        try:
            story.append(Image(logo_path, width=2.4 * inch, height=0.9 * inch,
                                kind="proportional", hAlign="LEFT"))
            story.append(Spacer(1, 8))
        except Exception:  # pragma: no cover
            logger.warning("estimate_pdf: failed to embed logo from %s", logo_path)

    company = payload["company"]
    hdr = payload["header"]
    header_t = Table([[
        [Paragraph(f"<b>{company['name']}</b>", styles["Heading3"]),
         Paragraph(company["address"] or "", styles["Normal"]),
         Paragraph(company["phone"] or "", styles["Normal"]),
         Paragraph(company["website"] or "", styles["Normal"])],
        [Paragraph("<b>Estimate</b>", big)],
        [Table([
            [Paragraph("Estimate #", label_r), Paragraph(str(hdr["estimate_number"]), value_r)],
            [Paragraph("Estimate Date", label_r), Paragraph(hdr["estimate_date"] or "", value_r)],
            [Paragraph("Customer #", label_r), Paragraph(hdr["customer_number"] or "", value_r)],
        ], colWidths=[1.3 * inch, 1.3 * inch])],
    ]], colWidths=[3.0 * inch, 1.8 * inch, 2.6 * inch])
    header_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(header_t)
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=rlcolors.HexColor("#111827")))
    story.append(Spacer(1, 12))

    bt = payload["bill_to"]
    story.append(Paragraph(f"<b>{bt.get('name') or ''}</b>", styles["Heading4"]))
    if bt.get("address"):
        story.append(Paragraph(bt["address"], styles["Normal"]))
    if payload.get("property_address"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"<b>Property Address:</b> {payload['property_address']}",
            styles["Normal"],
        ))
    if payload.get("title"):
        story.append(Spacer(1, 8))
        story.append(Paragraph(f"<b>{payload['title']}</b>", styles["Heading3"]))
    story.append(Spacer(1, 12))

    # Line items — Phase K79 · Feb-2026, updated K79-TOGGLE Feb-2026:
    #   1. Admin internal PDF (?internal=1)     → all columns, itemized
    #   2. Customer PDF, grouped ON (default)   → grouped rows
    #   3. Customer PDF, grouped OFF            → itemized customer rows
    #
    # The lock-on ship (which forced grouped for every customer PDF)
    # has been reverted; ``customer_group_display`` is once again the
    # source of truth for the customer surface. Legacy quotes with
    # the field missing / None default to grouped so historicals
    # never regress to itemized without an explicit operator flip.
    is_customer_pdf = payload["as_customer"]
    _cgd_raw = est.get("customer_group_display")
    _cgd_pref = True if _cgd_raw is None else bool(_cgd_raw)
    grouped_mode = is_customer_pdf and _cgd_pref
    if grouped_mode:
        cv = payload.get("customer_view") or {}
        headers = ["Service", "Description", "Subtotal"]
        colw = [2.0 * inch, 3.5 * inch, 1.5 * inch]
        rows = [headers]
        for g in cv.get("groups") or []:
            # Feb-2026 · Decline-per-group ship — struck groups render
            # with an inline <strike> tag on every cell so ReportLab's
            # Paragraph renderer applies the line-through visual.
            label_str = g.get("label") or "—"
            desc_str = g.get("description") or ""
            subtotal_str = f"{float(g.get('subtotal') or 0):.2f}"
            if g.get("declined"):
                rows.append([
                    Paragraph(f"<strike><b>{label_str}</b></strike>",
                              styles["Normal"]),
                    Paragraph(f"<strike>{desc_str}</strike>",
                              styles["Normal"]),
                    Paragraph(f"<strike>{subtotal_str}</strike>",
                              styles["Normal"]),
                ])
            else:
                rows.append([
                    Paragraph(f"<b>{label_str}</b>", styles["Normal"]),
                    Paragraph(desc_str, styles["Normal"]),
                    subtotal_str,
                ])
        if len(rows) == 1:
            rows.append([Paragraph("No services", styles["Normal"]),
                          "", "0.00"])
    elif is_customer_pdf:
        headers = ["Description", "Qty/Hr", "Visits", "Total"]
        colw = [4.0 * inch, 1.0 * inch, 1.0 * inch, 1.5 * inch]
        rows = [headers]
        for li in payload["line_items"]:
            base = [
                Paragraph(li.get("description") or "—", styles["Normal"]),
                f"{li.get('qty_hr') or li.get('quantity') or 0:g}",
                f"{li.get('visits') or 1:g}",
                f"{float(li.get('total') or 0):.2f}",
            ]
            rows.append(base)
    else:
        headers = ["Description", "Cost/Rate", "Qty/Hr", "Visits", "Margin %", "Total"]
        colw = [3.0 * inch, 0.9 * inch, 0.7 * inch, 0.7 * inch, 0.8 * inch, 1.0 * inch]
        rows = [headers]
        for li in payload["line_items"]:
            base = [
                Paragraph(li.get("description") or "—", styles["Normal"]),
                f"{float(li.get('cost_rate') or li.get('unit_price') or 0):.2f}",
                f"{li.get('qty_hr') or li.get('quantity') or 0:g}",
                f"{li.get('visits') or 1:g}",
                f"{float(li.get('margin_pct') or 0):.2f}",
                f"{float(li.get('total') or 0):.2f}",
            ]
            rows.append(base)
    lt = Table(rows, colWidths=colw)
    lt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("BACKGROUND", (0, 0), (-1, 0), rlcolors.HexColor("#F3F4F6")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E5E7EB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(lt)
    story.append(Spacer(1, 14))

    # Totals (right-aligned).
    tot = payload["totals"]
    # Feb-2026 · Decline-per-group ship — customer PDF renders the
    # EFFECTIVE (post-decline) totals so the number the customer signs
    # against matches what they see struck-out. Admin ``?internal=1``
    # PDF keeps the original numbers (grouped_mode is only ON for
    # customer surfaces so this branch is safe).
    if is_customer_pdf and tot.get("has_declined_lines"):
        _tot_subtotal = tot.get("adjusted_subtotal", tot.get("subtotal", 0))
        _tot_tax = tot.get("adjusted_tax", tot.get("taxes", 0))
        _tot_total = tot.get("adjusted_total", tot.get("total_estimated_cost", 0))
    else:
        _tot_subtotal = tot.get("subtotal", 0)
        _tot_tax = tot.get("taxes", 0)
        _tot_total = tot.get("total_estimated_cost", 0)
    tot_rows = [
        ["Subtotal", f"{_tot_subtotal:.2f}"],
        ["Taxes", f"{_tot_tax:.2f}"],
        ["Amount Paid", f"{tot.get('amount_paid', 0):.2f}"],
        ["Total Estimated Cost", f"{_tot_total:.2f}"],
    ]
    if not is_customer_pdf:
        tot_rows.extend([
            ["Estimated Profit", f"{tot.get('estimated_profit', 0):.2f}"],
            ["Total B.Hrs", f"{tot.get('total_b_hrs', 0):.2f}"],
            ["Total B.Hrs Revenue", f"{tot.get('total_b_hrs_revenue', 0):.2f}"],
        ])
    tot_t = Table(tot_rows, colWidths=[2.2 * inch, 1.0 * inch], hAlign="RIGHT")
    tot_t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, 3), (-1, 3), 0.6, rlcolors.HexColor("#111827")),
        ("FONT", (0, 3), (-1, 3), "Helvetica-Bold", 11),
    ]))
    story.append(tot_t)
    story.append(Spacer(1, 12))

    # Notes.
    if payload.get("notes"):
        story.append(Paragraph("<b>Notes:</b>", styles["Normal"]))
        story.append(Paragraph(payload["notes"], styles["Normal"]))
        story.append(Spacer(1, 12))

    # Footer disclaimer.
    disclaimer = (
        "This estimate is a good faith estimate only and is not a "
        "guarantee of final cost. It is based on anticipated labor, "
        "materials, and conditions known at the time of estimating. "
        "Unforeseen conditions, hidden issues, design changes, or "
        "client-requested modifications may result in additional costs "
        "beyond this estimate. Any additional charges will be documented "
        "and communicated for approval as soon as reasonably possible."
    )
    story.append(HRFlowable(width="100%", thickness=0.4, color=rlcolors.HexColor("#9CA3AF")))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<font size=8 color='#6B7280'>{disclaimer}</font>",
        styles["Normal"],
    ))
    # Feb-2026 · Theme Refresh — apply branded header/footer bands
    # on customer-facing surfaces only. Admin (?internal=1) PDFs keep
    # the plain layout so ops screens don't shift. Bands come from
    # ``get_effective_business_settings(absolutize=True)`` so any
    # relative logo_url is promoted to a full https URL — ReportLab
    # can't fetch same-origin ``/api/objects/…`` paths.
    _on_first, _on_later = None, None
    if is_customer_pdf:
        try:
            from services.tenants.business_settings import (
                get_effective_business_settings,
            )
            from services.tenants.pdf_theme import (
                build_header_footer_hooks, HEADER_BAND_HEIGHT,
                FOOTER_BAND_HEIGHT,
            )
            eff = await get_effective_business_settings(
                db, tenant["id"], absolutize=True,
            )
            company_lines = [
                eff.get("company_display_name"),
                (eff.get("mailing_address") or "").splitlines()[0]
                    if eff.get("mailing_address") else None,
                eff.get("phone"), eff.get("email"),
                eff.get("website"),
            ]
            _on_first, _on_later = build_header_footer_hooks(
                brand_hex=eff.get("brand_primary_hex"),
                title="ESTIMATE",
                company_display_name=eff.get("company_display_name"),
                company_lines=[c for c in company_lines if c],
                logo_absolute_url=eff.get("logo_url"),
                footer_note=eff.get("footer_note"),
            )
            # Add breathing room so story flows below the header
            # rectangle on page 1 and above the footer everywhere.
            pdf.topMargin = HEADER_BAND_HEIGHT + 0.15 * inch
            pdf.bottomMargin = FOOTER_BAND_HEIGHT + 0.15 * inch
        except Exception as exc:  # pragma: no cover
            logger.warning("estimate_pdf_theme_wire_failed: %s", exc)
            _on_first, _on_later = None, None
    if _on_first and _on_later:
        pdf.build(story, onFirstPage=_on_first, onLaterPages=_on_later)
    else:
        pdf.build(story)
    data = buf.getvalue()
    buf.close()
    filename = f"estimate-{hdr['estimate_number']}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
