"""DATA-PARITY-C2 · Feb-2026 — Portal/admin service-records parity.

The portal
(``routers/service_reports.py::list_my_service_reports``) and the
admin
(``routers/service_reports.py::notes_archive`` /
``_build_archive_pipeline``) both filter to
``submitted_at: {$ne: null}`` on customer-scoped jobs — same
visible-set definition by design (drafts are tech-WIP and not
shown to customers).

This test file locks the contract:

  1. Shared canonical filter ``visible_service_report_filter`` is
     the shape every reader must use.
  2. Portal count matches admin count for the same customer.
  3. Draft (unsubmitted) report is INVISIBLE to both surfaces.
  4. Audit endpoint auth gate (403 non-admin).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


_PREFIX = "TEST-sr-parity-"


def _mk_tid() -> str: return _PREFIX + uuid.uuid4().hex[:12]
def _mk_cid() -> str: return _PREFIX + "c-" + uuid.uuid4().hex[:12]


async def _seed(db, tid: str, cid: str) -> dict:
    """Seed one customer with two jobs: one with a SUBMITTED
    service report, one with a DRAFT (unsubmitted) report.
    Returns the submitted + draft report ids for assertions.
    """
    jid_sub = _PREFIX + "j-s-" + uuid.uuid4().hex[:8]
    jid_draft = _PREFIX + "j-d-" + uuid.uuid4().hex[:8]
    rid_sub = _PREFIX + "r-s-" + uuid.uuid4().hex[:8]
    rid_draft = _PREFIX + "r-d-" + uuid.uuid4().hex[:8]
    await db.customers.insert_one(
        {"id": cid, "tenant_id": tid, "name": "SR Fixture"},
    )
    for jid in (jid_sub, jid_draft):
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "customer_id": cid,
            "status": "completed", "title": "Visit",
        })
    await db.service_reports.insert_one({
        "id": rid_sub, "tenant_id": tid, "job_id": jid_sub,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.service_reports.insert_one({
        "id": rid_draft, "tenant_id": tid, "job_id": jid_draft,
        "submitted_at": None,
    })
    return {"submitted_id": rid_sub, "draft_id": rid_draft,
            "jid_sub": jid_sub, "jid_draft": jid_draft}


async def _cleanup(db, tid: str) -> None:
    await db.customers.delete_many({"tenant_id": tid})
    await db.jobs.delete_many({"tenant_id": tid})
    await db.service_reports.delete_many({"tenant_id": tid})


def _rebind(db) -> None:
    import routers.admin_migrations as _am
    _am.db = db


# ═══════════════════════════════════════════════════════════════════
# 1. Shared canonical filter matches only submitted reports.
# ═══════════════════════════════════════════════════════════════════
def test_canonical_filter_matches_submitted_but_not_draft():
    async def _go(db):
        from services.customer_service_records import (
            visible_service_report_filter,
        )
        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            fixture = await _seed(db, tid, cid)
            job_ids = [fixture["jid_sub"], fixture["jid_draft"]]
            q = visible_service_report_filter(tid, job_ids)
            matched_ids = {
                r["id"] async for r in db.service_reports.find(
                    q, {"_id": 0, "id": 1},
                )
            }
            assert fixture["submitted_id"] in matched_ids
            assert fixture["draft_id"] not in matched_ids
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2. Empty job-id set returns a filter that matches nothing.
# ═══════════════════════════════════════════════════════════════════
def test_canonical_filter_empty_job_ids_matches_no_rows():
    async def _go(db):
        from services.customer_service_records import (
            visible_service_report_filter,
        )
        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed(db, tid, cid)
            # Call with EMPTY job_ids — should return a shape that
            # matches zero rows (not a shape that forgets the
            # scope and leaks everything).
            q = visible_service_report_filter(tid, [])
            cnt = await db.service_reports.count_documents(q)
            assert cnt == 0
        finally:
            await _cleanup(db, tid)
    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3. Audit endpoint auth gate.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["customer", "technician"])
def test_service_records_audit_endpoint_rejects_non_admin(role):
    async def _go(db):
        _rebind(db)
        from routers.admin_migrations import (
            run_customer_service_records_audit,
        )
        user = {"id": "u", "role": role}
        tenant = {"id": "t-x"}
        with pytest.raises(HTTPException) as excinfo:
            await run_customer_service_records_audit(
                fix=False, limit=None, user=user, tenant=tenant,
            )
        assert excinfo.value.status_code == 403
    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4. Admin dry-run returns the expected report shape.
# ═══════════════════════════════════════════════════════════════════
def test_service_records_audit_admin_dry_run_report_shape():
    async def _go(db):
        _rebind(db)
        from routers.admin_migrations import (
            run_customer_service_records_audit,
        )
        tid, cid = _mk_tid(), _mk_cid()
        await _cleanup(db, tid)
        try:
            await _seed(db, tid, cid)
            user = {"id": "admin-x", "role": "admin"}
            tenant = {"id": tid}
            r = await run_customer_service_records_audit(
                fix=False, limit=None, user=user, tenant=tenant,
            )
            assert r["ok"] is True
            assert r["fix"] is False
            assert r["tenant_id"] == tid
            assert r["customers_scanned"] >= 1
            # Admin == portal count (same canonical filter).
            assert r["customers_drifted"] == 0
            assert "mismatches" in r
            assert "note" in r
        finally:
            await _cleanup(db, tid)
    run_test(_go)
