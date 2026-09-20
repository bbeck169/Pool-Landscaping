"""Phase A1 · Feb-2026 · Proactive Intelligence — Missed Service scan.

Producer #1 for the ``intelligence_alerts`` store. Every morning at
07:00 UTC (APScheduler) this scans every tenant's recurring-job
occurrences that were scheduled for yesterday and whose ``status``
is NOT in :data:`_COMPLETED_STATES`. Each hit becomes an ``urgent``
alert under ``category="missed_service"``.

Recurring-job detection
-----------------------
The current recurrence model stamps ``recurring_template_id`` on the
per-occurrence ``jobs`` row (verified live on the DB). We treat a
row as "recurring" when that field is set (non-empty). No
``is_recurring`` bool exists on the collection; ``parent_series_id``
is unused in prod today.

Idempotency
-----------
Each alert carries ``alert_key = "missed_service:job:{job_id}:{yyyy-mm-dd}"``.
The unique dedup index on ``(tenant_id, alert_key)`` guarantees
re-running the cron for the same date is a no-op.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from config import db
from services.intelligence.alerts import emit_alert

logger = logging.getLogger("intelligence.missed_service_scan")

# Statuses considered "closed" for a scheduled-but-not-worked
# occurrence. Anything OUTSIDE this set counts as missed for the
# purposes of A1.
_COMPLETED_STATES = {
    "completed",
    "skipped_by_customer",
    "cancelled_by_customer",
    "cancelled",       # legacy alias — some tenants stamp this
    "skipped",         # legacy alias
}


def _yesterday(now: Optional[datetime]) -> datetime:
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return (ref - timedelta(days=1)).astimezone(timezone.utc)


def _scheduled_date_prefix(job: Dict[str, Any]) -> str:
    """Return the YYYY-MM-DD portion of the job's scheduled date.
    Handles both ``2026-02-14`` and ``2026-02-14T09:00:00+00:00``
    (the two shapes present in seed data)."""
    raw = job.get("scheduled_date") or ""
    return str(raw)[:10]


async def _customer_name(tenant_id: str, customer_id: str) -> str:
    if not customer_id:
        return "(customer removed)"
    row = await db.customers.find_one(
        {"id": customer_id, "tenant_id": tenant_id},
        {"_id": 0, "name": 1},
    )
    return (row or {}).get("name") or customer_id


async def _iter_tenant_ids(explicit: Optional[str]) -> Iterable[str]:
    if explicit:
        return [explicit]
    out: List[str] = []
    async for t in db.tenants.find(
        {"active": True}, {"_id": 0, "id": 1},
    ):
        if t.get("id"):
            out.append(t["id"])
    return out


async def run_missed_service_scan(
    tenant_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Scan yesterday's recurring occurrences for the given tenant
    (or every active tenant when ``tenant_id`` is None).

    :returns: A summary dict:
        ``{"tenant_id", "date", "scanned_jobs", "alerts_emitted",
        "alerts_deduped"}``. When multiple tenants are scanned the
        top-level dict aggregates + also carries a per-tenant
        breakdown under ``"by_tenant"``.
    """
    ref = _yesterday(now)
    yday_prefix = ref.strftime("%Y-%m-%d")
    tenants = await _iter_tenant_ids(tenant_id)
    aggregate = {
        "tenant_id":      tenant_id,
        "date":           yday_prefix,
        "scanned_jobs":   0,
        "alerts_emitted": 0,
        "alerts_deduped": 0,
        "by_tenant":      {},
    }
    for tid in tenants:
        scanned = emitted = deduped = 0
        # Match both ``2026-02-14`` and ``2026-02-14T...`` shapes.
        query = {
            "tenant_id":             tid,
            "recurring_template_id": {"$exists": True, "$ne": None},
            "scheduled_date":        {"$regex": f"^{yday_prefix}"},
        }
        async for job in db.jobs.find(query, {
            "_id": 0, "id": 1, "customer_id": 1, "status": 1,
            "service_type": 1, "scheduled_date": 1,
            "assigned_technician_id": 1, "recurring_template_id": 1,
        }):
            scanned += 1
            if (job.get("status") or "") in _COMPLETED_STATES:
                continue
            job_id = job.get("id") or ""
            if not job_id:
                continue
            customer_name = await _customer_name(
                tid, job.get("customer_id") or "")
            service = job.get("service_type") or "Service"
            inserted, _doc = await emit_alert(
                tid,
                category="missed_service",
                severity="urgent",
                alert_key=f"missed_service:job:{job_id}:{yday_prefix}",
                title=f"Missed service: {customer_name}",
                body=(f"{service} scheduled {yday_prefix} was not "
                       f"completed"),
                customer_id=job.get("customer_id"),
                job_id=job_id,
                actor_context={
                    "scheduled_date":  _scheduled_date_prefix(job),
                    "assigned_tech_id": job.get(
                        "assigned_technician_id"),
                    "status":          job.get("status") or "unknown",
                    "recurring_template_id": job.get(
                        "recurring_template_id"),
                },
            )
            if inserted:
                emitted += 1
            else:
                deduped += 1
        aggregate["scanned_jobs"]   += scanned
        aggregate["alerts_emitted"] += emitted
        aggregate["alerts_deduped"] += deduped
        aggregate["by_tenant"][tid] = {
            "scanned_jobs":   scanned,
            "alerts_emitted": emitted,
            "alerts_deduped": deduped,
        }
    # When the caller specified a single tenant, mirror the counts
    # at the top-level for convenience and drop the by_tenant map.
    if tenant_id and tenant_id in aggregate["by_tenant"]:
        aggregate.update(aggregate["by_tenant"][tenant_id])
        aggregate["by_tenant"] = {tenant_id: aggregate["by_tenant"][tenant_id]}
    return aggregate


async def run_missed_service_scan_all_tenants() -> Dict[str, Any]:
    """APScheduler entry point — no arguments, no return.  Wraps the
    tenant-fan-out :func:`run_missed_service_scan` with logging."""
    try:
        result = await run_missed_service_scan(tenant_id=None)
        logger.info(
            "[missed-service-scan] date=%s scanned=%d emitted=%d "
            "deduped=%d",
            result["date"], result["scanned_jobs"],
            result["alerts_emitted"], result["alerts_deduped"],
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("[missed-service-scan] failed: %s", exc)
        return {"error": str(exc)}
