"""TD-customer-list-bulk-request-card-stripe-setupintent · Feb-2026.

Supersedes the generic template-based bulk request-card endpoint
(``customers_bulk_request_card.py``) with a real Stripe-backed flow.

Endpoints
---------
``POST /api/customers/bulk-request-card-setup-intent`` (admin only):
    Fire email + SMS to each selected customer with a unique
    single-use capture link scoped to that one customer. Preflight
    403s on cross-tenant / orphan customer_id (strict isolation,
    same shape as Ticket G/I).  Per-row dispatch degrades gracefully
    on Stripe-create or send failures without failing the whole
    batch.  Hard cap: 500 customers per call.

``GET /api/card-capture/{token}``:
    Public (no auth) — the capture page bootstraps itself from here.
    Returns customer_first_name, tenant_business_name, SetupIntent
    client_secret, publishable_key, expires_at.  410 on used /
    expired, 404 on unknown.

``POST /api/card-capture/{token}/confirm``:
    Public (no auth) — called after Stripe Elements confirmSetup
    returns a payment_method_id.  Atomically marks the token
    ``used_at`` (unique on ``token`` prevents double-use), mirrors
    the PM into ``db.payment_methods``, and stamps
    ``customer.stripe_default_payment_method_id`` +
    ``customer.card_on_file_added_at``.  410 on reuse.

Token
-----
Random ``secrets.token_urlsafe(32)`` persisted in
``customer_card_capture_tokens`` with:
  * Unique index on ``token`` (atomic single-use enforcement).
  * TTL via ``expires_at`` (7 days from creation).
  * ``used_at`` + ``used_ip`` + ``used_user_agent`` populated on
    successful confirm.

Tenant isolation is enforced server-side on every endpoint:
  * Bulk endpoint preflights customer_ids against the caller's
    tenant and 403s on any that resolve elsewhere / nowhere.
  * Capture endpoints resolve the token first, derive the
    tenant_id from the token row, then scope every downstream
    Mongo query to that tenant.  Never trust URL or body claims
    about tenancy.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import DuplicateKeyError

from config import db
from routers.tenants import get_current_tenant
from utils import get_current_user, now_iso


logger = logging.getLogger("customers_bulk_card_capture")
router = APIRouter()


_ADMIN_ROLES = ("admin", "manager", "super_admin")
_MAX_BULK = 500
_TOKEN_TTL_DAYS = 7


# ─── Pydantic bodies ──────────────────────────────────────────────
class BulkRequestCardSetupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_ids: List[str] = Field(min_length=1, max_length=_MAX_BULK)


class CardCaptureConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payment_method_id: str = Field(min_length=5, max_length=256)


# ─── Index bootstrap ──────────────────────────────────────────────
_indexes_ready = False


async def _ensure_indexes() -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        await db.customer_card_capture_tokens.create_index(
            "token", unique=True)
        await db.customer_card_capture_tokens.create_index("expires_at")
        await db.customer_card_capture_tokens.create_index(
            [("tenant_id", 1), ("customer_id", 1)])
    except Exception as e:   # pragma: no cover — only idempotency hiccups
        logger.warning("[card-capture] index create: %s", e)
    _indexes_ready = True


# ─── Helpers ──────────────────────────────────────────────────────
def _require_admin(user: dict) -> None:
    if (user.get("role") or "") not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin/manager only")


async def _categorise_missing_customers(missing_ids: List[str]) -> List[Dict]:
    hits: Dict[str, str] = {}
    async for d in db.customers.find(
        {"id": {"$in": missing_ids}}, {"_id": 0, "id": 1, "tenant_id": 1}
    ):
        hits[d["id"]] = d.get("tenant_id") or ""
    out: List[Dict] = []
    for mid in missing_ids:
        if mid in hits:
            out.append({"customer_id": mid, "reason": "foreign_tenant",
                        "tenant_id": hits[mid]})
        else:
            out.append({"customer_id": mid, "reason": "orphan"})
    return out


def _mint_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_token(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


_EMAIL_SUBJECT = "Payment method on file requested"
_EMAIL_BODY = (
    "Hi {first_name},\n\n"
    "{tenant_name} is requesting a payment method on file for future "
    "billing.\n\n"
    "Please use this secure link to add a card: {link}\n\n"
    "This link expires in 7 days."
)
_SMS_BODY = (
    "{tenant_name} is requesting a card on file. "
    "Add yours here (expires 7 days): {link}"
)


def _render_body(template: str, *, first_name: str,
                   tenant_name: str, link: str) -> str:
    return (template
             .replace("{first_name}", first_name or "there")
             .replace("{tenant_name}", tenant_name or "Your provider")
             .replace("{link}", link))


def _capture_base_url(tenant: Dict) -> str:
    import os
    return (
        os.environ.get("PUBLIC_FRONTEND_ORIGIN")
        or (tenant.get("brand") or {}).get("public_origin")
        or "https://app.plofv.com"
    ).strip().rstrip("/")


async def _dispatch_one(*, customer: Dict, tenant: Dict,
                          operator_id: str,
                          now: datetime) -> Dict[str, Any]:
    cid = customer["id"]
    email_to = (customer.get("email") or "").strip()
    phone_to = (customer.get("phone") or "").strip()

    if not email_to and not phone_to:
        return {"customer_id": cid, "status": "skipped_no_contact",
                "email_status": "skipped", "sms_status": "skipped"}

    # ─ Materialize stripe_customer_id if missing (per Q1a).
    try:
        from services.payments.stripe_charge import ensure_stripe_customer
        stripe_customer_id = await ensure_stripe_customer(
            tenant_id=tenant["id"], customer_id=cid,
        )
    except Exception as exc:   # noqa: BLE001
        logger.exception(
            "[card-capture] ensure_stripe_customer failed for %s: %s",
            cid, exc,
        )
        return {"customer_id": cid,
                "status": "skipped_stripe_customer_create_failed",
                "email_status": "skipped", "sms_status": "skipped",
                "error": f"stripe_customer: {exc!s}"}

    # ─ Mint single-use token row.  SetupIntent is created lazily
    #   on first GET /card-capture/{token} to keep this loop fast
    #   and avoid orphaning Stripe objects if the email never sends.
    token = _mint_token()
    token_doc = {
        "token": token, "token_hash": _hash_token(token),
        "tenant_id": tenant["id"], "customer_id": cid,
        "stripe_customer_id": stripe_customer_id,
        "setup_intent_id": None, "setup_intent_client_secret": None,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=_TOKEN_TTL_DAYS)).isoformat(),
        "used_at": None, "used_ip": None, "used_user_agent": None,
        "created_by": operator_id,
    }
    await db.customer_card_capture_tokens.insert_one(token_doc)

    link = f"{_capture_base_url(tenant)}/customer-portal/add-card/{token}"
    first_name = (customer.get("first_name")
                   or (customer.get("name") or "").split(" ")[0]
                   or "there")
    tenant_name = tenant.get("name") or "Your provider"

    email_status = "skipped"
    sms_status = "skipped"
    err: Optional[str] = None

    # ─ Email ────────────────────────────────────────────────────
    if email_to:
        try:
            from services.comms_email_adapter import send_email
            from services.comms_env_guard import CommsContext
            body = _render_body(_EMAIL_BODY, first_name=first_name,
                                 tenant_name=tenant_name, link=link)
            html = ('<pre style="font-family:inherit;white-space:pre-wrap">'
                    f"{body}</pre>")
            res = await send_email(
                tenant["id"], email_to,
                subject=_EMAIL_SUBJECT, html=html,
                context=CommsContext.SYSTEM,
            )
            email_status = res.get("status") or "sent"
            await db.communications_log.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant["id"], "customer_id": cid,
                "channel": "email", "direction": "outbound",
                "recipient": email_to, "subject": _EMAIL_SUBJECT,
                "body": body, "delivery_status": email_status,
                "provider": "resend",
                "provider_response_id": res.get("provider_id"),
                "trigger_entity": {
                    "kind": "customer_bulk_card_add_link",
                    "customer_id": cid, "token_hash": _hash_token(token),
                    "sent_by": operator_id,
                },
                "created_at": now_iso(),
            })
        except Exception as exc:   # noqa: BLE001
            email_status = "failed"
            err = f"email: {exc!s}"
            logger.exception("[card-capture] email send failed cid=%s", cid)

    # ─ SMS ──────────────────────────────────────────────────────
    if phone_to:
        try:
            from services.sms.rc_adapter import send as _sms_send
            body = _render_body(_SMS_BODY, first_name=first_name,
                                 tenant_name=tenant_name, link=link)
            res = await _sms_send(
                phone_to, body,
                tenant_id=tenant["id"], customer_id=cid,
                idempotency_key=f"customer-card-capture:{cid}:{token[:8]}",
            )
            sms_status = res.get("status") or "sent"
            await db.communications_log.insert_one({
                "id": str(uuid.uuid4()),
                "tenant_id": tenant["id"], "customer_id": cid,
                "channel": "sms", "direction": "outbound",
                "recipient": phone_to, "subject": None, "body": body,
                "delivery_status": sms_status, "provider": "ringcentral",
                "provider_response_id": res.get("provider_id"),
                "trigger_entity": {
                    "kind": "customer_bulk_card_add_link",
                    "customer_id": cid, "token_hash": _hash_token(token),
                    "sent_by": operator_id,
                },
                "created_at": now_iso(),
            })
        except Exception as exc:   # noqa: BLE001
            sms_status = "failed"
            err = (err + "; " if err else "") + f"sms: {exc!s}"
            logger.exception("[card-capture] sms send failed cid=%s", cid)

    if email_status == "sent" and sms_status == "sent":
        terminal = "sent_both"
    elif email_status == "sent":
        terminal = "sent_email_only"
    elif sms_status == "sent":
        terminal = "sent_sms_only"
    elif email_status == "failed" or sms_status == "failed":
        terminal = "error"
    else:
        terminal = "skipped_no_contact"

    out: Dict[str, Any] = {
        "customer_id": cid, "status": terminal,
        "email_status": email_status, "sms_status": sms_status,
    }
    if err:
        out["error"] = err
    return out


# ─── Bulk admin endpoint ────────────────────────────────────────
@router.post("/customers/bulk-request-card-setup-intent")
async def bulk_request_card_setup_intent(
    body: BulkRequestCardSetupBody,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    _require_admin(user)
    await _ensure_indexes()

    if len(body.customer_ids) > _MAX_BULK:
        raise HTTPException(400, {
            "error": "batch_size_exceeded", "max": _MAX_BULK,
            "received": len(body.customer_ids),
        })

    seen: set = set()
    customer_ids: List[str] = []
    for cid in body.customer_ids:
        if cid in seen:
            continue
        seen.add(cid)
        customer_ids.append(cid)

    rows = await db.customers.find(
        {"id": {"$in": customer_ids}, "tenant_id": tenant["id"]},
        {"_id": 0},
    ).to_list(len(customer_ids) + 1)
    resolved = {r["id"]: r for r in rows}
    missing = [cid for cid in customer_ids if cid not in resolved]
    if missing:
        errors = await _categorise_missing_customers(missing)
        raise HTTPException(status_code=403, detail={
            "error": "tenant_isolation_breach", "errors": errors,
        })

    now = datetime.now(timezone.utc)
    results: List[Dict[str, Any]] = []
    counts = {"email_sent": 0, "sms_sent": 0, "skipped": 0, "error": 0}
    for cid in customer_ids:
        row = await _dispatch_one(
            customer=resolved[cid], tenant=tenant,
            operator_id=user.get("id"), now=now,
        )
        results.append(row)
        if row["email_status"] == "sent":
            counts["email_sent"] += 1
        if row["sms_status"] == "sent":
            counts["sms_sent"] += 1
        if row["status"].startswith("skipped_"):
            counts["skipped"] += 1
        elif row["status"] == "error":
            counts["error"] += 1
    return {"results": results, "counts": counts}


# ─── Capture page endpoints (no auth; token is the authority) ───
async def _resolve_token(token: str) -> Dict[str, Any]:
    """Resolve + validate a capture token.  Raises on used, expired,
    or unknown — never leaks tenant information to the caller."""
    row = await db.customer_card_capture_tokens.find_one(
        {"token": token}, {"_id": 0})
    if not row:
        raise HTTPException(404, {"code": "token_not_found"})
    now = datetime.now(timezone.utc)
    try:
        exp = datetime.fromisoformat(row["expires_at"])
    except Exception:
        exp = now - timedelta(seconds=1)
    if now >= exp:
        raise HTTPException(410, {"code": "token_expired",
                                    "message": "This link has expired."})
    if row.get("used_at"):
        raise HTTPException(410, {"code": "token_already_used",
                                    "message": "This link has already been used."})
    return row


@router.get("/card-capture/{token}")
async def get_card_capture_context(token: str) -> Dict[str, Any]:
    import os
    row = await _resolve_token(token)
    tenant = await db.tenants.find_one(
        {"id": row["tenant_id"]}, {"_id": 0, "name": 1})
    customer = await db.customers.find_one(
        {"id": row["customer_id"], "tenant_id": row["tenant_id"]},
        {"_id": 0, "first_name": 1, "name": 1})
    first_name = ((customer or {}).get("first_name")
                   or ((customer or {}).get("name") or "").split(" ")[0]
                   or "there")

    # Lazily materialize the SetupIntent on first GET so a never-
    # clicked link never spawns a Stripe object.  Store back onto
    # the token row for subsequent reads.
    if not row.get("setup_intent_client_secret"):
        from services.payments.stripe_charge import create_setup_intent
        try:
            si = await create_setup_intent(
                tenant_id=row["tenant_id"],
                stripe_customer_id=row["stripe_customer_id"],
                payment_method_types=["card"],
            )
        except Exception as exc:   # noqa: BLE001
            logger.exception("[card-capture] create_setup_intent failed")
            raise HTTPException(502, {"code": "stripe_unavailable",
                                        "message": str(exc)})
        client_secret = si.get("client_secret")
        setup_intent_id = si.get("id") or si.get("setup_intent_id")
        publishable_key = si.get("publishable_key")
        await db.customer_card_capture_tokens.update_one(
            {"token": token},
            {"$set": {
                "setup_intent_id": setup_intent_id,
                "setup_intent_client_secret": client_secret,
                "publishable_key": publishable_key,
            }},
        )
        row["setup_intent_client_secret"] = client_secret
        row["setup_intent_id"] = setup_intent_id
        row["publishable_key"] = publishable_key

    return {
        "customer_first_name": first_name,
        "tenant_business_name": (tenant or {}).get("name") or "Your provider",
        "setup_intent_client_secret": row.get("setup_intent_client_secret"),
        "publishable_key": row.get("publishable_key"),
        "expires_at": row["expires_at"],
        "used": False,
    }


@router.post("/card-capture/{token}/confirm")
async def confirm_card_capture(
    token: str, body: CardCaptureConfirmBody, request: Request,
) -> Dict[str, Any]:
    # Atomic single-use: find-and-update guarded by ``used_at: None``.
    # Second confirm hit flips used_at==None → used_at==<ts>; the
    # third hit sees used_at set and 410s via _resolve_token.
    row = await _resolve_token(token)
    now_dt = datetime.now(timezone.utc)
    claim = await db.customer_card_capture_tokens.find_one_and_update(
        {"token": token, "used_at": None},
        {"$set": {
            "used_at": now_dt.isoformat(),
            "used_ip": (request.client.host if request.client else None),
            "used_user_agent": request.headers.get("user-agent"),
            "attached_payment_method_id": body.payment_method_id,
        }},
    )
    if not claim:
        raise HTTPException(410, {"code": "token_already_used"})

    # Mirror the PM into db.payment_methods (same shape as the Phase
    # 47c /attach endpoint — share the service helper if one exists;
    # inlined here to keep this ticket's blast radius tight).
    pm_doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": row["tenant_id"], "customer_id": row["customer_id"],
        "stripe_payment_method_id": body.payment_method_id,
        "stripe_customer_id": row["stripe_customer_id"],
        "is_default": True, "created_at": now_iso(),
        "source": "customer_card_capture_token",
    }
    await db.payment_methods.insert_one(pm_doc)
    await db.customers.update_one(
        {"id": row["customer_id"], "tenant_id": row["tenant_id"]},
        {"$set": {
            "stripe_default_payment_method_id": body.payment_method_id,
            "card_on_file_added_at": now_iso(),
        }},
    )
    return {"ok": True, "last4": None}
