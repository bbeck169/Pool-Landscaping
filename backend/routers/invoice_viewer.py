"""Feb 2026 · Slice Q — Invoice Viewer aggregator + PDF.

``GET /api/invoices/{iid}/full`` returns everything the online invoice
viewer needs in a single roundtrip.  Invoices live in the ``quotes``
collection with ``doc_type=invoice`` — the viewer is a pure read
layer so we can present the classic Vistancia stub-style layout
without touching the underlying schema.

Payload sections:
    company          — tenant identity + support contact
    bill_to          — customer identity + address
    property_address — formatted property address (falls back to bill_to)
    header           — invoice_number, invoice_date, credit_available,
                        outstanding_balance
    line_items       — pass-through from the quote row
    totals           — subtotal, this_invoice, amount_paid, total_due
    notes            — invoice.notes ‖ tenant default note
    is_due_on_receipt — computed flag driving the red marker

RBAC:
    customer   → own invoices only
    technician → 403 (billing surface)
    admin      → tenant-scoped
"""
from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from config import db, logger
from utils import get_current_user, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()


# ── Brand logo path resolver (Phase 34 · Feb 2026) ────────────────────
# Prefer a per-tenant custom logo when one has been uploaded; fall back
# to the shared brand mark shipped with the frontend so every generated
# invoice PDF still carries brand identity.
#
# Feb-2026 · Batch #4 · Logo ship — routed through a single helper
# (`get_tenant_logo_path`) so the P2 tenant-scoped upload flow only
# needs to change the constants below. The new Pool & Landscaping of
# Vistancia asset ships as the primary default; the legacy
# `/logo-full.png` stays as a last-resort fallback so any host that
# doesn't have the new asset yet still gets branded output.
_DEFAULT_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "static", "logos", "pool-landscaping-of-vistancia.png",
)
_LEGACY_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "public", "logo-full.png",
)
# Web-preview URL served by the frontend. Included in the API's
# ``company`` payload so the React viewers pick up the same asset the
# PDF renderer uses.
_DEFAULT_LOGO_URL = "/logos/pool-landscaping-of-vistancia@1x.png"


def get_tenant_logo_path(tenant: Dict[str, Any]) -> Optional[str]:
    """Filesystem path to the tenant's logo for ReportLab. Returns
    ``None`` when neither the override nor either default exists."""
    settings = (tenant or {}).get("settings") or {}
    biz = settings.get("business_card") or {}
    override = biz.get("logo_local_path") or (tenant or {}).get("logo_local_path")
    if override and os.path.exists(override):
        return override
    if os.path.exists(_DEFAULT_LOGO_PATH):
        return _DEFAULT_LOGO_PATH
    if os.path.exists(_LEGACY_LOGO_PATH):
        return _LEGACY_LOGO_PATH
    return None


def get_tenant_logo_url(tenant: Dict[str, Any]) -> str:
    """Web-preview URL for the tenant's logo. Returns the tenant's
    configured URL when present, else the shared default so every
    doc surface (invoice / quote / estimate / magic link) renders
    the same asset without a per-tenant seed."""
    t = tenant or {}
    return t.get("logo_url") or _DEFAULT_LOGO_URL


def _resolve_logo_path(tenant: Dict[str, Any]) -> Optional[str]:
    """Back-compat shim for callers that still import the old name."""
    return get_tenant_logo_path(tenant)


DEFAULT_NOTE = (
    "Pool & Landscaping of Vistancia appreciates your business. If you "
    "have any questions regarding your invoice or need further "
    "assistance, please feel free to contact us at {phone}. We are "
    "happy to help. Thank you for choosing Pool & Landscaping of "
    "Vistancia."
)


def _fmt_addr(addr: Any) -> Optional[str]:
    if not addr:
        return None
    if isinstance(addr, str):
        return addr.strip() or None
    if not isinstance(addr, dict):
        return None
    parts = [addr.get("line1"), addr.get("line2"),
             ", ".join([p for p in (addr.get("city"), addr.get("state")) if p]),
             addr.get("postal_code")]
    joined = ", ".join([p for p in parts if p])
    return joined or None


