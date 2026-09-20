"""Phase A3 · Feb-2026 · Proactive Intelligence — Churn Risk scan.

Producer #3 for the ``intelligence_alerts`` store. Detects two
independent early-warning signals per customer and emits ONE
alert per (customer, signal) tuple:

* **Signal 1 · Missed payments** — customer has ≥ 2 invoices
  currently in ``past_due`` / ``overdue``. ``urgent`` severity.
* **Signal 2 · Recurring cancellation** — a recurring job / series
  has been cancelled BY THE CUSTOMER (``status="cancelled_by_customer"``
  + ``is_recurring=True``). ``recommended`` severity. Only the
  customer-initiated status counts — office / admin cancellations
  are intentionally ignored per the Phase A3 spec.

Idempotency
-----------
* Missed-payments alert key encodes the current unpaid count:
  ``churn_risk:cust:{cid}:missed_payments:{count}``. Rerunning on
  the same count is a no-op; when the debt grows to N+1 a fresh
  alert emits (the count-2 alert remains historical).
* Recurring-cancellation alert key is per-cancelled-series:
  ``churn_risk:cust:{cid}:recurring_cancelled:{job_id}``. Once
  emitted the alert is permanently deduped for that job.

Both signals emit via the shared A1 ``emit_alert()`` helper.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from services.intelligence.alerts import emit_alert

logger = logging.getLogger("intelligence.churn_risk_scan")


_UNPAID_STATUSES = ("past_due", "overdue")


def _parse_iso(raw: Any) -> Optional[datetime]:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str) or not raw:
        return None
    try:
        # ``2026-02-14T09:00:00+00:00`` and ``2026-02-14`` both parse via fromisoformat.
        norm = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(norm)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _short_date(raw: Any) -> str:
    dt = _parse_iso(raw)
    if not dt:
        return str(raw)[:10] if isinstance(raw, str) else ""
    return dt.date().isoformat()


def _fmt_currency_cents(cents: int) -> str:
    try:
        v = float(cents) / 100.0
        return f"${v:,.2f}"
    except (TypeError, ValueError):
        return f"${cents}"


def _invoice_amount_cents(inv: Dict[str, Any]) -> int:
    """Best-effort read of the money owed on an invoice row.

    The invoice schema has drifted across phases; this helper checks
    the canonical fields in order and always returns a non-negative
    integer.  Unknown / string amounts are coerced via ``float``.
    """
    for key in ("amount_due_cents", "total_cents", "amount_due",
                 "total", "amount"):
        raw = inv.get(key)
        if raw is None or raw == "":
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        # Fields with ``_cents`` suffix are already in cents; everything
        # else is a dollar float — multiply.
        if key.endswith("_cents"):
            return int(round(val))
        return int(round(val * 100))
    return 0


def _invoice_days_overdue(inv: Dict[str, Any], ref: datetime) -> int:
    for key in ("due_date", "issued_at", "issue_date", "created_at"):
        raw = inv.get(key)
        dt = _parse_iso(raw)
        if dt:
            delta = ref - dt
            return max(int(delta.days), 0)
    return 0


async def _customer_name(tenant_id: str, cid: str) -> str:
    if not cid:
        return "(customer removed)"
    row = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant_id},
        {"_id": 0, "name": 1},
    )
    return (row or {}).get("name") or cid


async def _iter_tenant_ids(explicit: Optional[str]) -> List[str]:
    if explicit:
        return [explicit]
    out: List[str] = []
    async for t in db.tenants.find({"active": True},
                                    {"_id": 0, "id": 1}):
        if t.get("id"):
            out.append(t["id"])
    return out


async def _scan_missed_payments(
    tenant_id: str, ref: datetime,
) -> Dict[str, int]:
    """Emit one alert per customer with ≥2 unpaid invoices."""
    emitted = deduped = 0
    # Aggregate unpaid invoices per customer for this tenant.
    pipeline = [
        {"$match": {"tenant_id": tenant_id,
                     "status":    {"$in": list(_UNPAID_STATUSES)}}},
        {"$group": {"_id": "$customer_id",
                     "invoices": {"$push": "$$ROOT"}}},
        {"$match": {"$expr": {"$gte": [{"$size": "$invoices"}, 2]}}},
    ]
    async for group in db.invoices.aggregate(pipeline):
        cid = group.get("_id")
        if not cid:
            continue
        invoices = group.get("invoices") or []
        count = len(invoices)
        total_cents = sum(_invoice_amount_cents(i) for i in invoices)
        oldest_days = max(
            (_invoice_days_overdue(i, ref) for i in invoices),
            default=0,
        )
        invoice_ids = [str(i.get("id") or i.get("_id"))
                        for i in invoices]
        cname = await _customer_name(tenant_id, cid)

        title = (f"Payment risk: {cname} "
                 f"({count} unpaid invoices)")
        body = (f"{count} invoices past due totaling "
                f"{_fmt_currency_cents(total_cents)}. "
                f"Recommend collections outreach.")
        alert_key = (f"churn_risk:cust:{cid}:"
                     f"missed_payments:{count}")
        actor_context = {
            "signal":              "missed_payments",
            "invoice_count":       count,
            "total_amount_cents":  total_cents,
            "oldest_days_overdue": oldest_days,
            "invoice_ids":         invoice_ids,
        }
        inserted, _doc = await emit_alert(
            tenant_id,
            category="churn_risk",
            severity="urgent",
            alert_key=alert_key,
            title=title,
            body=body,
            customer_id=cid,
            job_id=None,
            actor_context=actor_context,
        )
        if inserted:
            emitted += 1
        else:
            deduped += 1

    return {"emitted": emitted, "deduped": deduped}


async def _scan_recurring_cancellations(
    tenant_id: str,
) -> Dict[str, int]:
    """Emit one alert per customer-cancelled recurring series /
    job.  Only ``status == "cancelled_by_customer"`` +
    ``is_recurring == True`` counts."""
    emitted = deduped = 0
    async for job in db.jobs.find(
        {"tenant_id": tenant_id,
         "status":    "cancelled_by_customer",
         "is_recurring": True},
        {"_id": 0, "id": 1, "customer_id": 1, "service_type": 1,
         "cancelled_at": 1, "cancellation_reason": 1,
         "updated_at": 1, "scheduled_date": 1,
         "parent_series_id": 1},
    ):
        jid = job.get("id")
        cid = job.get("customer_id")
        if not jid or not cid:
            continue
        cname = await _customer_name(tenant_id, cid)
        service = job.get("service_type") or "recurring service"
        cancelled_iso = (job.get("cancelled_at")
                         or job.get("updated_at")
                         or job.get("scheduled_date"))
        cancelled_short = _short_date(cancelled_iso)
        title = f"Churn risk: {cname} cancelled recurring service"
        body = (f"{service} recurring series cancelled on "
                f"{cancelled_short}. "
                f"Recommend save-the-account outreach.")
        alert_key = (f"churn_risk:cust:{cid}:"
                     f"recurring_cancelled:{jid}")
        actor_context = {
            "signal":              "recurring_cancelled",
            "job_id":              jid,
            "service_type":        service,
            "cancelled_at":        (cancelled_iso.isoformat()
                                     if isinstance(cancelled_iso, datetime)
                                     else cancelled_iso),
            "cancelled_at_short":  cancelled_short,
            "cancellation_reason": job.get("cancellation_reason"),
            "parent_series_id":    job.get("parent_series_id"),
        }
        inserted, _doc = await emit_alert(
            tenant_id,
            category="churn_risk",
            severity="recommended",
            alert_key=alert_key,
            title=title,
            body=body,
            customer_id=cid,
            job_id=jid,
            actor_context=actor_context,
        )
        if inserted:
            emitted += 1
        else:
            deduped += 1
    return {"emitted": emitted, "deduped": deduped}


async def _scan_one_tenant(
    tenant_id: str, ref: datetime,
) -> Dict[str, Any]:
    """Per-tenant fan-out for both churn signals."""
    # Approximate ``scanned_customers`` = distinct customers we
    # examined across both signals. Cheap enough at daily-cadence
    # to compute via a distinct().
    seen = set()
    async for row in db.invoices.aggregate([
        {"$match": {"tenant_id": tenant_id,
                     "status":    {"$in": list(_UNPAID_STATUSES)}}},
        {"$group": {"_id": "$customer_id"}},
    ]):
        if row.get("_id"):
            seen.add(row["_id"])
    async for row in db.jobs.aggregate([
        {"$match": {"tenant_id": tenant_id,
                     "status":    "cancelled_by_customer",
                     "is_recurring": True}},
        {"$group": {"_id": "$customer_id"}},
    ]):
        if row.get("_id"):
            seen.add(row["_id"])

    mp = await _scan_missed_payments(tenant_id, ref)
    rc = await _scan_recurring_cancellations(tenant_id)
    return {
        "scanned_customers": len(seen),
        "alerts_emitted":    mp["emitted"] + rc["emitted"],
        "alerts_deduped":    mp["deduped"] + rc["deduped"],
        "by_signal": {
            "missed_payments":     mp["emitted"],
            "recurring_cancelled": rc["emitted"],
        },
    }


async def run_churn_risk_scan(
    tenant_id: Optional[str] = None,
    now:       Optional[datetime] = None,
) -> Dict[str, Any]:
    """Scan for churn-risk signals across one or all active tenants."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    tids = await _iter_tenant_ids(tenant_id)
    aggregate: Dict[str, Any] = {
        "tenant_id":         tenant_id,
        "scanned_customers": 0,
        "alerts_emitted":    0,
        "alerts_deduped":    0,
        "by_signal": {"missed_payments": 0,
                       "recurring_cancelled": 0},
        "by_tenant":         {},
    }
    for tid in tids:
        summary = await _scan_one_tenant(tid, ref)
        aggregate["scanned_customers"] += summary["scanned_customers"]
        aggregate["alerts_emitted"]    += summary["alerts_emitted"]
        aggregate["alerts_deduped"]    += summary["alerts_deduped"]
        aggregate["by_signal"]["missed_payments"] += (
            summary["by_signal"]["missed_payments"])
        aggregate["by_signal"]["recurring_cancelled"] += (
            summary["by_signal"]["recurring_cancelled"])
        aggregate["by_tenant"][tid] = summary
    if tenant_id and tenant_id in aggregate["by_tenant"]:
        per = aggregate["by_tenant"][tenant_id]
        aggregate.update({
            "scanned_customers": per["scanned_customers"],
            "alerts_emitted":    per["alerts_emitted"],
            "alerts_deduped":    per["alerts_deduped"],
            "by_signal":         per["by_signal"],
        })
        aggregate["by_tenant"] = {tenant_id: per}
    return aggregate


async def run_churn_risk_scan_all_tenants() -> Dict[str, Any]:
    """APScheduler entry point — logs a compact summary line and
    swallows unexpected exceptions so a single-tenant failure
    doesn't crash the cron loop."""
    try:
        result = await run_churn_risk_scan(tenant_id=None)
        logger.info(
            "[churn-risk-scan] scanned=%d emitted=%d deduped=%d "
            "mp=%d rc=%d tenants=%d",
            result["scanned_customers"], result["alerts_emitted"],
            result["alerts_deduped"],
            result["by_signal"]["missed_payments"],
            result["by_signal"]["recurring_cancelled"],
            len(result["by_tenant"]),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("[churn-risk-scan] failed: %s", exc)
        return {"error": str(exc)}
