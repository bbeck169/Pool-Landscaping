"""Preview isolation · boot-scrubber regression tests."""
from __future__ import annotations

import asyncio
import importlib
import os
from datetime import datetime, timezone
from unittest.mock import patch


def _reload(env: str = "development"):
    os.environ["APP_ENV"] = env
    import services.preview_isolation.config as cfg
    importlib.reload(cfg)
    import services.preview_isolation as pi
    importlib.reload(pi)
    import services.preview_isolation.scrubber as sc
    importlib.reload(sc)
    return sc


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates = []

    def find(self, _query=None, _projection=None):
        rows = list(self.rows)

        class _Cursor:
            def __aiter__(self):
                self._it = iter(rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration
        return _Cursor()

    async def update_one(self, filt, update):
        self.updates.append((filt, update))

    async def insert_one(self, doc):
        self.rows.append(doc)

    async def count_documents(self, _q):
        return 0

    async def delete_many(self, _q):
        class _Res:
            deleted_count = len(self.rows)
        count = len(self.rows)
        self.rows = []
        res = _Res()
        res.deleted_count = count
        return res


class _FakeDB:
    def __init__(self):
        self.customers = _FakeCollection([
            {"_id": "oid-1", "id": "c1", "tenant_id": "t",
              "name": "Real Jane Doe", "email": "jane@real.com",
              "phone": "602-555-1234", "address": "1 Real St",
              "notes": "Contact at jane@real.com for ops"},
            {"_id": "oid-2", "id": "c2", "tenant_id": "t",
              "name": "Preview Customer0042",
              "email": "preview-customer0042@preview.local"},
        ])
        self.leads = _FakeCollection([
            {"_id": "oid-3", "id": "l1", "tenant_id": "t",
              "name": "Pat Kail", "email": "pat@real.com"},
        ])
        self.quotes = _FakeCollection([
            {"_id": "oid-4", "id": "q1",
              "customer_name": "Real Client LLC",
              "customer_email": "real@foo.com"},
        ])
        self.audit_logs = _FakeCollection()


# ────────────────────────────────────────────────────────────────────
# 1 · Production env — strict no-op.
# ────────────────────────────────────────────────────────────────────
def test_production_run_once_returns_skipped():
    sc = _reload("production")
    db = _FakeDB()

    async def _go():
        return await sc.run_once(db)
    out = _run(_go())
    assert out["skipped"] == "production_env"
    assert db.customers.updates == []
    assert db.leads.updates == []
    assert db.quotes.updates == []


# ────────────────────────────────────────────────────────────────────
# 2 · Non-localhost MONGO_URL — refuses to run.
# ────────────────────────────────────────────────────────────────────
def test_refuses_remote_mongo():
    sc = _reload("development")
    db = _FakeDB()

    async def _go():
        return await sc.run_once(db)
    with patch.dict(os.environ, {"MONGO_URL": "mongodb://remote-prod:27017"}):
        out = _run(_go())
    assert out["skipped"] == "non_localhost_mongo"
    assert db.customers.updates == []


# ────────────────────────────────────────────────────────────────────
# 3 · Preview env + localhost — scrubs real-PII rows + skips
#     already-synthetic rows.
# ────────────────────────────────────────────────────────────────────
def test_scrubs_real_rows_only():
    sc = _reload("development")
    db = _FakeDB()

    async def _go():
        return await sc.run_once(db)
    with patch.dict(os.environ, {"MONGO_URL": "mongodb://localhost:27017"}):
        out = _run(_go())
    assert out["ok"] is True
    counts = out["scrubbed_counts"]
    assert counts["customers"] == 1  # Only Jane; Preview Customer0042 is skipped.
    assert counts["leads"] == 1
    assert counts["quotes"] == 1
    # Audit row appended.
    assert any(r.get("event") == "pii_boot_scrub" for r in db.audit_logs.rows)


# ────────────────────────────────────────────────────────────────────
# 4 · 24h dedup — second run skips.
# ────────────────────────────────────────────────────────────────────
def test_recent_scrub_blocks_rerun():
    sc = _reload("development")
    db = _FakeDB()

    async def _recent(_q):
        return 1  # Simulates a recent audit row.
    db.audit_logs.count_documents = _recent

    async def _go():
        return await sc.run_once(db)
    with patch.dict(os.environ, {"MONGO_URL": "mongodb://localhost:27017"}):
        out = _run(_go())
    assert out["skipped"] == "recent_scrub_within_24h"
    assert db.customers.updates == []


def test_force_bypasses_dedup():
    sc = _reload("development")
    db = _FakeDB()

    async def _recent(_q):
        return 1
    db.audit_logs.count_documents = _recent

    async def _go():
        return await sc.run_once(db, force=True)
    with patch.dict(os.environ, {"MONGO_URL": "mongodb://localhost:27017"}):
        out = _run(_go())
    assert out["ok"] is True
    assert out["scrubbed_counts"]["customers"] == 1


# ────────────────────────────────────────────────────────────────────
# 5 · Non-customer users row is skipped — admin accounts untouched.
# ────────────────────────────────────────────────────────────────────
def test_admin_users_not_scrubbed():
    sc = _reload("development")
    db = _FakeDB()
    db.users = _FakeCollection([
        {"_id": "u1", "role": "customer", "name": "Real Customer",
          "email": "cust@real.com"},
        {"_id": "u2", "role": "admin", "name": "Admin Real",
          "email": "admin@real.com"},
        {"_id": "u3", "role": "tech", "name": "Tech Real",
          "email": "tech@real.com"},
    ])

    async def _go():
        return await sc.run_once(db)
    with patch.dict(os.environ, {"MONGO_URL": "mongodb://localhost:27017"}):
        out = _run(_go())
    assert out["scrubbed_counts"]["users"] == 1
    updated_ids = [f["_id"] for f, _u in db.users.updates]
    assert "u1" in updated_ids
    assert "u2" not in updated_ids
    assert "u3" not in updated_ids


# ────────────────────────────────────────────────────────────────────
# 6 · Missing collections are skipped quietly.
# ────────────────────────────────────────────────────────────────────
def test_missing_collections_skipped():
    sc = _reload("development")

    class _MinimalDB:
        def __init__(self):
            self.customers = _FakeCollection([
                {"_id": "oid-1", "name": "Real Kai", "email": "kai@real.com"},
            ])
            self.audit_logs = _FakeCollection()

    db = _MinimalDB()

    async def _go():
        return await sc.run_once(db)
    with patch.dict(os.environ, {"MONGO_URL": "mongodb://localhost:27017"}):
        out = _run(_go())
    assert out["ok"] is True
    for coll in ("leads", "outreach_prospects", "quotes", "invoices"):
        assert out["scrubbed_counts"].get(coll, 0) == 0
    assert out["scrubbed_counts"]["customers"] == 1
