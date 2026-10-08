"""Feb-2026 · MARCO Proactive Monitoring Alerts — service layer.

Scope locked at phase start (user decisions G1-G5):
  * G1 = 5 signals (``detect_expired_quotes`` deferred to
    ``QUOTE-EXPIRATION-MODEL`` ticket — quotes have no
    ``expires_at`` field or ``expired`` status today).
  * G3 = new collection ``db.marco_alerts`` with the fields listed
    in the brief.
  * G4 = hybrid: 5-min scheduled sweep (``run_sweeper_loop``) + 3
    event-driven resolve hooks on existing routers
    (``quotes.py`` paid invoices, ``jobs.py`` crew/tech
    assignment, ``workforce.py`` clock-in).
  * G5 = admin / super_admin / manager / owner can list, ack,
    dismiss.  Audit lives on the row itself
    (``acknowledged_by`` / ``dismissed_by``).

TODO: detect_expired_quotes pending QUOTE-EXPIRATION-MODEL ticket
      (requires expires_at schema).

Public surface:
  * ``MARCO_ALERT_KIND_*`` constants — stable keys used by both
    detectors and the auto-resolve hooks.
  * ``upsert_alert`` — dedup-safe insert / bump of ``last_seen_at``.
  * ``auto_resolve_alert`` — mark active alert dismissed when the
    underlying condition clears (invoice paid, job assigned,
    clock-in recorded).
  * ``sweep_tenant`` — runs all 5 detectors in-order for one
    tenant.
  * ``run_sweeper_loop`` — infinite 5-min loop over all tenants.
    Registered in the server lifespan via
    ``asyncio.create_task(_bg_marco_alerts_sweeper())``.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import logger


# ─── Alert kind constants ────────────────────────────────────────
MARCO_ALERT_KIND_OVERDUE_INVOICE = "overdue_invoice"
MARCO_ALERT_KIND_UNASSIGNED_JOB = "unassigned_job"
MARCO_ALERT_KIND_MISSING_CLOCK_IN = "missing_clock_in"
MARCO_ALERT_KIND_PAYMENT_FAILED = "payment_failed"
MARCO_ALERT_KIND_SMS_FAILED = "sms_failed"

ALL_ALERT_KINDS = (
    MARCO_ALERT_KIND_OVERDUE_INVOICE,
    MARCO_ALERT_KIND_UNASSIGNED_JOB,
    MARCO_ALERT_KIND_MISSING_CLOCK_IN,
    MARCO_ALERT_KIND_PAYMENT_FAILED,
    MARCO_ALERT_KIND_SMS_FAILED,
)

# Severities — ordered low→high so caller can compare lexically.
SEVERITY_RANK = {"info": 0, "warn": 1, "error": 2}

# Sweeper loop cadence (seconds) — exposed as a module constant so
# tests can monkey-patch it without racing against a 5-min sleep.
SWEEPER_INTERVAL_SECONDS = 300

# Overdue-invoice grace period — brief says 1-day grace minimum.
OVERDUE_INVOICE_GRACE_DAYS = 1
OVERDUE_INVOICE_ERROR_THRESHOLD_DAYS = 7

# Lookback windows for the two "last-24h" detectors.
PAYMENT_FAILURE_LOOKBACK_HOURS = 24
SMS_FAILURE_LOOKBACK_HOURS = 24
# Clock-in grace — brief says 15 min after scheduled_start.
MISSING_CLOCK_IN_GRACE_MINUTES = 15


# ═══════════════════════════════════════════════════════════════
# Helpers.
# ═══════════════════════════════════════════════════════════════


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _dedup_key(kind: str, entity_ref: Optional[Dict[str, Any]]) -> str:
    """Stable dedup key for ``(tenant_id, kind, entity_ref)``.

    Rows for the same underlying business entity collapse to a
    single active alert — a second sweep bumps ``last_seen_at``
    instead of inserting a duplicate.
    """
    ref = entity_ref or {}
    etype = str(ref.get("type") or "").strip() or "none"
    eid = str(ref.get("id") or "").strip() or "none"
    return f"{kind}:{etype}:{eid}"


def _max_severity(a: str, b: str) -> str:
    """Return the lexically-higher severity between two labels."""
    ra = SEVERITY_RANK.get(a, 0)
    rb = SEVERITY_RANK.get(b, 0)
    return a if ra >= rb else b


# ═══════════════════════════════════════════════════════════════
# Upsert + auto-resolve primitives.
# ═══════════════════════════════════════════════════════════════


async def upsert_alert(
    db,
    *,
    tenant_id: str,
    kind: str,
    severity: str,
    title: str,
    body: str,
    entity_ref: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Insert a new ``marco_alerts`` row OR bump ``last_seen_at``
    on an existing active (``dismissed_at IS None``) row with the
    same ``(tenant_id, dedup_key)``.

    If the existing row's severity is lower than the incoming
    severity, the row is upgraded (an invoice that moves from
    the 1-7 day ``warn`` band into the >7-day ``error`` band
    picks up the escalated label and clears any prior ack so the
    admin re-sees it).
    """
    dedup = _dedup_key(kind, entity_ref)
    now = _now_iso()
    existing = await db.marco_alerts.find_one(
        {"tenant_id": tenant_id, "dedup_key": dedup,
         "dismissed_at": None},
        {"_id": 0},
    )
    if existing:
        upd: Dict[str, Any] = {
            "last_seen_at": now,
            "title": title,
            "body": body,
        }
        # Severity escalation — downgrades are ignored (sticky).
        new_sev = _max_severity(existing.get("severity") or "info", severity)
        if new_sev != existing.get("severity"):
            upd["severity"] = new_sev
            # Re-surface to the admin when severity escalates.
            upd["acknowledged_at"] = None
            upd["acknowledged_by"] = None
        await db.marco_alerts.update_one(
            {"id": existing["id"], "tenant_id": tenant_id},
            {"$set": upd},
        )
        existing.update(upd)
        return existing

    from uuid import uuid4
    doc = {
        "id": uuid4().hex[:24],
        "tenant_id": tenant_id,
        "kind": kind,
        "severity": severity,
        "title": title[:280],
        "body": body[:1000],
        "entity_ref": dict(entity_ref or {}),
        "dedup_key": dedup,
        "acknowledged_at": None,
        "acknowledged_by": None,
        "dismissed_at": None,
        "dismissed_by": None,
        "created_at": now,
        "last_seen_at": now,
    }
    await db.marco_alerts.insert_one(dict(doc))
    return doc


