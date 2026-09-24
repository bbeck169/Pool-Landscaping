"""P57 · Pricebook soft-delete tenant isolation tests (Feb-2026).

Coverage matrix:

  1. Bulk-delete tenant isolation
     * cannot_reach_other_tenant_items          — mixed batch
     * ids_all_cross_tenant_returns_empty_deleted — all-cross batch
     * selector_based_stays_scoped              — query_selector path
  2. Single-item DELETE tenant isolation
     * delete_item_cannot_reach_other_tenant
     * delete_pricebook_item_cannot_reach_other_tenant
  3. Primitive structural guards
     * requires_tenant_id                        — None + missing arg
     * raises_on_empty_string_tenant_id          — '' + '   '
     * resolve_helper_requires_tenant_id         — sibling helper

Uses the same self-contained fake-DB fixture pattern as
test_p56_pricebook_bulk_update_categories.py — no Mongo
dependency, motor-loop independent, xdist-safe.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════
# Fake DB scaffolding (same shape as P56 tests)
# ══════════════════════════════════════════════════════════════════
class _Cursor:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = list(rows)

    def limit(self, n: int):
        return _Cursor(self._rows[:n])

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _UpdateResult:
    def __init__(self, matched: int, modified: int):
        self.matched_count = matched
        self.modified_count = modified


class _Coll:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []
        self.update_calls: List[Dict[str, Any]] = []
        self.insert_calls: List[Dict[str, Any]] = []

    def find(self, filt=None, projection=None):
        filt = filt or {}
        return _Cursor([r for r in self.rows if _match(r, filt)])

    async def find_one(self, filt=None, projection=None):
        filt = filt or {}
        for r in self.rows:
            if _match(r, filt):
                return dict(r)
        return None

    async def count_documents(self, filt=None):
        filt = filt or {}
        return sum(1 for r in self.rows if _match(r, filt))

    async def update_one(self, filt, update):
        self.update_calls.append(
            {"op": "update_one", "filter": filt, "update": update},
        )
        matched = 0
        modified = 0
        for r in self.rows:
            if _match(r, filt):
                matched = 1
                if "$set" in update:
                    for k, v in update["$set"].items():
                        if r.get(k) != v:
                            r[k] = v
                            modified = 1
                break
        return _UpdateResult(matched=matched, modified=modified)


def _match(doc: Dict[str, Any], filt: Dict[str, Any]) -> bool:
    for k, v in filt.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        actual = doc.get(k)
        if isinstance(v, dict):
            for op, arg in v.items():
                if op == "$ne" and actual == arg:
                    return False
                if op == "$exists":
                    present = k in doc
                    if bool(arg) != present:
                        return False
                if op == "$regex":
                    import re
                    flags = re.IGNORECASE if v.get("$options") == "i" else 0
                    if actual is None or not re.search(arg, str(actual), flags):
                        return False
        else:
            if actual != v:
                return False
    return True


class _FakeDB:
    def __init__(self):
        self.items = _Coll()
        self.quotes = _Coll()
        self.estimates = _Coll()
        self.billing_plans = _Coll()

    def __getitem__(self, name):
        return getattr(self, name)


# ══════════════════════════════════════════════════════════════════
# Seed helpers
# ══════════════════════════════════════════════════════════════════
TID_A = "tenant-A"
TID_B = "tenant-B"


def _seed_item(fake: _FakeDB, iid: str, *,
                tenant_id: str, active: bool = True,
                category: str = "Pool") -> None:
    fake.items.rows.append({
        "id": iid, "tenant_id": tenant_id,
        "name": f"Item {iid}", "category": category,
        "unit_price": 10.0, "active": active,
    })


def _actor(tenant_id: str = TID_A) -> dict:
    return {"id": "u_admin_a", "role": "admin",
            "email": "admin@a.example",
            "tenant_id": tenant_id}


@pytest.fixture()
def env(monkeypatch):
    """Wire the fake DB into the router module. Returns
    ``(fake, handlers)`` — handlers is a tuple of the three
    entry-point functions under P57 scrutiny."""
    fake = _FakeDB()
    from routers import items as it
    monkeypatch.setattr(it, "db", fake)
    return fake, (
        it.delete_item,
        it.delete_pricebook_item,
        it.bulk_delete_pricebook,
    )


# ══════════════════════════════════════════════════════════════════
# 1. Bulk-delete tenant isolation (H7 flag fix · Commit 1)
# ══════════════════════════════════════════════════════════════════
def test_bulk_delete_cannot_reach_other_tenant_items(env):
    """Seed tenant A with items X,Y,Z; tenant B with P,Q,R. Admin
    from tenant A bulk-deletes ids=[X, P, R]. Assert: X deleted,
    P and R untouched. Response's failed[] contains P and R with
    honest-telemetry error."""
    fake, (_, _, bulk_delete_pricebook) = env
    _seed_item(fake, "X", tenant_id=TID_A)
    _seed_item(fake, "Y", tenant_id=TID_A)
    _seed_item(fake, "Z", tenant_id=TID_A)
    _seed_item(fake, "P", tenant_id=TID_B)
    _seed_item(fake, "Q", tenant_id=TID_B)
    _seed_item(fake, "R", tenant_id=TID_B)
    from routers.items import _PricebookBulkDeleteIn
    body = _PricebookBulkDeleteIn(ids=["X", "P", "R"])
    res = _run(bulk_delete_pricebook(body=body, user=_actor(TID_A)))
    assert res["ok"] is True
    assert res["deleted_count"] == 1
    assert res["deleted"] == ["X"]
    failed_ids = {f["id"] for f in res["failed"]}
    assert failed_ids == {"P", "R"}
    for f in res["failed"]:
        assert f["status_code"] == 404
        assert "not found" in str(f["reason"]).lower()
    # On-disk assertion — B items untouched.
    p = next(r for r in fake.items.rows if r["id"] == "P")
    r_row = next(r for r in fake.items.rows if r["id"] == "R")
    assert "deleted_at" not in p and "deleted_at" not in r_row
    # A item X actually soft-deleted.
    x = next(r for r in fake.items.rows if r["id"] == "X")
    assert x.get("deleted_at") is not None


def test_bulk_delete_ids_all_cross_tenant_returns_empty_deleted(env):
    """Tenant A admin sends only tenant B ids. Zero deletions,
    all in failed[]."""
    fake, (_, _, bulk_delete_pricebook) = env
    _seed_item(fake, "P", tenant_id=TID_B)
    _seed_item(fake, "Q", tenant_id=TID_B)
    from routers.items import _PricebookBulkDeleteIn
    body = _PricebookBulkDeleteIn(ids=["P", "Q"])
    res = _run(bulk_delete_pricebook(body=body, user=_actor(TID_A)))
    assert res["deleted_count"] == 0
    assert res["deleted"] == []
    assert {f["id"] for f in res["failed"]} == {"P", "Q"}
    # Neither tenant B item touched.
    for r in fake.items.rows:
        assert "deleted_at" not in r


def test_bulk_delete_selector_based_stays_scoped(env):
    """Selector-based bulk-delete via ``{"query_selector": {"active":
    true}}``. Tenant A admin should ONLY sweep tenant A rows even
    though tenant B has plenty of matching active items too."""
    fake, (_, _, bulk_delete_pricebook) = env
    for i in range(3):
        _seed_item(fake, f"A{i}", tenant_id=TID_A, active=True)
    for i in range(3):
        _seed_item(fake, f"B{i}", tenant_id=TID_B, active=True)
    from routers.items import _PricebookBulkDeleteIn
    body = _PricebookBulkDeleteIn(
        query_selector={"active": True},
    )
    res = _run(bulk_delete_pricebook(body=body, user=_actor(TID_A)))
    # Only 3 A items deleted; zero B items enumerated.
    assert res["deleted_count"] == 3
    assert {d for d in res["deleted"]} == {"A0", "A1", "A2"}
    # Confirm B rows completely untouched (defence-in-depth check
    # against a partially-scoped enumerate query).
    for r in fake.items.rows:
        if r["tenant_id"] == TID_B:
            assert "deleted_at" not in r


# ══════════════════════════════════════════════════════════════════
# 2. Single-item DELETE tenant isolation (H7 expansion · Commit 1)
# ══════════════════════════════════════════════════════════════════
def test_delete_item_cannot_reach_other_tenant(env):
    """`DELETE /api/items/{iid}` on a cross-tenant id must hit
    the not-found branch — MOST IMPORTANT SECURITY TEST: a
    tenant-A admin should NOT be able to soft-delete a tenant-B
    row just by knowing its uuid."""
    fake, (delete_item, _, _) = env
    _seed_item(fake, "B-item-uuid", tenant_id=TID_B)
    with pytest.raises(HTTPException) as exc_info:
        _run(delete_item(iid="B-item-uuid", user=_actor(TID_A)))
    assert exc_info.value.status_code == 404
    # On-disk assertion — tenant B row completely untouched.
    b = next(r for r in fake.items.rows if r["id"] == "B-item-uuid")
    assert "deleted_at" not in b


def test_delete_pricebook_item_cannot_reach_other_tenant(env):
    """Alias endpoint `DELETE /api/pricebook/{iid}` — same fix,
    same test. Both endpoints route to _soft_delete_item and both
    were pre-P57 vulnerable."""
    fake, (_, delete_pricebook_item, _) = env
    _seed_item(fake, "B-alias-uuid", tenant_id=TID_B)
    with pytest.raises(HTTPException) as exc_info:
        _run(delete_pricebook_item(
            iid="B-alias-uuid", user=_actor(TID_A),
        ))
    assert exc_info.value.status_code == 404
    b = next(r for r in fake.items.rows if r["id"] == "B-alias-uuid")
    assert "deleted_at" not in b


def test_delete_item_happy_path_still_works(env):
    """Same-tenant delete happy path must still succeed. Guards
    against the tightening accidentally breaking legitimate
    tenant-scoped deletes."""
    fake, (delete_item, _, _) = env
    _seed_item(fake, "A-item-uuid", tenant_id=TID_A)
    result = _run(delete_item(iid="A-item-uuid", user=_actor(TID_A)))
    assert result["ok"] is True
    assert result["soft_deleted"] is True
    row = next(r for r in fake.items.rows if r["id"] == "A-item-uuid")
    assert row.get("deleted_at") is not None


# ══════════════════════════════════════════════════════════════════
# 3. Primitive structural guards (signature tightening · Commit 2)
# ══════════════════════════════════════════════════════════════════
def test_soft_delete_item_requires_tenant_id():
    """Positional-required tenant_id — calling with only 2 args
    must raise TypeError (Python signature enforcement)."""
    from routers.items import _soft_delete_item
    with pytest.raises(TypeError):
        _run(_soft_delete_item("some-id", "some-user"))


def test_soft_delete_item_raises_on_none_tenant_id():
    """Explicit `None` at the 3rd positional raises ValueError
    with a diagnostic that points reviewers at the correct
    remediation (introduce a distinct helper, don't relax the
    guard)."""
    from routers.items import _soft_delete_item
    with pytest.raises(ValueError) as exc_info:
        _run(_soft_delete_item("some-id", "some-user", None))
    msg = str(exc_info.value)
    assert "non-empty tenant_id" in msg
    assert "do NOT relax this guard" in msg


def test_soft_delete_item_raises_on_empty_string_tenant_id():
    """Empty-string tenant_id was the Q3 subtle-silent-pass state
    on the pre-P57 truthy guard. Tightening now rejects it
    unambiguously."""
    from routers.items import _soft_delete_item
    with pytest.raises(ValueError) as exc_info:
        _run(_soft_delete_item("some-id", "some-user", ""))
    assert "non-empty tenant_id" in str(exc_info.value)


def test_soft_delete_item_raises_on_whitespace_tenant_id():
    """Whitespace-only tenant_id caught by the `.strip()` check
    in the ValueError guard. Prevents an accidental caller from
    slipping a padded string past the primitive."""
    from routers.items import _soft_delete_item
    with pytest.raises(ValueError) as exc_info:
        _run(_soft_delete_item("some-id", "some-user", "   "))
    assert "non-empty tenant_id" in str(exc_info.value)


def test_resolve_pricebook_ids_requires_tenant_id():
    """Sibling helper tightening (`_resolve_pricebook_ids`) —
    same non-empty-string invariant on the enumerate path so
    a future direct caller of the helper can't bypass the
    primitive's tightening."""
    from routers.items import _resolve_pricebook_ids
    with pytest.raises(ValueError) as exc_info:
        _run(_resolve_pricebook_ids({}, [], None))
    assert "non-empty tenant_id" in str(exc_info.value)
    with pytest.raises(ValueError):
        _run(_resolve_pricebook_ids({}, [], ""))
    with pytest.raises(ValueError):
        _run(_resolve_pricebook_ids({}, [], "   "))
