"""Feb-2026 · Phase 20 P2 tie-in — Daily admin review digest.

Cron (`daily_review_digest`) runs at 08:00 tenant tz. For every
tenant with ``settings.daily_review_digest_enabled != False``
(default enabled):

1. Query ``reviews`` received in the last 24h with
   ``followup_status != "resolved"``.
2. For each, generate a suggested reply via the AI reply generator
   (Phase 20 P2). Store ``suggested_reply_text`` +
   ``suggested_reply_generated_at`` on the review so admin sees the
   same draft when they click through.
3. When ≥1 rows found, send an admin digest email via Resend using
   template `daily_review_digest_email` to the tenant's designated
   notifier (default: the ``resend`` integration owner from the
   Brian transfer step, or fall back to
   ``settings.internal_lead_notifications.email_to``).
4. When zero rows found, no email is sent — a return payload of
   ``{"count": 0, "sent": False}`` is still returned so schedulers
   can log the run.

The AI reply generator itself is a Phase 20 P2 deliverable. For
now this module ships with a placeholder implementation that
returns a template-based reply so the digest can be dry-run tested
end-to-end. Swap the placeholder for the real generator when P2
lands — the signature is stable.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config import db, logger
from utils import new_id, now_iso

_TENANT_TZ = ZoneInfo("America/Phoenix")


def _placeholder_reply(rating: int, author: Optional[str], text: str) -> str:
    """Phase 20 P2 will replace this with the real AI-generated reply.
    Signature intentionally stable so the swap is a one-line change."""
    who = author or "there"
    if rating >= 4:
        return (
            f"Thanks so much for the {rating}★ review, {who}! We're thrilled "
            "you had a great experience — we'll keep the standard high on "
            "your next visit."
        )
    return (
        f"Hi {who}, thanks for taking the time to share this. We're sorry "
        "you didn't get the experience you expected. A team member will "
        "reach out today to make it right — please expect a call."
    )


async def generate_suggested_reply_for_review(review: Dict[str, Any]) -> str:
    """Phase 20 P2 · LIVE — swapped from the placeholder to the real
    LLM-backed generator. Idempotent: once ``suggested_reply_text``
    is set on the row we return it as-is."""
    if review.get("suggested_reply_text"):
        return review["suggested_reply_text"]
    try:
        from routers.reviews_ai_reply import generate_reply
        reply = await generate_reply(
            tenant_id=review.get("tenant_id") or "",
            rating=int(review.get("star_rating") or 0),
            review_text=(review.get("public_comment")
                          or review.get("private_feedback") or ""),
            review_author=review.get("customer_name") or review.get("author_name"),
        )
    except Exception as e:
        logger.warning(f"[review-digest] LLM path failed: {e}")
        reply = _placeholder_reply(
            rating=int(review.get("star_rating") or 0),
            author=review.get("customer_name") or review.get("author_name"),
            text=review.get("public_comment") or review.get("private_feedback") or "",
        )
    try:
        await db.reviews.update_one(
            {"id": review.get("id")},
            {"$set": {"suggested_reply_text": reply,
                        "suggested_reply_generated_at": now_iso()}},
        )
    except Exception as e:
        logger.warning(f"[review-digest] persist reply failed: {e}")
    return reply


def _recipient_for_tenant(tenant: Dict[str, Any]) -> Optional[str]:
    settings = tenant.get("settings") or {}
    integrations = settings.get("integrations") or {}
    resend_owner_id = ((integrations.get("resend") or {}).get("owned_by_user_id"))
    ilnf = (settings.get("internal_lead_notifications") or {})
    return ilnf.get("email_to") or None  # caller resolves owner_id → email


def _digest_html(rows: List[Dict[str, Any]], company: str) -> str:
    parts: List[str] = []
    for r in rows:
        rating = int(r.get("star_rating") or 0)
        stars = "★" * rating + "☆" * (5 - rating)
        name = r.get("customer_name") or r.get("author_name") or "Guest"
        text = (r.get("public_comment") or r.get("private_feedback") or "")[:220]
        reply = r.get("suggested_reply_text") or ""
        parts.append(
            f'<div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px;margin:0 0 12px 0">'
            f'<div style="font-size:14px;font-weight:600">{stars} · {name}</div>'
            f'<div style="font-size:13px;color:#374151;margin:6px 0">{text}</div>'
            f'<div style="font-size:12px;color:#0f766e;background:#f0fdf4;border-radius:6px;padding:8px">'
            f'<strong>Suggested reply:</strong><br>{reply}</div></div>'
        )
    return "".join(parts)


async def send_digest_for_tenant(tenant: Dict[str, Any]) -> Dict[str, Any]:
    tid = tenant.get("id")
    settings = tenant.get("settings") or {}
    if settings.get("daily_review_digest_enabled") is False:
        return {"tenant_id": tid, "count": 0, "sent": False, "reason": "opted_out"}

    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = await db.reviews.find({
        "tenant_id": tid,
        "created_at": {"$gte": since},
        "$or": [{"followup_status": {"$ne": "resolved"}},
                 {"followup_status": {"$exists": False}}],
    }, {"_id": 0}).sort("created_at", -1).to_list(100)

    if not rows:
        return {"tenant_id": tid, "count": 0, "sent": False}

    # Generate suggested replies (idempotent per row).
    for r in rows:
        r["suggested_reply_text"] = await generate_suggested_reply_for_review(r)

    company = (settings.get("business_card") or {}).get("company_name") or tenant.get("name") or "Pool & Landscaping of Vistancia"
    ratings = [int(r.get("star_rating") or 0) for r in rows if r.get("star_rating")]
    avg = round(sum(ratings) / max(1, len(ratings)), 1) if ratings else 0
    low = sum(1 for r in ratings if 1 <= r <= 3)
    subject = f"{len(rows)} new review{'s' if len(rows) != 1 else ''} · avg {avg}★" + (
        f" · {low} need{'s' if low == 1 else ''} reply" if low else ""
    )
    html = (
        f'<html><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;'
        f'background:#f4f6f8;padding:24px 0;margin:0;color:#111827">'
        f'<div style="max-width:640px;margin:0 auto;background:#fff;border-radius:12px;padding:24px">'
        f'<h1 style="margin:0 0 4px 0;font-size:20px">{company} · Reviews digest</h1>'
        f'<div style="color:#6b7280;font-size:13px;margin:0 0 20px 0">{subject}</div>'
        f'{_digest_html(rows, company)}'
        f'</div></body></html>'
    )

    # Resolve recipient — resend integration owner's email > ilnf email.
    integrations = settings.get("integrations") or {}
    resend_owner_id = ((integrations.get("resend") or {}).get("owned_by_user_id"))
    to_email = None
    if resend_owner_id:
        owner = await db.users.find_one(
            {"id": resend_owner_id}, {"_id": 0, "email": 1},
        )
        to_email = (owner or {}).get("email")
    if not to_email:
        to_email = _recipient_for_tenant(tenant)
    if not to_email:
        return {"tenant_id": tid, "count": len(rows), "sent": False,
                 "reason": "no_recipient"}

    from services.email.resend_adapter import send as _resend_send
    result = await _resend_send(
        to=to_email, subject=subject, html=html,
        category="transactional",
        idempotency_key=f"review-digest-{tid}-{datetime.now(_TENANT_TZ).date().isoformat()}",
        tenant_id=tid,
        # Phase K72 · Feb-2026 — daily review digest goes to the
        # tenant's admin/owner. Not customer-facing; bypass the
        # K72 kill switch.
        audience="internal",
    )
    status = result.get("provider_status") or "failed"
    try:
        await db.communications_log.insert_one({
            "id": new_id(), "tenant_id": tid, "channel": "email",
            "to": to_email, "subject": subject,
            "template": "daily_review_digest_email",
            "status": status,
            "provider": result.get("provider") or "resend",
            "provider_response_id": result.get("provider_response_id"),
            "error": result.get("error"),
            "trigger_entity": {"kind": "daily_review_digest",
                                 "id": f"{tid}:{datetime.now(_TENANT_TZ).date().isoformat()}"},
            "created_at": now_iso(),
        })
    except Exception:
        pass
    return {"tenant_id": tid, "count": len(rows), "sent": status == "sent",
             "recipient": to_email, "provider_status": status}


async def run_daily_review_digest() -> Dict[str, Any]:
    """Called from the daily scheduler. Iterates all live tenants,
    calls send_digest_for_tenant for each, and returns an aggregate."""
    results: List[Dict[str, Any]] = []
    async for t in db.tenants.find(
        {"$or": [{"deleted_at": None}, {"deleted_at": {"$exists": False}}]},
        {"_id": 0},
    ):
        try:
            results.append(await send_digest_for_tenant(t))
        except Exception as e:
            logger.warning(f"[review-digest] tenant {t.get('id')} crashed: {e}")
    return {"tenants": len(results), "results": results}
