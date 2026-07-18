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
]
CANONICAL_LANDSCAPE_CHECKLIST = [
    "Mow lawn to spec height", "Edge walkways & beds",
    "Blow off hardscape", "Trim shrubs & hedges",
    "Weed all beds & pavers", "Inspect irrigation & report leaks",
    "Fertilize / spot-treat if scheduled", "Pick up debris & haul away",
    "Check pest / disease pressure", "Verify gates locked & site walk-through",
]
STANDARD_READING_KEYS = [
    "pH", "Free Cl", "Total Cl", "Alkalinity", "Calcium Hardness",
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
    rows: List[Dict[str, Any]] = []
    async for r in db.document_templates.find(
        {"tenant_id": tenant["id"]}, {"_id": 0}
    ).sort("updated_at", -1):
        rows.append(r)
    return {"count": len(rows), "rows": rows}


@router.delete("/checklist-templates/{tid}")
async def delete_template(tid: str,
                          user: dict = Depends(_require_admin),
                          tenant: dict = Depends(get_current_tenant)):
    r = await db.document_templates.delete_one(
        {"id": tid, "tenant_id": tenant["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "Template not found")
    return {"deleted": tid}


@router.get("/checklist-template/{tid}/pdf")
async def template_pdf(tid: str,
                       user: dict = Depends(_require_admin),
                       tenant: dict = Depends(get_current_tenant)):
    t = await db.document_templates.find_one(
        {"id": tid, "tenant_id": tenant["id"]}, {"_id": 0})
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
