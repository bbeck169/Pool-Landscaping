"""Feb-2026 · Customer-portal shared endpoints (Slice 3 · 3A + 3B + 3D).

3B — ``GET /api/customer-portal/summary`` returns the four numbers
     rendered as tiles at the top of the portal home page:
     balance_due, past_due, credit, next_service.

3A — ``POST /api/customer-portal/payment-methods/ach/link-session``
     kicks off a Stripe Financial Connections session for ACH bank
     verification. Wire-ready — behaves as a stub when
     ``STRIPE_SECRET_KEY`` is not configured (or the SDK call fails)
     so the frontend can render a disabled Connect button.

3D — ``POST /api/customer-portal/service-requests`` books an internal
     message + bell notification + best-effort Expo push to every
     admin in the customer's tenant when the customer taps the
     "Request Service" CTA on the portal.

All routes require ``role == "customer"`` and scope every read/write
strictly to ``current_user.customer_id`` in the current tenant.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import db, logger
from utils import get_current_user, new_id, now_iso
from routers.tenants import get_current_tenant

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════
# 3B · Portal summary tiles
# ═══════════════════════════════════════════════════════════════════════
def _require_customer(user: dict) -> str:
    if user.get("role") != "customer":
        raise HTTPException(403, "Customer portal only")
    cid = user.get("customer_id")
    if not cid:
        raise HTTPException(403, "Customer id missing on user")
    return cid


def _num(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


@router.get("/customer-portal/summary")
async def get_portal_summary(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """4-tile aggregate for the portal landing.

    Response shape::

        {
          "balance_due": 214.50,          # unpaid remaining on all open invoices
          "past_due": 89.00,              # subset of balance_due whose due_date < today
          "credit": 0.00,                 # overpayments across paid invoices
          "next_service": {               # or ``None``
            "date": "2026-08-05",
            "service_type": "Pool cleaning",
            "job_id": "…"
          },
          "breakdown": {
            "open_invoice_count": 3,
            "past_due_invoice_count": 1
          }
        }
    """
    cid = _require_customer(user)
    today = datetime.now(timezone.utc).date().isoformat()

    invs: List[Dict[str, Any]] = await db.quotes.find(
        {
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "doc_type": "invoice",
        },
        {"_id": 0},
    ).to_list(2000)

    balance_due = 0.0
    past_due = 0.0
    credit = 0.0
    open_ct = 0
    past_ct = 0
    for inv in invs:
        total = _num(inv.get("total"))
        paid = _num(inv.get("amount_paid"))
        remaining = round(total - paid, 2)
        due_date = str(inv.get("due_date") or "")[:10]
        if remaining > 0:
            balance_due += remaining
            open_ct += 1
            if due_date and due_date < today:
                past_due += remaining
                past_ct += 1
        elif remaining < 0:
            # Overpayment → treat the absolute difference as customer credit.
            credit += -remaining

    # Next-service — earliest scheduled job that is still open.
    next_job = await db.jobs.find_one(
        {
            "tenant_id": tenant["id"],
            "customer_id": cid,
            "status": {"$in": ["scheduled", "active", "pending", "requested"]},
        },
        {"_id": 0},
        sort=[("scheduled_start", 1), ("scheduled_date", 1)],
    )
    next_service = None
    if next_job:
        scheduled = (
            next_job.get("scheduled_start")
            or next_job.get("scheduled_date")
            or next_job.get("scheduled_at")
        )
        # Only return if it's today-or-future — a stale scheduled job
        # (e.g. never marked completed) shouldn't be dressed up as "next".
        if scheduled and str(scheduled)[:10] >= today:
            next_service = {
                "job_id": next_job.get("id"),
                "date": str(scheduled)[:10],
                "scheduled_start": scheduled,
                "service_type": (
                    next_job.get("service_type")
                    or next_job.get("job_type")
                    or next_job.get("title")
                    or "Service visit"
                ),
                "title": next_job.get("title"),
            }

    return {
        "balance_due": round(balance_due, 2),
        "past_due": round(past_due, 2),
        "credit": round(credit, 2),
        "next_service": next_service,
        "breakdown": {
            "open_invoice_count": open_ct,
            "past_due_invoice_count": past_ct,
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# 3A · ACH · Stripe Financial Connections link session (stubbed wire)
# ═══════════════════════════════════════════════════════════════════════
class AchLinkSessionResp(BaseModel):
    ok: bool
    reason: Optional[str] = None
    client_secret: Optional[str] = None
    session_id: Optional[str] = None


def _stripe_key_is_placeholder(key: str) -> bool:
    """Return True when ``key`` is empty or a well-known placeholder
    that must NOT be sent to Stripe.

    Anything Stripe would reject as malformed before hitting network
    (empty prefix, quotes accidentally captured from ``.env``, blank
    string, etc.) counts as a placeholder.  This lets the frontend
    render a grey "Coming soon" button in dev environments where an
    admin hasn't wired real credentials yet, without incurring a
    round-trip that would time out anyway.
    """
    k = (key or "").strip().strip('"').strip("'")
    if not k:
        return True
    # Well-known placeholder shapes.  ``sk_test_`` / ``sk_live_`` with no
    # suffix means someone pasted only the prefix.
    if k in {"sk_test_", "sk_live_", "sk_test_placeholder",
              "sk_live_placeholder", "sk_placeholder", "your_key_here"}:
        return True
    # A real Stripe key is always at least ~30 chars after the prefix.
    # ``sk_test_`` = 8 chars, so anything shorter than 24 total can't be
    # a live/test secret.
    if len(k) < 24:
        return True
    return False


def _stripe_configured() -> bool:
    """True when STRIPE_SECRET_KEY is present AND not a placeholder."""
    return not _stripe_key_is_placeholder(os.environ.get("STRIPE_SECRET_KEY") or "")


@router.post(
    "/customer-portal/payment-methods/ach/link-session",
    response_model=AchLinkSessionResp,
)
async def start_ach_link_session(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Create a Stripe Financial Connections session so the customer can
    verify their bank account instantly.

    When ``STRIPE_SECRET_KEY`` is empty the endpoint short-circuits and
    returns ``{ok: false, reason: "stripe_not_configured"}`` — the
    frontend uses this to render a disabled Connect button + tooltip.

    When the key is present, we ask Stripe for a real Financial
    Connections session bound to the customer's Stripe customer id
    (creating one on the fly if missing). No money moves — Financial
    Connections is verification only.
    """
    cid = _require_customer(user)

    if not _stripe_configured():
        return {"ok": False, "reason": "stripe_not_configured"}

    # Import lazily so the module loads even when Stripe SDK isn't wired.
    try:
        import stripe as _stripe

        _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or ""
    except Exception as exc:  # pragma: no cover — SDK missing
        logger.warning("Stripe SDK unavailable: %s", exc)
        return {"ok": False, "reason": "stripe_sdk_unavailable"}

    # Look up (or create) the customer's Stripe customer id.
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    ) or {}
    scid = cust.get("stripe_customer_id")
    if not scid:
        try:
            import asyncio as _asyncio

            sc = await _asyncio.to_thread(
                _stripe.Customer.create,
                email=cust.get("email") or user.get("email"),
                name=cust.get("name") or user.get("name"),
                metadata={
                    "customer_id": cid,
                    "tenant_id": tenant["id"],
                },
            )
            scid = sc.get("id") if isinstance(sc, dict) else getattr(sc, "id", None)
            if scid:
                await db.customers.update_one(
                    {"id": cid, "tenant_id": tenant["id"]},
                    {"$set": {"stripe_customer_id": scid}},
                )
        except Exception as exc:
            logger.warning("Stripe customer bootstrap failed: %s", exc)
            return {"ok": False, "reason": "stripe_customer_error"}

    try:
        import asyncio as _asyncio

        session = await _asyncio.to_thread(
            _stripe.financial_connections.Session.create,
            account_holder={"type": "customer", "customer": scid},
            permissions=["payment_method", "balances"],
            filters={"countries": ["US"]},
        )
        client_secret = (
            session.get("client_secret")
            if isinstance(session, dict)
            else getattr(session, "client_secret", None)
        )
        session_id = (
            session.get("id") if isinstance(session, dict) else getattr(session, "id", None)
        )
        if not client_secret:
            return {"ok": False, "reason": "stripe_error"}
        return {
            "ok": True,
            "client_secret": client_secret,
            "session_id": session_id,
        }
    except Exception as exc:
        logger.warning("Stripe Financial Connections session failed: %s", exc)
        return {"ok": False, "reason": "stripe_error"}


