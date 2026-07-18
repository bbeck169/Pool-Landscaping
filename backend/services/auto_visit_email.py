"""Phase 56.20 — Auto End-of-Visit Customer Email.

Fires an email to the customer when a tech submits a service report.
Pipeline:

    submit_service_report(...)  ← existing endpoint
        └── send_visit_summary_email(tenant, job, service_report)
                ├── idempotency check on outbound_emails
                ├── redact via _redact_report_for_customer (existing)
                ├── render HTML + plain-text bodies
                └── Resend dispatch OR log-only fallback if key missing

All rows land in `db.outbound_emails` regardless of send status so the
audit trail exists even when RESEND_API_KEY is unset. Non-blocking:
any exception here is caught + logged; the submit endpoint still
returns success.
"""
from __future__ import annotations
import os
import re
from typing import Optional

from config import db, logger
from utils import new_id, now_iso


AUTO_EMAIL_KEY = "auto_visit_email"


def _get_settings(tenant: dict) -> dict:
    s = (tenant or {}).get("settings") or {}
    return s.get(AUTO_EMAIL_KEY) or {}


def _is_enabled(tenant: dict) -> bool:
    return bool(_get_settings(tenant).get("enabled", False))


def _google_review_link(tenant: dict) -> str:
    return (_get_settings(tenant).get("google_review_link") or "").strip()


def _footer_text(tenant: dict) -> str:
    return (_get_settings(tenant).get("footer_text") or "").strip()


def _include_reviews_cta(tenant: dict) -> bool:
    return bool(_get_settings(tenant).get("include_reviews_cta", True))


def _visit_date_formatted(sr: dict, job: dict) -> str:
    ts = sr.get("submitted_at") or job.get("service_report_submitted_at") \
        or job.get("scheduled_start") or ""
    return (ts or "")[:10]


def _pool_body_sections(sr: dict) -> list[dict]:
    sections = []
    readings = sr.get("chemical_readings") or {}
    if isinstance(readings, dict) and readings:
        rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{k}</td>"
            f"<td style='padding:4px 0;font-weight:600'>{v}</td></tr>"
            for k, v in readings.items() if v not in (None, "", 0)
        )
        if rows:
            sections.append({
                "title": "Chemical readings",
                "html": f"<table cellspacing='0'>{rows}</table>",
                "text": "\n".join(f"  {k}: {v}" for k, v in readings.items()
                                  if v not in (None, "", 0)),
            })
    added = sr.get("chemicals_added") or []
    if added:
        items = "".join(
            f"<li>{c.get('name', c.get('type', 'Chemical'))} — "
            f"{c.get('amount', '')} {c.get('unit', '')}</li>"
            for c in added if isinstance(c, dict)
        )
        sections.append({
            "title": "Chemicals added",
            "html": f"<ul>{items}</ul>",
            "text": "\n".join(f"  • {c.get('name', 'Chemical')} — {c.get('amount', '')} {c.get('unit', '')}"
                              for c in added if isinstance(c, dict)),
        })
    checklist = sr.get("checklist_completed") or sr.get("checklist_items") or []
    done = [c for c in checklist
            if isinstance(c, dict) and c.get("done")]
    if done:
        items = "".join(f"<li>✓ {c.get('label', 'Item')}</li>" for c in done)
        sections.append({
            "title": "Completed",
            "html": f"<ul>{items}</ul>",
            "text": "\n".join(f"  ✓ {c.get('label', 'Item')}" for c in done),
        })
    algae = (sr.get("observations") or {}).get("visible_algae")
    if algae and algae != "none":
        msg = "Light algae was observed and treated." if algae == "light" \
            else "Heavy algae was observed and treated." if algae == "heavy" \
            else f"Algae ({algae}) was observed and treated."
        sections.append({
            "title": "Algae observation",
            "html": f"<p>{msg}</p>",
            "text": msg,
        })
    return sections


def _landscape_body_sections(sr: dict) -> list[dict]:
    checklist = sr.get("checklist_completed") or sr.get("checklist_items") or []
    done = [c for c in checklist if isinstance(c, dict) and c.get("done")]
    if not done:
        return []
    items = "".join(f"<li>✓ {c.get('label', 'Item')}</li>" for c in done)
    return [{
        "title": "Landscape checklist",
        "html": f"<ul>{items}</ul>",
        "text": "\n".join(f"  ✓ {c.get('label', 'Item')}" for c in done),
    }]


