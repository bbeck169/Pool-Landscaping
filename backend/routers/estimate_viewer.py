"""Feb 2026 · Slice R — Estimate Viewer aggregator + Accept/Decline + PDF.

Endpoints:
    GET  /api/estimates/{eid}/full            — role-projected viewer payload
    POST /api/estimates/{eid}/accept          — admin or portal customer
    POST /api/estimates/{eid}/decline         — same
    POST /api/estimates/{eid}/request-changes — same
    GET  /api/estimates/{eid}/magic-link      — admin issues token URL
    GET  /api/portal/estimates/via-token       — public, reads by JWT
    POST /api/portal/estimates/via-token/accept
    POST /api/portal/estimates/via-token/decline
    POST /api/portal/estimates/via-token/request-changes
    GET  /api/estimates/{eid}/pdf              — ReportLab

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
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from config import db, logger, JWT_SECRET, JWT_ALGO
from utils import get_current_user, now_iso, new_id
from routers.tenants import get_current_tenant
from routers.invoice_viewer import _resolve_logo_path
from routers.invoice_viewer import (
    _fmt_addr, _load_company, _load_customer,
)

router = APIRouter()

TOKEN_SUB = "est"
MAGIC_LINK_TTL_DAYS = 30

_CUSTOMER_LINE_HIDDEN = ("calc", "m_rate", "bh", "t_bh", "t_b_cost",
                          "margin_pct", "cost_rate", "unit_price", "cost")
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


async def _load_estimate(eid: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    return await db.quotes.find_one(
        {"id": eid, "tenant_id": tenant_id,
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
    return {
        "subtotal": round(subtotal, 2),
        "taxes": round(tax, 2),
        "amount_paid": round(amount_paid, 2),
        "total_estimated_cost": round(total, 2),
        "estimated_profit": round(est_profit, 2),
        "total_b_hrs": round(total_bhrs, 2),
        "total_b_hrs_revenue": round(total_bhrs_rev, 2),
    }


async def _build_payload(est: dict, tenant: dict, *,
                          as_customer: bool) -> Dict[str, Any]:
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
        "as_customer": as_customer,
        # K79 grouped preview — always included so the admin toolbar's
        # "Preview customer view" can render without a second call.
        "customer_view": customer_view,
    }


# ══════════════════════════════════════════════════════════════════
# GET /estimates/{eid}/full
# ══════════════════════════════════════════════════════════════════
@router.get("/estimates/{eid}/full")
async def get_estimate_full(eid: str,
                              user: dict = Depends(get_current_user),
                              tenant: dict = Depends(get_current_tenant)):
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    est = await _load_estimate(eid, tenant["id"])
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


async def _authorised_estimate(eid: str, user: dict,
                                tenant: dict) -> Dict[str, Any]:
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    est = await _load_estimate(eid, tenant["id"])
    if not est:
        raise HTTPException(404, "Estimate not found")
    if role == "customer" and est.get("customer_id") != user.get("customer_id"):
        raise HTTPException(404, "Estimate not found")
    return est


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


@router.post("/estimates/{eid}/accept")
async def accept_estimate(eid: str,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    est = await _authorised_estimate(eid, user, tenant)
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_accepted(est, tenant["id"], user.get("id"))
    await _notify_admins(
        tenant["id"], kind="quote_accepted",
        title=f"Estimate accepted by {est.get('customer_name') or 'customer'}",
        body=f"Estimate #{(est.get('id') or '')[:8]} was accepted.",
        href=f"/estimates/{eid}",
    )
    return await _build_payload(
        await _load_estimate(eid, tenant["id"]), tenant,
        as_customer=(user.get("role") == "customer"),
    )


@router.post("/estimates/{eid}/decline")
async def decline_estimate(eid: str, body: DeclineIn,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    est = await _authorised_estimate(eid, user, tenant)
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_declined(est, tenant["id"], user.get("id"), body.reason)
    await _notify_admins(
        tenant["id"], kind="quote_accepted",
        title=f"Estimate declined by {est.get('customer_name') or 'customer'}",
        body=(body.reason or "No reason given")[:200],
        href=f"/estimates/{eid}",
    )
    return await _build_payload(
        await _load_estimate(eid, tenant["id"]), tenant,
        as_customer=(user.get("role") == "customer"),
    )


@router.post("/estimates/{eid}/request-changes")
async def request_changes(eid: str, body: RequestChangesIn,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    est = await _authorised_estimate(eid, user, tenant)
    if not (body.message or "").strip():
        raise HTTPException(422, "message is required")
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_changes_requested(est, tenant["id"], user.get("id"), body.message)
    await _notify_admins(
        tenant["id"], kind="quote_accepted",
        title=f"Estimate change request from {est.get('customer_name') or 'customer'}",
        body=body.message[:200],
        href=f"/estimates/{eid}",
    )
    return await _build_payload(
        await _load_estimate(eid, tenant["id"]), tenant,
        as_customer=(user.get("role") == "customer"),
    )


# ══════════════════════════════════════════════════════════════════
# Magic-link tokens (public path)
# ══════════════════════════════════════════════════════════════════
def _sign_estimate_token(eid: str, cid: str, tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": TOKEN_SUB,
        "eid": eid,
        "cid": cid,
        "tid": tenant_id,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(days=MAGIC_LINK_TTL_DAYS),
    }
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


@router.get("/estimates/{eid}/magic-link")
async def issue_magic_link(eid: str,
                             user: dict = Depends(get_current_user),
                             tenant: dict = Depends(get_current_tenant)):
    if not _is_admin(user):
        raise HTTPException(403, "Admin only")
    est = await _load_estimate(eid, tenant["id"])
    if not est:
        raise HTTPException(404, "Estimate not found")
    cid = est.get("customer_id") or ""
    tok = _sign_estimate_token(eid, cid, tenant["id"])
    return {"token": tok, "url": f"/e/estimate?token={tok}",
             "expires_in_days": MAGIC_LINK_TTL_DAYS}


async def _load_est_from_token(tok: str) -> Dict[str, Any]:
    payload = _verify_estimate_token(tok)
    est = await db.quotes.find_one(
        {"id": payload["eid"], "tenant_id": payload["tid"]}, {"_id": 0},
    )
    if not est or est.get("customer_id") != payload["cid"]:
        raise HTTPException(401, "Invalid estimate link")
    tenant = await db.tenants.find_one({"id": payload["tid"]}, {"_id": 0})
    if not tenant:
        raise HTTPException(401, "Invalid estimate link")
    return {"est": est, "tenant": tenant, "cid": payload["cid"]}


@router.get("/portal/estimates/via-token")
async def view_estimate_via_token(token: str = Query(...)):
    ctx = await _load_est_from_token(token)
    return await _build_payload(ctx["est"], ctx["tenant"], as_customer=True)


@router.post("/portal/estimates/via-token/accept")
async def accept_via_token(token: str = Query(...)):
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_accepted(est, ctx["tenant"]["id"], f"token:{ctx['cid']}")
    await _notify_admins(
        ctx["tenant"]["id"], kind="quote_accepted",
        title="Estimate accepted via link",
        body=f"Estimate #{(est.get('id') or '')[:8]} accepted via magic link.",
        href=f"/estimates/{est['id']}",
    )
    return await _build_payload(
        await db.quotes.find_one({"id": est["id"]}, {"_id": 0}),
        ctx["tenant"], as_customer=True,
    )


@router.post("/portal/estimates/via-token/decline")
async def decline_via_token(body: DeclineIn, token: str = Query(...)):
    ctx = await _load_est_from_token(token)
    est = ctx["est"]
    if est.get("decision") in ("accepted", "declined"):
        raise HTTPException(409, "Estimate is already locked")
    await _mark_declined(est, ctx["tenant"]["id"], f"token:{ctx['cid']}", body.reason)
    await _notify_admins(
        ctx["tenant"]["id"], kind="quote_accepted",
        title="Estimate declined via link",
        body=(body.reason or "No reason given")[:200],
        href=f"/estimates/{est['id']}",
    )
    return await _build_payload(
        await db.quotes.find_one({"id": est["id"]}, {"_id": 0}),
        ctx["tenant"], as_customer=True,
    )


@router.post("/portal/estimates/via-token/request-changes")
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
        ctx["tenant"]["id"], kind="quote_accepted",
        title="Estimate change request via link",
        body=body.message[:200],
        href=f"/estimates/{est['id']}",
    )
    return await _build_payload(
        await db.quotes.find_one({"id": est["id"]}, {"_id": 0}),
        ctx["tenant"], as_customer=True,
    )


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
    ``GET /api/portal/estimates/via-token``.
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
@router.get("/estimates/{eid}/pdf")
async def estimate_pdf(eid: str,
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
    est = await _load_estimate(eid, tenant["id"])
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

    # Line items — Phase K79 · Feb-2026 — three modes:
    #   1. Admin internal PDF (?internal=1)     → all columns, itemized
    #   2. Customer PDF, grouped view enabled   → grouped rows
    #   3. Customer PDF, grouped view disabled  → itemized 4-column
    is_customer_pdf = payload["as_customer"]
    grouped_mode = (
        is_customer_pdf
        and bool(est.get("customer_group_display"))
    )
    if grouped_mode:
        cv = payload.get("customer_view") or {}
        headers = ["Service", "Description", "Subtotal"]
        colw = [2.0 * inch, 3.5 * inch, 1.5 * inch]
        rows = [headers]
        for g in cv.get("groups") or []:
            rows.append([
                Paragraph(f"<b>{g.get('label') or '—'}</b>",
                            styles["Normal"]),
                Paragraph(g.get("description") or "", styles["Normal"]),
                f"{float(g.get('subtotal') or 0):.2f}",
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
    tot_rows = [
        ["Subtotal", f"{tot.get('subtotal', 0):.2f}"],
        ["Taxes", f"{tot.get('taxes', 0):.2f}"],
        ["Amount Paid", f"{tot.get('amount_paid', 0):.2f}"],
        ["Total Estimated Cost", f"{tot.get('total_estimated_cost', 0):.2f}"],
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
    pdf.build(story)
    data = buf.getvalue()
    buf.close()
    filename = f"estimate-{hdr['estimate_number']}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
