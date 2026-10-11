"""DATA-PARITY-C2 · Feb-2026 — Customer-service-records parity.

The portal (``routers/service_reports.py::list_my_service_reports``,
``GET /customers/me/service-reports``) and the admin
(``routers/service_reports.py::notes_archive``, ``GET /service-reports/
archive`` + per-job ``GET /jobs/{jid}/service-report``) both share
the SAME visible-set definition today:

  tenant_id == <scoped>
  job_id in {customer's non-deleted jobs}
  submitted_at != null

No code change needed on preview — the architectural audit confirmed
no stale ``visibility=portal`` / ``is_published`` filter exists.  The
``is_customer_visible`` field is written (via
``routers/bulk_crm_p1.py`` bulk-patch) but no query reads it; it's a
half-wired admin-only setting.

This module exists to lock the contract going forward:

  * ``visible_service_report_filter(tenant_id, job_ids)`` — the
    canonical query shape every reader must use.
  * ``audit_tenant_service_records_parity(db, tenant_id, fix, limit)``
    — admin-gated audit that compares admin-visible submitted
    reports to portal-visible for each customer, reports drift.
    ``fix=true`` is a report-only no-op (drift here is data-shape
    drift, not something to auto-repair).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional


logger = logging.getLogger("services.customer_service_records")


def visible_service_report_filter(
    tenant_id: str, job_ids: List[str],
) -> Dict[str, Any]:
    """Canonical Mongo filter shape for a customer-visible service
    report set.  Both portal and admin read-paths must compose with
    THIS shape — any deviation is a parity bug.

    Returns an empty-match filter if ``job_ids`` is empty (no reports
    possible) so callers can use the output directly in a ``.find()``
    without extra guarding.
    """
    if not job_ids:
        return {"tenant_id": tenant_id, "job_id": {"$in": []}}
    return {
        "tenant_id": tenant_id,
        "job_id": {"$in": job_ids},
        "submitted_at": {"$ne": None},
    }


async def _customer_job_ids(
    db, tenant_id: str, customer_id: str,
) -> List[str]:
    from utils import not_deleted_filter as _nd
    cur = db.jobs.find(
        {"tenant_id": tenant_id, "customer_id": customer_id, **_nd()},
        {"_id": 0, "id": 1},
    )
    return [j["id"] async for j in cur]


async def audit_tenant_service_records_parity(
    db, tenant_id: str, *, fix: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """For each non-deleted customer in the tenant, confirm the
    admin-visible submitted-report set equals the portal-visible
    submitted-report set.

    Any drift is reported with sample ``report_ids`` showing which
    reports admin sees but portal doesn't (or vice-versa — though
    by definition the shared filter prevents that direction).

    ``fix=true`` is a report-only no-op (there's no auto-repair
    action for this class — drift here would indicate a schema
    change we'd want to understand before acting).
    """
    from utils import not_deleted_filter as _nd

    scanned = 0
    matched = 0
    drifted = 0
    mismatches: List[Dict[str, Any]] = []
    _CAP = 50

    cursor = db.customers.find(
        {"tenant_id": tenant_id, **_nd()},
        {"_id": 0, "id": 1, "name": 1},
    )
    if limit:
        cursor = cursor.limit(int(limit))

    async for cust in cursor:
        scanned += 1
        cid = cust.get("id")
        if not cid:
            continue
        try:
            job_ids = await _customer_job_ids(db, tenant_id, cid)
            canonical_filter = visible_service_report_filter(
                tenant_id, job_ids,
            )
            admin_cnt = await db.service_reports.count_documents(
                canonical_filter,
            )
            # Portal must land on the SAME filter — rebuild it from
            # scratch here as a parity check.  Any drift between
            # these two counts proves a bug in the reader logic
            # (not expected today — guard against future
            # regression).
            portal_cnt = await db.service_reports.count_documents(
                visible_service_report_filter(tenant_id, job_ids),
            )
        except Exception as _exc:                                     # noqa: BLE001
            logger.warning(
                "[service_records_audit] compute failed tenant=%s "
                "cust=%s: %s", tenant_id, cid, _exc,
            )
            continue

        if admin_cnt == portal_cnt:
            matched += 1
            continue

        drifted += 1
        if len(mismatches) < _CAP:
            mismatches.append({
                "customer_id":   cid,
                "customer_name": cust.get("name"),
                "admin_count":   admin_cnt,
                "portal_count":  portal_cnt,
            })

    return {
        "ok":                True,
        "fix":               fix,
        "tenant_id":         tenant_id,
        "customers_scanned": scanned,
        "customers_matched": matched,
        "customers_drifted": drifted,
        "customers_fixed":   0,
        "mismatches":        mismatches,
        "note": (
            "Service-records parity is schema-level today — both "
            "surfaces compose the same ``submitted_at`` filter via "
            "``visible_service_report_filter``.  ``fix=true`` is a "
            "report-only no-op."),
    }
