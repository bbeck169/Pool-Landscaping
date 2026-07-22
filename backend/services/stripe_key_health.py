"""Phase 4B follow-up · Feb 2026 — daily Stripe live-key health alert.

Runs once a day at 08:00 America/Phoenix (falls back to 15:00 UTC when
the ``zoneinfo`` stdlib module isn't available). Calls
``stripe.Account.retrieve()`` internally, and if Stripe refuses the key
(most commonly ``AuthenticationError`` from an expired/rotated key),
fans out an alert to tenant admins via the shipped Resend + Twilio
adapters — same code paths used by the rest of the app so any tenant
suppressions / transactional overrides continue to apply.

The scheduler wire-up lives in ``server.py`` (see the
``stripe_key_daily_health`` job registration next to the other
``scheduler.add_job(...)`` calls). Registration is a no-op when
``STRIPE_MODE`` is anything other than ``"live"``.

Idempotency
-----------
The job is safe to invoke repeatedly. We stash the last alert timestamp
and error-type hash in the ``ops_alerts_state`` collection keyed by
``kind="stripe_key_alert"``. If the same error signature reoccurs
within 4 hours we short-circuit — no email / SMS burst.

Alert body shape
----------------
Email::

    Subject: [URGENT] Stripe live key issue — customers cannot pay

    Stripe rejected the live key.

    Mode          : live
    Account (masked): acct_1…H4Ay
    Detected at   : 2026-02-15T15:00:04+00:00
    Error type    : AuthenticationError
    Error message : Expired API Key provided: sk_…Mtod

    Action:
      1. Rotate the sk_live key in the Stripe Dashboard.
      2. Update /app/backend/.env  →  STRIPE_SECRET_KEY=<new value>
      3. sudo supervisorctl restart backend
      4. Confirm with POST /api/dev/stripe-live-ping (admin).

    Until then, the Pay Now button will return a 502 to customers.

SMS::

    Pool & Landscaping of Vistancia — Stripe live key expired
    (AuthenticationError). Rotate ASAP; Pay Now is broken.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso

# 4h suppression window per user brief.
_IDEMPOTENCY_WINDOW = timedelta(hours=4)


def _mask_account(aid: Optional[str]) -> str:
    if not aid:
        return "(unset)"
    return f"{aid[:6]}…{aid[-4:]}" if len(aid) >= 10 else aid


def _err_hash(error_type: Optional[str], error_message: Optional[str]) -> str:
    payload = f"{error_type or ''}::{(error_message or '')[:180]}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


async def _ping_stripe() -> Dict[str, Any]:
    """Invoke ``stripe.Account.retrieve`` in-process. Never raises;
    always returns a shaped dict — mirrors the shape of the
    ``/api/dev/stripe-live-ping`` endpoint."""
    from services.stripe_client import get_stripe, is_configured, mode as _mode

    if not is_configured():
        return {
            "ok": False,
            "error_type": "not_configured",
            "error_message": "Stripe SDK is not configured.",
            "mode": _mode(),
        }
    stripe = get_stripe()
    try:
        acct = stripe.Account.retrieve()
    except Exception as exc:
        raw = str(exc)
        for banned in ("sk_live_", "sk_test_", "rk_live_", "rk_test_", "whsec_"):
            raw = raw.replace(banned, banned[:3] + "…")
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error_message": raw[:400],
            "mode": _mode(),
        }
    _get = (lambda o, k, d=None: o.get(k, d) if isinstance(o, dict)
             else getattr(o, k, d))
    return {
        "ok": True,
        "account_id": _get(acct, "id"),
        "charges_enabled": bool(_get(acct, "charges_enabled")),
        "payouts_enabled": bool(_get(acct, "payouts_enabled")),
        "mode": _mode(),
    }


async def _should_suppress(tenant_id: str, sig: str) -> bool:
    row = await db.ops_alerts_state.find_one(
        {"tenant_id": tenant_id, "kind": "stripe_key_alert"},
        {"_id": 0, "last_error_hash": 1, "last_sent_at": 1},
    )
    if not row:
        return False
    if row.get("last_error_hash") != sig:
        return False
    last = row.get("last_sent_at")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
    except Exception:
        return False
    return datetime.now(timezone.utc) - last_dt < _IDEMPOTENCY_WINDOW


async def _record_alert_state(tenant_id: str, sig: str) -> None:
    await db.ops_alerts_state.update_one(
        {"tenant_id": tenant_id, "kind": "stripe_key_alert"},
        {"$set": {
            "tenant_id": tenant_id,
            "kind": "stripe_key_alert",
            "last_error_hash": sig,
            "last_sent_at": now_iso(),
        }},
        upsert=True,
    )


async def _record_delivery(*, tenant_id: str, channel: str,
                            recipient: str, subject: Optional[str],
                            body: str, provider_res: Dict[str, Any],
                            trigger_id: str) -> None:
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "kind": "transactional",
        "trigger_entity": {"kind": "stripe_key_alert", "id": trigger_id},
        "customer_id": None,
        "channel": channel,
        "subject_rendered": subject or "",
        "body_rendered": body,
        "provider": provider_res.get("provider"),
        "provider_status": provider_res.get("provider_status"),
        "provider_response_id": provider_res.get("provider_response_id"),
        "attempts": provider_res.get("attempts") or 1,
        "mock": provider_res.get("provider") == "mock",
        "sent_at": now_iso(),
    }
    if channel == "email":
        doc["recipient_email"] = recipient
    else:
        doc["recipient_phone"] = recipient
    try:
        await db.marketing_deliveries.insert_one(doc)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"[stripe-key-alert] marketing_deliveries insert failed: {exc}")


def _build_email_html(mode: str, acct_masked: str, ts_iso: str,
                      err_type: str, err_msg: str) -> str:
    return (
        "<div style=\"font-family:Inter,Arial,sans-serif;max-width:620px;\">"
        "<h2 style=\"color:#991B1B;margin:0 0 8px;\">Stripe live key issue — Pay Now is broken.</h2>"
        f"<p><b>Mode</b>: {mode}</p>"
        f"<p><b>Account (masked)</b>: <code>{acct_masked}</code></p>"
        f"<p><b>Detected at</b>: {ts_iso}</p>"
        f"<p><b>Error type</b>: <code>{err_type}</code></p>"
        f"<p><b>Error message</b>: <code>{err_msg}</code></p>"
        "<hr style=\"border:none;border-top:1px solid #E2E8F0;margin:16px 0\">"
        "<p><b>Action</b>:</p>"
        "<ol style=\"margin:0 0 8px 20px;padding:0;\">"
        "<li>Rotate the <code>sk_live</code> key in the Stripe Dashboard.</li>"
        "<li>Update <code>/app/backend/.env</code> → <code>STRIPE_SECRET_KEY=&lt;new value&gt;</code>.</li>"
        "<li><code>sudo supervisorctl restart backend</code>.</li>"
        "<li>Confirm with <code>POST /api/dev/stripe-live-ping</code> (admin).</li>"
        "</ol>"
        "<p style=\"color:#64748B;font-size:12px;margin-top:16px;\">"
        "Until then, the Pay Now button will return a 502 to customers.</p>"
        "</div>"
    )


def _build_sms(err_type: str) -> str:
    return (
        f"Pool & Landscaping of Vistancia — Stripe live key expired "
        f"({err_type}). Rotate ASAP; Pay Now is broken."
    )


async def _resolve_recipients(tenant: dict) -> Dict[str, List[str]]:
    """Emails + SMS numbers to alert for a given tenant.
    * emails: every user with role in {admin, super_admin}.
    * sms:    ``tenant.sms_escalation_recipients`` first; else first
              admin user's phone if set."""
    tid = tenant["id"]
    users = await db.users.find(
        {"tenant_id": tid, "role": {"$in": ["admin", "super_admin"]},
         "active": {"$ne": False}},
        {"_id": 0, "email": 1, "phone": 1, "role": 1},
    ).to_list(50)
    emails = [u["email"] for u in users if u.get("email")]
    sms = list(tenant.get("sms_escalation_recipients") or [])
    if not sms:
        for u in users:
            if u.get("phone"):
                sms = [u["phone"]]
                break
    return {"emails": emails, "sms": sms}