def render_email(tenant: dict, job: dict, sr: dict, customer: dict) -> dict:
    """Return {subject, html, text}. `sr` must already be customer-redacted."""
    company = tenant.get("name") or "Pool & Landscaping"
    logo = tenant.get("logo_url") or ""
    kind = (sr.get("kind") or job.get("service_type") or "pool").lower()
    is_landscape = "landscape" in kind or "landscap" in kind
    visit_date = _visit_date_formatted(sr, job)
    subject = f"Your {company} service visit — {visit_date}"

    if is_landscape:
        sections = _landscape_body_sections(sr)
    else:
        sections = _pool_body_sections(sr)

    customer_notes = (sr.get("customer_notes") or "").strip()
    # Safety net: even though _redact strips internal_notes at data
    # source, we regex-scrub any accidental "internal_notes:" leak here.
    customer_notes = re.sub(r"internal[_ ]notes?\s*:.*",
                              "", customer_notes, flags=re.IGNORECASE)

    photos = [p for p in (sr.get("photos") or []) if isinstance(p, dict)]
    safe_photos = [p for p in photos
                   if not any(str(t).lower() in ("internal", "issue", "private")
                              for t in (p.get("tags") or []))]

    review_link = _google_review_link(tenant)
    include_reviews = _include_reviews_cta(tenant) and bool(review_link)
    custom_footer = _footer_text(tenant)
    app_url = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
    portal_link = f"{app_url}/portal/service-reports" if app_url else "/portal/service-reports"

    # ─── HTML ───────────────────────────────────────────────────────
    header_html = ""
    if logo:
        header_html += f'<img src="{logo}" alt="{company}" style="max-height:48px;margin-bottom:8px"/>'
    header_html += f'<h1 style="margin:0 0 4px;font-family:system-ui;font-size:20px">{company}</h1>'
    header_html += '<div style="color:#666;font-size:14px">Service visit summary</div>'

    info_rows = [
        ("Date", visit_date),
        ("Technician", sr.get("tech_name") or ""),
        ("Address", job.get("address") or ""),
    ]
    info_html = "".join(
        f"<tr><td style='padding:2px 12px 2px 0;color:#555'>{k}</td>"
        f"<td style='padding:2px 0;font-weight:600'>{v}</td></tr>"
        for k, v in info_rows if v
    )

    sections_html = "".join(
        f'<h3 style="margin:16px 0 4px;font-family:system-ui;font-size:15px">{s["title"]}</h3>{s["html"]}'
        for s in sections
    )
    notes_html = (f'<h3 style="margin:16px 0 4px;font-family:system-ui;font-size:15px">Notes from your tech</h3>'
                  f'<p style="white-space:pre-line;background:#f6f6f6;padding:12px;border-radius:6px">{customer_notes}</p>'
                  if customer_notes else "")
    photos_html = ""
    if safe_photos:
        photos_html = '<h3 style="margin:16px 0 4px;font-family:system-ui;font-size:15px">Photos</h3><div>'
        for p in safe_photos[:8]:
            u = p.get("url") or p.get("uri") or ""
            if u:
                photos_html += f'<img src="{u}" alt="Service photo" style="max-width:180px;margin:4px 4px 0 0;border-radius:4px"/>'
        photos_html += "</div>"

    cta_html = ""
    if include_reviews:
        cta_html += (f'<p><a href="{review_link}" style="background:#2563eb;color:#fff;text-decoration:none;'
                     f'padding:10px 16px;border-radius:6px;display:inline-block">Leave us a review</a></p>')
    cta_html += (f'<p><a href="{portal_link}" style="color:#2563eb">View full history in your portal →</a></p>')

    footer_html = ('<p style="color:#888;font-size:12px;margin-top:24px">'
                   'This is an automatic recap of the customer-facing portion of your visit. '
                   'Internal service notes are not included.')
    if custom_footer:
        footer_html += f' {custom_footer}'
    footer_html += (f' <br/><a href="{app_url}/portal/unsubscribe" style="color:#888">Unsubscribe</a>'
                    if app_url else '')
    footer_html += '</p>'

    html = (f'<div style="font-family:system-ui;max-width:600px;padding:20px">'
            f'{header_html}'
            f'<table style="margin-top:12px" cellspacing="0">{info_html}</table>'
            f'{sections_html}{notes_html}{photos_html}{cta_html}{footer_html}'
            f'</div>')

    # ─── Text ───────────────────────────────────────────────────────
    text_lines = [
        company, "Service visit summary", "",
        f"Date: {visit_date}",
        f"Tech: {sr.get('tech_name') or ''}",
        f"Address: {job.get('address') or ''}",
        "",
    ]
    for s in sections:
        text_lines.append(s["title"] + ":")
        text_lines.append(s["text"])
        text_lines.append("")
    if customer_notes:
        text_lines += ["Notes from your tech:", customer_notes, ""]
    if include_reviews:
        text_lines.append(f"Leave a review: {review_link}")
    text_lines.append(f"Portal: {portal_link}")
    if custom_footer:
        text_lines += ["", custom_footer]
    text_lines.append("")
    text_lines.append("Internal service notes are not included in this summary.")

    return {"subject": subject, "html": html, "text": "\n".join(text_lines),
            "kind": ("landscape" if is_landscape else "pool")}


