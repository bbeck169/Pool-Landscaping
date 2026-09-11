"""Feb-2026 · Service reminder cron + reschedule event helper.

Two customer-facing service lifecycle triggers with a shared
implementation surface:

    A. Service reminder cron
       Registered at 08:00 tenant-local. Scans jobs whose
       ``scheduled_date`` is 24-27 hours away (3-hour cron drift
       window) and no ``service_reminder_sent_at`` stamp. For each
       eligible job, fires email + SMS (channel-independently),
       stamps the job, and writes an audit row.

    B. Reschedule event
       Called synchronously from ``PUT /api/jobs/{jid}`` when
       ``scheduled_date`` changes. Fires email + SMS with the
       old→new datetime, writes an audit row. Deduplicates via the
       ``reschedule_notification_sent_at`` stamp keyed on the
       transition.

    C. Identity guard (F1 defense-in-depth)
       Every send path re-verifies
       ``job.customer_id == cust.id`` before rendering; on
       mismatch, logs ERROR and returns (never crashes the cron).

Audit collection: ``db.notifications_sent_log`` — one row per fire
capturing (tenant, job, customer, template key, channels, timing,
provider status, actor).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config import db
from utils import new_id, now_iso

logger = logging.getLogger("services.notifications_pipeline.service_notifications")

DEFAULT_TZ = "America/Phoenix"

# Cron window — reminders fire when the job's scheduled_date is
# between 24 and 27 hours out. The 3-hour tolerance absorbs cron
# drift (hourly cron + slow starts + tenant TZ jitter) without
# double-firing (idempotency stamp is authoritative).
REMINDER_LEAD_MIN_HOURS = 24
REMINDER_LEAD_MAX_HOURS = 27

# Only active jobs get reminders.
_REMINDER_STATUSES = {"scheduled", "confirmed", "pending"}

# Rate limit — the F2 backfill script established 5 sends/sec as
# the provider-safe default. Sleep between fires when a tenant
# has many due reminders.
_MIN_SLEEP_SECONDS_BETWEEN_SENDS = 0.2

# Template keys (also written to the audit row).
TPL_REMINDER_EMAIL = "service_reminder_email"
TPL_REMINDER_SMS = "service_reminder_sms"
TPL_RESCHEDULE_EMAIL = "reschedule_service_email"
TPL_RESCHEDULE_SMS = "reschedule_service_sms"


# ═══════════════════════════════════════════════════════════════════
# Preference helpers
# ═══════════════════════════════════════════════════════════════════
def _pref_enabled(cust: Dict[str, Any], key: str) -> bool:
    """Return True unless the customer explicitly opted out of the
    named preference. Missing key → True (backwards compatible)."""
    prefs = cust.get("notification_preferences") or {}
    return prefs.get(key, True) is not False


def _hard_sms_opt_out(cust: Dict[str, Any]) -> bool:
    """A ``sms_opt_in`` explicitly False is the hardest signal —
    matches the ``on_my_way`` router semantics."""
    return cust.get("sms_opt_in") is False


def _channel_opt_out(cust: Dict[str, Any], channel: str) -> bool:
    """Marketing-preferences channel toggle (``channel_opt_in``).
    Missing entry → NOT opted out."""
    coi = cust.get("channel_opt_in") or {}
    return coi.get(channel) is False


# ═══════════════════════════════════════════════════════════════════
# Tenant/timezone helpers
# ═══════════════════════════════════════════════════════════════════
def _tenant_tz(tenant: Dict[str, Any]) -> str:
    return (tenant.get("timezone") or "").strip() or DEFAULT_TZ


def _now_local(tenant: Dict[str, Any]) -> datetime:
    try:
        return datetime.now(ZoneInfo(_tenant_tz(tenant)))
    except Exception:  # noqa: BLE001 — unknown IANA
        return datetime.now(ZoneInfo(DEFAULT_TZ))


def _parse_scheduled_date(value: Optional[str],
                            tenant: Dict[str, Any]) -> Optional[datetime]:
    """Parse the job's ``scheduled_date`` — sometimes bare date
    (``YYYY-MM-DD``), sometimes ISO datetime. Returns a
    timezone-aware datetime in tenant-local time; ``None`` on
    unparseable input.

    Bare dates are interpreted as start-of-day in the tenant TZ.
    Naive ISO datetimes are also assumed tenant-local. Aware
    datetimes are converted to tenant TZ.
    """
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    tz = ZoneInfo(_tenant_tz(tenant))
    try:
        # Bare date — start of day in tenant TZ.
        if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            return datetime.fromisoformat(raw).replace(tzinfo=tz)
        # ISO datetime with 'Z' → convert to +00:00 first.
        candidate = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except ValueError:
        return None


def _fmt_local(dt: datetime, tenant: Dict[str, Any]) -> str:
    """Human-readable local time for template rendering."""
    tz = ZoneInfo(_tenant_tz(tenant))
    return dt.astimezone(tz).strftime("%a %b %-d at %-I:%M %p")


# ═══════════════════════════════════════════════════════════════════
# Template renderers — inline, colocated with the logic.
# ═══════════════════════════════════════════════════════════════════
def _render_reminder_sms(ctx: Dict[str, Any]) -> str:
    return (
        f"Reminder: {ctx['tenant_name']} is scheduled to visit "
        f"{ctx['customer_name']} for {ctx['service_type']} on "
        f"{ctx['scheduled_at_formatted']}. Reply STOP to opt out. "
        f"Questions? Call {ctx['tenant_phone']}."
    )


def _render_reminder_email(ctx: Dict[str, Any]) -> Dict[str, str]:
    subject = (
        f"Reminder: your {ctx['service_type']} visit tomorrow — "
        f"{ctx['tenant_name']}"
    )
    html = f"""
    <p>Hi {ctx['customer_name']},</p>
    <p>Just a friendly reminder that <strong>{ctx['tenant_name']}</strong>
       is scheduled to visit for
       <strong>{ctx['service_type']}</strong> on
       <strong>{ctx['scheduled_at_formatted']}</strong>.</p>
    <p>Need to reschedule? Call us at
       <strong>{ctx['tenant_phone']}</strong>.</p>
    <p>Thanks,<br/>{ctx['tenant_name']}</p>
    """.strip()
    return {"subject": subject, "html": html}


def _render_reschedule_sms(ctx: Dict[str, Any]) -> str:
    return (
        f"{ctx['tenant_name']}: your {ctx['service_type']} visit has "
        f"been rescheduled from {ctx['old_scheduled_at_formatted']} "
        f"to {ctx['new_scheduled_at_formatted']}. Questions? Call "
        f"{ctx['tenant_phone']}."
    )


def _render_reschedule_email(ctx: Dict[str, Any]) -> Dict[str, str]:
    subject = (
        f"Rescheduled: your {ctx['service_type']} visit — "
        f"{ctx['tenant_name']}"
    )
    html = f"""
    <p>Hi {ctx['customer_name']},</p>
    <p>Your <strong>{ctx['service_type']}</strong> visit with
       <strong>{ctx['tenant_name']}</strong> has been rescheduled.</p>
    <ul>
      <li><strong>Previously:</strong>
          {ctx['old_scheduled_at_formatted']}</li>
      <li><strong>Now:</strong>
          {ctx['new_scheduled_at_formatted']}</li>
    </ul>
    <p>Questions? Call us at
       <strong>{ctx['tenant_phone']}</strong>.</p>
    <p>Thanks,<br/>{ctx['tenant_name']}</p>
    """.strip()
    return {"subject": subject, "html": html}


# ═══════════════════════════════════════════════════════════════════
# Core dispatch — the two entry points below funnel through this.
# ═══════════════════════════════════════════════════════════════════
async def _fetch_customer_and_tenant(
    job: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Load ``cust`` + ``tenant``. Applies the F1 identity guard:
    on ``job.customer_id != cust.id`` mismatch, logs ERROR and
    returns None."""
    cid = job.get("customer_id")
    tid = job.get("tenant_id")
    if not cid or not tid:
        return None
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tid}, {"_id": 0},
    )
    if not cust:
        return None
    if cust.get("id") != cid:
        # F1 identity guard (defense-in-depth). Under the current
        # query — ``find_one({"id": cid, ...})`` — this branch is
        # unreachable by construction. Kept as a paved-road guard:
        # if a future refactor swaps the lookup key (e.g. resolves
        # by email or by customer.merged_into_id), this catches
        # any resulting identity drift before an SMS ships. The
        # ERROR log makes the invariant violation observable.
        logger.error(
            "notif identity_drift job_id=%s tenant_id=%s "
            "job.customer_id=%s cust.id=%s — skipping send",
            job.get("id"), tid, cid, cust.get("id"),
        )
        return None
    tenant = await db.tenants.find_one({"id": tid}, {"_id": 0})
    if not tenant:
        return None
    return {"cust": cust, "tenant": tenant}


