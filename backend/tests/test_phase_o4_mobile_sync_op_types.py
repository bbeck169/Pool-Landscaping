"""Phase O4 · Feb-2026 — POST /mobile/sync new op_types (G3).

The audit greenlights 4 new op_types:

    * ``job.arrive``        — offline replay of a GPS arrival ping.
    * ``invoice.create``    — on-site invoice created offline.
    * ``quote.create``      — on-site quote created offline.
    * ``customer.upsert``   — offline lead capture.

Every op_type MUST satisfy the sync contract:

    1. Fresh op → 200 + accepted[] entry with the server ids.
    2. Same ``client_op_id`` replayed → ``idempotent_replay: True``
       + no double write.
    3. ``customer.upsert`` echoes ``mobile_wins`` in the ``conflicts``
       array on the first successful call (audit invariant).
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os as _os_local
_ENV_BASE = _os_local.environ.get("PHASE_O4_TEST_BASE")
BASE = (_ENV_BASE or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db  # noqa: E402
from utils import new_id, now_iso  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def admin_ctx() -> dict:
    async def _find():
        u = await db.users.find_one(
            {"email": "admin@aquaterra.com"}, {"_id": 0})
        return u["tenant_id"]
    tid = _run(_find())
    return {"tenant_id": tid}


def _sync(admin_h, *ops):
    body = {"device_id": f"phase-o4-{uuid.uuid4().hex[:6]}",
             "operations": list(ops)}
    return requests.post(f"{API}/mobile/sync", headers=admin_h,
                          json=body, timeout=15).json()


# ═══════════ customer.upsert ═══════════════════════════════════════════
def test_sync_customer_upsert_inserts_new_row(admin_h, admin_ctx):
    op_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    op = {"client_op_id": op_id, "op_type": "customer.upsert",
           "entity_id": cid,
           "payload": {"name": "PhaseO4 Lead",
                        "phone": "+15555550101"}}
    try:
        r = _sync(admin_h, op)
        assert r["accepted"][0]["upserted"] == "inserted"
        # Mobile-wins conflict echoed.
        assert any(c["client_op_id"] == op_id
                    and c["resolution"] == "mobile_wins"
                    for c in r["conflicts"])
        # Row persisted on the customers collection.
        async def _cnt():
            return await db.customers.count_documents(
                {"id": cid, "tenant_id": admin_ctx["tenant_id"]})
        assert _run(_cnt()) == 1
    finally:
        async def _c():
            await db.customers.delete_one({"id": cid})
            await db.pending_sync_receipts.delete_many(
                {"client_op_id": op_id})
        _run(_c())


def test_sync_customer_upsert_replay_is_idempotent(admin_h, admin_ctx):
    op_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    op = {"client_op_id": op_id, "op_type": "customer.upsert",
           "entity_id": cid,
           "payload": {"name": "PhaseO4 Replay",
                        "phone": "+15555550102"}}
    try:
        r1 = _sync(admin_h, op)
        r2 = _sync(admin_h, op)
        assert r1["accepted"][0].get("idempotent_replay") is not True
        assert r2["accepted"][0].get("idempotent_replay") is True
        # Only ONE customer row.
        async def _cnt():
            return await db.customers.count_documents(
                {"id": cid, "tenant_id": admin_ctx["tenant_id"]})
        assert _run(_cnt()) == 1
    finally:
        async def _c():
            await db.customers.delete_one({"id": cid})
            await db.pending_sync_receipts.delete_many(
                {"client_op_id": op_id})
        _run(_c())


# ═══════════ invoice.create ════════════════════════════════════════════
def test_sync_invoice_create_persists_and_replays(admin_h, admin_ctx):
    op_id = str(uuid.uuid4())
    iid = str(uuid.uuid4())
    op = {"client_op_id": op_id, "op_type": "invoice.create",
           "entity_id": iid,
           "payload": {"title": "phase-o4-invoice",
                        "customer_name": "Test Cust",
                        "line_items": [{"description": "svc",
                                         "quantity": 1,
                                         "unit_price": 100.0}],
                        "subtotal": 100.0, "tax": 0.0, "total": 100.0,
                        "status": "draft",
                        "doc_type": "invoice"}}
    try:
        r1 = _sync(admin_h, op)
        r2 = _sync(admin_h, op)
        assert r1["accepted"][0]["server_id"] == iid
        assert r2["accepted"][0].get("idempotent_replay") is True
        # CRM quirk: invoices live in db.quotes with doc_type filter.
        async def _cnt():
            return await db.quotes.count_documents(
                {"id": iid, "tenant_id": admin_ctx["tenant_id"],
                  "doc_type": "invoice"})
        assert _run(_cnt()) == 1
        # And the numbering helper stamped an invoice_number on it.
        assert r1["accepted"][0].get("invoice_number")
    finally:
        async def _c():
            await db.quotes.delete_one({"id": iid})
            await db.pending_sync_receipts.delete_many(
                {"client_op_id": op_id})
        _run(_c())


# ═══════════ quote.create ══════════════════════════════════════════════
def test_sync_quote_create_persists_and_replays(admin_h, admin_ctx):
    op_id = str(uuid.uuid4())
    qid = str(uuid.uuid4())
    op = {"client_op_id": op_id, "op_type": "quote.create",
           "entity_id": qid,
           "payload": {"title": "phase-o4-quote",
                        "customer_name": "Test Cust",
                        "line_items": [{"description": "svc",
                                         "quantity": 1,
                                         "unit_price": 50.0}],
                        "subtotal": 50.0, "total": 50.0,
                        "status": "draft",
                        "doc_type": "quote"}}
    try:
        r1 = _sync(admin_h, op)
        r2 = _sync(admin_h, op)
        assert r1["accepted"][0]["server_id"] == qid
        assert r2["accepted"][0].get("idempotent_replay") is True
        async def _cnt():
            return await db.quotes.count_documents(
                {"id": qid, "tenant_id": admin_ctx["tenant_id"]})
        assert _run(_cnt()) == 1
    finally:
        async def _c():
            await db.quotes.delete_one({"id": qid})
            await db.pending_sync_receipts.delete_many(
                {"client_op_id": op_id})
        _run(_c())


# ═══════════ job.arrive ════════════════════════════════════════════════
def test_sync_job_arrive_starts_timer_and_replay_is_noop(admin_h, admin_ctx):
    tid = admin_ctx["tenant_id"]
    jid = new_id()
    async def _seed():
        await db.jobs.insert_one({
            "id": jid, "tenant_id": tid, "title": "phase-o4-arrive-sync",
            "status": "scheduled",
            "created_at": now_iso(), "updated_at": now_iso(),
        })
    _run(_seed())
    op_id = str(uuid.uuid4())
    op = {"client_op_id": op_id, "op_type": "job.arrive",
           "entity_id": jid,
           "payload": {"lat": 33.7, "lng": -112.1,
                        "arrived_at": now_iso()}}
    try:
        r1 = _sync(admin_h, op)
        r2 = _sync(admin_h, op)
        assert r1["accepted"][0]["server_id"] == jid
        assert r1["accepted"][0].get("timer_started_at")
        assert r2["accepted"][0].get("idempotent_replay") is True
        async def _j():
            return await db.jobs.find_one({"id": jid}, {"_id": 0})
        j = _run(_j())
        assert j["status"] == "in_progress"
        assert j.get("timer_start_method") == "mobile_offline_arrival"
    finally:
        async def _c():
            await db.jobs.delete_one({"id": jid})
            await db.pending_sync_receipts.delete_many(
                {"client_op_id": op_id})
        _run(_c())


def test_sync_unsupported_op_type_is_rejected(admin_h):
    op_id = str(uuid.uuid4())
    op = {"client_op_id": op_id, "op_type": "bogus.op",
           "entity_id": new_id(), "payload": {}}
    try:
        r = _sync(admin_h, op)
        assert not r["accepted"]
        assert r["failed"][0]["client_op_id"] == op_id
        assert "unsupported" in r["failed"][0]["reason"].lower()
    finally:
        async def _c():
            await db.pending_sync_receipts.delete_many(
                {"client_op_id": op_id})
        _run(_c())
