"""Phase T4 — Document Generators (admin-only).

Two document generators using the same `reportlab.platypus` pipeline
as `routers/jobs.py::_build_work_order_pdf` (established pattern
across invoice, work-order, check, and certificate PDFs).

Endpoints:
  * POST   /api/documents/checklist-template/save
  * GET    /api/documents/checklist-templates
  * GET    /api/documents/checklist-template/{id}/pdf
  * DELETE /api/documents/checklist-templates/{id}
  * POST   /api/documents/quick-service-report          → PDF stream

Storage collection `document_templates`:
    { id, tenant_id, name, visit_type, readings_rows, checklist_items,
      include_photos_section, include_customer_signature_line,
      include_tech_signature_line, include_notes_section,
      include_notes_internal, include_notes_customer,
      created_by, created_at, updated_at }
"""
from __future__ import annotations
from io import BytesIO
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant


router = APIRouter(prefix="/documents", tags=["documents"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# Canonical checklists — starter buttons on the UI dump these into the
# editable list; admins tune per template thereafter.
CANONICAL_POOL_CHECKLIST = [
    "Skim surface & empty baskets", "Brush walls & tile line",
    "Vacuum pool", "Check & clean filter",
    "Empty pump basket", "Verify equipment operation",
    "Test chemistry & balance", "Add chemicals as needed",
    "Backwash if needed", "Log readings & notes",
    # Phase CHK1 · Feb-2026 — three optional "emptied" items appended.
    # These are OPTIONAL by design and must never gate completion.
    # Casing/spacing preserved verbatim from the product brief.
    "Emptied skimmer basket",
    "Emptied leaf canister",
    "Emptied Betta Skimmer",
]
CANONICAL_LANDSCAPE_CHECKLIST = [
    "Mow lawn to spec height", "Edge walkways & beds",
    "Blow off hardscape", "Trim shrubs & hedges",
    "Weed all beds & pavers", "Inspect irrigation & report leaks",
    "Fertilize / spot-treat if scheduled", "Pick up debris & haul away",
    "Check pest / disease pressure", "Verify gates locked & site walk-through",
]
STANDARD_READING_KEYS = [
    # Phase P17.2 · Feb-2026 — retired ``Total Cl`` column (CHEM1
    # dropped total_chlorine from the Required Four; seed / document
    # generators no longer emit it).  Legacy stored docs still
    # resolve via ``chemistry_gate.ALIAS_MAP``; nothing to migrate.
    "pH", "Chlorine", "Alkalinity", "Calcium Hardness",
    "CYA", "Salt", "Temp", "Phosphates", "Copper", "Iron", "TDS",
]


# ─── Shared reportlab helpers ────────────────────────────────────────
def _get_reportlab():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rlcolors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )
    return dict(letter=letter, rlcolors=rlcolors, styles=getSampleStyleSheet(),
                inch=inch, SimpleDocTemplate=SimpleDocTemplate,
                Paragraph=Paragraph, Spacer=Spacer, Table=Table, TableStyle=TableStyle)


def _tenant_header(story, r, tenant):
    styles = r["styles"]
    name = tenant.get("name") or "Pool & Landscaping"
    phone = tenant.get("phone") or ""
    header_line = f"<b>{name}</b>"
    if phone:
        header_line += f" · {phone}"
    story.append(r["Paragraph"](header_line, styles["Heading3"]))
    story.append(r["Spacer"](1, 6))


def _blank_line(story, r, label: str, width: str = "5.5in"):
    story.append(r["Paragraph"](
        f'{label}: <font color="#CCCCCC">' + "_" * 60 + '</font>',
        r["styles"]["Normal"]))
    story.append(r["Spacer"](1, 4))


# ═══ T4.1 Checklist Template ═════════════════════════════════════════
class ChecklistTemplateIn(BaseModel):
    id: Optional[str] = None
    name: str
    visit_type: str = "pool"  # pool | landscape | both
    readings_rows: List[str] = Field(default_factory=list)
    checklist_items: List[str] = Field(default_factory=list)
    include_photos_section: bool = True
    include_customer_signature_line: bool = True
    include_tech_signature_line: bool = True
    include_notes_section: bool = True
    include_notes_internal: bool = True
    include_notes_customer: bool = True


@router.post("/checklist-template/save")
async def save_template(body: ChecklistTemplateIn,
                        user: dict = Depends(_require_admin),
                        tenant: dict = Depends(get_current_tenant)):
    now = now_iso()
    if body.id:
        r = await db.document_templates.find_one(
            {"id": body.id, "tenant_id": tenant["id"]}, {"_id": 0})
        if not r:
            raise HTTPException(404, "Template not found")
        upd = body.dict(exclude={"id"})
        upd["updated_at"] = now
        await db.document_templates.update_one(
            {"id": body.id, "tenant_id": tenant["id"]}, {"$set": upd})
        return {**r, **upd, "id": body.id}
    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "created_by": user["id"],
        "created_at": now,
        "updated_at": now,
        **body.dict(exclude={"id"}),
    }
    await db.document_templates.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/checklist-templates")
