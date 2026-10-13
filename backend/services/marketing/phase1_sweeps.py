"""Feb 2026 · Marketing · Phase 1 — Daily cron sweeps for time-based
events that don't fire from a synchronous router touchpoint.

Three events are handled here — they all share the same skeleton:

    for tenant in db.tenants:            # per-tenant loop, isolated
        try:
            handle(tenant)               # slow tenant does NOT block others
        except Exception as exc:
            logger.warning(...)

Per-tenant isolation is a hard requirement (see the "one slow query
shouldn't block another tenant" note in the spec). Each helper runs
its own query set inside the ``try`` block; the outer loop keeps
going regardless.

Events covered
--------------
* ``invoice_overdue`` — invoices whose ``due_date`` fell BEFORE today
  and whose ``payment_status`` isn't ``paid`` / ``refunded``. Only
  fires ONCE per invoice (dedupe via
  ``marketing_event_ledger`` unique index on
  ``(tenant, customer, event_key)``).
* ``customer_birthday`` — customers whose ``birthday`` MM-DD matches
  today (UTC). Correlation key is the customer id + year so the same
  customer fires ONCE per birthday (never twice on Feb-29 for
  non-leap edges either).
* ``service_anniversary`` — customers whose ``first_service_at`` or
  ``created_at`` MM-DD matches today AND the year offset is ≥1.
  Correlation key includes the anniversary year so a customer who
  hits 1yr, 2yr, 3yr fires cleanly each rollover.
* ``job_scheduled_reminder_1d`` — re-arm for schema_v2 sequences.
  The legacy sweep in ``drip_events.py`` still handles v1
  sequences; this delegates to ``emit_event`` so v2 sequences with
  the reminder event ALSO fire. Both paths dedupe against the same
  ledger so we don't double-send.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db

from services.marketing.event_dispatcher import emit_event


logger = logging.getLogger(__name__)


def _today_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_date(d: datetime) -> str:
    return d.date().isoformat()


async def _sweep_invoice_overdue(tenant_id: str) -> int:
    """Fire ``invoice_overdue`` for every unpaid invoice whose
    ``due_date`` is before today. Dedupes per-invoice via the ledger's
    unique key (correlation_id == invoice id).

    Only invoices that actually have a ``customer_id`` participate —
    dashboard-created invoices without a linked customer skip.

    Feb-2026 · Automation suppression gate — PDF-imported invoices
    (``automations_suppressed=True``) + non-unpaid invoices skip
    emission here. We also push the suppression predicate into the
    Mongo query as a first-pass filter so large PDF-imported
    archives don't dominate the per-tenant scan.  The per-row
    eligibility helper remains the authoritative gate.
    """
    from services.automations.eligibility import (
        is_invoice_eligible_for_automation,
        log_batch_skipped,
    )
    from utils import new_id as _new_run_id

    run_id = _new_run_id()
    now = _today_utc()
    today = _iso_date(now)
    fired = 0
    reason_breakdown: Dict[str, int] = {}
    skipped_total = 0
    cursor = db.quotes.find(
        {
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "due_date": {"$lt": today},
            "payment_status": {"$nin": ["paid", "refunded",
                                             "partially_refunded"]},
            "customer_id": {"$exists": True, "$nin": [None, ""]},
            # First-pass perf filter — authoritative gate is the
            # per-row helper below.
            "automations_suppressed": {"$ne": True},
        },
        {"_id": 0, "id": 1, "customer_id": 1, "due_date": 1,
         "total": 1, "amount_paid": 1, "payment_status": 1,
         "status": 1, "automations_suppressed": 1, "deleted_at": 1},
    )
    async for inv in cursor:
        eligible, reason = is_invoice_eligible_for_automation(
            inv, automation_kind="payment_reminder",
        )
        if not eligible:
            skipped_total += 1
            reason_breakdown[reason] = reason_breakdown.get(reason, 0) + 1
            logger.info(
                "automation.skipped kind=payment_reminder "
                "invoice_id=%s reason=%s", inv.get("id"), reason,
            )
            continue
        out = await emit_event(
            event="invoice_overdue",
            tenant_id=tenant_id,
            entity_id=inv.get("id"),
            customer_id=inv.get("customer_id"),
            payload_extras={"invoice": inv,
                              "correlation_id": inv.get("id")},
        )
        # ``emit_event`` returns ``deduped=1`` when the ledger already
        # has this event — that means the sweep is idempotent by
        # construction. We only count NEW fires so the summary log is
        # useful.
        if out.get("enrolled") or out.get("matched_sequences"):
            fired += 1
    await log_batch_skipped(
        tenant_id=tenant_id,
        automation_kind="payment_reminder",
        run_id=run_id,
        reason_breakdown=reason_breakdown,
        total_skipped=skipped_total,
    )
    return fired


async def _sweep_customer_birthday(tenant_id: str) -> int:
    """Fire ``customer_birthday`` for every customer whose
    ``birthday`` MM-DD == today. Correlation key = ``{customer_id}:{year}``
    so the same customer fires once per calendar year."""
    now = _today_utc()
    mmdd = now.strftime("%m-%d")
    year = now.year
    fired = 0
    cursor = db.customers.find(
        {"tenant_id": tenant_id,
         "birthday": {"$regex": f"-{mmdd}$"}},
        {"_id": 0, "id": 1, "birthday": 1},
    )
    async for cust in cursor:
        cid = cust.get("id")
        if not cid:
            continue
        out = await emit_event(
            event="customer_birthday",
            tenant_id=tenant_id,
            entity_id=cid,
            customer_id=cid,
            payload_extras={
                "birthday": cust.get("birthday"),
                "correlation_id": f"{cid}:birthday:{year}",
            },
        )
        if out.get("enrolled") or out.get("matched_sequences"):
            fired += 1
    return fired


async def _sweep_service_anniversary(tenant_id: str) -> int:
    """Fire ``service_anniversary`` for every customer whose
    ``first_service_at`` (fallback ``created_at``) MM-DD == today AND
    the anniversary year offset is ≥1.

    Correlation key: ``{customer_id}:anniversary:{years}`` so the 1yr,
    2yr, 3yr rollovers each fire cleanly.
    """
    now = _today_utc()
    mmdd = now.strftime("%m-%d")
    fired = 0
    # Match either ``first_service_at`` OR ``created_at`` on the same
    # month-day — we filter for the year offset in Python since Mongo
    # can't compute it cheaply without a $expr aggregation.
    cursor = db.customers.find(
        {"tenant_id": tenant_id,
         "$or": [
             {"first_service_at": {"$regex": f"-{mmdd}"}},
             {"created_at": {"$regex": f"-{mmdd}"}},
         ]},
        {"_id": 0, "id": 1, "first_service_at": 1, "created_at": 1},
    )
    async for cust in cursor:
        cid = cust.get("id")
        if not cid:
            continue
        anchor = cust.get("first_service_at") or cust.get("created_at") or ""
        try:
            anchor_dt = datetime.fromisoformat(str(anchor).replace("Z", "+00:00"))
            if anchor_dt.tzinfo is None:
                anchor_dt = anchor_dt.replace(tzinfo=timezone.utc)
            years = now.year - anchor_dt.year
        except Exception:
            continue
        # Skip same-year (year 0 = "created today") and future dates.
        if years < 1:
            continue
        # Guard against the anchor's MM-DD not matching today after
        # ISO parse — the $regex above is a coarse filter that also
        # matches ``YYYY-MM-DD`` occurring inside a longer timestamp;
        # re-check the month-day exactly here.
        if anchor_dt.strftime("%m-%d") != mmdd:
            continue
        out = await emit_event(
            event="service_anniversary",
            tenant_id=tenant_id,
            entity_id=cid,
            customer_id=cid,
            payload_extras={
                "anniversary_years": years,
                "anchor_date": anchor_dt.date().isoformat(),
                "correlation_id": f"{cid}:anniversary:{years}",
            },
        )
        if out.get("enrolled") or out.get("matched_sequences"):
            fired += 1
    return fired


async def _sweep_job_scheduled_reminder_1d(tenant_id: str) -> int:
    """Re-arm the day-before reminder for schema_v2 sequences.

    Legacy v1 sequences are handled by ``drip_events._sweep_job_scheduled_reminder_1d``
    (which enrols them into their own trigger_type=='job_scheduled_reminder_1d'
    match). This helper additionally emits the canonical
    ``job_scheduled_reminder_1d`` event so v2 sequences that name it in
    their conditions also fire. Both paths dedupe against the same
    ledger.
    """
    now = _today_utc()
    tomorrow = _iso_date(now + timedelta(days=1))
    fired = 0
    cursor = db.jobs.find(
        {"tenant_id": tenant_id,
         "scheduled_date": tomorrow,
         "status": {"$in": ["scheduled", "pending"]}},
        {"_id": 0, "id": 1, "customer_id": 1, "scheduled_date": 1,
         "work_class": 1, "technician_id": 1, "crew_id": 1,
         "job_value": 1, "total": 1},
    )
    async for job in cursor:
        jid = job.get("id")
        cid = job.get("customer_id")
        if not (jid and cid):
            continue
        out = await emit_event(
            event="job_scheduled_reminder_1d",
            tenant_id=tenant_id,
            entity_id=jid,
            customer_id=cid,
            scheduled_at=f"{tomorrow}T09:00:00+00:00",
            payload_extras={
                "job": job,
                "correlation_id": f"{jid}:reminder1d:{tomorrow}",
            },
        )
        if out.get("enrolled") or out.get("matched_sequences"):
            fired += 1
    return fired


# ─── Public entry point ──────────────────────────────────────────────
async def daily_phase1_trigger_sweep() -> Dict[str, Any]:
    """Runs once at 09:00 UTC (registered from ``server.py`` alongside
    the legacy M5c sweep).

    Returns a summary dict logged at INFO level so ops can grep the
    daily emit outcome.
    """
    total: Dict[str, Any] = {
        "tenants": 0,
        "invoice_overdue": 0,
        "customer_birthday": 0,
        "service_anniversary": 0,
        "job_scheduled_reminder_1d": 0,
        "tenants_errored": 0,
    }
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        total["tenants"] += 1
        tid = t.get("id")
        if not tid:
            continue
        # Per-tenant isolation: a crash inside one tenant's sweep MUST
        # NOT block another tenant. Each sub-sweep is wrapped so a
        # single slow query only affects its own bucket.
        try:
            total["invoice_overdue"] += await _sweep_invoice_overdue(tid)
        except Exception as exc:
            total["tenants_errored"] += 1
            logger.warning(
                "[phase1_sweeps] invoice_overdue tenant=%s crashed: %s",
                tid, exc,
            )
        try:
            total["customer_birthday"] += await _sweep_customer_birthday(tid)
        except Exception as exc:
            total["tenants_errored"] += 1
            logger.warning(
                "[phase1_sweeps] customer_birthday tenant=%s crashed: %s",
                tid, exc,
            )
        try:
            total["service_anniversary"] += await _sweep_service_anniversary(tid)
        except Exception as exc:
            total["tenants_errored"] += 1
            logger.warning(
                "[phase1_sweeps] service_anniversary tenant=%s crashed: %s",
                tid, exc,
            )
        try:
            total["job_scheduled_reminder_1d"] += (
                await _sweep_job_scheduled_reminder_1d(tid)
            )
        except Exception as exc:
            total["tenants_errored"] += 1
            logger.warning(
                "[phase1_sweeps] job_scheduled_reminder_1d tenant=%s crashed: %s",
                tid, exc,
            )
    logger.info("[phase1_sweeps] daily sweep — %s", total)
    return total
