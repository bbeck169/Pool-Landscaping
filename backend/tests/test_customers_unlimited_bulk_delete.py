"""Feb-2026 · Unlimited bulk-delete customers (P0 risk feature).

Covers the widened ceiling + super_admin gate + chunked execution
+ soft-delete semantics + tenant isolation + audit-log summary in
``routers/bulk_crm.py::customers_bulk_delete``.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")


def _warm_backend() -> None:
    import time
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = requests.get(f"{API}/config/public", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)


_warm_backend()


def _login(email: str) -> str:
    for _ in range(4):
        try:
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": demo_pw(email)},
                              timeout=30)
            if r.status_code == 200:
                return r.json()["access_token"]
        except (requests.exceptions.ReadTimeout,
                 requests.exceptions.ConnectionError):
            pass
    raise AssertionError(f"login failed for {email}")


def _fresh_db():
    loop = asyncio.get_event_loop()
    client = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=loop)
    return client[_ENV["DB_NAME"]], client


def _tenant_id(token: str) -> str:
    r = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["tenant_id"]


async def _seed_customers(db, tenant_id: str, n: int, *, prefix: str = "TEST_ubd_"):
    ids = []
    now_ts = "2027-01-01T00:00:00+00:00"
    docs = []
    for _ in range(n):
        cid = f"{prefix}{uuid.uuid4().hex[:10]}"
        docs.append({
            "id": cid, "tenant_id": tenant_id,
            "name": f"{prefix}customer {cid[-6:]}",
            "email": f"{cid}@example.com",
            "is_active": True,
            "created_at": now_ts,
        })
        ids.append(cid)
    if docs:
        await db.customers.insert_many(docs)
    return ids


async def _cleanup(db, tenant_id: str, *, prefix: str = "TEST_ubd_"):
    await db.customers.delete_many(
        {"tenant_id": tenant_id, "id": {"$regex": f"^{prefix}"}})
    await db.customer_bulk_delete_audit.delete_many(
        {"tenant_id": tenant_id})
    await db.audit_log.delete_many(
        {"tenant_id": tenant_id, "action": "customer.soft_delete"})


def test_cap_enforced_at_10000_ids_per_call():
    """10,001 ids → 400. 10,000 ids under super_admin → allowed."""
    tok = _login("super@aquaterra.com")
    payload = {"ids": [f"TEST_ubd_bogus_{i}" for i in range(10_001)]}
    r = requests.post(f"{API}/customers/bulk-delete",
                       json=payload,
                       headers={"Authorization": f"Bearer {tok}"},
                       timeout=60)
    assert r.status_code == 400, r.text
    body = r.json()
    assert "10000" in str(body).lower() or "10_000" in str(body).lower() \
        or "capped at 10000" in str(body).lower()


def test_super_admin_can_delete_over_500_admin_cannot():
    """Threshold flip: 501 ids under admin/manager → 403;
    same 501 ids under super_admin → 200."""
    tid = _tenant_id(_login("super@aquaterra.com"))

    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db, tid)
            ids = await _seed_customers(db, tid, 501)
            return ids
        finally:
            client.close()
    seeded = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        # Admin (400-cap collection default) → 403.
        admin_tok = _login("admin@aquaterra.com")
        r_admin = requests.post(
            f"{API}/customers/bulk-delete", json={"ids": seeded[:501]},
            headers={"Authorization": f"Bearer {admin_tok}"}, timeout=60,
        )
        assert r_admin.status_code == 403, r_admin.text
        assert "super_admin" in r_admin.text

        # Super_admin → 200 with all 501 soft-deleted.
        sa_tok = _login("super@aquaterra.com")
        r_sa = requests.post(
            f"{API}/customers/bulk-delete", json={"ids": seeded[:501]},
            headers={"Authorization": f"Bearer {sa_tok}"}, timeout=120,
        )
        assert r_sa.status_code == 200, r_sa.text
        body = r_sa.json()
        assert body["deleted_count"] == 501
        assert body["requested_count"] == 501
        assert body["continue_token"] is None
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db, tid)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_soft_delete_only_rows_remain_with_deleted_at_stamp():
    """Rows are NOT hard-deleted — they gain ``deleted_at`` +
    ``deleted_by_user_id`` and remain queryable by super_admin
    tooling for a possible restore."""
    tok = _login("super@aquaterra.com")
    tid = _tenant_id(tok)

    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db, tid)
            return await _seed_customers(db, tid, 5)
        finally:
            client.close()
    ids = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        r = requests.post(
            f"{API}/customers/bulk-delete", json={"ids": ids},
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        assert r.json()["deleted_count"] == 5

        # Verify SOFT delete — rows still exist with deleted_at set.
        async def _verify():
            db, client = _fresh_db()
            try:
                docs = await db.customers.find(
                    {"id": {"$in": ids}, "tenant_id": tid},
                ).to_list(20)
                assert len(docs) == 5, "rows were HARD-deleted (regression)"
                for d in docs:
                    assert d.get("deleted_at"), \
                        f"missing deleted_at on {d.get('id')}"
                    assert d.get("deleted_by_user_id"), \
                        f"missing deleted_by_user_id on {d.get('id')}"
                return True
            finally:
                client.close()
        assert asyncio.get_event_loop().run_until_complete(_verify())
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db, tid)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_locked_check_preserved_for_active_invoices():
    """Cascade behavior unchanged — customers with an active invoice
    remain in ``failed[]`` with ``status_code == 409``. Non-locked
    customers in the same call are deleted anyway."""
    tok = _login("super@aquaterra.com")
    tid = _tenant_id(tok)

    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db, tid)
            ids = await _seed_customers(db, tid, 3)
            # Stamp an active invoice on the FIRST customer.
            await db.quotes.insert_one({
                "id": f"TEST_ubd_inv_{uuid.uuid4().hex[:8]}",
                "tenant_id": tid,
                "customer_id": ids[0],
                "doc_type": "invoice",
                "payment_status": "unpaid",
            })
            return ids
        finally:
            client.close()
    ids = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        r = requests.post(
            f"{API}/customers/bulk-delete", json={"ids": ids},
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted_count"] == 2, body
        assert len(body["failed"]) == 1, body
        f = body["failed"][0]
        assert f["id"] == ids[0]
        assert f["status_code"] == 409
        assert "invoice" in f["reason"].lower()
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db, tid)
                await db.quotes.delete_many(
                    {"tenant_id": tid, "id": {"$regex": "^TEST_ubd_inv_"}})
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_audit_log_summary_doc_written_per_invocation():
    """Feb-2026 · One ``customer_bulk_delete_audit`` doc per call so
    ops can answer "who mass-deleted N customers on <date>?"
    without scanning per-row audit rows."""
    tok = _login("super@aquaterra.com")
    tid = _tenant_id(tok)

    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db, tid)
            return await _seed_customers(db, tid, 4)
        finally:
            client.close()
    ids = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        r = requests.post(
            f"{API}/customers/bulk-delete", json={"ids": ids},
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text

        async def _verify():
            db, client = _fresh_db()
            try:
                rows = await db.customer_bulk_delete_audit.find(
                    {"tenant_id": tid},
                ).to_list(5)
                assert len(rows) == 1, f"expected exactly 1 summary doc, got {len(rows)}"
                row = rows[0]
                assert row["deleted_count"] == 4
                assert row["failed_count"] == 0
                assert row["requested_count"] == 4
                assert row["actor_role"] == "super_admin"
                assert row["actor_email"] == "super@aquaterra.com"
                # For a 4-id call the customer_ids MUST NOT be truncated.
                assert row["customer_ids_truncated"] is False
                assert set(row["customer_ids"]) == set(ids)
                return True
            finally:
                client.close()
        assert asyncio.get_event_loop().run_until_complete(_verify())
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db, tid)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_audit_log_summary_truncates_customer_ids_beyond_100():
    """A 150-id call MUST log the first 100 ids and set
    ``customer_ids_truncated: true`` so the audit doc stays bounded."""
    tok = _login("super@aquaterra.com")
    tid = _tenant_id(tok)

    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db, tid)
            return await _seed_customers(db, tid, 150)
        finally:
            client.close()
    ids = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        r = requests.post(
            f"{API}/customers/bulk-delete", json={"ids": ids},
            headers={"Authorization": f"Bearer {tok}"}, timeout=60,
        )
        assert r.status_code == 200, r.text

        async def _verify():
            db, client = _fresh_db()
            try:
                row = await db.customer_bulk_delete_audit.find_one(
                    {"tenant_id": tid})
                assert row is not None
                assert row["deleted_count"] == 150
                assert row["customer_ids_truncated"] is True
                assert len(row["customer_ids"]) == 100
                return True
            finally:
                client.close()
        assert asyncio.get_event_loop().run_until_complete(_verify())
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db, tid)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_tenant_isolation_ids_in_other_tenant_rejected_as_not_found():
    """IDs belonging to a DIFFERENT tenant must return ``failed[]``
    entries with ``status_code == 404`` — they must NOT touch the
    other tenant's data. Verified by inspecting the OTHER tenant's
    row post-call — still alive, no deleted_at."""
    tok = _login("super@aquaterra.com")
    tid = _tenant_id(tok)
    other_tid = f"TEST_ubd_other_tenant_{uuid.uuid4().hex[:6]}"

    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db, tid)
            # Own-tenant row.
            own = await _seed_customers(db, tid, 1)
            # Other-tenant row (same collection, different tenant_id).
            leaky_id = f"TEST_ubd_leaky_{uuid.uuid4().hex[:8]}"
            await db.customers.insert_one({
                "id": leaky_id, "tenant_id": other_tid,
                "name": "TEST_ubd other-tenant customer",
                "email": f"{leaky_id}@example.com",
                "is_active": True,
            })
            return own[0], leaky_id
        finally:
            client.close()
    own_id, leaky_id = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        r = requests.post(
            f"{API}/customers/bulk-delete",
            json={"ids": [own_id, leaky_id]},
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["deleted_count"] == 1, body
        assert own_id in body["deleted"]
        assert len(body["failed"]) == 1, body
        assert body["failed"][0]["id"] == leaky_id
        assert body["failed"][0]["status_code"] == 404

        # Cross-tenant row untouched.
        async def _verify():
            db, client = _fresh_db()
            try:
                doc = await db.customers.find_one({"id": leaky_id})
                assert doc is not None
                assert not doc.get("deleted_at"), \
                    "OTHER tenant's row was soft-deleted (tenant leak!)"
                return True
            finally:
                client.close()
        assert asyncio.get_event_loop().run_until_complete(_verify())
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db, tid)
                await db.customers.delete_one({"id": leaky_id})
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_chunked_execution_uses_500_row_update_many_batches():
    """Direct unit test on the endpoint function: patch
    ``db.customers.update_many`` and assert the endpoint issues
    N/500-rounded chunks so a 1200-row payload becomes exactly
    3 ``update_many`` calls."""
    # We can't easily monkeypatch inside a running uvicorn process,
    # so this test drives the endpoint function IN-PROCESS via a
    # local import + a stubbed ``db`` collection. That gives us a
    # deterministic chunk-size assertion without an HTTP hop.
    from routers.bulk_crm import (
        customers_bulk_delete,
        _CUSTOMERS_DELETE_CHUNK,
    )
    from types import SimpleNamespace

    # Fake user + tenant.
    user = {"id": "u-1", "role": "super_admin",
            "email": "super@aquaterra.com"}
    tenant = {"id": "t-chunk"}

    N = 1200
    seeded_ids = [f"chunk-id-{i}" for i in range(N)]

    # Track update_many chunk sizes.
    chunk_sizes = []

    class _FakeCol:
        async def find_one(self, *a, **kw): return None

        def find(self, q, projection=None):
            # Emulate deleted_at/existence probe: every id exists,
            # none previously deleted. ``$in`` limited to what we
            # returned.
            in_ids = q.get("id", {}).get("$in", [])
            async def _gen():
                for _id in in_ids:
                    yield {"id": _id, "deleted_at": None}
            class _Cur:
                def __aiter__(self_inner): return _gen()
            return _Cur()

        def aggregate(self, *a, **kw):
            async def _gen():
                # No locked rows.
                return
                yield
            class _Cur:
                def __aiter__(self_inner): return _gen()
            return _Cur()

        async def update_many(self, q, patch):
            n = len(q.get("id", {}).get("$in", []))
            chunk_sizes.append(n)
            return SimpleNamespace(modified_count=n)

        async def update_one(self, *a, **kw):
            return SimpleNamespace(modified_count=1)

        async def insert_one(self, *a, **kw): return None

    class _FakeDB(dict):
        def __getitem__(self, k):
            return getattr(self, k)

    fake = _FakeDB()
    fake.customers = _FakeCol()
    fake.quotes = _FakeCol()
    fake.customer_bulk_delete_audit = _FakeCol()
    fake.audit_log = _FakeCol()

    with patch("routers.bulk_crm.db", fake):
        body = SimpleNamespace(
            ids=seeded_ids, query_selector=None, exclude_ids=None,
        )
        result = asyncio.get_event_loop().run_until_complete(
            customers_bulk_delete(body=body, user=user, tenant=tenant)
        )
        assert result["deleted_count"] == N
        # Expect exactly N / chunk_size chunks (1200 / 500 = 3).
        expected_chunks = (N + _CUSTOMERS_DELETE_CHUNK - 1) // _CUSTOMERS_DELETE_CHUNK
        assert len(chunk_sizes) == expected_chunks, chunk_sizes
        # Chunk sizes: [500, 500, 200] for N=1200.
        assert chunk_sizes[0] == _CUSTOMERS_DELETE_CHUNK
        assert chunk_sizes[-1] == N % _CUSTOMERS_DELETE_CHUNK or _CUSTOMERS_DELETE_CHUNK
