"""Phase 55-a · Aug-2026 — Homeworks importer scaffold contract."""
from __future__ import annotations
import pytest


class _DeleteResult:
    def __init__(self, n): self.deleted_count = n


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    @staticmethod
    def _match(d, q):
        for k, v in q.items():
            if d.get(k) != v:
                return False
        return True

    async def insert_one(self, d): self.docs.append(dict(d))

    async def find_one(self, q, projection=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    def find(self, q, projection=None):
        matches = [dict(d) for d in self.docs if self._match(d, q)]
        return _Cur(matches)

    async def update_one(self, q, upd):
        for d in self.docs:
            if self._match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    d[k] = v
                return

    async def delete_many(self, q):
        keep, dropped = [], 0
        for d in self.docs:
            if self._match(d, q):
                dropped += 1
            else:
                keep.append(d)
        self.docs = keep
        return _DeleteResult(dropped)


class _Cur:
    def __init__(self, docs): self.docs = docs

    def sort(self, k, dir=1):
        rev = dir == -1
        self.docs = sorted(self.docs, key=lambda d: d.get(k) or "",
                             reverse=rev)
        return self

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self.docs):
            raise StopAsyncIteration
        d = self.docs[self._i]; self._i += 1
        return d


@pytest.fixture
def fake_db(monkeypatch):
    from config import db as _real
    batches = _FakeColl()
    staging = _FakeColl()
    customers = _FakeColl()
    jobs = _FakeColl()
    monkeypatch.setattr(_real, "import_batches", batches, raising=False)
    monkeypatch.setattr(_real, "homeworks_staging", staging, raising=False)
    monkeypatch.setattr(_real, "customers", customers, raising=False)
    monkeypatch.setattr(_real, "jobs", jobs, raising=False)
    # __getitem__ path used by rollback loop.
    original_getitem = type(_real).__getitem__

    def _getitem(self, name):
        override = {"import_batches": batches,
                    "homeworks_staging": staging,
                    "customers": customers, "jobs": jobs}
        if name in override:
            return override[name]
        return original_getitem(self, name)
    monkeypatch.setattr(type(_real), "__getitem__", _getitem)
    return {"batches": batches, "staging": staging,
            "customers": customers, "jobs": jobs}


ADMIN = {"id": "u-a", "role": "admin", "tenant_id": "tenant-A"}
TENANT = {"id": "tenant-A"}


def test_create_batch_persists_pending_state(fake_db):
    import asyncio

    async def _run():
        from routers.homeworks_import import create_batch, _NewBatchIn
        r = await create_batch(
            _NewBatchIn(entity_types_planned=["customers", "jobs"]),
            user=ADMIN, tenant=TENANT,
        )
        assert r["state"] == "pending"
        assert r["source"] == "copilot_crm"
        assert r["tenant_id"] == "tenant-A"
        assert set(r["entity_types_planned"]) == {"customers", "jobs"}
        assert r["created_by_user_id"] == "u-a"
        assert len(fake_db["batches"].docs) == 1

    asyncio.run(_run())


def test_create_batch_rejects_unknown_entity_type(fake_db):
    import asyncio
    from fastapi import HTTPException

    async def _run():
        from routers.homeworks_import import create_batch, _NewBatchIn
        with pytest.raises(HTTPException) as ex:
            await create_batch(
                _NewBatchIn(entity_types_planned=["customers", "bogus"]),
                user=ADMIN, tenant=TENANT,
            )
        assert ex.value.status_code == 400
        assert ex.value.detail["error"] == "invalid_entity_types"
        assert "bogus" in ex.value.detail["unknown"]

    asyncio.run(_run())


def test_list_batches_scopes_to_tenant(fake_db):
    import asyncio

    async def _run():
        from routers.homeworks_import import list_batches
        fake_db["batches"].docs = [
            {"id": "b1", "tenant_id": "tenant-A", "state": "pending",
              "created_at": "2026-08-10T01:00:00"},
            {"id": "b2", "tenant_id": "tenant-B", "state": "pending",
              "created_at": "2026-08-10T02:00:00"},
        ]
        r = await list_batches(user=ADMIN, tenant=TENANT)
        ids = [b["id"] for b in r["batches"]]
        assert ids == ["b1"]

    asyncio.run(_run())