async def _alert_tenant(tenant: dict, ping: Dict[str, Any], ts_iso: str) -> Dict[str, int]:
    """Fan out email + SMS. Records marketing_deliveries rows."""
    err_type = ping.get("error_type") or "unknown"
    err_msg = ping.get("error_message") or ""
    acct = _mask_account(os.getenv("STRIPE_ACCOUNT_ID") or "")
    mode = ping.get("mode") or "live"
    subject = "[URGENT] Stripe live key issue — customers cannot pay"
    html = _build_email_html(mode, acct, ts_iso, err_type, err_msg)
    sms_body = _build_sms(err_type)
    trigger_id = ts_iso
    recipients = await _resolve_recipients(tenant)
    sent_email = 0
    sent_sms = 0

    resend_key = os.environ.get("RESEND_API_KEY") or ""
    if not resend_key:
        logger.warning("[stripe-key-alert] RESEND_API_KEY missing — email fanout skipped")
    else:
        from services.email.resend_adapter import send as _send_email
        for em in recipients["emails"]:
            try:
                res = await _send_email(
                    to=em, subject=subject, html=html,
                    category="transactional", tenant_id=tenant["id"],
                    idempotency_key=f"stripe-key-alert:{tenant['id']}:{ts_iso[:13]}",
                )
                await _record_delivery(
                    tenant_id=tenant["id"], channel="email",
                    recipient=em, subject=subject, body=html,
                    provider_res=res, trigger_id=trigger_id,
                )
                sent_email += 1
            except Exception as exc:  # pragma: no cover
                logger.warning(f"[stripe-key-alert] email send failed: {exc}")

    twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID") or ""
    if not twilio_sid:
        logger.warning("[stripe-key-alert] TWILIO_ACCOUNT_SID missing — SMS fanout skipped")
    else:
        from services.sms.twilio_adapter import send as _send_sms
        for phone in recipients["sms"]:
            try:
                res = await _send_sms(
                    to=phone, body=sms_body,
                    category="transactional", tenant_id=tenant["id"],
                    idempotency_key=f"stripe-key-alert:{tenant['id']}:{ts_iso[:13]}",
                )
                await _record_delivery(
                    tenant_id=tenant["id"], channel="sms",
                    recipient=phone, subject=None, body=sms_body,
                    provider_res=res, trigger_id=trigger_id,
                )
                sent_sms += 1
            except Exception as exc:  # pragma: no cover
                logger.warning(f"[stripe-key-alert] sms send failed: {exc}")

    return {"email": sent_email, "sms": sent_sms}


