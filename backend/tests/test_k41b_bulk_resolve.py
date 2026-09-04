"""Phase K41b · Feb-2026 — Data-Integrity bulk resolve endpoint tests.

Coverage matrix (K41b brief):
  • Happy path — assign + soft-delete succeed in bulk.
  • Shared bulk_batch_id stamped on every emitted
    ``dashboard_drilldown_edit`` audit event.
  • Auth negatives — non-admin roles → 403.
  • Batch cap — request with > 100 items → 400.
  • Partial failure — mixed valid/invalid rows report per-row status
    with 200 outer response.
  • Idempotency — replay identical response for repeated batch id
    within 60s.
  • Empty items → 400.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]

_CACHE: dict = {}


def _login(email: str, password: str = "password123") -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"login skipped for {email}: {r.status_code}")
    _CACHE[key] = r.json()["access_token"]
    return _CACHE[key]


def _me(token: str) -> dict:
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    return r.json() if r.status_code == 200 else {}


def _super_ctx() -> dict:
    if _CACHE.get("super_ctx"):
        return _CACHE["super_ctx"]
    tok = _login("super@aquaterra.com")
    me = _me(tok)
    _CACHE["super_ctx"] = {"token": tok, "tenant_id": me.get("tenant_id")}
    return _CACHE["super_ctx"]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _seed_orphan_customer_jobs(tenant_id: str, count: int) -> list:
    """Insert `count` jobs referencing a non-existent customer.

    Returns list of seeded job_ids.  Cleanup runs via the fixture
    finaliser so tests never leak.
    """
    dead_cust = f"TEST-K41B-DEAD-{uuid.uuid4().hex[:8]}"
    seeded = []
    now = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        jid = f"TEST-K41B-JOB-{uuid.uuid4().hex[:8]}"
        _db.jobs.insert_one({
            "id": jid,
            "tenant_id": tenant_id,
            "customer_id": dead_cust,
            "customer_name": f"K41b Seed {i}",
            "status": "scheduled",
            "created_at": now,
            "scheduled_date": now,
        })
        seeded.append(jid)
    return seeded


@pytest.fixture
def seeded_jobs():
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    ids = _seed_orphan_customer_jobs(tenant_id, 3)
    yield {"ctx": ctx, "ids": ids, "tenant_id": tenant_id}
    _db.jobs.delete_many({"id": {"$in": ids}})
    _db.audit_events.delete_many({"job_id": {"$in": ids}})


# ═════════════════════════════════════════════════════════════════════
# 1) Happy path — bulk soft-delete resolves every row + shares batch id
# ═════════════════════════════════════════════════════════════════════
def test_k41b_bulk_soft_delete_happy_path_shared_batch_id(seeded_jobs):
    ctx = seeded_jobs["ctx"]
    ids = seeded_jobs["ids"]

    items = [
        {"ref_class": "orphaned_customer_refs",
         "job_id": jid, "action": "delete"}
        for jid in ids
    ]
    batch_id = str(uuid.uuid4())

    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(ctx["token"]),
        json={"items": items, "bulk_batch_id": batch_id},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["succeeded"] == len(ids)
    assert body["failed"] == 0
    assert body["bulk_batch_id"] == batch_id
    assert len(body["results"]) == len(ids)
    for res in body["results"]:
        assert res["ok"] is True
        assert res["action"] == "delete"

    # Every audit event for these rows must carry the SAME bulk_batch_id.
    audits = list(_db.audit_events.find({
        "event_type": "dashboard_drilldown_edit",
        "job_id": {"$in": ids},
    }))
    assert len(audits) == len(ids), (
        f"Expected {len(ids)} per-row audits; found {len(audits)}."
    )
    batch_ids_seen = {a.get("bulk_batch_id") for a in audits}
    assert batch_ids_seen == {batch_id}, (
        f"All audits must share the batch id; got {batch_ids_seen}"
    )

    # Every job is now soft-deleted.
    for jid in ids:
        j = _db.jobs.find_one({"id": jid}, {"status": 1})
        assert j and j["status"] == "deleted"


# ═════════════════════════════════════════════════════════════════════
# 2) Assign happy path — bulk assign to a real customer
# ═════════════════════════════════════════════════════════════════════
def test_k41b_bulk_assign_customer_happy_path(seeded_jobs):
    ctx = seeded_jobs["ctx"]
    ids = seeded_jobs["ids"]
    tenant_id = seeded_jobs["tenant_id"]

    # Insert a real customer as the reassignment target.
    real_cust_id = f"TEST-K41B-CUST-{uuid.uuid4().hex[:8]}"
    _db.customers.insert_one({
        "id": real_cust_id, "tenant_id": tenant_id,
        "name": "K41b Real Customer",
    })
    try:
        items = [
            {"ref_class": "orphaned_customer_refs",
             "job_id": jid, "action": "assign",
             "target_id": real_cust_id}
            for jid in ids
        ]
        r = requests.post(
            f"{API}/dashboard/data-integrity/resolve-bulk",
            headers=_headers(ctx["token"]),
            json={"items": items},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["succeeded"] == len(ids)
        assert body["bulk_batch_id"], "server must mint a batch id"
        # Every job now points at the real customer.
        for jid in ids:
            j = _db.jobs.find_one({"id": jid}, {"customer_id": 1})
            assert j["customer_id"] == real_cust_id
    finally:
        _db.customers.delete_one({"id": real_cust_id})


# ═════════════════════════════════════════════════════════════════════
# 3) Auth negative — non-admin denied
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("email", [
    "manager@aquaterra.com",
    "carlos@aquaterra.com",
    "customer@aquaterra.com",
])
def test_k41b_bulk_denies_non_admin(email):
    tok = _login(email)
    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(tok),
        json={"items": [{"ref_class": "orphaned_customer_refs",
                          "job_id": "TEST-NA", "action": "delete"}]},
        timeout=15,
    )
    assert r.status_code == 403, r.text


def test_k41b_bulk_requires_auth():
    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        json={"items": []},
        timeout=15,
    )
    assert r.status_code in (401, 403), r.text


# ═════════════════════════════════════════════════════════════════════
# 4) Batch cap — > 100 items → 400
# ═════════════════════════════════════════════════════════════════════
def test_k41b_batch_cap_exceeded_400():
    ctx = _super_ctx()
    items = [
        {"ref_class": "orphaned_customer_refs",
         "job_id": f"TEST-CAP-{i}", "action": "delete"}
        for i in range(101)
    ]
    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(ctx["token"]),
        json={"items": items},
        timeout=30,
    )
    assert r.status_code == 400, r.text
    assert "batch_cap" in r.json()["detail"]


def test_k41b_empty_items_400():
    ctx = _super_ctx()
    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(ctx["token"]),
        json={"items": []},
        timeout=15,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "items_required"


# ═════════════════════════════════════════════════════════════════════
# 5) Partial failure — good + bad rows → 200 with per-row status
# ═════════════════════════════════════════════════════════════════════
def test_k41b_partial_failure_reports_per_row_status(seeded_jobs):
    ctx = seeded_jobs["ctx"]
    good_ids = seeded_jobs["ids"][:2]
    bad_id = "TEST-K41B-NOT-EXIST-XXXX"

    items = [
        {"ref_class": "orphaned_customer_refs",
         "job_id": jid, "action": "delete"}
        for jid in good_ids
    ]
    items.append({
        "ref_class": "orphaned_customer_refs",
        "job_id": bad_id, "action": "delete",
    })

    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(ctx["token"]),
        json={"items": items},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False  # at least one row failed
    assert body["succeeded"] == 2
    assert body["failed"] == 1
    by_job = {r["job_id"]: r for r in body["results"]}
    for jid in good_ids:
        assert by_job[jid]["ok"] is True
    assert by_job[bad_id]["ok"] is False
    assert by_job[bad_id]["error"] == "job_not_found"
    assert by_job[bad_id]["status_code"] == 404


def test_k41b_invalid_target_id_reported_as_row_failure(seeded_jobs):
    """Missing customer target for an assign should NOT roll back the
    other rows in the batch."""
    ctx = seeded_jobs["ctx"]
    tenant_id = seeded_jobs["tenant_id"]
    ids = seeded_jobs["ids"]

    real_cust_id = f"TEST-K41B-CUST-{uuid.uuid4().hex[:8]}"
    _db.customers.insert_one({
        "id": real_cust_id, "tenant_id": tenant_id,
        "name": "K41b Partial Target",
    })
    try:
        items = [
            # 1 good assign
            {"ref_class": "orphaned_customer_refs",
             "job_id": ids[0], "action": "assign",
             "target_id": real_cust_id},
            # 1 bad target -> should fail per-row
            {"ref_class": "orphaned_customer_refs",
             "job_id": ids[1], "action": "assign",
             "target_id": "TEST-K41B-BOGUS"},
        ]
        r = requests.post(
            f"{API}/dashboard/data-integrity/resolve-bulk",
            headers=_headers(ctx["token"]),
            json={"items": items},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["succeeded"] == 1
        assert body["failed"] == 1
        # The good row survived; the bad row error surfaced.
        assert _db.jobs.find_one({"id": ids[0]})["customer_id"] == real_cust_id
    finally:
        _db.customers.delete_one({"id": real_cust_id})


# ═════════════════════════════════════════════════════════════════════
# 6) Idempotency — same bulk_batch_id replayed within TTL returns the
# same result and does NOT re-apply the mutation
# ═════════════════════════════════════════════════════════════════════
def test_k41b_idempotency_replays_within_ttl(seeded_jobs):
    ctx = seeded_jobs["ctx"]
    ids = seeded_jobs["ids"]

    items = [
        {"ref_class": "orphaned_customer_refs",
         "job_id": jid, "action": "delete"}
        for jid in ids
    ]
    batch_id = str(uuid.uuid4())

    r1 = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(ctx["token"]),
        json={"items": items, "bulk_batch_id": batch_id},
        timeout=30,
    )
    assert r1.status_code == 200
    b1 = r1.json()
    audits_first = _db.audit_events.count_documents({
        "event_type": "dashboard_drilldown_edit",
        "bulk_batch_id": batch_id,
    })
    assert audits_first == len(ids)

    # Replay — same batch id.
    r2 = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(ctx["token"]),
        json={"items": items, "bulk_batch_id": batch_id},
        timeout=30,
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2.get("replayed") is True
    assert b2["bulk_batch_id"] == b1["bulk_batch_id"]
    assert b2["succeeded"] == b1["succeeded"]

    # And NO extra audits landed.
    audits_second = _db.audit_events.count_documents({
        "event_type": "dashboard_drilldown_edit",
        "bulk_batch_id": batch_id,
    })
    assert audits_second == audits_first, (
        "Replay must not emit a second wave of audit events."
    )
