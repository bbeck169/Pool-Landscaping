"""Phase 16 · Additions E + F · Feb-2026 — Lead post-create side effects.

Called from every lead-create path (``POST /api/leads`` admin manual
and ``POST /api/public/leads`` public form). Two concerns handled
here in a specific order so downstream reasoning is deterministic:

1. **Brian's internal notification (Addition F)** — fires FIRST so
   Brian sees every inbound, including rejects. Email to
   ``brian@plofv.com`` + SMS to ``+16028874400`` by default, sourced
   from ``tenant.internal_lead_notifications`` if the admin has
   overridden. Best-effort — a Resend/RC failure is captured as a
   ``failed`` row on ``marketing_deliveries`` but does not raise.

2. **Out-of-state auto-reject (Addition E)** — if the lead's service
   address state isn't in ``tenant.serviced_states`` (default
   ``["AZ"]``), the lead gets ``status="rejected"`` +
   ``rejected_reason="out_of_state"`` + a customer-facing auto-reply
   email through Resend. Brian's notification (already sent above)
   gains the ``STATUS: REJECTED`` header line so the two flows stay
   in sync.

Every notification (internal + customer-facing) writes one row to
``marketing_deliveries`` with ``trigger_entity.kind`` set so the
Communications Log page surfaces them cleanly.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from config import db, logger
from utils import new_id, now_iso

_DEFAULT_INTERNAL_EMAIL = "brian@plofv.com"
_DEFAULT_INTERNAL_SMS = "+16028874400"
_DEFAULT_SERVICED_STATES = ["AZ"]
_PHX = ZoneInfo("America/Phoenix")

# US state abbreviation regex — pulls the 2-letter code out of a
# free-form address if the caller didn't supply it separately. We
# accept 3+ digit ZIPs before/after, comma separators, etc.
_STATE_RE = re.compile(r"\b([A-Z]{2})\b(?=\s+\d{5}|\s*,?\s*\d{5}|\s*$)")


def _extract_state(lead: Dict[str, Any]) -> Optional[str]:
    """Extract a 2-letter US state code from the lead's stored state
    field or from the tail of the free-form service_address. Returns
    uppercase or None when nothing plausible found."""
    explicit = (lead.get("state") or "").strip().upper()
    if len(explicit) == 2 and explicit.isalpha():
        return explicit
    addr = (lead.get("service_address") or lead.get("address") or "").upper()
    if not addr:
        return None
    m = _STATE_RE.search(addr)
    return m.group(1) if m else None


async def _tenant_config(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    notif = (t.get("internal_lead_notifications") or {})
    return {
        "email": notif.get("email") or _DEFAULT_INTERNAL_EMAIL,
        "sms": notif.get("sms") or _DEFAULT_INTERNAL_SMS,
        "enabled": notif.get("enabled", True),
        "serviced_states": [s.upper() for s in
                              (t.get("serviced_states") or _DEFAULT_SERVICED_STATES)],
        "app_host": (t.get("app_host")
                     or "https://poolscape-audit.preview.emergentagent.com"),
    }


def _fmt_phx(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(_PHX).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return iso


def _compose_internal(lead: Dict[str, Any], cfg: Dict[str, Any],
                       reject_state: Optional[str]) -> Dict[str, str]:
    parts = []
    if reject_state:
        parts.append(f"STATUS: REJECTED — out of state ({reject_state})")
    name = lead.get("name") or "".join(filter(None, [
        (lead.get("first_name") or "").strip(),
        (lead.get("last_name") or "").strip(),
    ])).strip() or "(no name)"
    parts.append(f"Name: {name}")
    if lead.get("phone"):   parts.append(f"Phone: {lead['phone']}")
    if lead.get("email"):   parts.append(f"Email: {lead['email']}")
    addr = lead.get("service_address") or lead.get("address")
    if addr:                parts.append(f"Address: {addr}")
    msg = lead.get("message") or lead.get("service_interest")
    if msg:                 parts.append(f"Message: {msg}")
    parts.append(f"Source: {lead.get('source') or 'unknown'}")
    parts.append(f"When: {_fmt_phx(lead.get('created_at') or now_iso())}")
    link = f"{cfg['app_host']}/leads/{lead.get('id')}"
    parts.append(f"Detail: {link}")
    body = "\n".join(parts)
    subject_prefix = "[REJECTED] " if reject_state else "[New lead] "
    return {
        "subject": f"{subject_prefix}{name}",
        "body": body,
    }


async def _log_row(*, tenant_id: str, channel: str, recipient: str,
                    subject: Optional[str], body: str, provider: str,
                    trigger_kind: str, trigger_id: str,
                    status: str, error: Optional[str] = None,
                    provider_response_id: Optional[str] = None,
                    customer_id: Optional[str] = None) -> None:
    await db.marketing_deliveries.insert_one({
        "id": new_id(),
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "channel": channel,
        "kind": "transactional",
        "recipient": recipient,
        "subject": subject,
        "body": body,
        "trigger_entity": {"kind": trigger_kind, "id": trigger_id},
        "trigger_id": f"{trigger_kind}:{trigger_id}",
        "delivered": status == "sent",
        "delivery_status": status,
        "provider": provider,
        "provider_response_id": provider_response_id,
        "error": error,
        "created_at": now_iso(),
    })


async def _fire_internal_notification(lead: Dict[str, Any], cfg: Dict[str, Any],
                                        reject_state: Optional[str]) -> None:
    from services.email.resend_adapter import send as _send_email
    from services.sms.rc_adapter import send as _send_sms
    composed = _compose_internal(lead, cfg, reject_state)
    lid = lead.get("id") or ""

    # Email
    try:
        res = await _send_email(
            to=cfg["email"], subject=composed["subject"],
            html=composed["body"].replace("\n", "<br>"),
            category="transactional",
            tenant_id=lead.get("tenant_id"),
            idempotency_key=f"lead-internal:{lid}:email",
        )
        ok = (res or {}).get("provider_status") in ("sent", "mocked")
        await _log_row(
            tenant_id=lead["tenant_id"], channel="email",
            recipient=cfg["email"], subject=composed["subject"],
            body=composed["body"], provider="resend",
            trigger_kind="lead_created_internal_notification", trigger_id=lid,
            status="sent" if ok else "failed",
            error=None if ok else (res or {}).get("error"),
            provider_response_id=(res or {}).get("provider_response_id"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[lead-internal] email raised lid=%s: %s", lid, exc)
        await _log_row(
            tenant_id=lead["tenant_id"], channel="email",
            recipient=cfg["email"], subject=composed["subject"],
            body=composed["body"], provider="resend",
            trigger_kind="lead_created_internal_notification", trigger_id=lid,
            status="failed", error=str(exc),
        )

    # SMS
    try:
        res = await _send_sms(
            to=cfg["sms"], body=composed["body"],
            category="transactional",
            tenant_id=lead.get("tenant_id"),
            idempotency_key=f"lead-internal:{lid}:sms",
        )
        ok = (res or {}).get("provider_status") in ("sent", "mocked")
        await _log_row(
            tenant_id=lead["tenant_id"], channel="sms",
            recipient=cfg["sms"], subject=None,
            body=composed["body"], provider="ringcentral",
            trigger_kind="lead_created_internal_notification", trigger_id=lid,
            status="sent" if ok else "failed",
            error=None if ok else (res or {}).get("error"),
            provider_response_id=(res or {}).get("provider_response_id"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[lead-internal] sms raised lid=%s: %s", lid, exc)
        await _log_row(
            tenant_id=lead["tenant_id"], channel="sms",
            recipient=cfg["sms"], subject=None,
            body=composed["body"], provider="ringcentral",
            trigger_kind="lead_created_internal_notification", trigger_id=lid,
            status="failed", error=str(exc),
        )


async def _fire_customer_reject_reply(lead: Dict[str, Any],
                                        reject_state: str) -> None:
    """Auto-reply to the submitter that their address is out of the
    serviced area. Silent no-op when the lead has no email."""
    from services.email.resend_adapter import send as _send_email
    to_addr = (lead.get("email") or "").strip()
    if not to_addr:
        return
    subject = "Thanks for reaching out"
    body = (
        f"Hi {(lead.get('first_name') or lead.get('name') or 'there').split()[0]},\n\n"
        "Thanks for reaching out — unfortunately we don't currently service "
        f"your area ({reject_state}). We'll keep your info on file if that "
        "changes.\n\n— Pool & Landscaping of Vistancia Team"
    )
    lid = lead.get("id") or ""
    try:
        res = await _send_email(
            to=to_addr, subject=subject,
            html=body.replace("\n", "<br>"), category="transactional",
            tenant_id=lead.get("tenant_id"),
            idempotency_key=f"lead-reject-reply:{lid}",
        )
        ok = (res or {}).get("provider_status") in ("sent", "mocked")
        await _log_row(
            tenant_id=lead["tenant_id"], channel="email",
            recipient=to_addr, subject=subject, body=body,
            provider="resend",
            trigger_kind="lead_out_of_state_auto_reply", trigger_id=lid,
            status="sent" if ok else "failed",
            error=None if ok else (res or {}).get("error"),
            provider_response_id=(res or {}).get("provider_response_id"),
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("[lead-reject-reply] raised lid=%s: %s", lid, exc)
        await _log_row(
            tenant_id=lead["tenant_id"], channel="email",
            recipient=to_addr, subject=subject, body=body, provider="resend",
            trigger_kind="lead_out_of_state_auto_reply", trigger_id=lid,
            status="failed", error=str(exc),
        )


async def apply_lead_post_create(lead: Dict[str, Any]) -> Dict[str, Any]:
    """The single side-effect entry point every lead-create path calls
    AFTER inserting the lead row. Returns a dict of updates the caller
    should merge back onto the lead doc (``status``, ``rejected_*``).
    Safe to call from either the admin or public path."""
    cfg = await _tenant_config(lead["tenant_id"])

    # 1. Detect out-of-state.
    state = _extract_state(lead)
    reject_state: Optional[str] = None
    if state and state not in cfg["serviced_states"]:
        reject_state = state

    # 2. Fire internal notification (F) — always, with reject header if applicable.
    if cfg.get("enabled", True):
        try:
            await _fire_internal_notification(lead, cfg, reject_state)
        except Exception as exc:  # pragma: no cover - already caught internally
            logger.warning("[lead-post-create] internal notify crashed: %s", exc)

    # 3. Reject flow (E) — updates + customer auto-reply.
    updates: Dict[str, Any] = {}
    if reject_state:
        stamp = now_iso()
        updates.update({
            "status": "rejected",
            "rejected_reason": "out_of_state",
            "rejected_state": reject_state,
            "rejected_at": stamp,
        })
        await db.leads.update_one(
            {"id": lead["id"], "tenant_id": lead["tenant_id"]},
            {"$set": updates},
        )
        try:
            await _fire_customer_reject_reply(lead, reject_state)
        except Exception as exc:  # pragma: no cover
            logger.warning("[lead-post-create] reject reply crashed: %s", exc)
    return updates