def test_get_batch_detail_returns_staging_slice(fake_db):
    import asyncio

    async def _run():
        from routers.homeworks_import import get_batch
        fake_db["batches"].docs = [
            {"id": "b1", "tenant_id": "tenant-A", "state": "pending",
              "entity_counts": {}},
        ]
        for i in range(3):
            fake_db["staging"].docs.append({
                "id": f"s{i}", "tenant_id": "tenant-A",
                "batch_id": "b1", "entity_type": "customer",
                "imported_at": f"2026-08-10T0{i}:00:00",
            })
        r = await get_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["id"] == "b1"
        assert len(r["staging_latest"]) == 3


    asyncio.run(_run())


def test_rollback_empty_batch_is_idempotent(fake_db):
    """Rollback of a batch that never got scraped just flips state
    and reports zero purges — safe to call twice."""
    import asyncio

    async def _run():
        from routers.homeworks_import import rollback_batch
        fake_db["batches"].docs = [{
            "id": "b1", "tenant_id": "tenant-A", "state": "pending",
        }]
        r1 = await rollback_batch("b1", user=ADMIN, tenant=TENANT)
        assert r1["ok"] is True
        assert r1["batch_id"] == "b1"
        # Every collection reported 0 purges.
        assert all(v == 0 for v in r1["purged_counts"].values())
        # State flipped to rolled_back.
        assert fake_db["batches"].docs[0]["state"] == "rolled_back"

        # Second call → idempotent no-op.
        r2 = await rollback_batch("b1", user=ADMIN, tenant=TENANT)
        assert r2["ok"] is True
        assert r2.get("already_rolled_back") is True

    asyncio.run(_run())


def test_rollback_purges_customers_and_jobs_by_import_batch_id(fake_db):
    """When data has been inserted with an ``import_batch_id`` foreign
    key, rollback sweeps every row across every affected collection."""
    import asyncio

    async def _run():
        from routers.homeworks_import import rollback_batch
        fake_db["batches"].docs = [{
            "id": "b1", "tenant_id": "tenant-A", "state": "running",
        }]
        # Seed 3 customers + 2 jobs under batch b1 + 1 customer NOT in the batch.
        for i in range(3):
            fake_db["customers"].docs.append({
                "id": f"c{i}", "tenant_id": "tenant-A",
                "import_batch_id": "b1", "email": f"c{i}@x.com",
            })
        fake_db["customers"].docs.append({
            "id": "c-other", "tenant_id": "tenant-A",
            "import_batch_id": None, "email": "keep@x.com",
        })
        for i in range(2):
            fake_db["jobs"].docs.append({
                "id": f"j{i}", "tenant_id": "tenant-A",
                "import_batch_id": "b1",
            })
        r = await rollback_batch("b1", user=ADMIN, tenant=TENANT)
        assert r["purged_counts"]["customers"] == 3
        assert r["purged_counts"]["jobs"] == 2
        # The non-batch customer survives.
        surviving = [c["id"] for c in fake_db["customers"].docs]
        assert surviving == ["c-other"]

    asyncio.run(_run())


def test_role_gate_manager_and_tech_blocked_before_dependency_runs(fake_db):
    """require_admin fires at FastAPI dependency layer — so managers,
    techs and customers 403 before any batch logic runs."""
    from fastapi import HTTPException
    from utils import require_admin
    for role in ("manager", "technician", "customer", ""):
        with pytest.raises(HTTPException) as ex:
            require_admin({"role": role})
        assert ex.value.status_code == 403
    # Admin + super_admin pass.
    for role in ("admin", "super_admin"):
        assert require_admin({"role": role, "id": "u"})["id"] == "u"