async def list_templates(user: dict = Depends(_require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """List tenant-scoped templates + system-scoped (is_system: true)
    templates seeded by `migrations/seed_canonical_templates.py`. System
    rows are read-only (badge + clone-to-edit on the UI); tenant rows are
    editable/deletable as normal."""
    rows: List[Dict[str, Any]] = []
    async for r in db.document_templates.find(
        {"$or": [
            {"tenant_id": tenant["id"]},
            {"is_system": True},
        ]}, {"_id": 0}
    ).sort("updated_at", -1):
        rows.append(r)
    return {"count": len(rows), "rows": rows}


@router.delete("/checklist-templates/{tid}")
async def delete_template(tid: str,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    # System templates are shared library — never deletable per-tenant.
    sys_row = await db.document_templates.find_one(
        {"id": tid, "is_system": True}, {"_id": 0})
    if sys_row:
        raise HTTPException(403, "System templates cannot be deleted. Clone to edit instead.")
    r = await db.document_templates.delete_one(
        {"id": tid, "tenant_id": tenant["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "Template not found")
    return {"deleted": tid}


# ─── T4.1 (polish) — clone-to-edit for SYSTEM templates ─────────────
@router.post("/checklist-templates/{tid}/clone")
async def clone_template(tid: str,
                         user: dict = Depends(_require_admin),
                         tenant: dict = Depends(get_current_tenant)):
    """Clone any template (system OR tenant-scoped) into a fresh
    tenant-scoped row so admin can edit freely without touching the
    original. Idempotent per-caller: repeat clicks create separate copies
    — that's intentional (admin may want a v2 draft).
    """
    src = await db.document_templates.find_one(
        {"id": tid,
         "$or": [{"tenant_id": tenant["id"]}, {"is_system": True}]},
        {"_id": 0})
    if not src:
        raise HTTPException(404, "Template not found")
    now = now_iso()
    clone = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "is_system": False,
        "cloned_from_id": src.get("id"),
        "cloned_from_code": src.get("code"),
        "name": (src.get("name") or "Untitled") + " (copy)",
        "visit_type": src.get("visit_type", "pool"),
        "readings_rows": list(src.get("readings_rows") or []),
        "checklist_items": list(src.get("checklist_items") or []),
        "include_photos_section": src.get("include_photos_section", True),
        "include_customer_signature_line": src.get("include_customer_signature_line", True),
        "include_tech_signature_line": src.get("include_tech_signature_line", True),
        "include_notes_section": src.get("include_notes_section", True),
        "include_notes_internal": src.get("include_notes_internal", True),
        "include_notes_customer": src.get("include_notes_customer", True),
        "created_by": user["id"],
        "created_at": now,
        "updated_at": now,
    }
    await db.document_templates.insert_one(clone)
    clone.pop("_id", None)
    return clone


@router.get("/checklist-template/{tid}/pdf")
async def template_pdf(tid: str,
                       user: dict = Depends(_require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    # System templates render for any tenant so admins can preview before
    # cloning; tenant-scoped rows must belong to the caller.
    t = await db.document_templates.find_one(
        {"id": tid,
         "$or": [{"tenant_id": tenant["id"]}, {"is_system": True}]},
        {"_id": 0})
    if not t:
        raise HTTPException(404, "Template not found")
    r = _get_reportlab()
    buf = BytesIO()
    doc = r["SimpleDocTemplate"](buf, pagesize=r["letter"],
                                    title=f"Checklist — {t['name']}")
    story = []
    _tenant_header(story, r, tenant)
    story.append(r["Paragraph"](f"<b>{t['name']}</b>", r["styles"]["Title"]))
    story.append(r["Paragraph"](
        f"Visit type: {t.get('visit_type', 'pool').title()}",
        r["styles"]["Normal"]))
    story.append(r["Spacer"](1, 8))
    _blank_line(story, r, "Property")
    _blank_line(story, r, "Date")
    _blank_line(story, r, "Technician")
    story.append(r["Spacer"](1, 10))

    # Readings table
    readings = t.get("readings_rows") or []
    if readings:
        story.append(r["Paragraph"]("<b>Chemistry Readings</b>",
                                    r["styles"]["Heading3"]))
        rows = [["Reading", "Value", "Reading", "Value"]]
        for i in range(0, len(readings), 2):
            left = readings[i]
            right = readings[i + 1] if i + 1 < len(readings) else ""
            rows.append([left, "____________", right, "____________" if right else ""])
        tbl = r["Table"](rows, colWidths=[1.6 * r["inch"], 1.6 * r["inch"],
                                             1.6 * r["inch"], 1.6 * r["inch"]])
        tbl.setStyle(r["TableStyle"]([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
            ("BACKGROUND", (0, 0), (-1, 0), r["rlcolors"].HexColor("#F4F4F5")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, r["rlcolors"].HexColor("#E4E4E7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(tbl)
        story.append(r["Spacer"](1, 12))

    # Checklist section
    items = t.get("checklist_items") or []
    if items:
        story.append(r["Paragraph"]("<b>Checklist</b>", r["styles"]["Heading3"]))
        for it in items:
            story.append(r["Paragraph"](f"☐ &nbsp; {it}", r["styles"]["Normal"]))
        story.append(r["Spacer"](1, 12))

    if t.get("include_photos_section"):
        story.append(r["Paragraph"]("<b>Photos</b>", r["styles"]["Heading3"]))
        story.append(r["Paragraph"](
            "1) ______________________ &nbsp;&nbsp; 2) ______________________<br/>"
            "3) ______________________ &nbsp;&nbsp; 4) ______________________",
            r["styles"]["Normal"]))
        story.append(r["Spacer"](1, 10))

    if t.get("include_notes_section"):
        if t.get("include_notes_customer"):
            story.append(r["Paragraph"]("<b>Customer Notes</b>",
                                        r["styles"]["Heading3"]))
            story.append(r["Paragraph"]("_" * 90 + "<br/>" + "_" * 90 + "<br/>" + "_" * 90,
                                          r["styles"]["Normal"]))
            story.append(r["Spacer"](1, 8))
        if t.get("include_notes_internal"):
            story.append(r["Paragraph"]("<b>Internal Notes</b>",
                                        r["styles"]["Heading3"]))
            story.append(r["Paragraph"]("_" * 90 + "<br/>" + "_" * 90,
                                          r["styles"]["Normal"]))
            story.append(r["Spacer"](1, 10))

    if t.get("include_customer_signature_line") or t.get("include_tech_signature_line"):
        sig_rows = []
        if t.get("include_tech_signature_line"):
            sig_rows.append(["Technician signature", "_" * 30, "Date", "_" * 12])
        if t.get("include_customer_signature_line"):
            sig_rows.append(["Customer signature", "_" * 30, "Date", "_" * 12])
        tbl = r["Table"](sig_rows, colWidths=[1.8 * r["inch"], 2.6 * r["inch"],
                                                 0.6 * r["inch"], 1.4 * r["inch"]])
        tbl.setStyle(r["TableStyle"]([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(tbl)

    story.append(r["Spacer"](1, 20))
    story.append(r["Paragraph"](
        f'<font color="#888888" size="8">Template: {t["name"]} · Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d")}</font>',
        r["styles"]["Normal"]))

    doc.build(story)
    pdf = buf.getvalue()
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="checklist-{tid[:8]}.pdf"'})


# ═══ T4.2 Quick Service Report ═══════════════════════════════════════
class ChemReading(BaseModel):
    label: str
    value: str


class ChemAdded(BaseModel):
    name: str
    amount: str
    unit: str = ""


class QuickServiceReportIn(BaseModel):
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    property_address: Optional[str] = None
    visit_date: str
    tech_name: str
    visit_type: str = "pool"
    chemical_readings: List[ChemReading] = Field(default_factory=list)
    chemicals_added: List[ChemAdded] = Field(default_factory=list)
    checklist_items: List[str] = Field(default_factory=list)
    customer_notes: Optional[str] = ""
    photos: List[str] = Field(default_factory=list)
    include_signatures: bool = True


@router.post("/quick-service-report")
async def quick_service_report(body: QuickServiceReportIn,
                               user: dict = Depends(_require_admin),
                               tenant: dict = Depends(get_current_tenant)):
    # Resolve customer if id supplied.
    cust_name = body.customer_name or ""
    prop_addr = body.property_address or ""
    if body.customer_id:
        c = await db.customers.find_one(
            {"id": body.customer_id, "tenant_id": tenant["id"]}, {"_id": 0})
        if c:
            cust_name = cust_name or c.get("name", "")
            prop_addr = prop_addr or c.get("address", "")
    if not cust_name or not prop_addr:
        raise HTTPException(422, "customer_id or (customer_name + property_address) required")

    r = _get_reportlab()
    buf = BytesIO()
    doc = r["SimpleDocTemplate"](buf, pagesize=r["letter"],
                                    title=f"Service Report — {cust_name}")
    story = []
    _tenant_header(story, r, tenant)
    story.append(r["Paragraph"]("<b>Service Visit Report</b>", r["styles"]["Title"]))
    info_rows = [
        ["Customer", cust_name],
        ["Property", prop_addr],
        ["Date", body.visit_date],
        ["Technician", body.tech_name],
        ["Visit type", body.visit_type.title()],
    ]
    tbl = r["Table"](info_rows, colWidths=[1.5 * r["inch"], 5.0 * r["inch"]])
    tbl.setStyle(r["TableStyle"]([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, 0), (0, -1), r["rlcolors"].HexColor("#F4F4F5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, r["rlcolors"].HexColor("#E4E4E7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(r["Spacer"](1, 12))

    if body.chemical_readings:
        story.append(r["Paragraph"]("<b>Chemistry Readings</b>", r["styles"]["Heading3"]))
        rows = [["Reading", "Value"]]
        for cr in body.chemical_readings:
            rows.append([cr.label, cr.value])
        rt = r["Table"](rows, colWidths=[3.0 * r["inch"], 3.0 * r["inch"]])
        rt.setStyle(r["TableStyle"]([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
            ("BACKGROUND", (0, 0), (-1, 0), r["rlcolors"].HexColor("#F4F4F5")),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, r["rlcolors"].HexColor("#E4E4E7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(rt)
        story.append(r["Spacer"](1, 12))

    if body.chemicals_added:
        story.append(r["Paragraph"]("<b>Chemicals Added</b>", r["styles"]["Heading3"]))
        for c in body.chemicals_added:
            unit = f" {c.unit}" if c.unit else ""
            story.append(r["Paragraph"](f"• {c.name} — {c.amount}{unit}",
                                          r["styles"]["Normal"]))
        story.append(r["Spacer"](1, 12))

    if body.checklist_items:
        story.append(r["Paragraph"]("<b>Completed</b>", r["styles"]["Heading3"]))
        for it in body.checklist_items:
            story.append(r["Paragraph"](f"✓ {it}", r["styles"]["Normal"]))
        story.append(r["Spacer"](1, 12))

    if body.customer_notes:
        story.append(r["Paragraph"]("<b>Notes from your tech</b>",
                                    r["styles"]["Heading3"]))
        story.append(r["Paragraph"](body.customer_notes.replace("\n", "<br/>"),
                                      r["styles"]["Normal"]))
        story.append(r["Spacer"](1, 12))

    if body.include_signatures:
        sig_rows = [
            ["Technician signature", "_" * 30, "Date", "_" * 12],
            ["Customer signature", "_" * 30, "Date", "_" * 12],
        ]
        tbl2 = r["Table"](sig_rows, colWidths=[1.8 * r["inch"], 2.6 * r["inch"],
                                                  0.6 * r["inch"], 1.4 * r["inch"]])
        tbl2.setStyle(r["TableStyle"]([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(tbl2)

    doc.build(story)
    pdf = buf.getvalue()
    fname = f"service-report-{cust_name.split()[0].lower() if cust_name else 'customer'}-{body.visit_date}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


# Canonical helper endpoint the UI uses to seed its editors.
@router.get("/canonical-lists")
async def canonical_lists(user: dict = Depends(_require_admin)):
    return {
        "pool_checklist": CANONICAL_POOL_CHECKLIST,
        "landscape_checklist": CANONICAL_LANDSCAPE_CHECKLIST,
        "standard_reading_keys": STANDARD_READING_KEYS,
    }


# ═══ T4.3 · Route Valuation PDF ══════════════════════════════════════
class RouteValuationBreakdown(BaseModel):
    density: Optional[str] = None
    density_factor: Optional[float] = None
    churn_rate_pct: Optional[float] = None
    churn_factor: Optional[float] = None
    contract_length_avg_months: Optional[float] = None
    contract_factor: Optional[float] = None
    combined_factor: Optional[float] = None
    multiple_min: Optional[float] = None
    multiple_max: Optional[float] = None


class RouteValuationBenchmarks(BaseModel):
    industry_per_customer_low: Optional[float] = None
    industry_per_customer_high: Optional[float] = None
    position: Optional[str] = None


class RouteValuationPdfIn(BaseModel):
    """Accepts the exact result shape returned by
    `POST /api/calculators/route-valuation` so the PDF matches what admin
    sees on-screen. Frontend calls compute first, then submits the same
    result payload to this endpoint.
    """
    active_customers: int
    avg_monthly_revenue_per_customer: float
    total_monthly_revenue: float
    annual_revenue: float
    annual_gross_profit: float
    route_multiple: float
    route_valuation: float
    valuation_per_customer: float
    breakdown: Optional[RouteValuationBreakdown] = None
    benchmarks: Optional[RouteValuationBenchmarks] = None
    # Contextual echoes (optional; admin may want their inputs printed).
    generated_by: Optional[str] = None
    notes: Optional[str] = None


@router.post("/route-valuation-pdf")
async def route_valuation_pdf(
    body: RouteValuationPdfIn,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    r = _get_reportlab()
    buf = BytesIO()
    doc = r["SimpleDocTemplate"](buf, pagesize=r["letter"],
                                    title="Route Valuation")
    story = []
    _tenant_header(story, r, tenant)
    story.append(r["Paragraph"]("<b>Route Valuation</b>", r["styles"]["Title"]))
    story.append(r["Paragraph"](
        f'<font color="#888888" size="9">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
        f'{" · " + body.generated_by if body.generated_by else ""}</font>',
        r["styles"]["Normal"]))
    story.append(r["Spacer"](1, 12))

    # ─── Headline stats ──────────────────────────────────────────────
    headline_rows = [
        ["Active customers",          f"{body.active_customers:,}"],
        ["Total monthly revenue",     f"${body.total_monthly_revenue:,.2f}"],
        ["Annual revenue",            f"${body.annual_revenue:,.2f}"],
        ["Annual gross profit",       f"${body.annual_gross_profit:,.2f}"],
        ["Route multiple",            f"{body.route_multiple}x"],
        ["Route valuation",           f"${body.route_valuation:,.2f}"],
        ["Valuation per customer",    f"${body.valuation_per_customer:,.2f}"],
        ["Avg monthly rev / customer",f"${body.avg_monthly_revenue_per_customer:,.2f}"],
    ]
    tbl = r["Table"](headline_rows, colWidths=[2.6 * r["inch"], 3.4 * r["inch"]])
    tbl.setStyle(r["TableStyle"]([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, 0), (0, -1), r["rlcolors"].HexColor("#F4F4F5")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, r["rlcolors"].HexColor("#E4E4E7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(r["Spacer"](1, 14))

    # ─── Multiple breakdown ──────────────────────────────────────────
    if body.breakdown:
        bd = body.breakdown
        story.append(r["Paragraph"]("<b>Multiple breakdown</b>",
                                     r["styles"]["Heading3"]))
        bd_rows = [
            ["Density",             f"{bd.density or ''}  →  factor {bd.density_factor if bd.density_factor is not None else '—'}"],
            ["Churn rate",          f"{bd.churn_rate_pct if bd.churn_rate_pct is not None else '—'}%  →  factor {bd.churn_factor if bd.churn_factor is not None else '—'}"],
            ["Contract length",     f"{bd.contract_length_avg_months if bd.contract_length_avg_months is not None else '—'} mo  →  factor {bd.contract_factor if bd.contract_factor is not None else '—'}"],
            ["Combined factor",     f"{bd.combined_factor if bd.combined_factor is not None else '—'}  →  multiple lerped between {bd.multiple_min}x and {bd.multiple_max}x"],
        ]
        bt = r["Table"](bd_rows, colWidths=[2.0 * r["inch"], 4.0 * r["inch"]])
        bt.setStyle(r["TableStyle"]([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, r["rlcolors"].HexColor("#E4E4E7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(bt)
        story.append(r["Spacer"](1, 14))

    # ─── Industry benchmarks ─────────────────────────────────────────
    if body.benchmarks:
        b = body.benchmarks
        story.append(r["Paragraph"]("<b>Industry benchmark</b>",
                                     r["styles"]["Heading3"]))
        pos = (b.position or "").replace("_", " ")
        story.append(r["Paragraph"](
            f"Per-customer valuation of "
            f"<b>${body.valuation_per_customer:,.2f}</b> is "
            f"<b>{pos or '—'}</b> the industry band of "
            f"${b.industry_per_customer_low:,.0f} – "
            f"${b.industry_per_customer_high:,.0f}.",
            r["styles"]["Normal"]))
        story.append(r["Spacer"](1, 12))

    if body.notes:
        story.append(r["Paragraph"]("<b>Notes</b>", r["styles"]["Heading3"]))
        story.append(r["Paragraph"](
            body.notes.replace("\n", "<br/>"), r["styles"]["Normal"]))
        story.append(r["Spacer"](1, 12))

    story.append(r["Spacer"](1, 20))
    story.append(r["Paragraph"](
        '<font color="#888888" size="8">Estimates are based on user-supplied '
        'inputs and industry benchmarks. Verify against local market data.</font>',
        r["styles"]["Normal"]))

    doc.build(story)
    pdf = buf.getvalue()
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="route-valuation.pdf"'})