async def _load_company(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    return {
        "name": t.get("name") or "Pool & Landscaping",
        "address": t.get("hq_address_formatted") or t.get("hq_address") or "",
        "phone": t.get("support_phone_number") or "",
        "website": t.get("website") or "www.plofv.com",
        "email": t.get("support_email") or "",
        # Feb-2026 · Batch #4 · Logo ship — surface the tenant logo
        # URL so the shared React viewers (InvoiceView / EstimateView)
        # can render the same brand asset the PDF pipeline uses. Falls
        # back to the Pool & Landscaping of Vistancia default when the
        # tenant hasn't uploaded its own logo yet (P2 admin flow).
        "logo_url": get_tenant_logo_url(t),
    }


async def _load_customer(customer_id: str, tenant_id: str) -> Dict[str, Any]:
    if not customer_id:
        return {"name": "", "address": ""}
    c = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id}, {"_id": 0},
    ) or {}
    return {
        "id": c.get("id"),
        "customer_number": c.get("customer_number") or c.get("id", "")[:8],
        "name": c.get("name") or "",
        "address": _fmt_addr(c.get("address")),
        "phone": c.get("phone") or "",
        "email": c.get("email") or "",
    }


async def _load_property_address(inv: Dict[str, Any],
                                    tenant_id: str,
                                    bill_to_address: Optional[str]) -> Optional[str]:
    pid = inv.get("property_id")
    if pid:
        p = await db.properties.find_one(
            {"id": pid, "tenant_id": tenant_id}, {"_id": 0, "address": 1},
        )
        if p:
            addr = _fmt_addr(p.get("address"))
            if addr:
                return addr
    # Legacy invoices may carry the property address as a plain string.
    if inv.get("property_address"):
        return inv["property_address"]
    return bill_to_address


async def _compute_credit(customer_id: str, tenant_id: str) -> float:
    """Best-effort read of the customer's credit balance.  Never
    raises — the viewer degrades gracefully to ``0.00`` when the
    credit collection isn't present in this tenant."""
    if not customer_id:
        return 0.0
    try:
        row = await db.customer_credits.find_one(
            {"customer_id": customer_id, "tenant_id": tenant_id},
            {"_id": 0, "balance": 1},
        )
        if row and row.get("balance") is not None:
            return float(row.get("balance") or 0)
    except Exception:
        pass
    return 0.0


