"""Phase 56-a · Aug-2026 — Pricebook Suppliers backend contract.

Covers every endpoint landed in ``routers/pricebook_suppliers.py`` plus
the idempotent seed in ``services/pricebook_suppliers_seed.py``:

  * GET    /api/pricebook/suppliers?include_deleted=
  * POST   /api/pricebook/suppliers                 — create
  * PATCH  /api/pricebook/suppliers/{id}            — display_name + is_active only
  * DELETE /api/pricebook/suppliers/{id}            — soft delete
  * POST   /api/pricebook/suppliers/{id}/restore    — restore
  * services.pricebook_suppliers_seed.seed_pricebook_suppliers_for_tenant

Role gate (preflight §5 + Fix #5 mirror):
  * admin / super_admin / owner — allowed by ``require_admin``
  * manager / technician / customer — 403 at dependency layer, so
    ``include_deleted=true`` never lands on the query for them.

Write-once fields (preflight §5):
  * ``slug`` — set at create, PATCH ignores it.
  * ``income_category_id`` — set at create, PATCH ignores it.

Handlers are invoked directly with in-memory ``_FakeCollection`` stubs
(same style as ``test_autobilling_runs_soft_delete``) so no Motor loop.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest


# ─── Fake Motor collection ──────────────────────────────────────────────
class _FakeCollection:
    """Small async collection stub. Supports the operator subset the
    Phase 56-a router + seed actually exercise: equality, ``$in``,
    projection kwarg (ignored), and both ``find_one`` and ``find``.
    """

    def __init__(self, docs: List[Dict[str, Any]] | None = None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    @staticmethod
    def _match(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
        for k, v in q.items():
            dv = doc.get(k)
            if isinstance(v, dict) and "$in" in v:
                if dv not in v["$in"]:
                    return False
            elif dv != v:
                return False
        return True

    async def find_one(self, q, projection=None):
        for d in self.docs:
            if self._match(d, q):
                return dict(d)
        return None

    def find(self, q, projection=None):
        matches = [dict(d) for d in self.docs if self._match(d, q)]
        return _FakeCursor(matches)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def insert_many(self, docs):
        self.docs.extend(dict(d) for d in docs)

    async def update_one(self, q, upd):
        for d in self.docs:
            if self._match(d, q):
                for k, v in (upd.get("$set") or {}).items():
                    d[k] = v
                for k in (upd.get("$unset") or {}):
                    d.pop(k, None)
                return
        raise AssertionError(f"no match for {q!r}")

    async def count_documents(self, q):
        return sum(1 for d in self.docs if self._match(d, q))


class _FakeCursor:
    def __init__(self, docs): self.docs = docs

    def sort(self, key, direction=1):
        rev = (direction == -1)
        self.docs = sorted(self.docs, key=lambda d: d.get(key) or "", reverse=rev)
        return self

    async def to_list(self, cap): return self.docs[:cap]

    def __aiter__(self):
        self._i = 0
        return self

    async def __anext__(self):
        if self._i >= len(self.docs):
            raise StopAsyncIteration
        d = self.docs[self._i]
        self._i += 1
        return d


@pytest.fixture
def fake_db(monkeypatch):
    """Swap the four collections the router + seed touch."""
    from config import db as _real_db
    coll = _FakeCollection()
    audits = _FakeCollection()
    cats = _FakeCollection()
    tenants = _FakeCollection()
    monkeypatch.setattr(_real_db, "pricebook_suppliers", coll, raising=False)
    monkeypatch.setattr(_real_db, "audits", audits, raising=False)
    monkeypatch.setattr(_real_db, "income_categories", cats, raising=False)
    monkeypatch.setattr(_real_db, "tenants", tenants, raising=False)
    return {"suppliers": coll, "audits": audits,
            "cats": cats, "tenants": tenants}


TENANT = {"id": "tenant-A", "name": "Vistancia"}
OTHER  = {"id": "tenant-B", "name": "Peoria"}
ADMIN = {"id": "u-admin", "email": "admin@x", "role": "admin"}
SUPER = {"id": "u-super", "email": "super@x", "role": "super_admin"}
OWNER = {"id": "u-owner", "email": "owner@x", "role": "owner"}
MANAGER = {"id": "u-mgr", "email": "m@x", "role": "manager"}
TECH = {"id": "u-tech", "email": "t@x", "role": "technician"}


def _cat(cid: str, tenant_id: str, name: str, archived: bool = False):
    return {"id": cid, "tenant_id": tenant_id, "name": name,
            "is_archived": archived}


def _supp(sid: str, tenant_id: str = TENANT["id"], **overrides):
    d = {"id": sid, "tenant_id": tenant_id,
         "slug": overrides.get("slug", f"s-{sid}"),
         "display_name": overrides.get("display_name", f"S {sid}"),
         "income_category_id": overrides.get("income_category_id", "cat-pool"),
         "is_active": overrides.get("is_active", True),
         "is_seed": overrides.get("is_seed", False),
         "deleted_at": overrides.get("deleted_at", None)}
    for k, v in overrides.items():
        d.setdefault(k, v)
        d[k] = v
    return d


# ─── require_admin role gate — mirrors Fix #5 ───────────────────────────
@pytest.mark.parametrize("user", [ADMIN, SUPER, OWNER])
def test_require_admin_lets_admin_super_owner_through(user):
    from utils import require_admin
    assert require_admin(user)["id"] == user["id"]


@pytest.mark.parametrize("user", [MANAGER, TECH])
def test_require_admin_blocks_manager_tech_before_include_deleted(user):
    """The include_deleted flag never gets evaluated for non-admins —
    ``require_admin`` throws 403 at the dependency layer first."""
    from utils import require_admin
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ex:
        require_admin(user)
    assert ex.value.status_code == 403


# ─── GET /pricebook/suppliers ───────────────────────────────────────────
def test_list_hides_soft_deleted_by_default(fake_db):
    import asyncio

    async def _run():
        from routers.pricebook_suppliers import list_pricebook_suppliers
        fake_db["suppliers"].docs = [
            _supp("s1"),
            _supp("s2", deleted_at="2026-08-09T00:00:00"),
        ]
        rows = await list_pricebook_suppliers(
            income_category_id=None, include_deleted=False,
            user=ADMIN, tenant=TENANT,
        )
        ids = [r["id"] for r in rows]
        assert "s1" in ids and "s2" not in ids

    asyncio.run(_run())


def test_list_includes_deleted_when_flag_true(fake_db):
    import asyncio

    async def _run():
        from routers.pricebook_suppliers import list_pricebook_suppliers
        fake_db["suppliers"].docs = [
            _supp("s1"),
            _supp("s2", deleted_at="2026-08-09T00:00:00"),
        ]
        rows = await list_pricebook_suppliers(
            income_category_id=None, include_deleted=True,
            user=ADMIN, tenant=TENANT,
        )
        ids = [r["id"] for r in rows]
        assert "s1" in ids and "s2" in ids

    asyncio.run(_run())


def test_list_scopes_to_tenant(fake_db):
    """Rows on another tenant must never leak."""
    import asyncio

    async def _run():
        from routers.pricebook_suppliers import list_pricebook_suppliers
        fake_db["suppliers"].docs = [
            _supp("s1", tenant_id=TENANT["id"]),
            _supp("s2", tenant_id=OTHER["id"]),
        ]
        rows = await list_pricebook_suppliers(
            income_category_id=None, include_deleted=True,
            user=ADMIN, tenant=TENANT,
        )
        ids = [r["id"] for r in rows]
        assert ids == ["s1"]

    asyncio.run(_run())


# ─── POST /pricebook/suppliers ──────────────────────────────────────────
def test_create_happy_path(fake_db):
    import asyncio

    async def _run():
        from models import PricebookSupplierIn
        from routers.pricebook_suppliers import create_pricebook_supplier
        fake_db["cats"].docs = [_cat("cat-pool", TENANT["id"], "Pool")]
        body = PricebookSupplierIn(
            slug="Watkins",  # will be lowercased
            display_name="Watkins Wholesale",
            income_category_id="cat-pool",
        )
        row = await create_pricebook_supplier(body, user=ADMIN, tenant=TENANT)
        assert row["slug"] == "watkins"
        assert row["display_name"] == "Watkins Wholesale"
        assert row["income_category_id"] == "cat-pool"
        assert row["is_active"] is True
        assert row["is_seed"] is False
        assert row["tenant_id"] == TENANT["id"]
        assert row["created_by_user_id"] == ADMIN["id"]
        assert len(fake_db["suppliers"].docs) == 1

    asyncio.run(_run())


def test_create_rejects_duplicate_slug_in_same_tenant(fake_db):
    """409 on active dup. Deleted rows do NOT block re-create."""
    import asyncio

    async def _run():
        from fastapi import HTTPException
        from models import PricebookSupplierIn
        from routers.pricebook_suppliers import create_pricebook_supplier
        fake_db["cats"].docs = [_cat("cat-pool", TENANT["id"], "Pool")]
        fake_db["suppliers"].docs = [
            _supp("s1", slug="scp", income_category_id="cat-pool"),
        ]
        body = PricebookSupplierIn(
            slug="SCP", display_name="Another SCP",
            income_category_id="cat-pool",
        )
        with pytest.raises(HTTPException) as ex:
            await create_pricebook_supplier(body, user=ADMIN, tenant=TENANT)
        assert ex.value.status_code == 409

    asyncio.run(_run())


def test_create_rejects_archived_income_category(fake_db):
    import asyncio

    async def _run():
        from fastapi import HTTPException
        from models import PricebookSupplierIn
        from routers.pricebook_suppliers import create_pricebook_supplier
        fake_db["cats"].docs = [
            _cat("cat-old", TENANT["id"], "Retired", archived=True),
        ]
        body = PricebookSupplierIn(
            slug="scp", display_name="SCP", income_category_id="cat-old",
        )
        with pytest.raises(HTTPException) as ex:
            await create_pricebook_supplier(body, user=ADMIN, tenant=TENANT)
        assert ex.value.status_code == 400

    asyncio.run(_run())


# ─── PATCH /pricebook/suppliers/{id} ────────────────────────────────────
def test_patch_updates_display_name_and_is_active(fake_db):
    import asyncio

    async def _run():
        from models import PricebookSupplierPatch
        from routers.pricebook_suppliers import patch_pricebook_supplier
        fake_db["suppliers"].docs = [_supp("s1", display_name="Old", is_active=True)]
        row = await patch_pricebook_supplier(
            "s1",
            PricebookSupplierPatch(display_name="New Name", is_active=False),
            user=ADMIN, tenant=TENANT,
        )
        assert row["display_name"] == "New Name"
        assert row["is_active"] is False
        assert fake_db["suppliers"].docs[0]["display_name"] == "New Name"

    asyncio.run(_run())


def test_patch_ignores_slug_and_category_write_once(fake_db):
    """PATCH schema doesn't even accept slug / income_category_id.
    Prove: an attempt to sneak them via extra keys does nothing —
    PricebookSupplierPatch strips them at validation, so slug +
    income_category_id remain unchanged on disk."""
    import asyncio

    async def _run():
        from models import PricebookSupplierPatch
        from routers.pricebook_suppliers import patch_pricebook_supplier
        fake_db["suppliers"].docs = [
            _supp("s1", slug="scp", income_category_id="cat-pool"),
        ]
        # Pydantic will drop unknown fields (default behaviour on v2 without
        # ``extra=allow``). Passing them via dict init proves the schema
        # is the safety net.
        body = PricebookSupplierPatch(
            **{"display_name": "Renamed", "slug": "hacked",           # type: ignore[arg-type]
                "income_category_id": "cat-hacked"},
        )
        await patch_pricebook_supplier("s1", body, user=ADMIN, tenant=TENANT)
        row = fake_db["suppliers"].docs[0]
        assert row["slug"] == "scp"
        assert row["income_category_id"] == "cat-pool"
        assert row["display_name"] == "Renamed"

    asyncio.run(_run())


def test_patch_404_when_not_found(fake_db):
    import asyncio

    async def _run():
        from fastapi import HTTPException
        from models import PricebookSupplierPatch
        from routers.pricebook_suppliers import patch_pricebook_supplier
        with pytest.raises(HTTPException) as ex:
            await patch_pricebook_supplier(
                "s-x", PricebookSupplierPatch(display_name="X"),
                user=ADMIN, tenant=TENANT,
            )
        assert ex.value.status_code == 404

    asyncio.run(_run())


# ─── DELETE /pricebook/suppliers/{id} + restore ─────────────────────────
def test_soft_delete_and_restore_roundtrip(fake_db):
    import asyncio

    async def _run():
        from routers.pricebook_suppliers import (
            soft_delete_pricebook_supplier, restore_pricebook_supplier,
        )
        fake_db["suppliers"].docs = [_supp("s1")]
        res = await soft_delete_pricebook_supplier(
            "s1", user=ADMIN, tenant=TENANT,
        )
        assert res["deleted"] is True
        row = fake_db["suppliers"].docs[0]
        assert row["deleted_at"]
        assert row["deleted_by_user_id"] == ADMIN["id"]

        res2 = await restore_pricebook_supplier(
            "s1", user=SUPER, tenant=TENANT,
        )
        assert res2["restored"] is True
        row = fake_db["suppliers"].docs[0]
        assert row["deleted_at"] is None
        assert row["restored_by_user_id"] == SUPER["id"]
        assert row["restored_at"]
        assert "deleted_by_user_id" not in row

    asyncio.run(_run())


def test_soft_delete_is_idempotent(fake_db):
    import asyncio

    async def _run():
        from routers.pricebook_suppliers import soft_delete_pricebook_supplier
        fake_db["suppliers"].docs = [
            _supp("s1", deleted_at="2026-08-09T00:00:00"),
        ]
        res = await soft_delete_pricebook_supplier(
            "s1", user=ADMIN, tenant=TENANT,
        )
        assert res.get("already_deleted") is True

    asyncio.run(_run())


# ─── Seed idempotency ───────────────────────────────────────────────────
def test_seed_inserts_13_rows_on_empty_tenant(fake_db):
    import asyncio

    async def _run():
        from services.pricebook_suppliers_seed import (
            seed_pricebook_suppliers_for_tenant,
        )
        fake_db["cats"].docs = [
            _cat("cat-pool", TENANT["id"], "Pool"),
            _cat("cat-land", TENANT["id"], "Landscaping"),
        ]
        n = await seed_pricebook_suppliers_for_tenant(TENANT["id"])
        assert n == 13
        assert len(fake_db["suppliers"].docs) == 13
        # 4 pool + 9 landscape split.
        pool = [d for d in fake_db["suppliers"].docs
                if d["income_category_id"] == "cat-pool"]
        land = [d for d in fake_db["suppliers"].docs
                if d["income_category_id"] == "cat-land"]
        assert len(pool) == 4
        assert len(land) == 9
        # All rows must be marked is_seed=True.
        assert all(d["is_seed"] is True for d in fake_db["suppliers"].docs)

    asyncio.run(_run())


def test_seed_is_idempotent_and_respects_prior_deletes(fake_db):
    """Second call inserts zero. Even if the operator has soft-deleted
    the entire seed set, we do NOT re-seed — presence of ANY row on
    the tenant is treated as 'already seeded, hands off'."""
    import asyncio

    async def _run():
        from services.pricebook_suppliers_seed import (
            seed_pricebook_suppliers_for_tenant,
        )
        fake_db["cats"].docs = [
            _cat("cat-pool", TENANT["id"], "Pool"),
            _cat("cat-land", TENANT["id"], "Landscaping"),
        ]
        n1 = await seed_pricebook_suppliers_for_tenant(TENANT["id"])
        assert n1 == 13
        # Simulate user soft-deleting every seed row.
        for d in fake_db["suppliers"].docs:
            d["deleted_at"] = "2026-08-10T00:00:00"
        n2 = await seed_pricebook_suppliers_for_tenant(TENANT["id"])
        assert n2 == 0
        assert len(fake_db["suppliers"].docs) == 13  # unchanged

    asyncio.run(_run())


def test_seed_skips_when_income_categories_missing(fake_db):
    """No Pool / Landscaping category → skip cleanly (return 0) rather
    than half-seed with a broken FK."""
    import asyncio

    async def _run():
        from services.pricebook_suppliers_seed import (
            seed_pricebook_suppliers_for_tenant,
        )
        # cats empty
        n = await seed_pricebook_suppliers_for_tenant(TENANT["id"])
        assert n == 0
        assert len(fake_db["suppliers"].docs) == 0

    asyncio.run(_run())
