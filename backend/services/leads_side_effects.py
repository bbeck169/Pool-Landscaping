"""Phase 16 · Additions E + F · Feb-2026 — Lead post-create side effects.

Called from every lead-create path (``POST /api/leads`` admin manual
and ``POST /api/public/leads`` public form). Two concerns handled
here in a specific order so downstream reasoning is deterministic:

1. **Brian's internal notification (Addition F)** — fires FIRST so
   Brian sees every inbound, including rejects. Email to
   ``brian@plofv.com`` by default (sourced from
   ``tenant.internal_lead_notifications.email`` when the admin has
   overridden) + SMS to
   ``tenant.internal_lead_notifications.sms`` when set — the SMS
   branch short-circuits with an info log when the tenant has no
   configured number (Phase PHONE-PURGE · Feb-2026 removed the
   hardcoded fallback). Best-effort — a Resend/RC failure is
   captured as a ``failed`` row on ``marketing_deliveries`` but
   does not raise.

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
# Phase PHONE-PURGE · Feb-2026 — removed hardcoded plofv-internal
# SMS fallback. Internal SMS recipient now sources ONLY from
# ``tenant.internal_lead_notifications.sms``. Tenants without a
# configured number get email-only notifications (SMS branch
# short-circuits with an info log — see ``_fire_internal_notification``).
_DEFAULT_SERVICED_STATES = ["AZ"]
_PHX = ZoneInfo("America/Phoenix")

# US state abbreviation regex — pulls the 2-letter code out of a
# free-form address if the caller didn't supply it separately. We
# accept 3+ digit ZIPs before/after, comma separators, etc.
# Feb-2026 · Tightened tail-of-address matching. The previous
# heuristic matched ANY 2 uppercase letters at end-of-string, which
# turned "123 Test St" → state "ST" (a street-suffix false
# positive that auto-rejected legitimate leads). The parser now:
#   1. Matches against the RAW address (preserves case) so only
#      real uppercase codes match; street suffixes typed in title
#      case ("St", "Ave", "Rd") no longer trip the tail branch.
#   2. Validates the captured code against a whitelist of real US
#      state abbreviations. "ST" / "AV" / "RD" / "PL" etc. are
#      all NOT states and are dropped.
_STATE_RE = re.compile(r"\b([A-Z]{2})\b(?=\s+\d{5}|\s*,?\s*\d{5}|\s*$)")

_US_STATE_CODES = frozenset({
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
})


def _extract_state(lead: Dict[str, Any]) -> Optional[str]:
    """Extract a 2-letter US state code from the lead's stored state
    field or from the tail of the free-form service_address. Returns
    uppercase or None when nothing plausible found.

    Feb-2026 hardening — the free-form parse runs against the RAW
    address (case preserved) AND the captured token is validated
    against ``_US_STATE_CODES``. Any 2-letter word boundary that
    isn't a real state (e.g. street suffixes like "St", "Rd", or
    typos like "SW") is dropped so it can never auto-reject a
    legitimate lead."""
    explicit = (lead.get("state") or "").strip().upper()
    if len(explicit) == 2 and explicit.isalpha() and explicit in _US_STATE_CODES:
        return explicit
    addr = (lead.get("service_address") or lead.get("address") or "")
    if not addr:
        return None
    m = _STATE_RE.search(addr)
    if not m:
        return None
    code = m.group(1).upper()
    return code if code in _US_STATE_CODES else None


async def _tenant_config(tenant_id: str) -> Dict[str, Any]:
    t = await db.tenants.find_one({"id": tenant_id}, {"_id": 0}) or {}
    notif = (t.get("internal_lead_notifications") or {})
    return {
        "email": notif.get("email") or _DEFAULT_INTERNAL_EMAIL,
        # Phase PHONE-PURGE · Feb-2026 — no hardcoded fallback. Empty
        # string here signals the SMS branch downstream to short-circuit
        # with an info log rather than dial a stale number.
        "sms": notif.get("sms") or "",
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

    # Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — DB-first render for
    # the internal admin-alert HTML body.  Prefer the
    # ``lead_internal_admin_alert_email`` row in ``marketing_templates``
    # (tenant-specific > global default); fall through to the
    # newline→<br> conversion of ``composed['body']`` when the row
    # is absent OR the render blows up.  Subject stays composed
    # inline (the "[New lead] Name" / "[REJECTED] Name" convention
    # is not tenant-editable).
    email_html = composed["body"].replace("\n", "<br>")
    try:
        from services.marketing_template_lookup import (
            get_template_with_global_fallback,
        )
        from services.marketing.merge_tags import render_template
        tpl = await get_template_with_global_fallback(
            "lead_internal_admin_alert_email",
            lead.get("tenant_id") or None,
        )
        if tpl and tpl.get("body"):
            name = lead.get("name") or "".join(filter(None, [
                (lead.get("first_name") or "").strip(),
                (lead.get("last_name") or "").strip(),
            ])).strip() or "(no name)"
            addr = lead.get("service_address") or lead.get("address") or ""
            msg = lead.get("message") or lead.get("service_interest") or ""
            link = f"{cfg['app_host']}/leads/{lead.get('id')}"
            ctx = {
                "tenant": {"id": lead.get("tenant_id") or ""},
                "customer": {},
                "lead": lead,
                "lead_name": name,
                "lead_email": lead.get("email") or "",
                "lead_phone": lead.get("phone") or "",
                "lead_source": lead.get("source") or "unknown",
                "lead_message": msg,
                "lead_time_label": _fmt_phx(
                    lead.get("created_at") or now_iso(),
                ),
                "lead_link": link,
                "property_address": addr,
                "lead_reject_header": (
                    f"STATUS: REJECTED — out of state ({reject_state})"
                    if reject_state else ""
                ),
            }
            rendered_body, _ = render_template(
                tpl["body"], ctx, missing="empty",
            )
            if rendered_body:
                email_html = rendered_body
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "[lead-internal] template render failed — using hardcoded "
            "fallback lid=%s: %s", lid, exc,
        )

    # Email
    try:
        res = await _send_email(
            to=cfg["email"], subject=composed["subject"],
            html=email_html,
            category="transactional",
            tenant_id=lead.get("tenant_id"),
            idempotency_key=f"lead-internal:{lid}:email",
            # Phase K72 · Feb-2026 — internal admin notification.
            audience="internal",
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
    # Phase PHONE-PURGE · Feb-2026 — no hardcoded fallback. Skip
    # the SMS branch entirely when the tenant has no configured
    # internal-notification number; the email branch above still
    # fires so Brian / dispatcher still sees every inbound lead.
    if not cfg.get("sms"):
        logger.info(
            "[lead-internal] no tenant.internal_lead_notifications.sms "
            "configured — skipping internal SMS for lid=%s tenant=%s",
            lid, lead.get("tenant_id"),
        )
        return
    try:
        res = await _send_sms(
            to=cfg["sms"], body=composed["body"],
            category="transactional",
            tenant_id=lead.get("tenant_id"),
            idempotency_key=f"lead-internal:{lid}:sms",
            # Phase K72 · Feb-2026 — internal admin SMS notification.
            audience="internal",
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
    serviced area. Silent no-op when the lead has no email.

    Phase EMAIL-MIGRATE · Batch 2 · Feb-2026 — the body prefers the
    ``lead_thank_you_reply_email`` row in ``marketing_templates``
    (tenant-specific > global default) so tenants can rebrand the
    auto-reply.  Falls through to the hardcoded body when the row
    is absent OR the render fails.  The subject stays plain English
    (no i18n dependency for this branch).
    """
    from services.email.resend_adapter import send as _send_email
    to_addr = (lead.get("email") or "").strip()
    if not to_addr:
        return
    subject = "Thanks for reaching out"
    first_name = (
        lead.get("first_name")
        or lead.get("name")
        or "there"
    ).split()[0]
    # Fallback body (used when no DB row exists or the render blows up).
    fallback_body = (
        f"Hi {first_name},\n\n"
        "Thanks for reaching out — unfortunately we don't currently service "
        f"your area ({reject_state}). We'll keep your info on file if that "
        "changes.\n\n— Pool & Landscaping of Vistancia Team"
    )
    body_html = fallback_body.replace("\n", "<br>")
    tenant_id = lead.get("tenant_id") or ""
    try:
        from services.marketing_template_lookup import (
            get_template_with_global_fallback,
        )
        from services.marketing.merge_tags import render_template
        tpl = await get_template_with_global_fallback(
            "lead_thank_you_reply_email", tenant_id or None,
        )
        if tpl and tpl.get("body"):
            tenant_doc = await db.tenants.find_one(
                {"id": tenant_id}, {"_id": 0},
            ) if tenant_id else None
            ctx = {
                "tenant": tenant_doc or {},
                "customer": {},
                "recipient_name": first_name,
                "reject_state": reject_state,
            }
            rendered_subject, _ = render_template(
                tpl.get("subject") or subject, ctx, missing="empty",
            )
            rendered_body, _ = render_template(
                tpl["body"], ctx, missing="empty",
            )
            if rendered_body:
                subject = rendered_subject or subject
                body_html = rendered_body
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "[lead-reject-reply] template render failed — using "
            "hardcoded fallback lid=%s: %s", lead.get("id"), exc,
        )
    lid = lead.get("id") or ""
    body = fallback_body
    try:
        res = await _send_email(
            to=to_addr, subject=subject,
            html=body_html, category="transactional",
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
