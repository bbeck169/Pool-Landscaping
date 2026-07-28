"""Phase 19 · Customer Referral Program.

- 50% off 1 month of service reward, admin-approved, customer-only (no tech
  attribution, no tech surface). Multi-channel share (copy / email / SMS /
  social / QR). Public tracker + apply endpoints for the signup flow.
- Every response is tenant-scoped. Tech role (`role == "technician"`) is
  blocked with 403 on the entire authenticated surface — only the two public
  endpoints (/track, /apply) are exempt.
- No silent mocking: SMS invites route through the RingCentral adapter
  (services.sms.rc_adapter). When RC is unconfigured the adapter fails
  closed with ``provider="mock"`` and we surface ``status="pending_sms"``.
"""
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import db, logger, APP_PUBLIC_URL
from utils import now_iso, new_id, get_current_user, require_admin
from routers.tenants import get_current_tenant

router = APIRouter()

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LEN = 8
_REWARD_PCT = 50


def _require_customer(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "customer":
        raise HTTPException(403, "Referral hub is customer-only")
    return user


def _reject_tech(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") == "technician":
        raise HTTPException(403, "Referral program not available for techs")
    return user


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


async def _ensure_indexes():
    try:
        await db.referral_codes.create_index("code", unique=True)
        await db.referral_codes.create_index(
            [("tenant_id", 1), ("customer_id", 1)], unique=True
        )
        await db.referral_conversions.create_index([("tenant_id", 1), ("status", 1)])
        await db.service_credits.create_index(
            [("tenant_id", 1), ("customer_id", 1), ("months_remaining", 1)]
        )
    except Exception as e:
        logger.warning(f"referral index create skipped: {e}")


async def _get_or_create_code(tenant_id: str, customer_id: str) -> dict:
    await _ensure_indexes()
    existing = await db.referral_codes.find_one(
        {"tenant_id": tenant_id, "customer_id": customer_id}, {"_id": 0}
    )
    if existing:
        return existing
    # Try until we get a unique code.
    for _ in range(8):
        code = _gen_code()
        if not await db.referral_codes.find_one({"code": code}):
            break
    else:
        raise HTTPException(500, "Could not allocate referral code")
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "code": code,
        "created_at": now_iso(),
    }
    await db.referral_codes.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _link_for(code: str) -> str:
    origin = (APP_PUBLIC_URL or "").rstrip("/")
    return f"{origin}/signup?ref={code}" if origin else f"/signup?ref={code}"


def _qr_url(link: str) -> str:
    # Use a reliable free QR endpoint. Front-end can also render locally.
    return f"https://api.qrserver.com/v1/create-qr-code/?size=280x280&data={quote(link, safe='')}"


async def _stats(tenant_id: str, customer_id: str) -> dict:
    q = {"tenant_id": tenant_id, "referrer_customer_id": customer_id}
    invites = await db.referral_invites.count_documents(q)
    signups = await db.referral_conversions.count_documents(q)
    approved = await db.referral_conversions.count_documents({**q, "status": "approved"})
    pending = await db.referral_conversions.count_documents({**q, "status": "pending_review"})
    credits = await db.service_credits.find(
        {"tenant_id": tenant_id, "customer_id": customer_id, "source": "referral"},
        {"_id": 0}
    ).to_list(200)
    available = sum(1 for c in credits if c.get("months_remaining", 0) > 0)
    return {
        "invites_sent": invites,
        "signups": signups,
        "converted": approved,
        "pending_review": pending,
        "credits_earned_pct": _REWARD_PCT * approved,
        "credits_available_months": available,
    }


# ═══════════════════════ Customer surface ═══════════════════════════════════
@router.get("/referrals/me")
async def my_referral(
    user: dict = Depends(_require_customer),
    tenant: dict = Depends(get_current_tenant),
):
    code_doc = await _get_or_create_code(tenant["id"], user["id"])
    link = _link_for(code_doc["code"])
    invites = await db.referral_invites.find(
        {"tenant_id": tenant["id"], "referrer_customer_id": user["id"]},
        {"_id": 0}
    ).sort("sent_at", -1).to_list(200)
    return {
        "referral_code": code_doc["code"],
        "referral_link": link,
        "share_qr_url": _qr_url(link),
        "reward_pct": _REWARD_PCT,
        "reward_description": f"{_REWARD_PCT}% off 1 month of service",
        "stats": await _stats(tenant["id"], user["id"]),
        "invites": invites,
    }


class GenerateReq(BaseModel):
    force: bool = False


@router.post("/referrals/me/generate")
async def regenerate_code(
    body: GenerateReq = GenerateReq(),
    user: dict = Depends(_require_customer),
    tenant: dict = Depends(get_current_tenant),
):
    existing = await db.referral_codes.find_one(
        {"tenant_id": tenant["id"], "customer_id": user["id"]}, {"_id": 0}
    )
    if existing and not body.force:
        raise HTTPException(400, "Send force=true to rotate your code")
    for _ in range(8):
        code = _gen_code()
        if not await db.referral_codes.find_one({"code": code}):
            break
    else:
        raise HTTPException(500, "Could not allocate code")
    if existing:
        await db.referral_codes.update_one(
            {"tenant_id": tenant["id"], "customer_id": user["id"]},
            {"$set": {"code": code, "created_at": now_iso()}},
        )
    else:
        await db.referral_codes.insert_one({
            "id": new_id(), "tenant_id": tenant["id"], "customer_id": user["id"],
            "code": code, "created_at": now_iso(),
        })
    return {"code": code, "referral_link": _link_for(code)}


class Recipient(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class InviteReq(BaseModel):
    channel: str  # email | sms | copy | social
    recipients: Optional[List[Recipient]] = None
    message: Optional[str] = None


@router.post("/referrals/invite")
async def send_invite(
    body: InviteReq,
    user: dict = Depends(_require_customer),
    tenant: dict = Depends(get_current_tenant),
):
    if body.channel not in ("email", "sms", "copy", "social"):
        raise HTTPException(400, f"Unsupported channel {body.channel}")
    code_doc = await _get_or_create_code(tenant["id"], user["id"])
    import os as _os
    resend_ready = bool(_os.environ.get("RESEND_API_KEY"))
    results = []
    recipients = body.recipients or [Recipient()]
    for r in recipients:
        status = "sent"
        error = None
        if body.channel == "sms":
            if not r.phone:
                status = "pending_sms"
                error = "phone missing"
            else:
                # Feb-2026 Twilio→RC consolidation — call the RC adapter
                # directly. It fails-closed with provider="mock" when RC
                # is unconfigured; surface that as pending_sms so the
                # invite is still recorded.
                try:
                    from services.sms.rc_adapter import send as _sms_send
                    _sms_body = (f"{user.get('name','A friend')} thinks you'll "
                                   f"love Pool & Landscaping. Use their referral "
                                   f"link — they'll earn 50% off a month of "
                                   f"service: {_link_for(code_doc['code'])}")
                    res = await _sms_send(
                        to=r.phone, body=_sms_body,
                        category="transactional",
                        tenant_id=tenant["id"],
                        idempotency_key=f"referral-invite:{code_doc['code']}:{r.phone}",
                    )
                    ps = (res or {}).get("provider_status")
                    if ps in ("sent", "queued", "delivered", "accepted"):
                        status = "sent"
                    elif ps in ("mocked", "dry_run"):
                        status = "pending_sms"
                        error = ("SMS delivery not configured — invite recorded, "
                                   "delivery starts once RingCentral is wired")
                    else:
                        status = "failed"
                        error = (res or {}).get("error") or "sms-send-failed"
                except Exception as exc:
                    logger.warning("[referrals] SMS invite failed: %s", exc)
                    status = "failed"
                    error = str(exc)[:120]
        elif body.channel == "email":
            if not (resend_ready and r.email):
                status = "pending_resend" if not resend_ready else "sent"
                error = "Email delivery pending Resend credentials" if not resend_ready else None
                if r.email and resend_ready:
                    # Best-effort dispatch; if it throws we still record the invite.
                    try:
                        from routers.marketing import send_email_via_resend  # type: ignore
                        await send_email_via_resend(
                            to=r.email, subject="You've been referred — 50% off first month",
                            html=f"<p>{user.get('name','A friend')} thinks you'll love Pool & Landscaping. "
                                 f"Use their referral link and they'll earn 50% off a month of service:"
                                 f"</p><p><a href=\"{_link_for(code_doc['code'])}\">"
                                 f"{_link_for(code_doc['code'])}</a></p>",
                        )
                    except Exception as e:
                        status = "failed"
                        error = str(e)
        invite = {
            "id": new_id(),
            "tenant_id": tenant["id"],
            "referrer_customer_id": user["id"],
            "channel": body.channel,
            "recipient_name": r.name,
            "recipient_email": r.email,
            "recipient_phone": r.phone,
            "code": code_doc["code"],
            "sent_at": now_iso(),
            "status": status,
            "error": error,
        }
        await db.referral_invites.insert_one(invite)
        invite.pop("_id", None)
        results.append(invite)
    return {"invites": results, "reward_pct": _REWARD_PCT}


# ═══════════════════════ Public (no auth) ═══════════════════════════════════
@router.get("/referrals/track/{code}")
async def track_referral(code: str):
    """Public. Renders the "you were referred by X" banner on signup."""
    code_doc = await db.referral_codes.find_one({"code": code}, {"_id": 0})
    if not code_doc:
        raise HTTPException(404, "Referral code not found")
    tenant = await db.tenants.find_one({"id": code_doc["tenant_id"]}, {"_id": 0})
    customer = await db.customers.find_one(
        {"id": code_doc["customer_id"], "tenant_id": code_doc["tenant_id"]}, {"_id": 0}
    )
    if not customer:
        # Fall back to user record if a customer doc doesn't exist.
        customer = await db.users.find_one(
            {"id": code_doc["customer_id"], "tenant_id": code_doc["tenant_id"]}, {"_id": 0}
        ) or {}
    first_name = ((customer.get("name") or "").split(" ") or [""])[0] or "A friend"
    brand = {
        "name": tenant.get("brand_name") if tenant else None,
        "logo_url": tenant.get("logo_url") if tenant else None,
        "primary_color": (tenant or {}).get("brand_color"),
    }
    return {
        "referrer_first_name": first_name,
        "referrer_tenant_id": code_doc["tenant_id"],
        "tenant_brand": brand,
        "reward_pct": _REWARD_PCT,
    }


class ApplyReq(BaseModel):
    code: str
    new_customer_id: str
    source_channel: Optional[str] = None


@router.post("/referrals/apply")
async def apply_referral(body: ApplyReq):
    """Public. Called by the signup flow after a new customer signs up.

    Records a pending-review conversion and notifies admins in-tenant.
    """
    code_doc = await db.referral_codes.find_one({"code": body.code}, {"_id": 0})
    if not code_doc:
        raise HTTPException(404, "Referral code not found")
    if code_doc["customer_id"] == body.new_customer_id:
        raise HTTPException(400, "Cannot refer yourself")
    dup = await db.referral_conversions.find_one({
        "tenant_id": code_doc["tenant_id"],
        "new_customer_id": body.new_customer_id,
    })
    if dup:
        return {"ok": True, "already_recorded": True, "conversion_id": dup["id"]}
    conv = {
        "id": new_id(),
        "tenant_id": code_doc["tenant_id"],
        "referrer_customer_id": code_doc["customer_id"],
        "new_customer_id": body.new_customer_id,
        "code": body.code,
        "source_channel": body.source_channel,
        "status": "pending_review",
        "admin_notes": None, "decided_by": None, "decided_at": None,
        "credit_id": None,
        "created_at": now_iso(),
    }
    await db.referral_conversions.insert_one(conv)
    conv.pop("_id", None)
    # Notify tenant admins via WS.
    try:
        from routers.realtime import bus
        admins = await db.users.find(
            {"tenant_id": code_doc["tenant_id"],
             "role": {"$in": ["admin", "super_admin"]}},
            {"_id": 0, "id": 1}
        ).to_list(200)
        for a in admins:
            await bus.broadcast(a["id"], {
                "type": "referral.pending",
                "payload": {"conversion_id": conv["id"]},
            })
    except Exception as e:
        logger.warning(f"WS notify failed: {e}")
    return {"ok": True, "conversion_id": conv["id"]}


# ═══════════════════════ Admin surface ══════════════════════════════════════
@router.get("/referrals/admin/queue")
async def admin_queue(
    status: Optional[str] = "pending_review",
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    q = {"tenant_id": tenant["id"]}
    if status:
        q["status"] = status
    rows = await db.referral_conversions.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    # Enrich with referrer + new-customer names.
    for r in rows:
        ref = await db.customers.find_one(
            {"id": r["referrer_customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        ) or await db.users.find_one(
            {"id": r["referrer_customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        ) or {}
        newc = await db.customers.find_one(
            {"id": r["new_customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        ) or await db.users.find_one(
            {"id": r["new_customer_id"], "tenant_id": tenant["id"]}, {"_id": 0}
        ) or {}
        r["referrer_name"] = ref.get("name") or ref.get("email") or "—"
        r["new_customer_name"] = newc.get("name") or newc.get("email") or "—"
    return rows


class DecisionReq(BaseModel):
    reason: Optional[str] = None
    notes: Optional[str] = None


@router.post("/referrals/admin/{cid}/approve")
async def admin_approve(
    cid: str,
    body: DecisionReq = DecisionReq(),
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    conv = await db.referral_conversions.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not conv:
        raise HTTPException(404, "Conversion not found")
    if conv["status"] == "approved":
        return conv  # idempotent
    now = now_iso()
    # Determine which tier applies (Phase 20B.4). This is the referrer's
    # Nth approved conversion (counting the one about to be approved).
    prior_approved = await db.referral_conversions.count_documents(
        {"tenant_id": tenant["id"], "status": "approved",
         "referrer_customer_id": conv["referrer_customer_id"]}
    )
    nth = prior_approved + 1
    try:
        from routers.referral_tiers import get_settings, pick_tier
        settings = await get_settings(tenant["id"])
        tier = pick_tier(settings, nth)
        reward_pct = float(tier.get("credit_pct", _REWARD_PCT))
        months = int(tier.get("credit_months", 1))
    except Exception as e:
        logger.warning(f"tier lookup failed, using default: {e}")
        reward_pct = float(_REWARD_PCT)
        months = 1
    # Issue the tiered service credit.
    credit = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": conv["referrer_customer_id"],
        "kind": "percent_off_month",
        "pct": reward_pct,
        "months_remaining": months,
        "source": "referral",
        "source_conversion_id": cid,
        "granted_at": now,
        "granted_by": user["id"],
        "redeemed_at": None,
        "redemption_invoice_id": None,
    }
    await db.service_credits.insert_one(credit)
    await db.referral_conversions.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {
            "status": "approved", "decided_by": user["id"], "decided_at": now,
            "credit_id": credit["id"], "admin_notes": body.notes,
            "tier_applied": {"pct": reward_pct, "months": months, "nth": nth},
        }},
    )
    # Notify the referring customer via WS.
    try:
        from routers.realtime import bus
        await bus.broadcast(conv["referrer_customer_id"], {
            "type": "referral.approved",
            "payload": {"credit_id": credit["id"], "pct": reward_pct,
                        "months": months},
        })
    except Exception as e:
        logger.warning(f"WS notify failed: {e}")
    return {
        "ok": True, "credit_id": credit["id"], "status": "approved",
        "reward_pct": reward_pct, "months": months, "nth_conversion": nth,
    }


@router.post("/referrals/admin/{cid}/reject")
async def admin_reject(
    cid: str,
    body: DecisionReq,
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    if not (body.reason or "").strip():
        raise HTTPException(400, "Rejection requires a reason")
    conv = await db.referral_conversions.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0}
    )
    if not conv:
        raise HTTPException(404, "Conversion not found")
    now = now_iso()
    await db.referral_conversions.update_one(
        {"id": cid, "tenant_id": tenant["id"]},
        {"$set": {"status": "rejected", "decided_by": user["id"],
                  "decided_at": now, "admin_notes": body.reason}},
    )
    try:
        from routers.realtime import bus
        await bus.broadcast(conv["referrer_customer_id"], {
            "type": "referral.rejected",
            "payload": {"reason": body.reason},
        })
    except Exception as e:
        logger.warning(f"WS notify failed: {e}")
    return {"ok": True, "status": "rejected"}


@router.get("/referrals/admin/analytics")
async def admin_analytics(
    user: dict = Depends(require_admin),
    tenant: dict = Depends(get_current_tenant),
):
    tid = tenant["id"]
    total_invites = await db.referral_invites.count_documents({"tenant_id": tid})
    by_channel_cursor = db.referral_invites.aggregate([
        {"$match": {"tenant_id": tid}},
        {"$group": {"_id": "$channel", "count": {"$sum": 1}}},
    ])
    invites_by_channel = {row["_id"]: row["count"] async for row in by_channel_cursor}

    conv_by_month_cursor = db.referral_conversions.aggregate([
        {"$match": {"tenant_id": tid}},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 7]},
            "total": {"$sum": 1},
            "approved": {"$sum": {"$cond": [{"$eq": ["$status", "approved"]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ])
    conversions_by_month = [
        {"month": row["_id"], "total": row["total"], "approved": row["approved"]}
        async for row in conv_by_month_cursor
    ]

    approved_total = await db.referral_conversions.count_documents(
        {"tenant_id": tid, "status": "approved"}
    )
    total_conversions = await db.referral_conversions.count_documents({"tenant_id": tid})
    approval_rate = (approved_total / total_conversions) if total_conversions else 0.0

    # Top referrers.
    top_cursor = db.referral_conversions.aggregate([
        {"$match": {"tenant_id": tid, "status": "approved"}},
        {"$group": {"_id": "$referrer_customer_id",
                    "converted_count": {"$sum": 1}}},
        {"$sort": {"converted_count": -1}},
        {"$limit": 10},
    ])
    top_referrers = []
    async for row in top_cursor:
        cust = await db.customers.find_one(
            {"id": row["_id"], "tenant_id": tid}, {"_id": 0}
        ) or await db.users.find_one(
            {"id": row["_id"], "tenant_id": tid}, {"_id": 0}
        ) or {}
        top_referrers.append({
            "customer_id": row["_id"],
            "name": cust.get("name") or cust.get("email") or "—",
            "converted_count": row["converted_count"],
            "credits_issued": row["converted_count"],
        })

    # Average time-to-convert (created_at → decided_at) in days.
    approved_docs = await db.referral_conversions.find(
        {"tenant_id": tid, "status": "approved",
         "decided_at": {"$ne": None}}, {"_id": 0}
    ).to_list(500)
    if approved_docs:
        durations = []
        for d in approved_docs:
            try:
                c = datetime.fromisoformat(d["created_at"].replace("Z", "+00:00"))
                dc = datetime.fromisoformat(d["decided_at"].replace("Z", "+00:00"))
                durations.append((dc - c).total_seconds() / 86400.0)
            except Exception:
                pass
        avg_days = sum(durations) / len(durations) if durations else 0.0
    else:
        avg_days = 0.0

    return {
        "total_invites": total_invites,
        "invites_by_channel": invites_by_channel,
        "conversions_by_month": conversions_by_month,
        "top_referrers": top_referrers,
        "approval_rate": round(approval_rate, 3),
        "average_time_to_convert_days": round(avg_days, 2),
    }


# ═══════════════════════ Credit application (invoicing) ═════════════════════
async def apply_referral_credits_to_invoice(invoice: dict) -> dict:
    """Idempotent hook — called from invoice generation. Applies at most one
    unredeemed referral credit to the invoice's service-line subtotal, capped
    at reducing the total to 0.
    """
    if not isinstance(invoice, dict):
        return invoice
    tid = invoice.get("tenant_id")
    cid = invoice.get("customer_id")
    if not tid or not cid:
        return invoice
    credit = await db.service_credits.find_one({
        "tenant_id": tid,
        "customer_id": cid,
        "months_remaining": {"$gt": 0},
        "kind": "percent_off_month",
    }, sort=[("granted_at", 1)])
    if not credit:
        return invoice
    subtotal = float(invoice.get("subtotal") or 0)
    if subtotal <= 0:
        return invoice
    off = round(subtotal * credit["pct"] / 100.0, 2)
    off = min(off, subtotal)
    new_subtotal = round(subtotal - off, 2)
    tax_rate = float(invoice.get("tax_rate") or 0) / 100.0 if invoice.get("tax_rate") else 0.0
    new_tax = round(new_subtotal * tax_rate, 2) if tax_rate else float(invoice.get("tax") or 0)
    new_total = round(new_subtotal + new_tax, 2)

    applied = invoice.get("applied_credits") or []
    applied.append({
        "credit_id": credit["id"],
        "amount_off_usd": off,
        "kind": credit["kind"],
        "pct": credit["pct"],
    })
    invoice["subtotal"] = new_subtotal
    invoice["tax"] = new_tax
    invoice["total"] = new_total
    invoice["applied_credits"] = applied

    remaining = int(credit.get("months_remaining", 0)) - 1
    upd = {"months_remaining": remaining}
    if remaining <= 0:
        upd["redeemed_at"] = now_iso()
        upd["redemption_invoice_id"] = invoice.get("id")
    await db.service_credits.update_one({"id": credit["id"]}, {"$set": upd})
    return invoice
