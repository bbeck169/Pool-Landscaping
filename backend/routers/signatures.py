"""Phase 15A — Digital signatures for quotes/estimates."""
import hashlib
import json
import secrets
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from pydantic import BaseModel

from config import db, logger, APP_PUBLIC_URL, RESEND_API_KEY, EMAIL_FROM
from utils import now_iso, new_id, require_admin, notify_customer
from routers.tenants import get_current_tenant

router = APIRouter()


def _mk_token() -> str:
    return secrets.token_urlsafe(24)


def _sign_url(token: str) -> str:
    base = (APP_PUBLIC_URL or "").rstrip("/")
    return f"{base}/portal/sign/{token}"


def _hash_doc(doc: dict) -> str:
    payload = {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "customer_id": doc.get("customer_id"),
        "line_items": doc.get("line_items", []),
        "subtotal": doc.get("subtotal"),
        "tax": doc.get("tax"),
        "total": doc.get("total"),
        "terms": doc.get("terms", ""),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def _send_sign_email(customer: dict, url: str, doc_title: str, message: str = "",
                             *, tenant_id: Optional[str] = None) -> bool:
    """Feb-2026 · Multi-Contact Phase 2 · fan-out (manual).

    Admin-triggered signature-request email — bypasses the
    customer-level mute (admin's explicit action). Per-entry
    opt-outs still respected via the helper."""
    if not RESEND_API_KEY:
        return False
    from services.customer_multi_contact import active_email_recipients
    recipients = active_email_recipients(customer, context="manual")
    if not recipients:
        return False
    sent_any = False
    for addr in recipients:
        try:
            import resend
            resend.api_key = RESEND_API_KEY
            resend.Emails.send({
                "from": EMAIL_FROM or "onboarding@resend.dev",
                "to": [addr],
                "subject": f"Please sign: {doc_title}",
                "html": (
                    f"<p>Hi {customer.get('name','')},</p>"
                    + (f"<p>{message}</p>" if message else "")
                    + f"<p><a href='{url}' style='background:#0284C7;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;'>Review &amp; sign</a></p>"
                ),
            })
            sent_any = True
        except Exception as e:
            logger.warning(f"Signature email failed for {addr}: {e}")
    return sent_any


class RequestSignatureIn(BaseModel):
    signer_email: Optional[str] = None
    message: Optional[str] = ""


@router.post("/quotes/{qid}/request-signature")
async def request_signature(qid: str, body: Optional[RequestSignatureIn] = None,
                            admin: dict = Depends(require_admin),
                            tenant: dict = Depends(get_current_tenant)):
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Quote not found")
    cust = await db.customers.find_one(
        {"id": doc.get("customer_id"), "tenant_id": tenant["id"]}, {"_id": 0}
    ) or {}
    signer_email = (body.signer_email if body and body.signer_email else cust.get("email") or "").strip().lower()
    if not signer_email:
        raise HTTPException(400, "No signer email on file")

    token = _mk_token()
    payload_hash = _hash_doc(doc)
    sig_req = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "token": token,
        "doc_type": doc.get("doc_type", "quote"),
        "doc_id": qid,
        "customer_id": doc.get("customer_id"),
        "signer_email": signer_email,
        "signer_name": None,
        "signature_svg": None,
        "signed_at": None,
        "ip_address": None,
        "user_agent": None,
        "hash": payload_hash,
        "created_at": now_iso(),
        "message": (body.message if body else "") or "",
    }
    await db.signatures.insert_one(sig_req)
    sig_req.pop("_id", None)
    url = _sign_url(token)
    emailed = await _send_sign_email(cust, url, doc.get("title", "Estimate"), (body.message if body else "") or "", tenant_id=tenant["id"])
    await db.quotes.update_one(
        {"id": qid, "tenant_id": tenant["id"]},
        {"$set": {"signature_requested_at": now_iso(), "signature_token": token}},
    )
    return {"ok": True, "url": url, "token": token, "emailed": emailed}