async def send_visit_summary_email(tenant: dict, job: dict, sr: dict) -> Optional[dict]:
    """Fire the visit-summary email. Non-blocking — any error is logged
    and swallowed so a failed email never breaks the submit flow.

    Idempotent: skips send if outbound_emails already has a
    (kind=visit_summary, service_report_id, customer_id) row.
    """
    if not _is_enabled(tenant):
        return None
    try:
        customer_id = job.get("customer_id")
        if not customer_id:
            return None
        customer = await db.customers.find_one(
            {"id": customer_id, "tenant_id": tenant["id"]}, {"_id": 0}
        )
        if not customer:
            return None
        to_email = (customer.get("email") or "").strip()
        if not to_email:
            return None
        sr_id = sr.get("id")
        # Idempotency check.
        dupe = await db.outbound_emails.find_one({
            "kind": "visit_summary",
            "service_report_id": sr_id,
            "customer_id": customer_id,
        }, {"_id": 0, "id": 1, "status": 1})
        if dupe:
            return {"skipped": "idempotent", "existing": dupe}

        # Redact via the same helper used by the customer portal.
        from routers.service_reports import _redact_report_for_customer
        safe_sr = _redact_report_for_customer(dict(sr))

        rendered = render_email(tenant, job, safe_sr, customer)
        row = {
            "id": new_id(),
            "kind": "visit_summary",
            "tenant_id": tenant["id"],
            "customer_id": customer_id,
            "service_report_id": sr_id,
            "job_id": job.get("id"),
            "to": to_email,
            "subject": rendered["subject"],
            "html": rendered["html"],
            "text": rendered["text"],
            "report_kind": rendered["kind"],
            "created_at": now_iso(),
            "status": "pending",
        }
        resend_key = os.environ.get("RESEND_API_KEY")
        if not resend_key:
            row["status"] = "not_sent_missing_key"
            await db.outbound_emails.insert_one(row)
            return row
        try:
            import resend  # type: ignore
            resend.api_key = resend_key
            resp = resend.Emails.send({
                "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
                "to": [to_email],
                "subject": rendered["subject"],
                "html": rendered["html"],
                "text": rendered["text"],
            })
            row["status"] = "sent"
            row["resend_id"] = (resp or {}).get("id") if isinstance(resp, dict) else None
            await db.outbound_emails.insert_one(row)
            return row
        except Exception as e:
            row["status"] = "failed"
            row["error"] = str(e)[:200]
            await db.outbound_emails.insert_one(row)
            logger.warning(f"visit-summary email send failed: {type(e).__name__}: {str(e)[:120]}")
            return row
    except Exception as e:
        logger.warning(f"send_visit_summary_email top-level error: {type(e).__name__}: {str(e)[:120]}")
        return None
