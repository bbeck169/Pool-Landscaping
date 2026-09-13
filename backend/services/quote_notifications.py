"""
Feb-2026 · Phase B — Quote / Estimate approve + decline notifications.

Extends the bell-only fanout from ``estimate_viewer._notify_admins`` with
email + SMS dispatch to tenant admins when a customer approves or
declines a quote/estimate. Kept in a dedicated service so:

  1. The 6 call-sites (auth'd approve/decline + magic-link approve/decline
     + top-level via-token approve/decline) share one implementation.
  2. Recipient resolution / rate-limiting / audit logging live in one
     place, not spread across the router.
  3. Vitest + backend tests can exercise it without spinning up the
     full FastAPI app.

Behaviour contract (per human-locked scoping memo):

  * Recipients come from ``tenant.lead_notification_recipients`` — the
    same rich-shape list Phase K63 already ships (opt-in email + phone
    per row). Falls back to workforce-admin user emails / phones when
    the tenant list is empty. Logs a WARN when neither resolves.

  * Approve always dispatches. Decline is gated on the tenant's
    ``notify_admin_on_decline`` boolean (default True).

  * Per-line decline events do NOT dispatch here (deferred to Phase C).
    Only the two top-level events call ``notify_quote_decision`` — the
    per-line endpoints just update state.

  * Fire-and-forget: dispatch is scheduled onto ``BackgroundTasks``
    (or awaited in tests via ``_run_now``) and callers return 200
    regardless of email/SMS outcome. Every attempt lands in
    ``db.comms_send_log`` with ``status`` in
    ``{"sent","failed","rate_limited","suppressed"}``.

  * Rate limit: max 3 sends per (tenant_id, doc_id, kind, channel) per
    hour to defend against retry storms. The 4th write into the log
    is a ``status=rate_limited`` row so admins can see the skipped
    attempt in the diagnostics table.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config import db

logger = logging.getLogger("services.quote_notifications")


# ── Rate-limit knob (per doc, per event, per channel) ────────────
_RATE_LIMIT_MAX = 3
_RATE_LIMIT_WINDOW = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _short_id(doc_id: Optional[str]) -> str:
    """First 8 chars of the UUID — used in email subject + SMS body."""
    return (doc_id or "")[:8].upper()


# ── Recipient resolution ─────────────────────────────────────────

async def resolve_recipients(tenant: Dict[str, Any]) -> Tuple[
    List[Dict[str, str]], str,
]:
    """Return ``(recipients, source)`` where each recipient is a dict
    with ``email`` (str or "") and ``phone`` (E.164 str or "").

    ``source`` is either ``"tenant_settings"`` when the rich-shape
    ``lead_notification_recipients`` list yielded any rows, or
    ``"workforce_admins"`` when we fell back to the admin user pool.

    A recipient can opt-out of a specific channel per K63 — we honour
    ``email_on`` / ``sms_on`` flags on each row.
    """
    tid = tenant.get("id") if isinstance(tenant, dict) else None
    rows = tenant.get("lead_notification_recipients") or [] if tenant else []

    out: List[Dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        email = (row.get("email") or "").strip()
        phone = (row.get("phone") or "").strip()
        email_on = bool(row.get("email_on", True)) if email else False
        sms_on = bool(row.get("sms_on", True)) if phone else False
        if not (email_on or sms_on):
            continue
        out.append({
            "email": email if email_on else "",
            "phone": phone if sms_on else "",
            "name": (row.get("name") or "").strip(),
        })
    if out:
        return out, "tenant_settings"

    # Fallback — workforce admins with email / phone.
    if not tid:
        return [], "workforce_admins"
    admins = await db.users.find(
        {"tenant_id": tid,
          "role": {"$in": ["admin", "super_admin"]}},
        {"_id": 0, "id": 1, "email": 1, "phone": 1, "name": 1},
    ).to_list(50)
    for u in admins:
        email = (u.get("email") or "").strip()
        phone = (u.get("phone") or "").strip()
        if not (email or phone):
            continue
        out.append({
            "email": email,
            "phone": phone,
            "name": (u.get("name") or "").strip(),
        })
    return out, "workforce_admins"


# ── Rate limiting via comms_send_log ─────────────────────────────

async def _is_rate_limited(*, tenant_id: str, doc_id: str, kind: str,
                             channel: str) -> bool:
    """True when ≥ ``_RATE_LIMIT_MAX`` successful sends have already
    landed for this (tenant, doc, kind, channel) inside the rolling
    hour window."""
    since = (_now() - _RATE_LIMIT_WINDOW).isoformat()
    q = {
        "tenant_id": tenant_id,
        "doc_id": doc_id,
        "kind": kind,
        "channel": channel,
        "status": {"$in": ["sent", "queued"]},
        "created_at": {"$gte": since},
    }
    count = await db.comms_send_log.count_documents(q)
    return count >= _RATE_LIMIT_MAX


async def _log_send(*, tenant_id: str, doc_id: str, kind: str,
                     channel: str, recipient: str, status: str,
                     error: Optional[str] = None,
                     provider_id: Optional[str] = None) -> None:
    """Redact-friendly row writer. Mirrors the K63 lead notification
    audit shape but keeps the ``kind`` + ``doc_id`` fields the tester
    checklist reads back out."""
    try:
        await db.comms_send_log.insert_one({
            "tenant_id": tenant_id,
            "doc_id": doc_id,
            "kind": kind,
            "channel": channel,
            "recipient": recipient,
            "status": status,
            "error": error,
            "provider_id": provider_id,
            "created_at": _now().isoformat(),
        })
    except Exception:  # pragma: no cover — audit is best-effort
        logger.exception("comms_send_log insert failed")


# ── Template rendering ───────────────────────────────────────────

def _doc_label(doc_type: str) -> str:
    return "Quote" if doc_type == "quote" else "Estimate"


def _admin_href(*, doc_type: str, doc_id: str,
                  frontend_origin: str) -> str:
    """Return an absolute-URL deep link to the admin doc view."""
    base = (frontend_origin or "").rstrip("/")
    path = ("/invoices/" if doc_type == "invoice"
            else "/quotes/") + doc_id
    return f"{base}{path}" if base else path


def render_email(*, event: str, doc_type: str, doc: Dict[str, Any],
                    frontend_origin: str) -> Tuple[str, str, str]:
    """Return ``(subject, html, text)`` for the given event."""
    doc_id = doc.get("id") or ""
    customer_name = doc.get("customer_name") or "a customer"
    total = doc.get("total") or 0
    try:
        total_str = f"${float(total):,.2f}"
    except (TypeError, ValueError):
        total_str = str(total)
    label = _doc_label(doc_type)
    href = _admin_href(doc_type=doc_type, doc_id=doc_id,
                        frontend_origin=frontend_origin)
    short = _short_id(doc_id)

    if event == "quote_accepted":
        subject = f"[{label} #{short}] Accepted by {customer_name}"
        headline = f"{customer_name} accepted {label.lower()} #{short}."
    else:  # quote_declined
        subject = f"[{label} #{short}] Declined by {customer_name}"
        headline = f"{customer_name} declined {label.lower()} #{short}."
        reason = (doc.get("decline_reason") or "").strip()
        if reason:
            headline += f" Reason: {reason}"

    html = (
        f"<div style=\"font-family:system-ui,sans-serif;font-size:14px\">"
        f"<p>{headline}</p>"
        f"<p><strong>Total:</strong> {total_str}<br/>"
        f"<strong>{label}:</strong> #{short}<br/>"
        f"<strong>Customer:</strong> {customer_name}</p>"
        f"<p><a href=\"{href}\">Open {label.lower()} in admin →</a></p>"
        f"</div>"
    )
    text = (
        f"{headline}\n\n"
        f"Total: {total_str}\n"
        f"{label}: #{short}\n"
        f"Customer: {customer_name}\n"
        f"Open in admin: {href}\n"
    )
    return subject, html, text


def render_sms(*, event: str, doc_type: str, doc: Dict[str, Any],
                 frontend_origin: str) -> str:
    """Return a ≤160-char SMS body."""
    doc_id = doc.get("id") or ""
    customer_name = doc.get("customer_name") or "customer"
    total = doc.get("total") or 0
    try:
        total_str = f"${float(total):,.0f}"
    except (TypeError, ValueError):
        total_str = str(total)
    label = _doc_label(doc_type)
    short = _short_id(doc_id)
    verb = "accepted" if event == "quote_accepted" else "declined"
    href = _admin_href(doc_type=doc_type, doc_id=doc_id,
                         frontend_origin=frontend_origin)
    body = f"{customer_name} {verb} {label} #{short} ({total_str}). {href}"
    return body[:160]


# ── Public entry point ───────────────────────────────────────────

async def notify_quote_decision(
    *,
    tenant: Dict[str, Any],
    doc: Dict[str, Any],
    event: str,
    actor_id: Optional[str] = None,
    frontend_origin: str = "",
) -> Dict[str, Any]:
    """Dispatch email + SMS to tenant admins for a top-level
    approve/decline. Returns a summary dict for tests + observability.

    ``event`` must be one of ``quote_accepted`` / ``quote_declined``.
    """
    if event not in ("quote_accepted", "quote_declined"):
        raise ValueError(f"unsupported event {event!r}")

    tenant_id = tenant.get("id")
    doc_id = doc.get("id")
    doc_type = doc.get("doc_type") or "quote"
    if not (tenant_id and doc_id):
        logger.warning(
            "notify_quote_decision: missing tenant/doc id (event=%s)", event,
        )
        return {"skipped": "missing_ids"}

    # Gate the decline path on the tenant toggle (default True).
    if event == "quote_declined":
        allow = tenant.get("notify_admin_on_decline")
        if allow is None:
            allow = True
        if not allow:
            logger.info(
                "notify_quote_decision: decline suppressed by tenant "
                "notify_admin_on_decline=false (tenant=%s doc=%s)",
                tenant_id, doc_id,
            )
            return {"suppressed": "tenant_disabled"}

    recipients, source = await resolve_recipients(tenant)
    if not recipients:
        logger.warning(
            "notify_quote_decision: no recipients resolved "
            "(tenant=%s doc=%s event=%s)",
            tenant_id, doc_id, event,
        )
        return {"skipped": "no_recipients", "source": source}

    subject, html, text = render_email(
        event=event, doc_type=doc_type, doc=doc,
        frontend_origin=frontend_origin,
    )
    # Feb-2026 · Email Base Template Theming — P3 flip.
    # Admin-facing notification also carries brand identity now.
    # Resolve branding ONCE per notification (multi-recipient fan-out
    # below reuses the wrapped html — do NOT re-fetch per recipient).
    try:
        from services.email.theming import wrap_html_in_shell
        from services.tenants.business_settings import (
            get_effective_business_settings,
        )
        _branding = await get_effective_business_settings(
            db, tenant_id, absolutize=True,
        )
        html = wrap_html_in_shell(html, _branding)
    except Exception as _be:  # noqa: BLE001
        logger.warning(
            "notify_quote_decision: branding wrap failed, using "
            "raw html (tenant=%s doc=%s): %s",
            tenant_id, doc_id, _be,
        )
    sms_body = render_sms(
        event=event, doc_type=doc_type, doc=doc,
        frontend_origin=frontend_origin,
    )

    # Lazy imports keep the module import graph light for tests that
    # monkey-patch the adapters.
    from services.email.resend_adapter import send as _send_email
    from services.sms.rc_adapter import send as _send_sms

    email_ok = email_rl = email_fail = 0
    sms_ok = sms_rl = sms_fail = 0

    for r in recipients:
        # ── Email ─────────────────────────────────────────────
        if r.get("email"):
            if await _is_rate_limited(tenant_id=tenant_id, doc_id=doc_id,
                                         kind=event, channel="email"):
                await _log_send(
                    tenant_id=tenant_id, doc_id=doc_id, kind=event,
                    channel="email", recipient=r["email"],
                    status="rate_limited",
                )
                email_rl += 1
            else:
                try:
                    resp = await _send_email(
                        to=r["email"], subject=subject, html=html,
                        text=text,
                        category="transactional",
                        tenant_id=tenant_id,
                        idempotency_key=f"{event}:{doc_id}:{r['email']}",
                        audience="internal",
                        allow_off_allowlist=True,
                    ) or {}
                    status = resp.get("status") or "sent"
                    if status in ("sent", "queued", "mocked",
                                    "test_allowlist_dryrun",
                                    "kill_switch_dryrun"):
                        await _log_send(
                            tenant_id=tenant_id, doc_id=doc_id, kind=event,
                            channel="email", recipient=r["email"],
                            status="sent", provider_id=resp.get("provider_id"),
                        )
                        email_ok += 1
                    else:
                        await _log_send(
                            tenant_id=tenant_id, doc_id=doc_id, kind=event,
                            channel="email", recipient=r["email"],
                            status="failed",
                            error=str(resp.get("error") or status),
                        )
                        email_fail += 1
                except Exception as exc:  # pragma: no cover
                    await _log_send(
                        tenant_id=tenant_id, doc_id=doc_id, kind=event,
                        channel="email", recipient=r["email"],
                        status="failed", error=str(exc),
                    )
                    email_fail += 1

        # ── SMS ───────────────────────────────────────────────
        if r.get("phone"):
            if await _is_rate_limited(tenant_id=tenant_id, doc_id=doc_id,
                                         kind=event, channel="sms"):
                await _log_send(
                    tenant_id=tenant_id, doc_id=doc_id, kind=event,
                    channel="sms", recipient=r["phone"],
                    status="rate_limited",
                )
                sms_rl += 1
            else:
                try:
                    resp = await _send_sms(
                        to=r["phone"], body=sms_body,
                        tenant_id=tenant_id,
                        idempotency_key=f"{event}:{doc_id}:{r['phone']}",
                        category="transactional",
                        audience="internal",
                        allow_off_allowlist=True,
                    ) or {}
                    status = resp.get("status") or "sent"
                    if status in ("sent", "queued", "mocked",
                                    "test_allowlist_dryrun",
                                    "kill_switch_dryrun"):
                        await _log_send(
                            tenant_id=tenant_id, doc_id=doc_id, kind=event,
                            channel="sms", recipient=r["phone"],
                            status="sent",
                            provider_id=resp.get("provider_id"),
                        )
                        sms_ok += 1
                    else:
                        await _log_send(
                            tenant_id=tenant_id, doc_id=doc_id, kind=event,
                            channel="sms", recipient=r["phone"],
                            status="failed",
                            error=str(resp.get("error") or status),
                        )
                        sms_fail += 1
                except Exception as exc:  # pragma: no cover
                    await _log_send(
                        tenant_id=tenant_id, doc_id=doc_id, kind=event,
                        channel="sms", recipient=r["phone"],
                        status="failed", error=str(exc),
                    )
                    sms_fail += 1

    return {
        "tenant_id": tenant_id, "doc_id": doc_id, "event": event,
        "recipient_source": source,
        "recipient_count": len(recipients),
        "email": {"sent": email_ok, "rate_limited": email_rl,
                    "failed": email_fail},
        "sms":   {"sent": sms_ok,   "rate_limited": sms_rl,
                    "failed": sms_fail},
    }