async def _write_audit(
    *, tenant_id: str, job_id: str, customer_id: str,
    template_key: str, channels_sent: List[str],
    channels_skipped: List[str], actor: str,
    extras: Optional[Dict[str, Any]] = None,
) -> str:
    doc = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "job_id": job_id,
        "customer_id": customer_id,
        "template_key": template_key,
        "channels_sent": channels_sent,
        "channels_skipped": channels_skipped,
        "actor": actor,
        "sent_at": now_iso(),
    }
    if extras:
        doc.update(extras)
    try:
        await db.notifications_sent_log.insert_one(doc)
    except Exception as exc:  # pragma: no cover — audit-only
        logger.warning(
            "notifications_sent_log insert failed: %s", exc,
        )
    return doc["id"]


async def _fire(
    *, cust: Dict[str, Any], tenant: Dict[str, Any],
    email_pref_key: str, sms_pref_key: str,
    email_tpl_key: str, sms_tpl_key: str,
    email_ctx: Dict[str, Any], sms_body: str,
    subject: str, html: str,
) -> Dict[str, List[str]]:
    """Fire email + SMS in parallel-ish (sequentially — the adapter
    handles its own rate). Returns dict with
    ``channels_sent`` / ``channels_skipped`` for the audit row.

    Preference precedence (each channel independently):

    1. Hard opt-out (``sms_opt_in=False`` for SMS) → skip
    2. Marketing channel toggle
       (``channel_opt_in.{email|sms}=False``) → skip
    3. New notification-preferences key (this feature) → skip
    4. Missing address (no phone / no email) → skip
    5. Otherwise fire.
    """
    tenant_id = tenant["id"]
    channels_sent: List[str] = []
    channels_skipped: List[str] = []

    # ── EMAIL ────────────────────────────────────────────────────
    email = (cust.get("email") or "").strip()
    if not email:
        channels_skipped.append("email:no_address")
    elif _channel_opt_out(cust, "email"):
        channels_skipped.append("email:channel_opt_out")
    elif not _pref_enabled(cust, email_pref_key):
        channels_skipped.append(f"email:{email_pref_key}_off")
    else:
        try:
            from services.comms_email_adapter import send_email
            result = await send_email(
                tenant_id=tenant_id, to_email=email,
                subject=subject, html=html,
                from_name=tenant.get("name") or "Service Team",
            )
            status = result.get("status")
            if status in ("sent", "mocked"):
                channels_sent.append("email")
            elif status == "skipped_opted_out":
                channels_skipped.append("email:communication_opt_outs")
            elif status == "not_sent_missing_key":
                channels_skipped.append("email:missing_key")
            else:
                channels_skipped.append(f"email:{status or 'unknown'}")
        except Exception as exc:  # noqa: BLE001 — never break cron
            logger.warning("email send crashed: %s", exc)
            channels_skipped.append("email:crash")

    # ── SMS ──────────────────────────────────────────────────────
    phone = (cust.get("phone")
              or (cust.get("mobiles") or [{}])[0].get("number_e164")
              or "").strip()
    if not phone:
        channels_skipped.append("sms:no_address")
    elif _hard_sms_opt_out(cust):
        channels_skipped.append("sms:hard_opt_out")
    elif _channel_opt_out(cust, "sms"):
        channels_skipped.append("sms:channel_opt_out")
    elif not _pref_enabled(cust, sms_pref_key):
        channels_skipped.append(f"sms:{sms_pref_key}_off")
    else:
        try:
            from services.comms_sms_adapter import send_sms
            result = await send_sms(
                tenant_id=tenant_id, to_phone=phone, body=sms_body,
            )
            status = result.get("status")
            if status in ("sent", "mocked"):
                channels_sent.append("sms")
            elif status == "skipped_opted_out":
                channels_skipped.append("sms:communication_opt_outs")
            else:
                channels_skipped.append(f"sms:{status or 'unknown'}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("sms send crashed: %s", exc)
            channels_skipped.append("sms:crash")

    return {"channels_sent": channels_sent,
             "channels_skipped": channels_skipped}


# ═══════════════════════════════════════════════════════════════════
# A. 24-hr service reminder cron
# ═══════════════════════════════════════════════════════════════════
async def _due_reminder_jobs_for_tenant(
    tenant: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return jobs whose ``scheduled_date`` is within the [24, 27)
    hour window relative to ``now`` in tenant TZ AND that haven't
    already been reminder-stamped."""
    tenant_id = tenant["id"]
    now_local = _now_local(tenant)
    window_start = now_local + timedelta(hours=REMINDER_LEAD_MIN_HOURS)
    window_end = now_local + timedelta(hours=REMINDER_LEAD_MAX_HOURS)

    # Prefilter on tenant + status + no stamp; TZ math is done in
    # Python because ``scheduled_date`` is a heterogeneous string
    # (bare date OR ISO datetime).
    prefilter = {
        "tenant_id": tenant_id,
        "status": {"$in": list(_REMINDER_STATUSES)},
        "$or": [
            {"service_reminder_sent_at": None},
            {"service_reminder_sent_at": {"$exists": False}},
        ],
        "$and": [
            {"$or": [{"deleted_at": None},
                       {"deleted_at": {"$exists": False}}]},
        ],
        "customer_id": {"$exists": True, "$ne": None},
        "scheduled_date": {"$exists": True, "$ne": None},
    }
    due: List[Dict[str, Any]] = []
    cursor = db.jobs.find(prefilter, {"_id": 0, "photos.data": 0})
    async for job in cursor:
        dt = _parse_scheduled_date(job.get("scheduled_date"), tenant)
        if dt is None:
            continue
        if window_start <= dt < window_end:
            due.append(job)
    return due


async def fire_reminder_for_job(
    job: Dict[str, Any], *, actor: str = "system_cron",
) -> Dict[str, Any]:
    """Send the 24-hr reminder for a single job. Idempotency-safe:
    stamps the job with ``service_reminder_sent_at``. Callers
    (cron OR reschedule short-window branch) rely on this stamp
    to skip.

    Never raises. Returns an audit summary.
    """
    resolved = await _fetch_customer_and_tenant(job)
    if not resolved:
        return {"ok": False, "reason": "unresolved_identity",
                 "channels_sent": []}
    cust = resolved["cust"]
    tenant = resolved["tenant"]

    dt = _parse_scheduled_date(job.get("scheduled_date"), tenant)
    if dt is None:
        return {"ok": False, "reason": "unparseable_scheduled_date",
                 "channels_sent": []}

    ctx = {
        "customer_name": cust.get("name") or "Customer",
        "service_type": job.get("service_type") or "your service",
        "scheduled_at_formatted": _fmt_local(dt, tenant),
        "tenant_name": tenant.get("name") or "Service Team",
        "tenant_phone": tenant.get("phone")
                          or tenant.get("main_phone") or "",
    }
    sms_body = _render_reminder_sms(ctx)
    email = _render_reminder_email(ctx)

    outcome = await _fire(
        cust=cust, tenant=tenant,
        email_pref_key="reminders_email",
        sms_pref_key="reminders_sms",
        email_tpl_key=TPL_REMINDER_EMAIL,
        sms_tpl_key=TPL_REMINDER_SMS,
        email_ctx=ctx, sms_body=sms_body,
        subject=email["subject"], html=email["html"],
    )
    channels_sent = outcome["channels_sent"]

    # Stamp only when the outcome is TERMINAL — either at least one
    # channel was actually sent, or every skip was for a permanent
    # reason (opt-out, no-address, feature-pref-off). Transient
    # skips (``:failed``, ``:crash``, ``:unknown``, ``:missing_key``)
    # leave the stamp OFF so the next cron tick retries. Otherwise
    # a Resend outage silently drops that customer's reminder
    # forever.
    all_skips = outcome["channels_skipped"]
    transient_markers = (":failed", ":crash", ":unknown",
                          ":missing_key")
    has_transient_skip = any(
        any(m in s for m in transient_markers) for s in all_skips
    )
    terminal_ok = bool(channels_sent) or not has_transient_skip

    stamp_now = now_iso() if terminal_ok else None
    if terminal_ok:
        await db.jobs.update_one(
            {"id": job["id"], "tenant_id": tenant["id"]},
            {"$set": {"service_reminder_sent_at": stamp_now}},
        )
    audit_id = await _write_audit(
        tenant_id=tenant["id"], job_id=job["id"],
        customer_id=cust["id"],
        template_key="service_reminder",
        channels_sent=channels_sent,
        channels_skipped=outcome["channels_skipped"],
        actor=actor,
        extras={"scheduled_at": dt.isoformat(),
                 "stamped": bool(stamp_now)},
    )
    return {
        "ok": True, "audit_id": audit_id,
        "channels_sent": channels_sent,
        "channels_skipped": outcome["channels_skipped"],
        "reminder_sent_at": stamp_now,
        "will_retry": not terminal_ok,
    }


async def service_reminder_cron_tick() -> Dict[str, Any]:
    """Hourly cron entry point.

    Iterates every tenant; for each tenant whose current LOCAL hour
    is exactly the trigger hour (default 08), scans for reminder-
    eligible jobs and fires. Duplicate-fire protected by
    ``scheduler_lease`` at the top of the tick + the job-level
    ``service_reminder_sent_at`` stamp.
    """
    import asyncio  # noqa: PLC0415 — local
    fire_hour = int(os.environ.get(
        "SERVICE_REMINDER_LOCAL_HOUR", "8",
    ))
    total_fires = 0
    total_scanned_tenants = 0
    per_tenant: List[Dict[str, Any]] = []

    async for tenant in db.tenants.find({}, {"_id": 0}):
        local_hour = _now_local(tenant).hour
        if local_hour != fire_hour:
            continue
        total_scanned_tenants += 1

        # Duplicate-fire lease per tenant per hour.
        try:
            from services.comms_hardening.scheduler_lease import (
                try_acquire_lease,
            )
            tick_iso = _now_local(tenant).strftime("%Y-%m-%dT%H:00")
            lease = await try_acquire_lease(
                tenant_id=tenant["id"],
                job_id="service_reminder_cron",
                tick_iso=tick_iso,
            )
            if not lease.get("acquired"):
                continue
        except Exception as exc:  # noqa: BLE001 — soft-fail lease
            logger.warning("lease acquire failed: %s", exc)

        due = await _due_reminder_jobs_for_tenant(tenant)
        tenant_fires = 0
        for job in due:
            result = await fire_reminder_for_job(job)
            if result.get("ok") and result.get("channels_sent"):
                tenant_fires += 1
            total_fires += 1
            # Provider rate protection.
            await asyncio.sleep(_MIN_SLEEP_SECONDS_BETWEEN_SENDS)
        per_tenant.append({
            "tenant_id": tenant["id"],
            "eligible_jobs": len(due),
            "sends_fired": tenant_fires,
        })

    logger.info(
        "[service_reminder_cron] scanned_tenants=%d total_fires=%d",
        total_scanned_tenants, total_fires,
    )
    return {
        "scanned_tenants": total_scanned_tenants,
        "total_fires": total_fires,
        "per_tenant": per_tenant,
    }


def register_service_reminder_cron(scheduler: Any) -> None:
    """Called from ``server.py`` startup when the scheduler is
    enabled. Runs on the top of every hour; the per-tenant local-
    hour gate inside ``service_reminder_cron_tick`` picks the
    right tenants."""
    try:
        scheduler.add_job(
            service_reminder_cron_tick,
            "cron",
            minute=0,
            id="service_reminder_cron",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("[service_reminder_cron] registered (hourly, "
                     "per-tenant local-hour gate)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[service_reminder_cron] register failed: %s",
                          exc)


async def ensure_indexes() -> None:
    """Idempotent boot helper — registers the unique compound index
    that makes reschedule idempotency crash-safe under concurrent
    PATCHes. Called from ``scripts/ensure_indexes.py`` per the F2
    ops runbook (prod skips inline index create).
    """
    try:
        await db.notifications_sent_log.create_index(
            [("tenant_id", 1), ("job_id", 1),
              ("template_key", 1), ("transition_key", 1)],
            name="notif_sent_log_transition_unique",
            unique=True,
            partialFilterExpression={
                "transition_key": {"$exists": True, "$type": "string"},
            },
            background=True,
        )
    except Exception as exc:  # noqa: BLE001 — never block boot
        logger.warning(
            "notifications_sent_log unique index create failed: %s",
            exc,
        )


# ═══════════════════════════════════════════════════════════════════
# B. Reschedule event helper
# ═══════════════════════════════════════════════════════════════════
async def fire_reschedule_notification(
    *, job: Dict[str, Any],
    old_scheduled_date: Optional[str],
    new_scheduled_date: Optional[str],
    actor_user_id: Optional[str],
) -> Dict[str, Any]:
    """Called by ``PUT /api/jobs/{jid}`` right after a
    ``scheduled_date`` change. Idempotent per transition — if the
    same old→new pair has already fired, second call is a no-op.

    Never raises. Returns an audit summary.

    Guardrails (in order):
      1. Both dates must be non-empty AND different (change detect).
      2. Job status must be reminder-eligible (``scheduled``,
         ``confirmed``, ``pending``). Completed / cancelled /
         could-not-service jobs MUST NOT emit customer-facing
         reschedule copy — the visit is already over. Testing
         agent regression fix (Feb-2026).
      3. New scheduled date must NOT be in the past — back-dating
         a completed visit for data cleanup should never trigger
         a customer notification. Testing agent regression fix.
      4. F1 identity guard — customer resolves to the same id the
         job references.
    """
    if not old_scheduled_date or not new_scheduled_date:
        return {"ok": False, "reason": "missing_dates",
                 "channels_sent": []}
    if str(old_scheduled_date).strip() == str(new_scheduled_date).strip():
        return {"ok": False, "reason": "no_change",
                 "channels_sent": []}

    # Guardrail 2 — status gate. Mirrors ``_REMINDER_STATUSES`` on
    # the cron path so both surfaces share the same "notify-worthy"
    # definition.
    status = (job.get("status") or "").lower()
    if status and status not in _REMINDER_STATUSES:
        return {"ok": False, "reason": f"status_not_notifiable:{status}",
                 "channels_sent": []}

    resolved = await _fetch_customer_and_tenant(job)
    if not resolved:
        return {"ok": False, "reason": "unresolved_identity",
                 "channels_sent": []}
    cust = resolved["cust"]
    tenant = resolved["tenant"]

    old_dt = _parse_scheduled_date(old_scheduled_date, tenant)
    new_dt = _parse_scheduled_date(new_scheduled_date, tenant)
    if old_dt is None or new_dt is None:
        return {"ok": False, "reason": "unparseable_dates",
                 "channels_sent": []}

    # Guardrail 3 — past-date guard. If the NEW date is already in
    # the past (any negative delta), skip. Data-cleanup back-dates
    # commonly move a completed visit's scheduled_date to align
    # with the actual visit date; the customer must not receive a
    # "we've moved your appointment" notification for something
    # that already happened.
    now_utc = datetime.now(timezone.utc)
    new_dt_utc = new_dt.astimezone(timezone.utc)
    hours_until_new = (new_dt_utc - now_utc).total_seconds() / 3600
    if hours_until_new < 0:
        return {"ok": False, "reason": "new_date_in_past",
                 "channels_sent": []}

    # ── Idempotency: check for prior audit row with the same
    # transition. Keyed by the tuple (job_id, old, new) so a
    # tech accidentally re-PATCHing the same value twice doesn't
    # double-notify.
    stamp_key = f"{old_scheduled_date}→{new_scheduled_date}"
    prior = await db.notifications_sent_log.find_one({
        "tenant_id": tenant["id"],
        "job_id": job["id"],
        "template_key": "reschedule_service",
        "transition_key": stamp_key,
    }, {"_id": 0, "id": 1})
    if prior:
        return {"ok": True, "no_op": True, "channels_sent": [],
                 "reason": "already_notified_for_this_transition"}

    ctx = {
        "customer_name": cust.get("name") or "Customer",
        "service_type": job.get("service_type") or "your service",
        "old_scheduled_at_formatted": _fmt_local(old_dt, tenant),
        "new_scheduled_at_formatted": _fmt_local(new_dt, tenant),
        "tenant_name": tenant.get("name") or "Service Team",
        "tenant_phone": tenant.get("phone")
                          or tenant.get("main_phone") or "",
    }
    sms_body = _render_reschedule_sms(ctx)
    email = _render_reschedule_email(ctx)

    outcome = await _fire(
        cust=cust, tenant=tenant,
        email_pref_key="reschedule_email",
        sms_pref_key="reschedule_sms",
        email_tpl_key=TPL_RESCHEDULE_EMAIL,
        sms_tpl_key=TPL_RESCHEDULE_SMS,
        email_ctx=ctx, sms_body=sms_body,
        subject=email["subject"], html=email["html"],
    )

    audit_id = await _write_audit(
        tenant_id=tenant["id"], job_id=job["id"],
        customer_id=cust["id"],
        template_key="reschedule_service",
        channels_sent=outcome["channels_sent"],
        channels_skipped=outcome["channels_skipped"],
        actor=f"user:{actor_user_id}" if actor_user_id else "system",
        extras={
            "transition_key": stamp_key,
            "old_scheduled_at": old_dt.isoformat(),
            "new_scheduled_at": new_dt.isoformat(),
        },
    )

    # Short-window dedup: if the NEW scheduled date is <24hr away
    # AND the job has NOT yet been reminder-stamped, stamp it now
    # so the 24hr reminder cron doesn't double-send. The reschedule
    # notification itself communicates the timing.
    if hours_until_new < REMINDER_LEAD_MIN_HOURS and not job.get(
        "service_reminder_sent_at",
    ):
        await db.jobs.update_one(
            {"id": job["id"], "tenant_id": tenant["id"]},
            {"$set": {"service_reminder_sent_at": now_iso()}},
        )

    return {
        "ok": True, "audit_id": audit_id,
        "channels_sent": outcome["channels_sent"],
        "channels_skipped": outcome["channels_skipped"],
    }