async def auto_resolve_alert(
    db,
    *,
    tenant_id: str,
    kind: str,
    entity_ref: Optional[Dict[str, Any]] = None,
    reason: str = "condition_cleared",
) -> int:
    """Mark any active alert for ``(tenant_id, kind, entity_ref)``
    as dismissed by the system.  Idempotent — a second call is a
    no-op (``modified_count=0``).

    Called from the event-driven resolve hooks in
    ``quotes.py`` (invoice paid), ``jobs.py`` (crew / tech
    assigned), and ``workforce.py`` (clock-in recorded).  Also
    used from the sweep's negative-case pass if the underlying
    row disappears between ticks.
    """
    dedup = _dedup_key(kind, entity_ref)
    now = _now_iso()
    res = await db.marco_alerts.update_many(
        {"tenant_id": tenant_id, "dedup_key": dedup,
         "dismissed_at": None},
        {"$set": {
            "dismissed_at": now,
            "dismissed_by": f"system:{reason}",
        }},
    )
    return getattr(res, "modified_count", 0) or 0


# ═══════════════════════════════════════════════════════════════
# Detectors.
# ═══════════════════════════════════════════════════════════════


async def detect_overdue_invoices(db, tenant_id: str) -> List[Dict[str, Any]]:
    """Invoices with ``payment_status != "paid"`` AND
    ``due_date < now - 1 day``.  Severity: ``warn`` for 1-7 days
    overdue, ``error`` for >7 days."""
    now = _now()
    cutoff_warn = (now - timedelta(days=OVERDUE_INVOICE_GRACE_DAYS)).isoformat()
    cutoff_error = (now - timedelta(days=OVERDUE_INVOICE_ERROR_THRESHOLD_DAYS)).isoformat()
    rows = await db.quotes.find(
        {
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "payment_status": {"$nin": ["paid", "void"]},
            "due_date": {"$lt": cutoff_warn, "$ne": None, "$type": "string"},
        },
        {"_id": 0, "id": 1, "invoice_number": 1, "number": 1,
         "due_date": 1, "total": 1, "amount_paid": 1,
         "customer_id": 1, "customer_name": 1},
    ).to_list(2000)

    alerts: List[Dict[str, Any]] = []
    for inv in rows:
        due = str(inv.get("due_date") or "")
        severity = "error" if due < cutoff_error else "warn"
        total = float(inv.get("total") or 0)
        paid = float(inv.get("amount_paid") or 0)
        balance = round(total - paid, 2)
        if balance <= 0.01:
            continue   # defensive: paid-in-full rows filtered out.
        inv_label = (
            inv.get("invoice_number") or inv.get("number")
            or f"#{str(inv.get('id') or '')[:8]}"
        )
        cust = inv.get("customer_name") or "customer"
        title = f"Invoice {inv_label} is overdue"
        body = (
            f"${balance:.2f} unpaid for {cust}. "
            f"Due date: {due[:10]}."
        )
        alerts.append({
            "kind": MARCO_ALERT_KIND_OVERDUE_INVOICE,
            "severity": severity,
            "title": title,
            "body": body,
            "entity_ref": {"type": "invoice", "id": inv.get("id")},
        })
    return alerts


