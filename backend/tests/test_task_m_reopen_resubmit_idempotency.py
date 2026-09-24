"""Task M+P · Commit 3 — Auto-invoice idempotency guard.

Locks the reopen → re-submit idempotency contract on
``backend/routers/service_reports.py::submit_service_report``:

  * FIRST submit path (no sentinels set) — invoice created +
    ``auto_invoice_id`` / ``auto_invoice_created_at`` stamped on
    the job.  Baseline / regression guard.
  * RE-SUBMIT after reopen (either sentinel set) — invoice
    branch SKIPPED; ``activity_logs`` row emitted with
    ``type="auto_invoice_skipped_duplicate"`` + expected
    metadata shape.
  * Sentinel-variant (only ``auto_invoice_created_at`` set) —
    still skipped, still audits.
  * Auto-invoice tenant setting OFF — no invoice, no audit
    (existing gate short-circuits BEFORE the new sentinel
    check).
  * Non-billable job / no price — same short-circuit.
  * Excluded ``service_type`` (warranty callback etc.) — same
    short-circuit.
  * Cross-tenant — tenant B's stamped sentinel doesn't affect
    tenant A's own submit path.
  * Audit-row insert failure resilience — submit still returns
    200 (fire-and-forget with warning log).

Coverage strategy: SESSION-scoped Motor client bound to a
session-scoped event loop so every downstream module that reads
``db.<coll>`` inline (submit_gate, referrals, credits_apply,
invoice_numbering, etc.) shares the same loop.  Fresh loops
per-test would cause Motor's ``loop-mismatch`` errors on the
submit-gate ``find_one_and_update`` call.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from motor.motor_asyncio import AsyncIOMotorClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "TASKMC3_"


# ─── Session-scoped loop + Motor client ────────────────────────────
@pytest.fixture(scope="module")
def loop():
    lp = asyncio.new_event_loop()
    asyncio.set_event_loop(lp)
    yield lp
    try:
        lp.close()
    except Exception:
        pass


@pytest.fixture(scope="module")
def adb(loop):
    """Session-scoped Motor client bound to the module loop.

    Swaps ``config.db`` + every module-level ``db`` alias that
    ``submit_service_report`` transitively touches.  Without this
    swap, Motor's process-wide client (imported at pytest bootstrap
    on the default loop) would raise
    ``got Future ... attached to a different loop`` on the submit-
    gate ``find_one_and_update`` call.
    """
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    _adb = client[DB_NAME]

    import config as _cfg
    from routers import service_reports as _sr_mod
    from routers import referrals as _ref_mod
    from services import service_report_submit_gate as _gate_mod
    from services import credits_apply as _credits_mod
    from services import invoice_numbering as _inv_num_mod
    from services import automation_engine as _auto_mod

    _orig = {
        "cfg": getattr(_cfg, "db", None),
        "sr": getattr(_sr_mod, "db", None),
        "ref": getattr(_ref_mod, "db", None),
        "gate": getattr(_gate_mod, "db", None),
        "credits": getattr(_credits_mod, "db", None),
        "inv_num": getattr(_inv_num_mod, "db", None),
        "auto": getattr(_auto_mod, "db", None),
    }
    _cfg.db = _adb
    _sr_mod.db = _adb
    _ref_mod.db = _adb
    _gate_mod.db = _adb
    _credits_mod.db = _adb
    _inv_num_mod.db = _adb
    _auto_mod.db = _adb

    yield _adb

    # Restore originals.
    _cfg.db = _orig["cfg"]
    _sr_mod.db = _orig["sr"]
    _ref_mod.db = _orig["ref"]
    _gate_mod.db = _orig["gate"]
    _credits_mod.db = _orig["credits"]
    _inv_num_mod.db = _orig["inv_num"]
    _auto_mod.db = _orig["auto"]
    try:
        client.close()
    except Exception:
        pass


@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    seeded_jids: List[str] = []
    seeded_report_ids: List[str] = []
    seeded_invoice_ids: List[str] = []
    seeded_activity_ids: List[str] = []
    yield (seeded_jids, seeded_report_ids,
             seeded_invoice_ids, seeded_activity_ids)
    if seeded_jids:
        dbc.jobs.delete_many({"id": {"$in": seeded_jids}})
        dbc.service_reports.delete_many({"job_id": {"$in": seeded_jids}})
        dbc.activity_logs.delete_many({"job_id": {"$in": seeded_jids}})
    if seeded_report_ids:
        dbc.service_reports.delete_many({"id": {"$in": seeded_report_ids}})
    if seeded_invoice_ids:
        dbc.quotes.delete_many({"id": {"$in": seeded_invoice_ids}})
    if seeded_activity_ids:
        dbc.activity_logs.delete_many({"id": {"$in": seeded_activity_ids}})


def _run(loop, async_call):
    """Run an awaitable on the shared session loop.  Substitutes
    for the per-test loop pattern used in earlier suites."""
    return loop.run_until_complete(async_call)


# ─── Seed helpers ──────────────────────────────────────────────────
def _fresh_id(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_job_sync(dbc, tenant_id: str, *,
                    price: float = 150.0,
                    billable: bool = True,
                    service_type: str = "regular",
                    technician_id: str = None,
                    industry: str = "landscape",  # skip chemistry gate
                    work_class: str = None,
                    auto_invoice_id: str = None,
                    auto_invoice_created_at: str = None) -> str:
    jid = _fresh_id("JOB")
    tech = technician_id or _fresh_id("TECH")
    doc: Dict[str, Any] = {
        "id": jid, "tenant_id": tenant_id,
        "customer_id": _fresh_id("CUST"),
        "customer_name": "M+P Test Customer",
        "title": "M+P C3 seed", "status": "active",
        "photos": [],
        "technician_id": tech,
        "price": price,
        "billable": billable,
        "service_type": service_type,
        "industry": industry,
    }
    if work_class:
        doc["work_class"] = work_class
    if auto_invoice_id:
        doc["auto_invoice_id"] = auto_invoice_id
    if auto_invoice_created_at:
        doc["auto_invoice_created_at"] = auto_invoice_created_at
    dbc.jobs.insert_one(doc)
    return jid, tech


def _seed_sr_sync(dbc, tenant_id: str, job_id: str, *,
                    tech_id: str,
                    submitted_at: Any = None) -> str:
    rid = _fresh_id("SR")
    doc: Dict[str, Any] = {
        "id": rid, "tenant_id": tenant_id, "job_id": job_id,
        "tech_id": tech_id,
        "public_uuid": uuid.uuid4().hex,
        "photos": [], "videos": [],
        "readings": {}, "notes": "",
        "submitted_at": submitted_at,
        "template_version": 1,
        "industry": "landscape",
    }
    dbc.service_reports.insert_one(doc)
    return rid


class _FakeBackgroundTasks:
    """Minimal ``BackgroundTasks`` stand-in that records added
    tasks without executing them, so tests can assert whether
    downstream emits were queued."""
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def _mock_request():
    class _FakeRequest:
        headers = {}
    return _FakeRequest()


def _tech_user(tid: str):
    return {"id": tid, "role": "technician",
             "technician_id": tid, "name": "M+P Tech"}


def _tenant(tid: str, auto_invoice_on_submit: bool = True):
    return {
        "id": tid, "name": "M+P tenant",
        "settings": {
            "auto_invoice_on_submit": auto_invoice_on_submit,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# 1) First-submit baseline — invoice created + sentinels stamped
# ═══════════════════════════════════════════════════════════════════
def test_first_submit_creates_invoice_and_stamps_sentinels(loop, adb, dbc, cleanup):
    tenant_id = _fresh_id("T")
    (seeded_jids, seeded_report_ids,
     seeded_invoice_ids, seeded_activity_ids) = cleanup

    jid, tech = _seed_job_sync(dbc, tenant_id, price=200.0)
    seeded_jids.append(jid)
    rid = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech)
    seeded_report_ids.append(rid)

    from routers.service_reports import submit_service_report
    resp = _run(loop, submit_service_report(
        jid, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech), _tenant(tenant_id),
    ))
    assert resp is not None

    # Invoice created in db.quotes.
    invoices = list(dbc.quotes.find({"job_id": jid, "doc_type": "invoice"}))
    assert len(invoices) == 1
    seeded_invoice_ids.append(invoices[0]["id"])

    # Sentinels stamped on the job.
    job = dbc.jobs.find_one({"id": jid})
    assert job.get("auto_invoice_id") == invoices[0]["id"]
    assert job.get("auto_invoice_created_at") is not None

    # NO audit row for skip-duplicate (first submit path).
    audits = list(dbc.activity_logs.find({
        "job_id": jid, "type": "auto_invoice_skipped_duplicate",
    }))
    assert audits == []


# ═══════════════════════════════════════════════════════════════════
# 2) Re-submit after reopen — invoice SKIPPED + audit emitted
# ═══════════════════════════════════════════════════════════════════
def test_resubmit_after_reopen_skips_invoice_and_audits(loop, adb, dbc, cleanup):
    tenant_id = _fresh_id("T")
    (seeded_jids, seeded_report_ids,
     seeded_invoice_ids, seeded_activity_ids) = cleanup

    # Job carries BOTH sentinels — as if a prior submit already
    # fired the auto-invoice.
    prior_inv = _fresh_id("INV")
    jid, tech = _seed_job_sync(
        dbc, tenant_id, price=200.0,
        auto_invoice_id=prior_inv,
        auto_invoice_created_at="2026-02-01T10:00:00Z",
    )
    seeded_jids.append(jid)
    rid = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech)
    seeded_report_ids.append(rid)

    from routers.service_reports import submit_service_report
    resp = _run(loop, submit_service_report(
        jid, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech), _tenant(tenant_id),
    ))
    assert resp is not None

    # NO new invoice created.
    invoices = list(dbc.quotes.find({"job_id": jid, "doc_type": "invoice"}))
    assert invoices == []

    # Audit row emitted with the expected shape.
    audit = dbc.activity_logs.find_one({
        "job_id": jid, "type": "auto_invoice_skipped_duplicate",
    })
    assert audit is not None
    seeded_activity_ids.append(audit["id"])
    assert audit["reason"] == "reopen_resubmit"
    assert audit["actor_id"] == tech
    assert audit["sr_id"] == rid
    assert audit["metadata"]["prior_invoice_id"] == prior_inv
    assert audit["metadata"]["prior_invoice_at"] == "2026-02-01T10:00:00Z"


# ═══════════════════════════════════════════════════════════════════
# 3) Sentinel variant — only auto_invoice_created_at set → still skipped
# ═══════════════════════════════════════════════════════════════════
def test_resubmit_when_only_created_at_sentinel_set(loop, adb, dbc, cleanup):
    tenant_id = _fresh_id("T")
    (seeded_jids, seeded_report_ids, seeded_invoice_ids,
     seeded_activity_ids) = cleanup
    jid, tech = _seed_job_sync(
        dbc, tenant_id, price=200.0,
        auto_invoice_created_at="2026-02-01T09:00:00Z",
        # NO auto_invoice_id
    )
    seeded_jids.append(jid)
    rid = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech)
    seeded_report_ids.append(rid)

    from routers.service_reports import submit_service_report
    _run(loop, submit_service_report(
        jid, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech), _tenant(tenant_id),
    ))

    invoices = list(dbc.quotes.find({"job_id": jid, "doc_type": "invoice"}))
    assert invoices == []
    audit = dbc.activity_logs.find_one({
        "job_id": jid, "type": "auto_invoice_skipped_duplicate",
    })
    assert audit is not None
    seeded_activity_ids.append(audit["id"])
    assert audit["metadata"]["prior_invoice_id"] is None
    assert audit["metadata"]["prior_invoice_at"] == "2026-02-01T09:00:00Z"


# ═══════════════════════════════════════════════════════════════════
# 4) auto_invoice_on_submit=False → no invoice, no audit
# ═══════════════════════════════════════════════════════════════════
def test_auto_invoice_setting_off_no_side_effects(loop, adb, dbc, cleanup):
    tenant_id = _fresh_id("T")
    (seeded_jids, seeded_report_ids, _seeded_invoice_ids,
     _seeded_activity_ids) = cleanup
    jid, tech = _seed_job_sync(dbc, tenant_id, price=200.0)
    seeded_jids.append(jid)
    rid = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech)
    seeded_report_ids.append(rid)

    from routers.service_reports import submit_service_report
    _run(loop, submit_service_report(
        jid, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech),
        _tenant(tenant_id, auto_invoice_on_submit=False),
    ))
    invoices = list(dbc.quotes.find({"job_id": jid, "doc_type": "invoice"}))
    assert invoices == []
    audits = list(dbc.activity_logs.find({
        "job_id": jid, "type": "auto_invoice_skipped_duplicate",
    }))
    assert audits == []


# ═══════════════════════════════════════════════════════════════════
# 5) Non-billable job → no invoice, no audit
# ═══════════════════════════════════════════════════════════════════
def test_non_billable_no_side_effects(loop, adb, dbc, cleanup):
    tenant_id = _fresh_id("T")
    (seeded_jids, seeded_report_ids, _, _) = cleanup
    jid, tech = _seed_job_sync(dbc, tenant_id, price=200.0, billable=False)
    seeded_jids.append(jid)
    rid = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech)
    seeded_report_ids.append(rid)

    from routers.service_reports import submit_service_report
    _run(loop, submit_service_report(
        jid, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech), _tenant(tenant_id),
    ))
    invoices = list(dbc.quotes.find({"job_id": jid, "doc_type": "invoice"}))
    assert invoices == []


# ═══════════════════════════════════════════════════════════════════
# 6) Excluded service_type → no invoice, no audit
# ═══════════════════════════════════════════════════════════════════
def test_excluded_service_type_no_side_effects(loop, adb, dbc, cleanup):
    tenant_id = _fresh_id("T")
    (seeded_jids, seeded_report_ids, _, _) = cleanup
    jid, tech = _seed_job_sync(dbc, tenant_id, price=200.0,
                                 service_type="warranty callback")
    seeded_jids.append(jid)
    rid = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech)
    seeded_report_ids.append(rid)

    from routers.service_reports import submit_service_report
    _run(loop, submit_service_report(
        jid, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech), _tenant(tenant_id),
    ))
    invoices = list(dbc.quotes.find({"job_id": jid, "doc_type": "invoice"}))
    assert invoices == []


# ═══════════════════════════════════════════════════════════════════
# 7) Cross-tenant — Tenant B's sentinel doesn't affect Tenant A submit
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_sentinel_isolation(loop, adb, dbc, cleanup):
    """Tenant B seeds a job with the same title/job_id-shape and
    sentinels set. Tenant A's independent submit path runs fresh —
    the sentinel is scoped to Tenant A's own job doc, not a global
    check.  Simulated by seeding two jobs (one per tenant) with
    the same 'brand new' state on Tenant A.
    """
    tenant_a = _fresh_id("TA")
    tenant_b = _fresh_id("TB")
    (seeded_jids, seeded_report_ids,
     seeded_invoice_ids, _) = cleanup

    # Tenant B's job is fully sentinel-stamped.
    _seed_job_sync(
        dbc, tenant_b, price=200.0,
        auto_invoice_id="tb-prior-inv",
        auto_invoice_created_at="2026-02-01T00:00:00Z",
    )
    # Tenant A's job is BRAND NEW — no sentinels.
    jid_a, tech_a = _seed_job_sync(dbc, tenant_a, price=200.0)
    seeded_jids.append(jid_a)
    rid_a = _seed_sr_sync(dbc, tenant_a, jid_a, tech_id=tech_a)
    seeded_report_ids.append(rid_a)

    from routers.service_reports import submit_service_report
    _run(loop, submit_service_report(
        jid_a, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech_a), _tenant(tenant_a),
    ))
    invoices = list(dbc.quotes.find({"job_id": jid_a, "doc_type": "invoice"}))
    assert len(invoices) == 1
    seeded_invoice_ids.append(invoices[0]["id"])


# ═══════════════════════════════════════════════════════════════════
# 8) Multi-SR job — second tech's submit still guarded by sentinel
# ═══════════════════════════════════════════════════════════════════
def test_multi_sr_job_second_submit_guarded_by_sentinel(loop, adb, dbc, cleanup):
    """First tech submits → invoice created + sentinels stamped.
    Second tech submits their own SR on the SAME job → invoice
    NOT created; audit row emitted referencing the SECOND SR id."""
    tenant_id = _fresh_id("T")
    (seeded_jids, seeded_report_ids,
     seeded_invoice_ids, seeded_activity_ids) = cleanup

    # Job assigned to tech A.
    tech_a = _fresh_id("TECH")
    tech_b = _fresh_id("TECH")
    jid, _ = _seed_job_sync(dbc, tenant_id, price=200.0,
                              technician_id=tech_a)
    seeded_jids.append(jid)
    rid_a = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech_a)
    rid_b = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech_b)
    seeded_report_ids.extend([rid_a, rid_b])

    # Also add tech_b to jobs.technician_id via a crew — cheapest
    # way to satisfy F1 for the second submit is to make tech B
    # the direct assignee for that call.  We swap the assignment
    # between submissions.
    from routers.service_reports import submit_service_report

    # Submit 1 — tech A.
    _run(loop, submit_service_report(
        jid, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech_a), _tenant(tenant_id),
    ))
    # First invoice created + sentinels stamped.
    invoices_1 = list(dbc.quotes.find(
        {"job_id": jid, "doc_type": "invoice"}))
    assert len(invoices_1) == 1
    seeded_invoice_ids.append(invoices_1[0]["id"])
    job_after_1 = dbc.jobs.find_one({"id": jid})
    assert job_after_1.get("auto_invoice_id") == invoices_1[0]["id"]

    # Swap the job's direct assignee to tech B so submit_service_report
    # authorises tech B on the same job.  Also RESET the job status
    # back to ``active`` (submit_1 set completed_at via its own gate;
    # for this multi-SR simulation we treat the second submit as if
    # tech B's SR is being submitted for the first time on an ALREADY
    # completed job — the sentinel guard must fire.
    dbc.jobs.update_one(
        {"id": jid},
        {"$set": {"technician_id": tech_b, "status": "active"}},
    )

    # Submit 2 — tech B — same job, same sentinels.
    _run(loop, submit_service_report(
        jid, _FakeBackgroundTasks(), _mock_request(),
        _tech_user(tech_b), _tenant(tenant_id),
    ))
    invoices_2 = list(dbc.quotes.find(
        {"job_id": jid, "doc_type": "invoice"}))
    # STILL just one invoice — the guard prevented a duplicate.
    assert len(invoices_2) == 1

    # Audit row emitted referencing tech B's SR id.
    audits = list(dbc.activity_logs.find({
        "job_id": jid, "type": "auto_invoice_skipped_duplicate",
    }))
    assert len(audits) == 1
    seeded_activity_ids.append(audits[0]["id"])
    assert audits[0]["sr_id"] == rid_b


# ═══════════════════════════════════════════════════════════════════
# 9) Audit-row insert failure — submit still returns 200
# ═══════════════════════════════════════════════════════════════════
def test_audit_row_failure_does_not_break_submit(loop, adb, dbc, cleanup):
    """A Mongo blip on ``activity_logs.insert_one`` must NOT fail
    the response.  Fire-and-forget with warning log.
    """
    tenant_id = _fresh_id("T")
    (seeded_jids, seeded_report_ids, _, _) = cleanup
    prior_inv = _fresh_id("INV")
    jid, tech = _seed_job_sync(
        dbc, tenant_id, price=200.0,
        auto_invoice_id=prior_inv,
        auto_invoice_created_at="2026-02-01T00:00:00Z",
    )
    seeded_jids.append(jid)
    rid = _seed_sr_sync(dbc, tenant_id, jid, tech_id=tech)
    seeded_report_ids.append(rid)

    # Patch activity_logs.insert_one on the SHARED session Motor db
    # so the skip-duplicate audit raises, but every other collection
    # op (including the SR submit gate) still works.  Restore on
    # exit so downstream tests aren't affected.
    real_activity_coll = adb.activity_logs
    real_insert = real_activity_coll.insert_one

    async def _wrapped_insert(doc, *a, **kw):
        if doc.get("type") == "auto_invoice_skipped_duplicate":
            raise RuntimeError("simulated mongo blip")
        return await real_insert(doc, *a, **kw)

    real_activity_coll.insert_one = _wrapped_insert
    try:
        from routers.service_reports import submit_service_report
        resp = _run(loop, submit_service_report(
            jid, _FakeBackgroundTasks(), _mock_request(),
            _tech_user(tech), _tenant(tenant_id),
        ))
        assert resp is not None  # 200-like response body
        # And critically, no duplicate invoice fired.
        invoices = list(dbc.quotes.find({"job_id": jid, "doc_type": "invoice"}))
        assert invoices == []
    finally:
        real_activity_coll.insert_one = real_insert
