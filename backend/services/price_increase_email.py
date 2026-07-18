"""Ship 1 · T3.2 — Recommend price increase email pipeline.

Renders + sends (or drafts) a price-increase recommendation email to a
customer flagged by the Cost per Pool tab. Follows the same
outbound_emails audit pattern as `services/auto_visit_email.py`:

    * status="draft"                — admin previewed and saved
    * status="not_sent_missing_key" — send attempted but RESEND_API_KEY absent
    * status="sent"                 — Resend accepted (has resend_id)
    * status="failed"               — Resend errored (has error snippet)

Idempotency key differs from visit_summary: keyed on
    {tenant_id, customer_id, module=price_increase, price_snapshot}
where price_snapshot = f"{current_price}->{recommended_price}". A new
recommendation for the same customer at a different current_price is
a legitimate re-fire, not a duplicate.
"""
from __future__ import annotations
import os
from typing import Optional

from config import db, logger
from utils import new_id, now_iso


MODULE = "price_increase"
KIND = "price_increase_recommendation"


def _price_snapshot(current: float, recommended: float) -> str:
    return f"{round(float(current or 0), 2)}->{round(float(recommended or 0), 2)}"


def _idempotency_key(tenant_id: str, customer_id: str, snapshot: str) -> str:
    return f"{tenant_id}:{customer_id}:{MODULE}:{snapshot}"


def render_email(
    tenant: dict,
    customer: dict,
    *,
    current_price: float,
    recommended_price: float,
    current_margin_pct: Optional[float],
    effective_date: str,
    reason: Optional[str] = None,
) -> dict:
    company = (tenant or {}).get("name") or "Pool & Landscaping"
    logo = (tenant or {}).get("logo_url") or ""
    first_name = ((customer or {}).get("name") or "there").split(" ")[0]
    delta = round(float(recommended_price) - float(current_price), 2)
    delta_pct = (delta / float(current_price) * 100) if current_price else 0.0
    reason_line = (reason or "").strip()

    subject = f"An update to your {company} service pricing"

    header_html = ""
    if logo:
        header_html = f'<img src="{logo}" alt="{company}" style="max-height:56px;margin-bottom:8px" />'
    header_html += f'<h2 style="margin:0;color:#111;font-family:system-ui">{company}</h2>'

    reason_html = ""
    if reason_line:
        reason_html = (
            f'<p style="margin:10px 0 0;color:#374151">'
            f'{reason_line}'
            f'</p>'
        )

    html = (
        f'<div style="font-family:system-ui;max-width:600px;padding:20px;color:#111">'
        f'{header_html}'
        f'<p>Hi {first_name},</p>'
        f'<p>Thank you for being a valued customer. We want to give you plenty '
        f'of notice about a small adjustment to your service pricing, effective '
        f'<b>{effective_date}</b>.</p>'
        f'<table cellspacing="0" style="margin:12px 0;border-collapse:collapse">'
        f'<tr><td style="padding:6px 16px 6px 0;color:#555">Current price per visit</td>'
        f'<td style="padding:6px 0;font-weight:600">${current_price:.2f}</td></tr>'
        f'<tr><td style="padding:6px 16px 6px 0;color:#555">New price per visit</td>'
        f'<td style="padding:6px 0;font-weight:700;color:#0f766e">${recommended_price:.2f}</td></tr>'
        f'<tr><td style="padding:6px 16px 6px 0;color:#555">Change</td>'
        f'<td style="padding:6px 0">${delta:+.2f} ({delta_pct:+.1f}%)</td></tr>'
        f'<tr><td style="padding:6px 16px 6px 0;color:#555">Effective date</td>'
        f'<td style="padding:6px 0">{effective_date}</td></tr>'
        f'</table>'
        f'{reason_html}'
        f'<p>Rising costs of chemicals, fuel, and equipment have made this '
        f'adjustment necessary so we can keep providing you with reliable, '
        f'high-quality service. Your service schedule and technician will not '
        f'change.</p>'
        f'<p>If you have any questions, just reply to this email — we\'re happy '
        f'to walk through it with you.</p>'
        f'<p style="margin-top:24px">Thanks for trusting us with your pool.<br/>'
        f'<b>The {company} team</b></p>'
        f'</div>'
    )

    text_lines = [
        f"Hi {first_name},",
        "",
        f"Thank you for being a valued customer. We want to give you plenty of "
        f"notice about a small adjustment to your service pricing, effective "
        f"{effective_date}.",
        "",
        f"  Current price per visit: ${current_price:.2f}",
        f"  New price per visit:     ${recommended_price:.2f}",
        f"  Change:                  ${delta:+.2f} ({delta_pct:+.1f}%)",
        f"  Effective date:          {effective_date}",
        "",
    ]
    if reason_line:
        text_lines += [reason_line, ""]
    text_lines += [
        "Rising costs of chemicals, fuel, and equipment have made this "
        "adjustment necessary so we can keep providing you with reliable, "
        "high-quality service. Your service schedule and technician will not "
        "change.",
        "",
        "If you have any questions, just reply to this email — we're happy to "
        "walk through it with you.",
        "",
        f"Thanks for trusting us with your pool.",
        f"The {company} team",
    ]

    return {"subject": subject, "html": html, "text": "\n".join(text_lines)}