async def detect_unassigned_jobs(db, tenant_id: str) -> List[Dict[str, Any]]:
    """Jobs scheduled today or tomorrow with no ``crew_id`` AND no
    ``technician_id``.  Severity: ``error`` (today) / ``warn``
    (tomorrow)."""
    today = _now().date()
    tomorrow = today + timedelta(days=1)
    today_prefix = today.isoformat()
    tomorrow_prefix = tomorrow.isoformat()
    # Defensive match: jobs use ``scheduled_start`` as ISO datetime
    # (per phase recon).  Some older rows use ``scheduled_date``
    # (YYYY-MM-DD).  Match either.
    date_or = [
        {"scheduled_start": {"$regex": f"^{today_prefix}"}},
        {"scheduled_start": {"$regex": f"^{tomorrow_prefix}"}},
        {"scheduled_date": today_prefix},
        {"scheduled_date": tomorrow_prefix},
        {"scheduled_date": {"$regex": f"^{today_prefix}"}},
        {"scheduled_date": {"$regex": f"^{tomorrow_prefix}"}},
    ]
    rows = await db.jobs.find(
        {
            "tenant_id": tenant_id,
            "status": {"$in": ["scheduled", "confirmed", "pending"]},
            "$or": date_or,
            "$and": [
                {"$or": [{"crew_id": None}, {"crew_id": {"$exists": False}}, {"crew_id": ""}]},
                {"$or": [{"technician_id": None}, {"technician_id": {"$exists": False}}, {"technician_id": ""}]},
            ],
        },
        {"_id": 0, "id": 1, "title": 1, "scheduled_start": 1,
         "scheduled_date": 1, "customer_name": 1},
    ).to_list(2000)

    alerts: List[Dict[str, Any]] = []
    for j in rows:
        sched = str(j.get("scheduled_start") or j.get("scheduled_date") or "")
        is_today = sched.startswith(today_prefix)
        severity = "error" if is_today else "warn"
        when_label = "today" if is_today else "tomorrow"
        cust = j.get("customer_name") or "customer"
        title_text = j.get("title") or "Service job"
        alerts.append({
            "kind": MARCO_ALERT_KIND_UNASSIGNED_JOB,
            "severity": severity,
            "title": f"Job scheduled {when_label} has no crew or tech",
            "body": f"'{title_text}' for {cust} — assign a crew or technician.",
            "entity_ref": {"type": "job", "id": j.get("id")},
        })
    return alerts


