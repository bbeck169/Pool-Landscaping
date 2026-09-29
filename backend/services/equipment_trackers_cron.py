"""Phase 11 · Feb 2026 — Equipment Service Tracker cron dispatcher.

Runs once per hour on the top of every clock hour. For each tenant,
resolves the tenant's local time (fallback ``America/Phoenix``); when
the local weekday is Monday and the local hour is 08, dispatches the
weekly admin digest and (if enabled) the customer-facing reminders.

Design choices baked in from the Phase 11 spec:
* Per-tenant local-hour dispatch — NEVER a global TZ-blind cron.
* Idempotency: the digest logs one ``outbound_emails`` row per
  ``(tenant_id, iso_week, "equipment_service_digest", recipient_id)``.
* Customer reminders are OFF unless the tenant sets
  ``equipment_service_customer_reminders_enabled = true``.
* Uses uppercase Phase-9 merge tags via
  :func:`services.marketing.merge_tags.render_template` — never inline
  f-string substitution.

Kept independent of :mod:`routers.equipment_trackers` so the router
stays free of any scheduler dependency; the cron is scheduler-owned.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config import db, logger
from services.marketing.merge_tags import render_template, render_context

DEFAULT_TZ = "America/Phoenix"
DIGEST_KIND = "equipment_service_digest"
REMINDER_KIND_EMAIL = "equipment_service_reminder_email"
REMINDER_KIND_SMS = "equipment_service_reminder_sms"


def _iso_week(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y:04d}-W{w:02d}"


def _tenant_tz(tenant: dict) -> str:
    tz = (tenant.get("timezone") or "").strip()
    return tz or DEFAULT_TZ


def _now_local(tenant: dict) -> datetime:
    try:
        return datetime.now(ZoneInfo(_tenant_tz(tenant)))
    except Exception:
        return datetime.now(ZoneInfo(DEFAULT_TZ))


def _add_months_iso(iso_date: str, months: int) -> str:
    from calendar import monthrange
    d = date.fromisoformat(iso_date[:10])
    m = d.month - 1 + int(months)
    y = d.year + m // 12
    mm = m % 12 + 1
    dd = min(d.day, monthrange(y, mm)[1])
    return date(y, mm, dd).isoformat()


def _status(due_at: Optional[str], coming_days: int) -> str:
    if not due_at:
        return "current"
    try:
        due = date.fromisoformat(str(due_at)[:10])
    except (TypeError, ValueError):
        return "current"
    today = date.today()
    if due < today:
        return "past_due"
    if (due - today).days <= int(coming_days or 30):
        return "coming_due"
    return "current"


# ───────────────────── Public entry point (scheduler) ─────────────────
async def hourly_scan() -> Dict[str, Any]:
    """Called by APScheduler every hour on the hour.

    Iterates tenants and checks whether it is Monday 08:00 local time
    for each. Fires the weekly digest + optional customer reminders
    per matching tenant."""
    tenants = await db.tenants.find(
        {},
        {"_id": 0, "id": 1, "name": 1, "timezone": 1,
         "equipment_service_customer_reminders_enabled": 1,
         "equipment_service_coming_due_days": 1},
    ).to_list(1000)
    fired: List[str] = []
    skipped = 0
    for t in tenants:
        try:
            local = _now_local(t)
        except Exception as exc:
            logger.warning(f"[phase11-cron] tz resolve failed for {t.get('id')}: {exc}")
            continue
        if local.weekday() != 0 or local.hour != 8:
            skipped += 1
            continue
        try:
            await run_weekly_for_tenant(t)
            fired.append(t.get("id") or "")
        except Exception as exc:  # pragma: no cover — never break scheduler tick
            logger.warning(f"[phase11-cron] tenant {t.get('id')} run failed: {exc}")
    return {"fired": fired, "skipped": skipped, "total": len(tenants)}


async def run_weekly_for_tenant(tenant: dict) -> Dict[str, Any]:
    """Public helper — also called by manual admin trigger + pytest."""
    coming = int(tenant.get("equipment_service_coming_due_days") or 30) or 30
    trackers = await db.equipment_service_trackers.find(
        {"tenant_id": tenant["id"], "is_active": True}, {"_id": 0},
    ).to_list(5000)
    coming_due: List[dict] = []
    past_due: List[dict] = []
    for r in trackers:
        s = _status(r.get("due_at"), coming)
        if s == "coming_due":
            coming_due.append(r)
        elif s == "past_due":
            past_due.append(r)

    digest_res = await _dispatch_admin_digest(
        tenant, coming_due=coming_due, past_due=past_due,
    )
    reminders_res = {"skipped": True, "reason": "reminders_disabled"}
    if tenant.get("equipment_service_customer_reminders_enabled"):
        reminders_res = await _dispatch_customer_reminders(
            tenant, coming_due=coming_due, past_due=past_due,
        )
    return {
        "tenant_id": tenant["id"],
        "coming_due": len(coming_due),
        "past_due": len(past_due),
        "digest": digest_res,
        "reminders": reminders_res,
    }


# ─────────────────────────── Admin digest ─────────────────────────────
def _row_html(r: dict, cust_map: Dict[str, dict], status: str) -> str:
    c = cust_map.get(r.get("customer_id"), {})
    name = c.get("name") or "—"
    addr = c.get("address") or ""
    label = "Filter" if r.get("tracker_type") == "filter" else \
            "Salt Cell" if r.get("tracker_type") == "salt_cell" else \
            (r.get("tracker_type") or "").replace("_", " ").title()
    color = "#DC2626" if status == "past_due" else "#EA580C"
    return (
        f"<tr><td style='padding:6px 10px'>{label}</td>"
        f"<td style='padding:6px 10px'>{name}</td>"
        f"<td style='padding:6px 10px'>{addr}</td>"
        f"<td style='padding:6px 10px; color:{color}; font-weight:600'>"
        f"{r.get('due_at') or '—'}</td></tr>"
    )


async def _dispatch_admin_digest(
    tenant: dict,
    *,
    coming_due: List[dict],
    past_due: List[dict],
) -> Dict[str, Any]:
    if not coming_due and not past_due:
        return {"skipped": True, "reason": "nothing_due"}

    admins = await db.users.find(
        {"tenant_id": tenant["id"], "role": {"$in": ["admin", "super_admin"]}},
        {"_id": 0, "id": 1, "email": 1, "name": 1},
    ).to_list(200)
    if not admins:
        return {"skipped": True, "reason": "no_admins"}

    cust_ids = list({r.get("customer_id") for r in (coming_due + past_due)
                     if r.get("customer_id")})
    cust_map: Dict[str, dict] = {}
    if cust_ids:
        async for c in db.customers.find(
            {"id": {"$in": cust_ids}, "tenant_id": tenant["id"]},
            {"_id": 0, "id": 1, "name": 1, "address": 1},
        ):
            cust_map[c["id"]] = c

    rows_html = "".join(_row_html(r, cust_map, "past_due") for r in past_due)
    rows_html += "".join(_row_html(r, cust_map, "coming_due") for r in coming_due)
    subject = (
        f"[{tenant.get('name', 'Pool CRM')}] Equipment service due — "
        f"{len(past_due)} past due, {len(coming_due)} coming up"
    )
    html = (
        "<div style='font-family:Inter,Arial,sans-serif; color:#111'>"
        f"<h2 style='margin:0 0 6px 0'>Equipment service digest</h2>"
        f"<p style='color:#4B5563; margin:0 0 14px 0'>"
        f"{len(past_due)} past due · {len(coming_due)} coming due within "
        f"{int(tenant.get('equipment_service_coming_due_days') or 30)} days"
        "</p>"
        "<table style='border-collapse:collapse; width:100%; "
        "border:1px solid #E5E7EB'>"
        "<thead><tr style='background:#F3F4F6'>"
        "<th align='left' style='padding:8px 10px'>Equipment</th>"
        "<th align='left' style='padding:8px 10px'>Customer</th>"
        "<th align='left' style='padding:8px 10px'>Address</th>"
        "<th align='left' style='padding:8px 10px'>Due Date</th>"
        "</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
        "</div>"
    )

    from services.email.resend_adapter import send as _send
    iso_week = _iso_week(datetime.now(timezone.utc))
    results = []
    for admin in admins:
        email = admin.get("email")
        if not email:
            continue
        dedup = await db.outbound_emails.find_one({
            "tenant_id": tenant["id"], "recipient_id": admin.get("id"),
            "iso_week": iso_week, "kind": DIGEST_KIND, "status": "sent",
        })
        if dedup:
            results.append({"email": email, "status": "skipped_dupe"})
            continue
        res = await _send(
            to=email, subject=subject, html=html,
            category="transactional", tenant_id=tenant["id"],
            idempotency_key=f"{DIGEST_KIND}:{tenant['id']}:{admin.get('id')}:{iso_week}",
        )
        status = (
            "sent" if res.get("provider_status") in ("sent", "queued")
            else "mocked" if res.get("provider_status") == "mocked"
            else "failed"
        )
        try:
            await db.outbound_emails.insert_one({
                "tenant_id": tenant["id"], "recipient_id": admin.get("id"),
                "recipient_email": email, "iso_week": iso_week,
                "kind": DIGEST_KIND, "status": status,
                "subject": subject, "sent_at": datetime.now(timezone.utc).isoformat(),
                "provider_response_id": res.get("provider_response_id"),
            })
        except Exception as exc:
            logger.warning(f"[phase11-cron] outbound log failed: {exc}")
        results.append({"email": email, "status": status})
    return {"recipients": len(results), "results": results, "iso_week": iso_week}


# ─────────────────────── Customer-facing reminders ────────────────────
_REMINDER_EMAIL_TEMPLATE = (
    "<p>Hi {{CUSTOMER_FIRST_NAME}},</p>"
    "<p>Your {{EQUIPMENT_TYPE}} is due for its next cleaning on "
    "<strong>{{EQUIPMENT_DUE_DATE}}</strong> "
    "(last cleaned {{EQUIPMENT_LAST_CLEANED_DATE}}, cadence every "
    "{{EQUIPMENT_INTERVAL_MONTHS}} months).</p>"
    "<p>We'll be in touch to confirm a service date. Reply to this "
    "email if you'd like to schedule right away.</p>"
    "<p>— The {{COMPANY_NAME}} team</p>"
)
_REMINDER_SMS_TEMPLATE = (
    "Hi {{CUSTOMER_FIRST_NAME}} — your {{EQUIPMENT_TYPE}} is due "
    "{{EQUIPMENT_DUE_DATE}}. — {{COMPANY_NAME}}"
)


def _fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%b %-d, %Y")
    except (TypeError, ValueError):
        return str(iso)


def build_equipment_ctx(tracker: dict, customer: dict, tenant: dict) -> Dict[str, Any]:
    """Assemble a merge-tag ctx bundle including the ``equipment_tracker``
    scope so the 4 new EQUIPMENT_* tags resolve. Used both by cron
    reminders and by the /preview / /test-send endpoints when a caller
    passes an ``equipment_tracker`` sample block."""
    ctx = render_context(
        customer={
            "name": customer.get("name") or "",
            "email": customer.get("email"),
            "phone": customer.get("phone"),
            "address": customer.get("address"),
        },
        tenant={
            "name": tenant.get("name"),
            "phone": tenant.get("phone"),
            "email": tenant.get("email"),
        },
    )
    label = "Filter" if tracker.get("tracker_type") == "filter" else \
            "Salt Cell" if tracker.get("tracker_type") == "salt_cell" else \
            (tracker.get("tracker_type") or "").replace("_", " ").title()
    ctx["equipment_tracker"] = {
        "type_label": label,
        "tracker_type": tracker.get("tracker_type"),
        "last_cleaned_at": tracker.get("last_cleaned_at"),
        "last_cleaned_at_pretty": _fmt_date(tracker.get("last_cleaned_at")),
        "due_at": tracker.get("due_at"),
        "due_at_pretty": _fmt_date(tracker.get("due_at")),
        "interval_months": tracker.get("interval_months") or 0,
    }
    return ctx


async def _dispatch_customer_reminders(
    tenant: dict,
    *,
    coming_due: List[dict],
    past_due: List[dict],
) -> Dict[str, Any]:
    from services.email.resend_adapter import send as _send_email
    try:
        from services.sms.rc_adapter import send as _send_sms
    except Exception:
        _send_sms = None  # type: ignore

    cust_ids = list({r.get("customer_id") for r in (coming_due + past_due)
                     if r.get("customer_id")})
    cust_map: Dict[str, dict] = {}
    if cust_ids:
        async for c in db.customers.find(
            {"id": {"$in": cust_ids}, "tenant_id": tenant["id"]},
            {"_id": 0},
        ):
            cust_map[c["id"]] = c

    iso_week = _iso_week(datetime.now(timezone.utc))
    email_count = sms_count = failed = skipped = 0

    # Phase EMAIL-MIGRATE · Batch 3 · Feb-2026 — DB-first email body.
    # Prefer the ``equipment_tracker_weekly_reminder_email`` row in
    # ``marketing_templates`` (tenant-specific > global default);
    # fall through to the module-level ``_REMINDER_EMAIL_TEMPLATE``
    # constant when the row is absent OR the render blows up.  The
    # DB lookup fires ONCE for the whole cron pass — the per-tracker
    # loop just re-renders against the cached body.
    tpl_body: Optional[str] = None
    try:
        from services.marketing_template_lookup import (
            get_template_with_global_fallback,
        )
        tpl = await get_template_with_global_fallback(
            "equipment_tracker_weekly_reminder_email",
            (tenant or {}).get("id") or None,
        )
        if tpl and tpl.get("body"):
            tpl_body = tpl["body"]
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "[phase11-cron] equipment reminder template lookup "
            "failed — using constant fallback: %s", exc,
        )
        tpl_body = None

    for r in (past_due + coming_due):
        cust = cust_map.get(r.get("customer_id"))
        if not cust:
            skipped += 1
            continue
        ctx = build_equipment_ctx(r, cust, tenant)
        subject_rendered, _s_missing = render_template(
            f"Your {{{{EQUIPMENT_TYPE}}}} cleaning is due", ctx,
        )
        html_rendered, _h_missing = render_template(
            tpl_body or _REMINDER_EMAIL_TEMPLATE, ctx,
        )
        sms_rendered, _sm_missing = render_template(_REMINDER_SMS_TEMPLATE, ctx)

        # Email path
        if cust.get("email"):
            dedup = await db.outbound_emails.find_one({
                "tenant_id": tenant["id"], "recipient_id": cust.get("id"),
                "iso_week": iso_week, "kind": REMINDER_KIND_EMAIL,
                "tracker_id": r.get("id"), "status": "sent",
            })
            if not dedup:
                res = await _send_email(
                    to=cust["email"],
                    subject=subject_rendered,
                    html=html_rendered,
                    category="transactional",
                    tenant_id=tenant["id"],
                    idempotency_key=(
                        f"{REMINDER_KIND_EMAIL}:{r.get('id')}:{iso_week}"
                    ),
                )
                status = (
                    "sent" if res.get("provider_status") in ("sent", "queued")
                    else "mocked" if res.get("provider_status") == "mocked"
                    else "failed"
                )
                if status == "sent" or status == "mocked":
                    email_count += 1
                else:
                    failed += 1
                try:
                    await db.outbound_emails.insert_one({
                        "tenant_id": tenant["id"],
                        "recipient_id": cust.get("id"),
                        "recipient_email": cust["email"],
                        "iso_week": iso_week,
                        "kind": REMINDER_KIND_EMAIL,
                        "tracker_id": r.get("id"),
                        "status": status,
                        "subject": subject_rendered,
                        "sent_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    pass

        # SMS path (optional adapter)
        if cust.get("phone") and _send_sms is not None:
            try:
                await _send_sms(
                    to=cust["phone"],
                    body=sms_rendered,
                    category="transactional",
                    tenant_id=tenant["id"],
                    idempotency_key=(
                        f"{REMINDER_KIND_SMS}:{r.get('id')}:{iso_week}"
                    ),
                )
                sms_count += 1
            except Exception as exc:
                logger.warning(f"[phase11-cron] SMS send failed: {exc}")
                failed += 1

    return {
        "emails_sent": email_count,
        "sms_sent": sms_count,
        "failed": failed,
        "skipped": skipped,
        "iso_week": iso_week,
    }
