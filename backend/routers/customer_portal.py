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


def _stripe_configured() -> bool:
    return bool((os.environ.get("STRIPE_SECRET_KEY") or "").strip())


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
    """Customer taps "Request Service" → three effects fire atomically:

    1. **Internal direct message** inserted into ``db.messages`` (the
       same collection the admin inbox reads from). The message body
       is server-composed from the customer's identity + address plus
       the submitted ``service_type / preferred_date / notes``.
    2. **Bell notifications** enqueued for every ``admin`` /
       ``super_admin`` in the tenant via
       ``services.notifications.enqueue_for_tenant_admins`` (kind =
       ``inbound_customer_message``). Bell + realtime WS/SSE fan-out
       are honoured by the shared notification engine.
    3. **Expo push** best-effort to every admin device via
       ``routers.mobile_push.send_push_to_user``. Silent no-op when
       ``EXPO_PUSH_ACCESS_TOKEN`` is unset (or no devices registered).

    Effects 2 + 3 are best-effort — a transport failure never blocks
    the write. Effect 1 is authoritative: without the message doc the
    admin has nothing to open, so a persistence failure returns 500.
    """
    cid = _require_customer(user)

    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"]}, {"_id": 0},
    ) or {}
    customer_name = user.get("name") or cust.get("name") or "Customer"
    address = (
        cust.get("address")
        or cust.get("street_address")
        or (cust.get("property") or {}).get("address")
        or ""
    )

    service_type = (body.service_type or "").strip() or None
    preferred_date = (body.preferred_date or "").strip() or None
    notes = (body.notes or "").strip() or None

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
    try:
        from services.notifications import enqueue_for_tenant_admins

        title = f"Service request from {customer_name}"
        summary = (service_type or "Service request") + (
            f" · {preferred_date}" if preferred_date else ""
        )
        # Feb-2026 fix — the previous ``/messages?customer_id={cid}``
        # href pointed at a route that doesn't exist in the admin
        # web app, so tapping the bell entry 404'd. The admin thread
        # view lives at ``/communication/:customer_id`` (see
        # frontend/src/pages/phase14/Phase14Pages.jsx —
        # ``CommunicationThread``) which reads from
        # ``GET /api/communications/{customer_id}`` returning every
        # message in ``db.messages`` for that customer.
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
    # arrive without polling. Best-effort — same pattern as
    # ``send_my_message`` in ``routers/portal.py``.
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

    return {
        "ok": True,
        "message_id": msg_id,
        "message": msg_doc,
        "notified_admins": len(bell_ids),
        "push_results": push_results,
    }