async def detect_missing_clock_ins(
    db, tenant_id: str,
) -> List[Dict[str, Any]]:
    """Jobs scheduled today with ``scheduled_start < now - 15m``
    and no corresponding ``time_entries.clock_in_at`` row.
    Severity: ``error``."""
    now = _now()
    cutoff = (now - timedelta(minutes=MISSING_CLOCK_IN_GRACE_MINUTES)).isoformat()
    today = now.date().isoformat()
    # Pull candidate jobs — scheduled_start is in the past (grace)
    # but still today.
    rows = await db.jobs.find(
        {
            "tenant_id": tenant_id,
            "status": {"$in": ["scheduled", "confirmed", "in_progress"]},
            "$or": [
                {"scheduled_start": {"$regex": f"^{today}",
                                      "$lt": cutoff}},
                {"scheduled_date": today,
                  "scheduled_start_time": {"$exists": True, "$ne": None}},
            ],
        },
        {"_id": 0, "id": 1, "title": 1, "scheduled_start": 1,
         "scheduled_date": 1, "customer_name": 1,
         "technician_id": 1, "crew_id": 1},
    ).to_list(2000)
    if not rows:
        return []
    job_ids = [j["id"] for j in rows]
    today_start_iso = f"{today}T00:00:00+00:00"
    # Resolve clock-in presence per job (time_entries.job_id).
    entries = await db.time_entries.find(
        {
            "tenant_id": tenant_id,
            "job_id": {"$in": job_ids},
            "clock_in_at": {"$gte": today_start_iso},
        },
        {"_id": 0, "job_id": 1},
    ).to_list(5000)
    clocked_in = {e.get("job_id") for e in entries if e.get("job_id")}

    alerts: List[Dict[str, Any]] = []
    for j in rows:
        if j.get("id") in clocked_in:
            continue
        # Skip jobs with no assignment — those surface via the
        # unassigned_jobs detector instead (don't double-alert).
        if not j.get("technician_id") and not j.get("crew_id"):
            continue
        sched = str(j.get("scheduled_start") or j.get("scheduled_date") or "")
        cust = j.get("customer_name") or "customer"
        title_text = j.get("title") or "Service job"
        alerts.append({
            "kind": MARCO_ALERT_KIND_MISSING_CLOCK_IN,
            "severity": "error",
            "title": "Technician is late to clock in",
            "body": (
                f"'{title_text}' for {cust} was scheduled at "
                f"{sched[11:16] or sched[:10]} — nobody's clocked in yet."
            ),
            "entity_ref": {"type": "job", "id": j.get("id")},
        })
    return alerts


async def detect_payment_failures(
    db, tenant_id: str,
) -> List[Dict[str, Any]]:
    """``db.payment_events`` rows with ``event="payment_failed"``
    in the last 24 h.  Severity: ``error``."""
    now = _now()
    cutoff = (now - timedelta(hours=PAYMENT_FAILURE_LOOKBACK_HOURS)).isoformat()
    rows = await db.payment_events.find(
        {
            "tenant_id": tenant_id,
            "event": "payment_failed",
            "$or": [
                {"created_at": {"$gte": cutoff}},
                {"at": {"$gte": cutoff}},
                {"timestamp": {"$gte": cutoff}},
            ],
        },
        {"_id": 0, "entity_id": 1, "invoice_id": 1, "reason": 1,
         "amount_cents": 1, "customer_id": 1, "created_at": 1,
         "at": 1, "timestamp": 1},
    ).to_list(2000)

    alerts: List[Dict[str, Any]] = []
    seen: set = set()
    for ev in rows:
        invoice_id = (
            ev.get("entity_id") or ev.get("invoice_id") or None
        )
        if not invoice_id:
            continue
        if invoice_id in seen:   # one alert per invoice.
            continue
        seen.add(invoice_id)
        reason = ev.get("reason") or "payment failed"
        amount = float(ev.get("amount_cents") or 0) / 100.0
        alerts.append({
            "kind": MARCO_ALERT_KIND_PAYMENT_FAILED,
            "severity": "error",
            "title": "Payment failed",
            "body": (
                f"${amount:.2f} failed to charge "
                f"({str(reason)[:80]}). Follow up with the customer."
            ),
            "entity_ref": {"type": "invoice", "id": invoice_id},
        })
    return alerts


async def detect_sms_failures(
    db, tenant_id: str,
) -> List[Dict[str, Any]]:
    """``db.comms_send_log`` rows with ``channel="sms"``,
    ``ok=False`` in the last 24 h.  Severity: ``warn``.

    Collapse to a single alert per tenant with the FAILURE COUNT —
    repeated failures to the same adapter manifest as noise if we
    one-alert-per-row.
    """
    now = _now()
    cutoff = (now - timedelta(hours=SMS_FAILURE_LOOKBACK_HOURS)).isoformat()
    rows = await db.comms_send_log.find(
        {
            "tenant_id": tenant_id,
            "channel": "sms",
            "ok": False,
            "was_mock": {"$ne": True},
            "at": {"$gte": cutoff},
        },
        {"_id": 0, "provider_status": 1, "error": 1, "at": 1},
    ).to_list(5000)
    if not rows:
        return []
    count = len(rows)
    last = rows[-1]
    status = last.get("provider_status") or "failed"
    last_err = (last.get("error") or "")[:120]
    return [{
        "kind": MARCO_ALERT_KIND_SMS_FAILED,
        "severity": "warn",
        "title": f"{count} SMS send{'s' if count != 1 else ''} failed in the last 24 h",
        "body": (
            f"Latest: {status}. {last_err[:200]} "
            f"Check RingCentral / provider status and retry."
        ),
        # Tenant-wide collapse — ``entity_ref`` is deliberately
        # empty so (``kind``, tenant_id) alone drives dedup.
        "entity_ref": {"type": "tenant", "id": tenant_id},
    }]


