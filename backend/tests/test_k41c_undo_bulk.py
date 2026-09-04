"""Phase K41c · Feb-2026 — Undo Last Bulk (Data-Integrity) tests.

Coverage matrix (K41c brief):
  • Happy — bulk soft-delete + undo within 10 min restores every row
    and stamps a companion ``dashboard_drilldown_bulk_undone`` event
    per row with ``undone_from_batch_id`` linking back to the source.
  • Happy — bulk assign customer + undo reverts ``customer_id`` to
    the ``before`` value captured in the source audit rows.
  • Window expired — a 10-minute+ old batch returns 410 ``window_expired``.
  • Already undone — second undo on the same batch returns 409
    ``already_undone`` (no re-mutation).
  • Partial failure — a job hard-deleted between soft-delete and undo
    is surfaced in the ``failed`` array, others in ``restored``.
  • 403 for non-admin.
  • Idempotency — replayed request within 60s returns the same
    response with ``replayed: true`` and NO extra mutations.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone, timedelta
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
    dead_cust = f"TEST-K41C-DEAD-{uuid.uuid4().hex[:8]}"
    seeded = []
    now = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        jid = f"TEST-K41C-JOB-{uuid.uuid4().hex[:8]}"
        _db.jobs.insert_one({
            "id": jid,
            "tenant_id": tenant_id,
            "customer_id": dead_cust,
            "customer_name": f"K41c Seed {i}",
            "status": "scheduled",
            "created_at": now,
            "scheduled_date": now,
        })
        seeded.append(jid)
    return seeded


@pytest.fixture
def seeded_orphans():
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    ids = _seed_orphan_customer_jobs(tenant_id, 3)
    yield {"ctx": ctx, "ids": ids, "tenant_id": tenant_id}
    _db.jobs.delete_many({"id": {"$in": ids}})
    _db.audit_events.delete_many({"job_id": {"$in": ids}})


def _run_bulk(ctx, items, batch_id=None):
    body = {"items": items}
    if batch_id:
        body["bulk_batch_id"] = batch_id
    r = requests.post(
        f"{API}/dashboard/data-integrity/resolve-bulk",
        headers=_headers(ctx["token"]),
        json=body, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ═════════════════════════════════════════════════════════════════════
# 1) Happy — bulk soft-delete + undo restores every row + audit chain
# ═════════════════════════════════════════════════════════════════════
def test_k41c_undo_bulk_soft_delete_happy_path(seeded_orphans):
    ctx = seeded_orphans["ctx"]
    ids = seeded_orphans["ids"]

    batch_id = str(uuid.uuid4())
    items = [
        {"ref_class": "orphaned_customer_refs",
         "job_id": jid, "action": "delete"}
        for jid in ids
    ]
    b = _run_bulk(ctx, items, batch_id=batch_id)
    assert b["succeeded"] == len(ids)

    # Every seeded job is soft-deleted.
    for jid in ids:
        j = _db.jobs.find_one({"id": jid}, {"status": 1, "deleted_at": 1})
        assert j["status"] == "deleted"
        assert j.get("deleted_at")

    # Undo.
    r = requests.post(
        f"{API}/dashboard/data-integrity/undo-bulk",
        headers=_headers(ctx["token"]),
        json={"bulk_batch_id": batch_id}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["bulk_batch_id"] == batch_id
    assert len(body["restored"]) == len(ids)
    assert body["failed"] == []
    assert body["undo_batch_id"], "server must mint an undo batch id"

    # Jobs restored — status back to original, deleted markers cleared.
    for jid in ids:
        j = _db.jobs.find_one({"id": jid}, {"status": 1, "deleted_at": 1})
        assert j["status"] == "scheduled"
        assert j.get("deleted_at") is None

    # Audit chain — every companion event points back to the source
    # batch via ``undone_from_batch_id``.
    companion_rows = list(_db.audit_events.find({
        "event_type": "dashboard_drilldown_bulk_undone",
        "undone_from_batch_id": batch_id,
    }))
    assert len(companion_rows) == len(ids)
    for c in companion_rows:
        assert c["job_id"] in ids
        assert c["undone_from_batch_id"] == batch_id
        assert c["source"] == "dashboard_drilldown_undo"


# ═════════════════════════════════════════════════════════════════════
# 2) Happy — bulk assign customer + undo reverts customer_id
# ═════════════════════════════════════════════════════════════════════
def test_k41c_undo_bulk_assign_customer_reverts_before_value(seeded_orphans):
    ctx = seeded_orphans["ctx"]
    tenant_id = seeded_orphans["tenant_id"]
    ids = seeded_orphans["ids"]

    real_cust_id = f"TEST-K41C-CUST-{uuid.uuid4().hex[:8]}"
    _db.customers.insert_one({
        "id": real_cust_id, "tenant_id": tenant_id, "name": "K41c Target",
    })

    # Capture the original customer_id for each job (all point at the
    # same dead ref).
    originals = {
        j["id"]: j.get("customer_id")
        for j in _db.jobs.find({"id": {"$in": ids}},
                                {"id": 1, "customer_id": 1})
    }

    batch_id = str(uuid.uuid4())
    items = [
        {"ref_class": "orphaned_customer_refs",
         "job_id": jid, "action": "assign",
         "target_id": real_cust_id}
        for jid in ids
    ]
    try:
        _run_bulk(ctx, items, batch_id=batch_id)

        # Every seeded job now points at the real customer.
        for jid in ids:
            j = _db.jobs.find_one({"id": jid}, {"customer_id": 1})
            assert j["customer_id"] == real_cust_id

        # Undo.
        r = requests.post(
            f"{API}/dashboard/data-integrity/undo-bulk",
            headers=_headers(ctx["token"]),
            json={"bulk_batch_id": batch_id}, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # Every job restored to its original (dead) customer_id.
        for jid in ids:
            j = _db.jobs.find_one({"id": jid}, {"customer_id": 1})
            assert j["customer_id"] == originals[jid]
    finally:
        _db.customers.delete_one({"id": real_cust_id})


# ═════════════════════════════════════════════════════════════════════
# 3) Window expired — an 11-minute-old batch returns 410
# ═════════════════════════════════════════════════════════════════════
def test_k41c_window_expired_returns_410():
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    # Seed a fake audit row that is 11 minutes old.  We bypass the
    # bulk endpoint so the window can be forced.
    fake_batch = f"TEST-K41C-EXPIRED-{uuid.uuid4().hex[:8]}"
    old_ts = (datetime.now(timezone.utc)
              - timedelta(minutes=11)).isoformat()
    job_id = f"TEST-K41C-JOB-{uuid.uuid4().hex[:8]}"
    _db.jobs.insert_one({
        "id": job_id, "tenant_id": tenant_id,
        "status": "deleted", "deleted_at": old_ts,
    })
    _db.audit_events.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "dashboard_drilldown_edit",
        "tile": "data-integrity", "field": "status",
        "before": "scheduled", "after": "deleted",
        "actor_id": "x", "tenant_id": tenant_id,
        "timestamp": old_ts,
        "job_id": job_id, "action": "delete",
        "bulk_batch_id": fake_batch,
    })
    try:
        r = requests.post(
            f"{API}/dashboard/data-integrity/undo-bulk",
            headers=_headers(ctx["token"]),
            json={"bulk_batch_id": fake_batch}, timeout=30,
        )
        assert r.status_code == 410, r.text
        assert r.json()["detail"] == "window_expired"
    finally:
        _db.jobs.delete_one({"id": job_id})
        _db.audit_events.delete_many({"bulk_batch_id": fake_batch})


# ═════════════════════════════════════════════════════════════════════
# 4) Already-undone — the "already undone" branch returns 409
#
# NOTE: The 60s in-memory idempotency cache lives in the server
# process, so we cannot flush it from the pytest side.  Instead we
# construct the "already undone" state directly by seeding both the
# source audit rows AND a companion ``dashboard_drilldown_bulk_undone``
# row with a synthetic ``bulk_batch_id`` that was NEVER submitted via
# the API — so the server-side cache misses and the endpoint reaches
# the actual already-undone check.
# ═════════════════════════════════════════════════════════════════════
def test_k41c_already_undone_returns_409():
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    fake_batch = f"TEST-K41C-DBLUNDO-{uuid.uuid4().hex[:8]}"
    fresh_ts = datetime.now(timezone.utc).isoformat()
    job_id = f"TEST-K41C-JOB-{uuid.uuid4().hex[:8]}"

    _db.jobs.insert_one({
        "id": job_id, "tenant_id": tenant_id,
        "status": "deleted", "deleted_at": fresh_ts,
    })
    _db.audit_events.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "dashboard_drilldown_edit",
        "tile": "data-integrity", "field": "status",
        "before": "scheduled", "after": "deleted",
        "actor_id": "seed", "tenant_id": tenant_id,
        "timestamp": fresh_ts,
        "job_id": job_id, "action": "delete",
        "bulk_batch_id": fake_batch,
    })
    # Pre-seed a companion "already undone" row to force the 409 path.
    _db.audit_events.insert_one({
        "id": str(uuid.uuid4()),
        "event_type": "dashboard_drilldown_bulk_undone",
        "tile": "data-integrity", "job_id": job_id,
        "actor_id": "seed", "tenant_id": tenant_id,
        "timestamp": fresh_ts,
        "undone_from_batch_id": fake_batch,
        "undo_batch_id": str(uuid.uuid4()),
        "source": "dashboard_drilldown_undo",
    })
    try:
        r = requests.post(
            f"{API}/dashboard/data-integrity/undo-bulk",
            headers=_headers(ctx["token"]),
            json={"bulk_batch_id": fake_batch}, timeout=30,
        )
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == "already_undone"
    finally:
        _db.jobs.delete_one({"id": job_id})
        _db.audit_events.delete_many({"bulk_batch_id": fake_batch})
        _db.audit_events.delete_many({"undone_from_batch_id": fake_batch})


# ═════════════════════════════════════════════════════════════════════
# 5) Partial failure — one job hard-deleted between soft-delete + undo
# ═════════════════════════════════════════════════════════════════════
def test_k41c_partial_failure_when_job_hard_deleted(seeded_orphans):
    ctx = seeded_orphans["ctx"]
    ids = seeded_orphans["ids"]

    batch_id = str(uuid.uuid4())
    items = [
        {"ref_class": "orphaned_customer_refs",
         "job_id": jid, "action": "delete"}
        for jid in ids
    ]
    _run_bulk(ctx, items, batch_id=batch_id)

    # Hard-delete the first job to simulate the edge case.
    hard_gone = ids[0]
    _db.jobs.delete_one({"id": hard_gone})

    r = requests.post(
        f"{API}/dashboard/data-integrity/undo-bulk",
        headers=_headers(ctx["token"]),
        json={"bulk_batch_id": batch_id}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    restored_ids = {r["job_id"] for r in body["restored"]}
    failed_ids = {f["job_id"] for f in body["failed"]}
    assert hard_gone in failed_ids
    for f in body["failed"]:
        if f["job_id"] == hard_gone:
            assert f["error"] == "job_not_found"
    # The other two restored.
    for jid in ids[1:]:
        assert jid in restored_ids
        j = _db.jobs.find_one({"id": jid}, {"status": 1})
        assert j["status"] == "scheduled"


# ═════════════════════════════════════════════════════════════════════
# 6) Auth negative
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("email", [
    "manager@aquaterra.com",
    "carlos@aquaterra.com",
    "customer@aquaterra.com",
])
def test_k41c_undo_denies_non_admin(email):
    tok = _login(email)
    r = requests.post(
        f"{API}/dashboard/data-integrity/undo-bulk",
        headers=_headers(tok),
        json={"bulk_batch_id": "TEST-NA"}, timeout=15,
    )
    assert r.status_code == 403, r.text


def test_k41c_undo_batch_not_found_returns_404():
    ctx = _super_ctx()
    r = requests.post(
        f"{API}/dashboard/data-integrity/undo-bulk",
        headers=_headers(ctx["token"]),
        json={"bulk_batch_id": f"TEST-K41C-MISSING-{uuid.uuid4().hex[:8]}"},
        timeout=15,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "batch_not_found"


# ═════════════════════════════════════════════════════════════════════
# 7) Idempotent replay within TTL
# ═════════════════════════════════════════════════════════════════════
def test_k41c_undo_replay_returns_replayed_flag(seeded_orphans):
    ctx = seeded_orphans["ctx"]
    ids = seeded_orphans["ids"]

    batch_id = str(uuid.uuid4())
    items = [
        {"ref_class": "orphaned_customer_refs",
         "job_id": jid, "action": "delete"}
        for jid in ids
    ]
    _run_bulk(ctx, items, batch_id=batch_id)

    r1 = requests.post(
        f"{API}/dashboard/data-integrity/undo-bulk",
        headers=_headers(ctx["token"]),
        json={"bulk_batch_id": batch_id}, timeout=30,
    )
    assert r1.status_code == 200
    audits_first = _db.audit_events.count_documents({
        "event_type": "dashboard_drilldown_bulk_undone",
        "undone_from_batch_id": batch_id,
    })
    assert audits_first == len(ids)

    r2 = requests.post(
        f"{API}/dashboard/data-integrity/undo-bulk",
        headers=_headers(ctx["token"]),
        json={"bulk_batch_id": batch_id}, timeout=30,
    )
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2.get("replayed") is True

    audits_second = _db.audit_events.count_documents({
        "event_type": "dashboard_drilldown_bulk_undone",
        "undone_from_batch_id": batch_id,
    })
    assert audits_second == audits_first, (
        "Replay must not emit a second wave of companion audits."
    )
