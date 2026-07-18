"""Ship 3 · Item B — Recommendations queue (stale price-increase drafts).

Admin dashboard widget backend. Surfaces `price_increase_recommendation`
outbound_emails with `status: "draft"` older than N days so admins can
clear the "I saved a draft and forgot" pile.

Endpoints (all admin + super_admin only):
    GET  /api/recommendations-queue?older_than_days=7&kind=price_increase_recommendation
    POST /api/recommendations-queue/{email_id}/send
    POST /api/recommendations-queue/{email_id}/discard

Send flips the draft to sent / failed / not_sent_missing_key via the
same pipeline as services/price_increase_email.py. Discard marks the
row status=discarded + adds discarded_by + discarded_at for the audit
trail (row is preserved for compliance).
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from utils import get_current_user, now_iso
from routers.tenants import get_current_tenant


router = APIRouter(tags=["recommendations-queue"])


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    if (user or {}).get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    return user


_ALLOWED_KINDS = {"price_increase_recommendation"}


@router.get("/recommendations-queue")
async def list_recommendations_queue(
    older_than_days: int = Query(7, ge=0, le=365),
    kind: str = Query("price_increase_recommendation"),
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if kind not in _ALLOWED_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(_ALLOWED_KINDS)}")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    rows: list[dict] = []
    async for row in db.outbound_emails.find({
        "tenant_id": tenant["id"],
        "kind": kind,
        "status": "draft",
        "created_at": {"$lt": cutoff},
    }, {"_id": 0}).sort("created_at", 1):
        # Age calculation (days).
        try:
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            age_days = round((datetime.now(timezone.utc) - created).total_seconds() / 86400, 1)
        except Exception:
            age_days = None
        # Look up customer name for the widget.
        cust = await db.customers.find_one(
            {"id": row.get("customer_id"), "tenant_id": tenant["id"]},
            {"_id": 0, "name": 1, "email": 1})
        rows.append({
            "id": row["id"],
            "customer_id": row.get("customer_id"),
            "customer_name": (cust or {}).get("name") or "",
            "customer_email": row.get("to") or (cust or {}).get("email") or "",
            "current_price": row.get("current_price"),
            "recommended_price": row.get("recommended_price"),
            "current_margin_pct": row.get("current_margin_pct"),
            "gap_dollars": round(float(row.get("recommended_price") or 0)
                                  - float(row.get("current_price") or 0), 2),
            "gap_pct": (round((float(row["recommended_price"]) - float(row["current_price"]))
                              / max(1e-6, float(row["current_price"])) * 100, 1)
                        if row.get("current_price") else None),
            "effective_date": row.get("effective_date"),
            "reason": row.get("reason"),
            "subject": row.get("subject"),
            "age_days": age_days,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        })
    return {"count": len(rows), "rows": rows,
            "cutoff_days": older_than_days, "kind": kind}


@router.post("/recommendations-queue/{email_id}/send")
async def send_from_queue(
    email_id: str,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.outbound_emails.find_one(
        {"id": email_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "Draft not found")
    if row.get("status") != "draft":
        raise HTTPException(409, f"Row is not a draft (status: {row.get('status')})")

    to_email = (row.get("to") or "").strip()
    if not to_email:
        upd = {"status": "failed", "error": "no customer email on file",
               "updated_at": now_iso(), "sent_by_user_id": user["id"]}
        await db.outbound_emails.update_one({"id": email_id}, {"$set": upd})
        return {"id": email_id, **upd}

    resend_key = os.environ.get("RESEND_API_KEY")
    if not resend_key:
        upd = {"status": "not_sent_missing_key", "updated_at": now_iso(),
               "sent_by_user_id": user["id"]}
        await db.outbound_emails.update_one({"id": email_id}, {"$set": upd})
        return {"id": email_id, **upd}

    try:
        import resend  # type: ignore
        resend.api_key = resend_key
        resp = resend.Emails.send({
            "from": os.environ.get("RESEND_FROM", "onboarding@resend.dev"),
            "to": [to_email],
            "subject": row["subject"],
            "html": row["html"],
            "text": row["text"],
        })
        upd = {
            "status": "sent",
            "resend_id": (resp or {}).get("id") if isinstance(resp, dict) else None,
            "sent_by_user_id": user["id"],
            "updated_at": now_iso(),
        }
    except Exception as e:
        upd = {"status": "failed", "error": str(e)[:200],
               "sent_by_user_id": user["id"], "updated_at": now_iso()}
        logger.warning(f"queue-send failed: {type(e).__name__}: {str(e)[:120]}")

    await db.outbound_emails.update_one({"id": email_id}, {"$set": upd})
    return {"id": email_id, **upd}


@router.post("/recommendations-queue/{email_id}/discard")
async def discard_from_queue(
    email_id: str,
    user: dict = Depends(_require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    r = await db.outbound_emails.find_one(
        {"id": email_id, "tenant_id": tenant["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Draft not found")
    if r.get("status") not in ("draft",):
        raise HTTPException(409, f"Only drafts can be discarded (status: {r.get('status')})")
    upd = {
        "status": "discarded",
        "discarded_by_user_id": user["id"],
        "discarded_by_name": user.get("name") or user.get("email"),
        "discarded_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.outbound_emails.update_one({"id": email_id}, {"$set": upd})
    return {"id": email_id, **upd}