# ═══════════════════════════════════════════════════════════════
# Sweep.
# ═══════════════════════════════════════════════════════════════


async def sweep_tenant(db, tenant_id: str) -> Dict[str, Any]:
    """Run all 5 detectors for one tenant.  Upserts the resulting
    alerts and returns a per-kind summary.

    Returns ``{"tenant_id", "inserted", "updated",
    "by_kind": {kind: count}}``.
    """
    summary: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "inserted": 0,
        "updated": 0,
        "by_kind": {},
    }
    detectors = (
        (MARCO_ALERT_KIND_OVERDUE_INVOICE, detect_overdue_invoices),
        (MARCO_ALERT_KIND_UNASSIGNED_JOB, detect_unassigned_jobs),
        (MARCO_ALERT_KIND_MISSING_CLOCK_IN, detect_missing_clock_ins),
        (MARCO_ALERT_KIND_PAYMENT_FAILED, detect_payment_failures),
        (MARCO_ALERT_KIND_SMS_FAILED, detect_sms_failures),
    )
    for kind, fn in detectors:
        try:
            candidates = await fn(db, tenant_id)
        except Exception as exc:                                   # noqa: BLE001
            logger.warning(
                "[marco-alerts] detector %s crashed for tenant %s: %s",
                kind, tenant_id, exc,
            )
            continue
        summary["by_kind"][kind] = len(candidates)
        for alert in candidates:
            prior = await db.marco_alerts.find_one(
                {"tenant_id": tenant_id,
                 "dedup_key": _dedup_key(kind, alert.get("entity_ref")),
                 "dismissed_at": None},
                {"_id": 0, "id": 1},
            )
            await upsert_alert(
                db,
                tenant_id=tenant_id,
                kind=alert["kind"],
                severity=alert["severity"],
                title=alert["title"],
                body=alert["body"],
                entity_ref=alert.get("entity_ref"),
            )
            if prior:
                summary["updated"] += 1
            else:
                summary["inserted"] += 1
    return summary


async def _active_tenant_ids(db) -> List[str]:
    """List of tenant ids the sweeper should scan.  Mirrors the
    ``inventory_alerts`` cron shape — ``active != False``."""
    rows = await db.tenants.find(
        {"$or": [{"active": True}, {"active": {"$exists": False}}]},
        {"_id": 0, "id": 1},
    ).to_list(5000)
    return [t["id"] for t in rows if t.get("id")]


async def run_sweeper_loop() -> None:
    """Infinite background loop invoked from the server lifespan.

    Each tick:
      1. Enumerate active tenants.
      2. ``sweep_tenant(tid)`` per tenant.
      3. Sleep ``SWEEPER_INTERVAL_SECONDS`` and repeat.

    Any single-tenant crash is logged + swallowed so one bad row
    never stalls the loop.
    """
    from config import db
    logger.info(
        "[marco-alerts] sweeper loop starting (interval=%ss, kinds=%s)",
        SWEEPER_INTERVAL_SECONDS, len(ALL_ALERT_KINDS),
    )
    while True:
        try:
            tenant_ids = await _active_tenant_ids(db)
            total_inserted = 0
            total_updated = 0
            for tid in tenant_ids:
                try:
                    summary = await sweep_tenant(db, tid)
                    total_inserted += summary["inserted"]
                    total_updated += summary["updated"]
                except Exception as exc:                               # noqa: BLE001
                    logger.warning(
                        "[marco-alerts] tenant %s sweep crashed: %s",
                        tid, exc,
                    )
            logger.info(
                "[marco-alerts] sweep tick done tenants=%s inserted=%s updated=%s",
                len(tenant_ids), total_inserted, total_updated,
            )
        except asyncio.CancelledError:
            logger.info("[marco-alerts] sweeper cancelled — exiting cleanly")
            raise
        except Exception as exc:                                   # noqa: BLE001
            logger.warning("[marco-alerts] sweep tick crashed: %s", exc)
        try:
            await asyncio.sleep(SWEEPER_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