# ─── Public: fetch doc payload for signing ────────────────────────────────
@router.get("/public/sign/{token}")
async def public_get_sign_doc(token: str):
    sig = await db.signatures.find_one({"token": token}, {"_id": 0})
    if not sig:
        raise HTTPException(404, "Signature request not found")
    doc = await db.quotes.find_one({"id": sig["doc_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    # Return a limited safe view (no internal fields).
    return {
        "signed": bool(sig.get("signed_at")),
        "signed_at": sig.get("signed_at"),
        "signer_name": sig.get("signer_name"),
        "message": sig.get("message", ""),
        "doc": {
            "id": doc.get("id"),
            "title": doc.get("title"),
            "doc_type": doc.get("doc_type"),
            "customer_name": doc.get("customer_name"),
            "line_items": doc.get("line_items", []),
            "subtotal": doc.get("subtotal"),
            "tax": doc.get("tax"),
            "tax_rate": doc.get("tax_rate"),
            "total": doc.get("total"),
            "notes": doc.get("notes", ""),
            "terms": doc.get("terms", ""),
        },
    }


class SubmitSignatureIn(BaseModel):
    signer_name: str
    signature_svg: str  # base64 PNG data URL


@router.post("/public/sign/{token}/submit")
async def public_submit_signature(token: str, body: SubmitSignatureIn, request: Request):
    sig = await db.signatures.find_one({"token": token}, {"_id": 0})
    if not sig:
        raise HTTPException(404, "Signature request not found")
    if sig.get("signed_at"):
        raise HTTPException(400, "Already signed")
    if not (body.signer_name or "").strip():
        raise HTTPException(400, "Signer name required")
    if not (body.signature_svg or "").strip():
        raise HTTPException(400, "Signature required")

    doc = await db.quotes.find_one({"id": sig["doc_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")

    client_ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                 or (request.client.host if request.client else "unknown"))
    ua = request.headers.get("user-agent", "unknown")

    now = now_iso()
    signed_hash = _hash_doc(doc)
    await db.signatures.update_one(
        {"id": sig["id"]},
        {"$set": {
            "signer_name": body.signer_name.strip(),
            "signature_svg": body.signature_svg,
            "signed_at": now,
            "ip_address": client_ip,
            "user_agent": ua,
            "hash": signed_hash,
        }},
    )
    await db.quotes.update_one(
        {"id": sig["doc_id"]},
        {"$set": {
            "status": "signed",
            "signed_at": now,
            "signer_name": body.signer_name.strip(),
            "signature_id": sig["id"],
        }},
    )
    try:
        await db.activity_log.insert_one({
            "id": new_id(),
            "tenant_id": sig.get("tenant_id"),
            "kind": "signature_submitted",
            "doc_id": sig["doc_id"],
            "signer_name": body.signer_name.strip(),
            "ip_address": client_ip,
            "created_at": now,
        })
    except Exception:
        pass
    if doc.get("customer_id"):
        await notify_customer(doc["customer_id"], "Document signed",
                              f"'{doc.get('title','')}' has been signed. Thanks!", job_id=None)
    return {"ok": True, "signed_at": now}


@router.get("/quotes/{qid}/signature")
async def admin_get_signature(qid: str,
                              admin: dict = Depends(require_admin),
                              tenant: dict = Depends(get_current_tenant)):
    sig = await db.signatures.find_one(
        {"doc_id": qid, "tenant_id": tenant["id"], "signed_at": {"$ne": None}},
        {"_id": 0},
    )
    if not sig:
        return {"signed": False}
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    current_hash = _hash_doc(doc) if doc else None
    return {
        "signed": True,
        "signer_name": sig.get("signer_name"),
        "signed_at": sig.get("signed_at"),
        "ip_address": sig.get("ip_address"),
        "user_agent": sig.get("user_agent"),
        "hash": sig.get("hash"),
        "hash_matches": current_hash == sig.get("hash"),
        "signature_svg": sig.get("signature_svg"),
        "sign_url": _sign_url(sig["token"]) if sig.get("token") else None,
    }


# ─── Signed PDF ─────────────────────────────────────────────────────────────
def _build_signed_pdf(doc: dict, sig: dict) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors as rlcolors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    import base64

    label = "Invoice" if doc.get("doc_type") == "invoice" else "Estimate"
    buf = BytesIO()
    pdf_doc = SimpleDocTemplate(buf, pagesize=letter, title=f"Signed {label} {doc.get('id','')[:8]}")
    styles = getSampleStyleSheet()
    story = []
    # Watermark line at top
    when = (sig.get("signed_at") or "")[:19]
    story.append(Paragraph(f"<font color='#22C55E'><b>SIGNED — {when}</b></font>", styles["Title"]))
    story.append(Paragraph("Pool &amp; Landscaping of Vistancia", styles["Normal"]))
    story.append(Spacer(1, 12))

    header_rows = [
        [f"{label} #", (doc.get("id") or "")[:8].upper()],
        ["Title", doc.get("title", "")],
        ["Customer", doc.get("customer_name", "")],
        ["Status", "Signed"],
        ["Total", f"${float(doc.get('total') or 0):,.2f}"],
    ]
    t = Table(header_rows, colWidths=[1.4 * inch, 5.0 * inch])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 10),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, 0), (0, -1), rlcolors.HexColor("#F4F4F5")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E4E4E7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))

    # Line items
    line_rows = [["Description", "Qty", "Unit", "Total"]]
    for li in (doc.get("line_items") or []):
        qty = float(li.get("quantity") or 0)
        unit = float(li.get("unit_price") or 0)
        line_rows.append([li.get("description", ""), f"{qty:g}", f"${unit:,.2f}", f"${qty * unit:,.2f}"])
    lt = Table(line_rows, colWidths=[3.6 * inch, 0.8 * inch, 1.1 * inch, 1.1 * inch])
    lt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("BACKGROUND", (0, 0), (-1, 0), rlcolors.HexColor("#F4F4F5")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, rlcolors.HexColor("#E4E4E7")),
    ]))
    story.append(lt)
    story.append(Spacer(1, 16))

    # Signature block
    story.append(Paragraph("<b>Signature</b>", styles["Heading3"]))
    story.append(Paragraph(f"Signed by: <b>{sig.get('signer_name','')}</b>", styles["Normal"]))
    # Embed the drawn signature image if we can decode the data URL.
    svg = sig.get("signature_svg") or ""
    if svg.startswith("data:image/"):
        try:
            header, b64 = svg.split(",", 1)
            img_bytes = base64.b64decode(b64)
            img_buf = BytesIO(img_bytes)
            story.append(Image(img_buf, width=3.0 * inch, height=1.0 * inch))
        except Exception as e:
            logger.warning(f"signed pdf image embed failed: {e}")
    story.append(Spacer(1, 8))
    audit_line = (
        f"Signed by <b>{sig.get('signer_name','')}</b> at <b>{sig.get('signed_at','')}</b> "
        f"from IP <b>{sig.get('ip_address','')}</b>. "
        f"Document hash: <font face='Courier' size='8'>{sig.get('hash','')}</font>."
    )
    story.append(Paragraph(audit_line, styles["Normal"]))

    pdf_doc.build(story)
    data = buf.getvalue()
    buf.close()
    return data


@router.get("/public/sign/{token}/pdf")
async def public_signed_pdf(token: str):
    sig = await db.signatures.find_one({"token": token}, {"_id": 0})
    if not sig or not sig.get("signed_at"):
        raise HTTPException(404, "Signed document not found")
    doc = await db.quotes.find_one({"id": sig["doc_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    pdf = _build_signed_pdf(doc, sig)
    filename = f"signed-{doc.get('doc_type','doc')}-{doc.get('id','')[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/quotes/{qid}/signed-pdf")
async def admin_signed_pdf(qid: str,
                           admin: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    sig = await db.signatures.find_one(
        {"doc_id": qid, "tenant_id": tenant["id"], "signed_at": {"$ne": None}},
        {"_id": 0},
    )
    if not sig:
        raise HTTPException(404, "Not signed yet")
    doc = await db.quotes.find_one({"id": qid, "tenant_id": tenant["id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Document not found")
    pdf = _build_signed_pdf(doc, sig)
    filename = f"signed-{doc.get('doc_type','doc')}-{qid[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