class AchAttachIn(BaseModel):
    """Payload the frontend posts after the Financial Connections widget
    resolves with a verified bank account id.  Purely wire-ready — no
    charges are moved. The endpoint records a ``payment_methods`` doc
    (``type='ach'``) for the customer with ``verified=false`` so admin
    can see the connection was requested; the ``verified`` flag flips
    to ``true`` once we wire the Stripe webhook confirming the account.
    """

    stripe_bank_account_id: Optional[str] = None
    session_id: Optional[str] = None


@router.post("/customer-portal/payment-methods/ach/attach")
async def attach_ach_result(
    body: AchAttachIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """Persist the Financial Connections resolution as a
    ``payment_methods`` document. Not wired to any charge path."""
    cid = _require_customer(user)
    if not _stripe_configured():
        # Guard rail — the frontend gates this behind the same env
        # check, but re-verify server-side.
        raise HTTPException(400, "stripe_not_configured")

    doc = {
        "id": new_id(),
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "type": "ach",
        "verified": False,
        "stripe_bank_account_id": body.stripe_bank_account_id,
        "session_id": body.session_id,
        "created_at": now_iso(),
    }
    await db.payment_methods.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "payment_method": doc}


@router.get("/customer-portal/payment-methods")
async def list_payment_methods(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    """List all payment methods (card + ACH) the customer has on file.

    Card data comes from the ``customers`` doc (existing Stripe setup
    session flow); ACH rows come from the ``payment_methods`` collection.
    """
    cid = _require_customer(user)
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    ) or {}
    out: List[Dict[str, Any]] = []
    if cust.get("default_payment_method_id"):
        out.append({
            "type": "card",
            "brand": cust.get("pm_brand") or "Card",
            "last4": cust.get("pm_last4") or "",
            "verified": True,
            "default": True,
        })
    ach_rows = await db.payment_methods.find(
        {"tenant_id": tenant["id"], "customer_id": cid, "type": "ach"},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    for row in ach_rows:
        out.append({
            "type": "ach",
            "id": row.get("id"),
            "verified": bool(row.get("verified")),
            "stripe_bank_account_id": row.get("stripe_bank_account_id"),
            "created_at": row.get("created_at"),
        })
    return {"methods": out, "stripe_configured": _stripe_configured()}


# ═══════════════════════════════════════════════════════════════════════
# 3D · Service-request CTA — fires internal message + bell + push
# ═══════════════════════════════════════════════════════════════════════
class ServiceRequestIn(BaseModel):
    service_type: Optional[str] = None
    preferred_date: Optional[str] = None
    notes: Optional[str] = None
    # Phase 34 · Feb-2026 · Task I — customer-portal service requests
    # now capture a single free-text field instead of a Service Type
    # dropdown. ``request_details`` supersedes ``notes`` when both are
    # supplied; ``notes`` is preserved so mobile clients still on the
    # old schema keep working during the rollout window.
    request_details: Optional[str] = None


# Phase 34 · Feb-2026 · Task I — where staff notifications land when a
# customer submits a service request. Values here are the PLOFV tenant
# defaults; production should lift these to tenant settings under
# ``settings.notifications.service_request_email/sms`` so multi-tenant
# operators can point them at their own dispatchers.
# TODO — Phase 35 · promote these to per-tenant settings + admin UI.
_SERVICE_REQUEST_EMAIL_FALLBACK = "brian@plofv.com"
_SERVICE_REQUEST_SMS_FALLBACK = "+16028874400"


def _resolve_service_request_email(tenant: Dict[str, Any]) -> str:
    notif = ((tenant or {}).get("settings") or {}).get("notifications") or {}
    return (notif.get("service_request_email")
            or _SERVICE_REQUEST_EMAIL_FALLBACK)


def _resolve_service_request_sms(tenant: Dict[str, Any]) -> str:
    notif = ((tenant or {}).get("settings") or {}).get("notifications") or {}
    return (notif.get("service_request_sms")
            or _SERVICE_REQUEST_SMS_FALLBACK)


def _fmt_service_request_body(
    customer_name: str,
    address: str,
    service_type: Optional[str],
    preferred_date: Optional[str],
    notes: Optional[str],
) -> str:
    """Build the human-readable message body the admin sees in the inbox.

    Kept compact — the internal-messages UI truncates aggressively, so
    front-load the who + what.
    """
    lines = [
        f"New service request from {customer_name}.",
        f"Service: {service_type or 'Not specified'}",
    ]
    if preferred_date:
        lines.append(f"Preferred date: {preferred_date}")
    if address:
        lines.append(f"Address: {address}")
    if (notes or "").strip():
        lines.append("")
        lines.append("Notes:")
        lines.append(notes.strip())
    return "\n".join(lines)


@router.post("/customer-portal/service-requests")
async def create_service_request(
    body: ServiceRequestIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> Dict[str, Any]:
    """Customer taps "Request Service" → four effects fire:

    1. **Internal direct message** inserted into ``db.messages``.
    2. **Bell notifications** enqueued for every admin/super_admin.
    3. **Expo push** best-effort to every admin device.
    4. **Email to Brian + SMS to the operations line** (Phase 34 ·
       Task I). Both are wrapped in try/except so a failed email
       does not block the SMS and vice versa. Destinations resolve
       from ``tenant.settings.notifications.service_request_email
       / _sms`` with a hardcoded PLOFV fallback.

    Effects 2–4 are best-effort — transport failures never block the
    write. Effect 1 is authoritative: without the message doc the
    admin has nothing to open, so a persistence failure returns 500.
    """
    cid = _require_customer(user)

    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    ) or {}
    customer_name = user.get("name") or cust.get("name") or "Customer"
    customer_phone = (
        cust.get("phone")
        or cust.get("primary_phone")
        or user.get("phone")
        or ""
    )
    customer_email = (
        cust.get("email")
        or user.get("email")
        or ""
    )
    address = (
        cust.get("address")
        or cust.get("street_address")
        or (cust.get("property") or {}).get("address")
        or ""
    )

    # Phase 34 · Task I — ``request_details`` is the new free-text
    # payload. Fall back to legacy ``notes`` when older clients still
    # POST that field so we don't break in-flight mobile builds.
    request_details = (
        (body.request_details or "").strip()
        or (body.notes or "").strip()
        or None
    )
    # ``service_type`` is now optional. Default to ``general_request``
    # server-side so downstream dashboards + auto-assign rules never
    # crash on a missing category.
    service_type = (body.service_type or "").strip() or "general_request"
    preferred_date = (body.preferred_date or "").strip() or None
    notes = request_details  # kept for backwards-compat consumers

    text = _fmt_service_request_body(
        customer_name=customer_name,
        address=address,
        service_type=service_type,
        preferred_date=preferred_date,
        notes=notes,
    )

    msg_id = new_id()
    msg_doc = {
        "id": msg_id,
        "tenant_id": tenant["id"],
        "customer_id": cid,
        "sender": "customer",
        "sender_name": customer_name,
        "text": text,
        "kind": "service_request",
        "service_request": {
            "service_type": service_type,
            "preferred_date": preferred_date,
            "notes": notes,
            "request_details": request_details,
            "address": address,
        },
        "read_by_customer": True,
        "read_by_staff": False,
        "created_at": now_iso(),
    }
    await db.messages.insert_one(msg_doc)
    msg_doc.pop("_id", None)

    # ─── Bell + realtime + Expo push ─── best-effort, never raise.
    push_results: List[Dict[str, Any]] = []
    bell_ids: List[str] = []
    email_result: Dict[str, Any] = {"provider_status": "skipped"}
    sms_result: Dict[str, Any] = {"provider_status": "skipped"}
    try:
        from services.notifications import enqueue_for_tenant_admins

        title = f"Service request from {customer_name}"
        summary = (service_type or "Service request") + (
            f" · {preferred_date}" if preferred_date else ""
        )
        href = f"/communication/{cid}"
        bell_ids = await enqueue_for_tenant_admins(
            tenant["id"],
            kind="inbound_customer_message",
            title=title,
            body=summary,
            source_ref={
                "kind": "service_request",
                "message_id": msg_id,
                "customer_id": cid,
            },
            href=href,
            priority="normal",
        )
    except Exception as exc:  # pragma: no cover — logged, never blocks the ack
        logger.warning("service_request bell enqueue failed: %s", exc)

    # Realtime broadcast so any admin with the inbox open sees the row
    # arrive without polling.
    try:
        from routers.realtime import bus

        admins = await db.users.find(
            {
                "tenant_id": tenant["id"],
                "role": {"$in": ["admin", "super_admin"]},
            },
            {"_id": 0, "id": 1},
        ).to_list(200)
        payload = {
            "type": "service_request",
            "payload": {
                "customer_id": cid,
                "customer_name": customer_name,
                "service_type": service_type,
                "preferred_date": preferred_date,
                "message_id": msg_id,
            },
        }
        for a in admins:
            if a.get("id"):
                try:
                    await bus.broadcast(a["id"], payload)
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("service_request realtime broadcast failed: %s", exc)

    # Expo push — silent no-op when the transport isn't wired.
    try:
        from routers.mobile_push import send_push_to_user

        admin_ids = await db.users.find(
            {
                "tenant_id": tenant["id"],
                "role": {"$in": ["admin", "super_admin"]},
            },
            {"_id": 0, "id": 1},
        ).to_list(200)
        push_title = "New service request"
        push_body = f"{customer_name} — {service_type or 'Service request'}"
        for a in admin_ids:
            if not a.get("id"):
                continue
            try:
                r = await send_push_to_user(
                    a["id"],
                    push_title,
                    push_body,
                    data={
                        "kind": "service_request",
                        "message_id": msg_id,
                        "customer_id": cid,
                    },
                )
                push_results.append({"user_id": a["id"], **(r or {})})
            except Exception as exc:
                push_results.append(
                    {"user_id": a["id"], "pushed": False, "reason": str(exc)[:120]}
                )
    except Exception as exc:
        logger.warning("service_request push fan-out failed: %s", exc)

    # ─── Phase 34 · Task I — Email + SMS notifications ───────────
    # Isolated try/except per channel so one transport failure never
    # blocks the other AND never masks the customer's success ack.
    to_email = _resolve_service_request_email(tenant)
    to_sms = _resolve_service_request_sms(tenant)
    request_short = (request_details or "").strip()[:140]
    deep_link = f"/communication/{cid}"

    try:
        from services.email.resend_adapter import send as _send_email

        subject = f"New Service Request from {customer_name}"
        html_parts = [
            "<div style=\"font-family:-apple-system,'Inter',sans-serif;"
            "color:#0F172A;max-width:640px;margin:0 auto;padding:24px;\">",
            f"<h2 style=\"margin:0 0 12px;\">New Service Request</h2>",
            f"<p style=\"margin:0 0 4px;\"><b>Customer:</b> {customer_name}</p>",
        ]
        if customer_email:
            html_parts.append(
                f"<p style=\"margin:0 0 4px;\"><b>Email:</b> "
                f"<a href=\"mailto:{customer_email}\">{customer_email}</a></p>"
            )
        if customer_phone:
            html_parts.append(
                f"<p style=\"margin:0 0 4px;\"><b>Phone:</b> "
                f"<a href=\"tel:{customer_phone}\">{customer_phone}</a></p>"
            )
        if address:
            html_parts.append(
                f"<p style=\"margin:0 0 4px;\"><b>Address:</b> {address}</p>"
            )
        if preferred_date:
            html_parts.append(
                f"<p style=\"margin:0 0 4px;\"><b>Preferred date:</b> "
                f"{preferred_date}</p>"
            )
        html_parts.append(
            "<hr style=\"border:none;border-top:1px solid #E2E8F0;"
            "margin:16px 0;\"/>"
        )
        html_parts.append(
            f"<div style=\"white-space:pre-wrap;font-size:15px;"
            f"line-height:1.5;\">{(request_details or 'No details provided').strip()}</div>"
        )
        app_url = os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
        if app_url:
            full_link = f"{app_url}{deep_link}"
            html_parts.append(
                f"<p style=\"margin:20px 0 0;\">"
                f"<a href=\"{full_link}\" style=\"display:inline-block;"
                f"background:#0284C7;color:#fff;padding:10px 16px;"
                f"border-radius:8px;text-decoration:none;font-weight:600;\">"
                f"View request</a></p>"
            )
        html_parts.append("</div>")
        email_result = await _send_email(
            to=to_email,
            subject=subject,
            html="".join(html_parts),
            category="transactional",
            tenant_id=tenant["id"],
            customer_id=cid,
        )
        logger.info(
            "service_request email_sent to=%s status=%s attempts=%s",
            to_email,
            email_result.get("provider_status"),
            email_result.get("attempts"),
        )
    except Exception as exc:  # pragma: no cover — never blocks the ack
        logger.warning("service_request email send failed: %s", exc)
        email_result = {"provider_status": "failed", "error": str(exc)[:200]}

    try:
        from services.sms.rc_adapter import send as _send_sms

        sms_short = request_short + ("…" if request_details and len(request_details) > 140 else "")
        sms_body = (
            f"New service request from {customer_name}"
            + (f" ({customer_phone})" if customer_phone else "")
            + f": {sms_short}"
            + (f" View: {deep_link}" if deep_link else "")
        )
        sms_result = await _send_sms(
            to=to_sms,
            body=sms_body,
            category="transactional",
            tenant_id=tenant["id"],
            customer_id=cid,
        )
        logger.info(
            "service_request sms_sent to=%s status=%s attempts=%s",
            to_sms,
            sms_result.get("provider_status"),
            sms_result.get("attempts"),
        )
    except Exception as exc:  # pragma: no cover — never blocks the ack
        logger.warning("service_request sms send failed: %s", exc)
        sms_result = {"provider_status": "failed", "error": str(exc)[:200]}

    return {
        "ok": True,
        "message_id": msg_id,
        "message": msg_doc,
        "notified_admins": len(bell_ids),
        "push_results": push_results,
        "email_notification": {
            "to": to_email,
            "status": email_result.get("provider_status"),
        },
        "sms_notification": {
            "to": to_sms,
            "status": sms_result.get("provider_status"),
        },
    }
