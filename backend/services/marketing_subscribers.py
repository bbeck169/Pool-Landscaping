"""Marketing · Phase M1 — Subscriber mirror + confirmation helpers.

Two responsibilities:

1. **CRM mirror**: whenever a customer is created (or an existing
   customer is updated with an email for the first time), upsert a row
   into the ``subscribers`` collection with ``source="crm_customer"``
   and ``status="subscribed"`` (already-consented via service agreement,
   per the M1 product spec).

2. **Double-opt-in helpers**: generate + verify a signed confirmation
   token for public signup-form subscribers. Reuses the same HMAC
   pattern used by ``routers/comms.py::_sign_unsubscribe`` so we don't
   introduce a second signing scheme.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any, Dict, Optional

from config import db, logger
from utils import new_id, now_iso


CONFIRM_PURPOSE = "confirm_sub"


# ─── HMAC helpers ─────────────────────────────────────────────────────

def sign_confirmation(tenant_id: str, email: str) -> str:
    secret = os.environ.get("JWT_SECRET") or "dev"
    payload = f"{tenant_id}|{email.lower()}|{CONFIRM_PURPOSE}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


def verify_confirmation(tenant_id: str, email: str, token: str) -> bool:
    if not (tenant_id and email and token):
        return False
    expected = sign_confirmation(tenant_id, email)
    return hmac.compare_digest(token, expected)


# ─── Mirror hook ──────────────────────────────────────────────────────

async def mirror_customer_created(tenant_id: str, customer: Dict[str, Any]) -> None:
    """Idempotent upsert of a subscribers row for a CRM customer.

    Called from ``routers/customers.create_customer`` right after the
    ``customer.created`` domain event is emitted. Never raises — a
    subscriber-mirror failure must never block customer creation.
    """
    try:
        email = (customer.get("email") or "").strip().lower()
        phone = (customer.get("phone") or "").strip()
        if not email and not phone:
            return  # nothing to key on
        # Prefer email as the natural key when present, else phone.
        key: Dict[str, Any] = {"tenant_id": tenant_id}
        if email:
            key["email"] = email
        else:
            key["phone"] = phone
        existing = await db.subscribers.find_one(key, {"_id": 0})
        if existing:
            # Already mirrored — just refresh the customer_id link.
            if existing.get("customer_id") != customer.get("id"):
                await db.subscribers.update_one(
                    {"id": existing["id"]},
                    {"$set": {"customer_id": customer.get("id"),
                              "updated_at": now_iso()}},
                )
            return
        doc = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "email": email or None,
            "phone": phone or None,
            "first_name": customer.get("first_name") or "",
            "last_name": customer.get("last_name") or "",
            "status": "subscribed",
            "source": "crm_customer",
            "customer_id": customer.get("id"),
            "tags": [],
            "attributes": {},
            "consent_at": now_iso(),
            "confirmed_at": now_iso(),
            "unsubscribed_at": None,
            "confirmation_token": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.subscribers.insert_one(doc)
    except Exception as e:
        logger.warning(f"[marketing] mirror_customer_created failed: {e}")


# ─── Confirmation email body ──────────────────────────────────────────

def build_confirmation_html(*, tenant_name: str, confirm_url: str,
                             first_name: str = "") -> str:
    who = f" {first_name}" if first_name else ""
    return (
        "<!doctype html><html><body style=\"font-family:Arial,sans-serif;"
        "max-width:560px;margin:32px auto;padding:0 20px;color:#111\">"
        f"<h2 style=\"margin:0 0 12px\">Please confirm your subscription</h2>"
        f"<p>Hi{who},</p>"
        f"<p>Thanks for subscribing to updates from "
        f"<strong>{tenant_name}</strong>. Please confirm your email "
        f"address by clicking the button below — this makes sure we "
        f"only send messages to real inboxes.</p>"
        f"<p style=\"margin:24px 0\">"
        f"<a href=\"{confirm_url}\" style=\"display:inline-block;"
        f"padding:12px 20px;background:#0284C7;color:#fff;"
        f"text-decoration:none;border-radius:6px\">Confirm subscription</a>"
        f"</p>"
        f"<p style=\"color:#666;font-size:13px\">If you didn't sign up, "
        f"you can safely ignore this email.</p>"
        "</body></html>"
    )


# ─── Confirmation dispatch ────────────────────────────────────────────

async def send_confirmation_email(*, tenant: Dict[str, Any],
                                     subscriber: Dict[str, Any]) -> Dict[str, Any]:
    """Send the double-opt-in confirmation email.

    Uses the same ``send_email`` adapter as Comms; opt-out protection
    still applies (someone who previously opted-out can't be pulled
    back in via a stealth signup).
    """
    from services.comms_email_adapter import send_email
    email = subscriber.get("email") or ""
    if not email:
        return {"status": "failed", "error": "subscriber has no email"}
    tenant_id = tenant["id"]
    token = sign_confirmation(tenant_id, email)
    base = (
        tenant.get("portal_link")
        or os.environ.get("APP_PUBLIC_URL", "").rstrip("/")
        or ""
    )
    confirm_url = (
        f"{base}/marketing/confirm?token={token}"
        f"&e={email}&t={tenant_id}"
    )
    html = build_confirmation_html(
        tenant_name=tenant.get("name") or "",
        confirm_url=confirm_url,
        first_name=(subscriber.get("first_name") or "").strip(),
    )
    return await send_email(
        tenant_id, email,
        subject=f"Confirm your subscription to {tenant.get('name') or ''}".strip(),
        html=html,
        from_name=tenant.get("name") or None,
    )