async def find_existing(tenant_id: str, customer_id: str,
                          current_price: float, recommended_price: float) -> Optional[dict]:
    key = _idempotency_key(tenant_id, customer_id,
                           _price_snapshot(current_price, recommended_price))
    return await db.outbound_emails.find_one(
        {"kind": KIND, "idempotency_key": key}, {"_id": 0}
    )


async def save_or_send(
    tenant: dict,
    customer: dict,
    *,
    current_price: float,
    recommended_price: float,
    current_margin_pct: Optional[float],
    effective_date: str,
    reason: Optional[str],
    action: str,  # "draft" | "send"
) -> dict:
    """Idempotent: repeated calls with the same price_snapshot return the
    existing row. `action=send` on an existing draft flips it to sent
    (or failed / not_sent_missing_key) but keeps the same row id."""
    snapshot = _price_snapshot(current_price, recommended_price)
    key = _idempotency_key(tenant["id"], customer["id"], snapshot)
    existing = await db.outbound_emails.find_one(
        {"kind": KIND, "idempotency_key": key}, {"_id": 0}
    )
    rendered = render_email(
        tenant, customer,
        current_price=float(current_price),
        recommended_price=float(recommended_price),
        current_margin_pct=current_margin_pct,
        effective_date=effective_date,
        reason=reason,
    )
    to_email = ((customer or {}).get("email") or "").strip()
    row_id = (existing or {}).get("id") or new_id()
    row = {
        "id": row_id,
        "kind": KIND,
        "module": MODULE,
        "tenant_id": tenant["id"],
        "customer_id": customer["id"],
        "to": to_email,
        "subject": rendered["subject"],
        "html": rendered["html"],
        "text": rendered["text"],
        "price_snapshot": snapshot,
        "current_price": round(float(current_price), 2),
        "recommended_price": round(float(recommended_price), 2),
        "current_margin_pct": current_margin_pct,
        "effective_date": effective_date,
        "reason": (reason or None),
        "idempotency_key": key,
        "updated_at": now_iso(),
    }
    if not existing:
        row["created_at"] = now_iso()

    if action == "draft":
        row["status"] = "draft"
        await db.outbound_emails.update_one(
            {"kind": KIND, "idempotency_key": key},
            {"$set": row},
            upsert=True,
        )
        return row

    # action == "send"
    if not to_email:
        row["status"] = "failed"
        row["error"] = "customer has no email address on file"
        await db.outbound_emails.update_one(
            {"kind": KIND, "idempotency_key": key},
            {"$set": row},
            upsert=True,
        )
        return row

    resend_key = os.environ.get("RESEND_API_KEY")
    if not resend_key:
        row["status"] = "not_sent_missing_key"
        await db.outbound_emails.update_one(
            {"kind": KIND, "idempotency_key": key},
            {"$set": row},
            upsert=True,
        )
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
        await db.outbound_emails.update_one(
            {"kind": KIND, "idempotency_key": key},
            {"$set": row},
            upsert=True,
        )
        return row
    except Exception as e:
        row["status"] = "failed"
        row["error"] = str(e)[:200]
        await db.outbound_emails.update_one(
            {"kind": KIND, "idempotency_key": key},
            {"$set": row},
            upsert=True,
        )
        logger.warning(
            f"price-increase email send failed: {type(e).__name__}: {str(e)[:120]}"
        )
        return row