async def run_stripe_key_health_scan() -> Dict[str, Any]:
    """APScheduler entry point. See module docstring for shape."""
    mode = (os.environ.get("STRIPE_MODE") or "").lower()
    if mode != "live":
        logger.info(f"[stripe-key-alert] skip: STRIPE_MODE={mode or '(unset)'}")
        return {"skipped": True, "reason": "not_live_mode"}
    ping = await _ping_stripe()
    if ping.get("ok"):
        logger.info(
            f"[stripe-key-alert] OK — account={ping.get('account_id')} "
            f"charges_enabled={ping.get('charges_enabled')}"
        )
        return {"ok": True, "alerted": False, "account_id": ping.get("account_id"),
                 "ping": ping, "email_sent": 0, "sms_sent": 0,
                 "cooldown_active": False}
    logger.warning(
        f"[stripe-key-alert] FAIL type={ping.get('error_type')} "
        f"msg={(ping.get('error_message') or '')[:200]}"
    )
    sig = _err_hash(ping.get("error_type"), ping.get("error_message"))
    ts_iso = now_iso()
    fanned: Dict[str, int] = {"email": 0, "sms": 0}
    tenants_alerted = 0
    tenants_suppressed = 0
    earliest_expiry: Optional[datetime] = None
    async for t in db.tenants.find(
        {"active": {"$ne": False}}, {"_id": 0, "id": 1, "sms_escalation_recipients": 1},
    ):
        if await _should_suppress(t["id"], sig):
            tenants_suppressed += 1
            # Track when the cooldown expires (for the manual-run response).
            row = await db.ops_alerts_state.find_one(
                {"tenant_id": t["id"], "kind": "stripe_key_alert"},
                {"_id": 0, "last_sent_at": 1},
            ) or {}
            last = row.get("last_sent_at")
            if last:
                try:
                    last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                    exp = last_dt + _IDEMPOTENCY_WINDOW
                    if earliest_expiry is None or exp < earliest_expiry:
                        earliest_expiry = exp
                except Exception:
                    pass
            continue
        counts = await _alert_tenant(t, ping, ts_iso)
        await _record_alert_state(t["id"], sig)
        fanned["email"] += counts["email"]
        fanned["sms"] += counts["sms"]
        tenants_alerted += 1
    return {
        "ok": False,
        "alerted": tenants_alerted > 0,
        "tenants_alerted": tenants_alerted,
        "tenants_suppressed": tenants_suppressed,
        "cooldown_active": tenants_alerted == 0 and tenants_suppressed > 0,
        "cooldown_expires_at": (
            earliest_expiry.isoformat().replace("+00:00", "Z")
            if earliest_expiry else None
        ),
        "email_sent": fanned["email"],
        "sms_sent": fanned["sms"],
        "signature": sig,
        "ping": ping,
    }