async def _load_invoice(iid: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    # Feb-2026 · P2 Item 3 — portal read-path guard. This helper feeds
    # both ``GET /invoices/{iid}/full`` (portal viewer aggregator) and
    # ``GET /invoices/{iid}/pdf`` (portal PDF generator), each of
    # which is customer-accessible. Soft-deleted invoices MUST NOT
    # render — return None so the router 404s the caller.
    return await db.quotes.find_one(
        {"id": iid, "tenant_id": tenant_id, "doc_type": "invoice",
          "$or": [
              {"deleted_at": None},
              {"deleted_at": {"$exists": False}},
          ]},
        {"_id": 0},
    )


async def _authorize(user: dict, inv: Dict[str, Any]) -> None:
    role = user.get("role") or ""
    if role == "technician":
        raise HTTPException(403, "Not allowed")
    if role == "customer":
        if inv.get("customer_id") != user.get("customer_id"):
            raise HTTPException(404, "Invoice not found")


async def _build_viewer_payload(iid: str, tenant: dict, user: dict) -> Dict[str, Any]:
    inv = await _load_invoice(iid, tenant["id"])
    if not inv:
        raise HTTPException(404, "Invoice not found")
    await _authorize(user, inv)

    company = await _load_company(tenant["id"])
    bill_to = await _load_customer(inv.get("customer_id"), tenant["id"])
    property_address = await _load_property_address(
        inv, tenant["id"], bill_to.get("address"),
    )
    credit_available = await _compute_credit(bill_to.get("id"), tenant["id"])

    subtotal = float(inv.get("subtotal") or 0)
    tax = float(inv.get("tax") or 0)
    total = float(inv.get("total") or 0)
    amount_paid = float(inv.get("amount_paid") or 0)
    total_due = round(max(total - amount_paid, 0), 2)

    payment_status = (inv.get("payment_status") or "").lower()
    is_due_on_receipt = total_due > 0 and payment_status not in ("paid", "voided")

    notes = (inv.get("notes") or "").strip()
    if not notes:
        notes = DEFAULT_NOTE.replace("{phone}", company.get("phone") or "us")

    invoice_number = (
        inv.get("invoice_number")
        or inv.get("number")
        or (inv.get("id") or "")[:8].upper()
    )
    invoice_date = (
        inv.get("issued_at")
        or inv.get("created_at")
        or ""
    )[:10]

    line_items = []
    for li in (inv.get("line_items") or []):
        qty = float(li.get("quantity") or 0)
        unit = float(li.get("unit_price") or 0)
        pct = float(li.get("discount_pct") or li.get("percent") or 0)
        row_total = round(qty * unit * (1 - pct / 100.0), 2)
        line_items.append({
            "description": li.get("description") or li.get("name") or "",
            "cost_rate": unit,
            "qty_hr": qty,
            "percent": pct,
            "total": row_total,
        })

    return {
        "invoice_id": inv.get("id"),
        "status": inv.get("status") or "sent",
        "payment_status": payment_status or "unpaid",
        "is_due_on_receipt": is_due_on_receipt,
        "company": company,
        "bill_to": bill_to,
        "property_address": property_address,
        "header": {
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "credit_available": round(credit_available, 2),
            "outstanding_balance": round(float(inv.get("outstanding_balance") or 0), 2),
        },
        "line_items": line_items,
        "notes": notes,
        "totals": {
            "subtotal": round(subtotal, 2),
            "this_invoice": round(total, 2),
            "amount_paid": round(amount_paid, 2),
            "total_due": total_due,
            "tax": round(tax, 2),
            # Task SS Phase 2 · Feb 2026 — surface the credit-applied
            # summary so the InvoiceView annotation can render on both
            # portal + admin views without a second fetch.
            "credits_applied_cents": int(inv.get("credits_applied_cents") or 0),
            "paid_method": inv.get("paid_method"),
        },
        "credits_applied_cents": int(inv.get("credits_applied_cents") or 0),
        "paid_method": inv.get("paid_method"),
        "title": inv.get("title") or "",
        # INV-SERIALIZE-PAID · Feb-2026 — surface the paid-status
        # fields the mobile invoice detail view consumes (see
        # mobile/app/invoice/[id].tsx:166-167). ``paid_at`` is a
        # straight pass-through of the ISO string stamped by the
        # PDFI-PAID-B commit lane (pdf_commit.py:749) or the
        # FIN-PARITY-A reconciler. ``is_paid`` is derived from
        # ``payment_status == "paid"`` — matches the precedent
        # in routers/quotes.py:1865 and the mobile consumer's
        # own fallback. ``is_paid`` is NOT persisted on the
        # invoice doc; it is a view-only convenience.
        "paid_at": inv.get("paid_at"),
        "is_paid": payment_status == "paid",
    }


@router.get("/invoices/{iid}/full")
async def get_invoice_full(iid: str,
                            request: Request,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    result = await _build_viewer_payload(iid, tenant, user)

    # Phase K47 · Feb-2026 — record portal-authenticated customer
    # views. Admin/office/dispatcher views are NOT tracked here
    # (this is a customer-engagement signal, not an internal
    # audit log). The magic-link viewer records email/sms opens in
    # a separate hook — see ``routers/invoice_magic_view.py``.
    if (user.get("role") or "").lower() == "customer":
        try:
            from services.invoice_view_tracker import record_invoice_view
            ua = request.headers.get("user-agent")
            ip = request.client.host if request.client is not None else None
            await record_invoice_view(
                invoice_id=iid,
                tenant_id=tenant["id"],
                source="portal",
                user_agent=ua,
                ip=ip,
            )
        except Exception:  # pragma: no cover — defensive
            pass

    return result


# ══════════════════════════════════════════════════════════════════
# PDF endpoint mirroring the Vistancia-style layout.
# ══════════════════════════════════════════════════════════════════
@router.get("/invoices/{iid}/pdf")
async def get_invoice_pdf(iid: str,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    payload = await _build_viewer_payload(iid, tenant, user)
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rlcolors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
        Image,
    )

    styles = getSampleStyleSheet()
    right = ParagraphStyle("right", parent=styles["Normal"], alignment=2, fontSize=10)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=rlcolors.grey)
    big = ParagraphStyle("big", parent=styles["Title"], alignment=2, fontSize=28)
    label_r = ParagraphStyle("labelr", parent=styles["Normal"], alignment=2,
                              fontSize=9, textColor=rlcolors.grey)
    value_r = ParagraphStyle("valuer", parent=styles["Normal"], alignment=2,
                              fontSize=10, fontName="Helvetica-Bold")

    buf = BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=letter, title=f"Invoice {payload['header']['invoice_number']}",
                              leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                              topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    story = []

    # ── Brand logo (Phase 34 · Feb 2026) ────────────────────────
    # Per-tenant override wins; falls back to the shared brand logo
    # bundled with the frontend so every generated invoice PDF
    # carries the same brand identity as estimates + login screens.
    logo_path = _resolve_logo_path(tenant)
    if logo_path:
        try:
            story.append(Image(logo_path, width=2.4 * inch, height=0.9 * inch,
                                kind="proportional", hAlign="LEFT"))
            story.append(Spacer(1, 8))
        except Exception:  # pragma: no cover — never let a missing asset kill the PDF
            logger.warning("invoice_pdf: failed to embed logo from %s", logo_path)

    # ── Header (two columns) ────────────────────────────────────
    company = payload["company"]
    company_block = [
        Paragraph(f"<b>{company['name']}</b>", styles["Heading3"]),
        Paragraph(company["address"] or "", styles["Normal"]),
        Paragraph(company["phone"] or "", styles["Normal"]),
        Paragraph(company["website"] or "", styles["Normal"]),
    ]
    hdr = payload["header"]
    right_block = [
        Paragraph("<b>Invoice</b>", big),
        Spacer(1, 6),
        Table([
            [Paragraph("Invoice #", label_r), Paragraph(str(hdr["invoice_number"]), value_r)],
            [Paragraph("Invoice Date", label_r), Paragraph(hdr["invoice_date"] or "", value_r)],
            [Paragraph("Credit Available", label_r), Paragraph(f"{hdr['credit_available']:.2f}", value_r)],
            [Paragraph("Outstanding Balance", label_r), Paragraph(f"{hdr['outstanding_balance']:.2f}", value_r)],
        ], colWidths=[1.3 * inch, 1.3 * inch]),
    ]
    header_t = Table([[company_block, right_block]],
                      colWidths=[3.8 * inch, 3.6 * inch])
    header_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(header_t)
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5, color=rlcolors.HexColor("#111827")))
    story.append(Spacer(1, 12))

    # ── Bill To ─────────────────────────────────────────────────
    bt = payload["bill_to"]
    story.append(Paragraph(f"<b>{bt.get('name') or ''}</b>", styles["Heading4"]))
    if bt.get("address"):
        story.append(Paragraph(bt["address"], styles["Normal"]))
    story.append(Spacer(1, 10))
    if payload.get("property_address"):
        story.append(Paragraph(
            f"<b>Property Address:</b> {payload['property_address']}",
            styles["Normal"],
        ))
    story.append(Spacer(1, 12))

    # ── Line items ──────────────────────────────────────────────
    # Phase 14B · Feb-2026 — thread Phase 7A form_template styles
    # into the line_items_table so admin style edits in the
    # editor propagate to printed invoice PDFs. Zero-regression:
    # when no template is saved (or the fetch fails), the helper
    # returns ``None`` and we fall back to the pre-14B hex
    # literals verbatim.
    from services.documents.pdf_template_styles import (
        load_pdf_template_styles, hex_or_default,
    )
    _tpl_styles = await load_pdf_template_styles(
        tenant_id=tenant.get("id"), form_type="invoice",
    )
    _li_style = (_tpl_styles or {}).get("line_items_table") or {}
    _li_bg = hex_or_default(_li_style.get("bg_color"), "#F3F4F6")
    _li_border = hex_or_default(_li_style.get("border_color"), "#E5E7EB")
    _li_pad = _li_style.get("padding_y")
    _li_pad = int(_li_pad) if isinstance(_li_pad, (int, float)) else 4
    rows = [["Description", "Cost/Rate", "Qty/Hr", "%", "Total"]]
    for li in payload["line_items"]:
        rows.append([
            Paragraph(li["description"] or "—", styles["Normal"]),
            f"{li['cost_rate']:.2f}",
            f"{li['qty_hr']:g}",
            f"{li['percent']:.2f}",
            f"{li['total']:.2f}",
        ])
    lt = Table(rows,
                colWidths=[3.6 * inch, 0.9 * inch, 0.7 * inch, 0.6 * inch, 0.9 * inch])
    lt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("BACKGROUND", (0, 0), (-1, 0), rlcolors.HexColor(_li_bg)),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (2, 1), (2, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor(_li_border)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), _li_pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), _li_pad),
    ]))
    story.append(lt)
    story.append(Spacer(1, 14))

    # ── Totals (right-aligned) ──────────────────────────────────
    tot = payload["totals"]
    tot_rows = [
        ["Subtotal", f"{tot['subtotal']:.2f}"],
        ["This Invoice", f"{tot['this_invoice']:.2f}"],
        ["Amount Paid", f"{tot['amount_paid']:.2f}"],
        ["Total Due", f"{tot['total_due']:.2f}"],
    ]
    tot_t = Table(tot_rows, colWidths=[1.6 * inch, 1.0 * inch],
                    hAlign="RIGHT")
    tot_t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, rlcolors.HexColor("#111827")),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 11),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tot_t)
    story.append(Spacer(1, 12))

    # ── Notes ──────────────────────────────────────────────────
    story.append(Paragraph("<b>Notes:</b>", styles["Normal"]))
    story.append(Paragraph(payload["notes"], styles["Normal"]))
    story.append(Spacer(1, 12))

    if payload["is_due_on_receipt"]:
        due_style = ParagraphStyle("due", parent=styles["Normal"], alignment=2,
                                    fontSize=12, textColor=rlcolors.HexColor("#B91C1C"),
                                    fontName="Helvetica-Bold")
        story.append(Paragraph("Due on Receipt", due_style))
        story.append(Spacer(1, 12))

    # ── Payment stub ────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.8, dash=(2, 3),
                              color=rlcolors.HexColor("#6B7280")))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>PAYMENT STUB</b>", styles["Heading3"]))
    stub_left = [
        Paragraph(f"<b>{bt.get('name') or ''}</b>", styles["Normal"]),
        Paragraph(bt.get("address") or "", styles["Normal"]),
        Spacer(1, 6),
        Paragraph(f"<b>{company['name']}</b>", styles["Normal"]),
        Paragraph(company["address"] or "", styles["Normal"]),
        Paragraph(company["phone"] or "", styles["Normal"]),
        Paragraph(company["website"] or "", styles["Normal"]),
    ]
    stub_right = Table([
        ["Customer", bt.get("name") or ""],
        ["Invoice #", str(hdr["invoice_number"])],
        ["Invoice Date", hdr["invoice_date"] or ""],
        ["Outstanding Balance", f"{hdr['outstanding_balance']:.2f}"],
        ["This Invoice", f"{tot['this_invoice']:.2f}"],
        ["Total Due on Account", f"{tot['total_due']:.2f}"],
        ["Amount Paid", f"{tot['amount_paid']:.2f}"],
    ], colWidths=[1.5 * inch, 1.5 * inch])
    stub_right.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E5E7EB")),
    ]))
    stub_t = Table([[stub_left, stub_right]], colWidths=[3.6 * inch, 3.4 * inch])
    stub_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(stub_t)

    pdf.build(story)
    data = buf.getvalue()
    buf.close()
    filename = f"invoice-{hdr['invoice_number']}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
