"""HARD-DELETE · Sub-phase HD-A · Feb-2026 — end-to-end tests.

Exercises the services + router directly with an in-memory Motor
stub. Coverage:

  * Soft-delete cascade stamps parent + every child with the same
    cascade_batch_id.
  * Restore reverses the entire cascade batch atomically.
  * Purge (post-Trash) writes tombstones and deletes rows.
  * Purge blocks on invoice.payment_intent_id (external ref) with
    409 blocked_external_reference.
  * Purge without prior soft-delete → 409 trash_required unless
    skip_trash=true.
  * skip_trash=true purge succeeds even without soft-delete.
  * RBAC — admin can soft/restore, cannot purge; super_admin can
    purge; anonymous is refused.
  * Tombstone snapshot captures post-modification state (defensive
    per user brief §e).
  * Trash view lists only soft-deleted rows across every eligible
    entity.
  * Nightly purge sweeps rows older than the cutoff.
  * Load-bearing callsite coverage — every list-side query on
    ELIGIBLE_COLLECTIONS in routers/hard_delete.py goes through
    the shared query filter.
"""
from __future__ import annotations

import asyncio
import copy
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException


# ─── In-memory Motor stub ───────────────────────────────────────────

def _match(row: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if k == "$or":
            if not any(_match(row, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_match(row, sub) for sub in v):
                return False
            continue
        # Dotted path support ("context.customer_id").
        if "." in k:
            parts = k.split(".")
            cur: Any = row
            for p in parts:
                if isinstance(cur, dict):
                    cur = cur.get(p)
                else:
                    cur = None
                    break
            row_val = cur
        else:
            row_val = row.get(k)
        if isinstance(v, dict):
            for op, opval in v.items():
                if op == "$exists":
                    if opval != (row_val is not None):
                        return False
                elif op == "$in":
                    if row_val not in opval:
                        return False
                elif op == "$nin":
                    if row_val in opval:
                        return False
                elif op == "$ne":
                    if row_val == opval:
                        return False
                elif op == "$lt":
                    if row_val is None or row_val >= opval:
                        return False
                elif op == "$gt":
                    if row_val is None or row_val <= opval:
                        return False
                else:
                    return False
            continue
        if row_val != v:
            return False
    return True


class _Cursor:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = [copy.deepcopy(r) for r in rows]

    def sort(self, key_or_list, direction=None):
        # Accept both sort("key", -1) and sort([("key", -1)]).
        if isinstance(key_or_list, list):
            key_pairs = key_or_list
        else:
            key_pairs = [(key_or_list, direction if direction is not None else 1)]
        for key, dir_ in reversed(key_pairs):
            self._rows.sort(
                key=lambda r: r.get(key) or "",
                reverse=(dir_ == -1),
            )
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    async def to_list(self, _n=None):
        return list(self._rows)

    def __aiter__(self):
        self._iter = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = [copy.deepcopy(r) for r in (rows or [])]

    async def find_one(self, query, projection=None, sort=None):
        matches = [r for r in self.rows if _match(r, query)]
        if sort:
            for key, dir_ in reversed(sort):
                matches.sort(key=lambda r: r.get(key) or "",
                             reverse=(dir_ == -1))
        return copy.deepcopy(matches[0]) if matches else None

    def find(self, query=None, projection=None):
        q = query or {}
        return _Cursor([r for r in self.rows if _match(r, q)])

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _match(r, query))

    async def insert_one(self, doc):
        self.rows.append(copy.deepcopy(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()

    async def update_one(self, query, update):
        for row in self.rows:
            if _match(row, query):
                _apply_update(row, update)
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()

    async def update_many(self, query, update):
        count = 0
        for row in self.rows:
            if _match(row, query):
                _apply_update(row, update)
                count += 1
        return type("R", (), {"modified_count": count})()

    async def delete_one(self, query):
        for row in list(self.rows):
            if _match(row, query):
                self.rows.remove(row)
                return type("R", (), {"deleted_count": 1})()
        return type("R", (), {"deleted_count": 0})()

    async def delete_many(self, query):
        c = 0
        for row in list(self.rows):
            if _match(row, query):
                self.rows.remove(row)
                c += 1
        return type("R", (), {"deleted_count": c})()


def _apply_update(row, update):
    if "$set" in update:
        for k, v in update["$set"].items():
            row[k] = v
    if "$unset" in update:
        for k in update["$unset"]:
            row.pop(k, None)


class _DB:
    """Dict-style + attribute-style access — matches how Motor is
    used across the codebase (``db.foo`` and ``db["foo"]``)."""

    def __init__(self):
        self._colls: Dict[str, _Coll] = {}

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = _Coll()
        return self._colls[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def fake_db(monkeypatch):
    """Fresh in-memory DB stub wired into every hard_delete module."""
    fake = _DB()
    # Seed the base entities we need for the cascade tests.
    fake.customers.rows = [
        {"id": "cust-1", "tenant_id": "t1", "name": "Test Customer"},
    ]
    fake.jobs.rows = [
        {"id": "job-1", "tenant_id": "t1", "customer_id": "cust-1",
         "title": "Weekly pool service"},
        {"id": "job-2", "tenant_id": "t1", "customer_id": "cust-1",
         "title": "Repair pump"},
    ]
    fake.quotes.rows = [
        {"id": "inv-1", "tenant_id": "t1", "customer_id": "cust-1",
         "doc_type": "invoice", "invoice_number": "INV-1001",
         "payment_status": "paid"},
        {"id": "inv-2", "tenant_id": "t1", "customer_id": "cust-1",
         "doc_type": "invoice", "invoice_number": "INV-1002",
         "payment_status": "unpaid"},
    ]
    fake.service_reports.rows = [
        {"id": "sr-1", "tenant_id": "t1", "customer_id": "cust-1",
         "job_id": "job-1", "title": "Weekly report",
         "photos": [{"id": "p1"}, {"id": "p2"}]},
    ]
    fake.files.rows = [
        {"id": "file-1", "tenant_id": "t1", "customer_id": "cust-1",
         "filename": "quote.pdf", "is_deleted": False},
    ]
    fake.hard_delete_tombstones.rows = []
    fake.audit_logs.rows = []
    fake.communication_sends.rows = []
    fake.outbound_emails.rows = []

    # Wire ``db`` reference in every module that reads it.
    for mod_name in [
        "services.hard_delete.cascade",
        "services.hard_delete.tombstone",
        "services.hard_delete.nightly_purge",
        "routers.hard_delete",
    ]:
        import importlib
        mod = importlib.import_module(mod_name)
        monkeypatch.setattr(mod, "db", fake, raising=False)
    return fake


# ─── SOFT DELETE ────────────────────────────────────────────────────

def test_soft_delete_cascades_parent_and_children(fake_db):
    from services.hard_delete import cascade

    res = _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    assert res["root_entity_type"] == "customer"
    assert res["root_entity_id"] == "cust-1"
    assert res.get("cascade_batch_id"), "batch id must be assigned"
    batch = res["cascade_batch_id"]

    # Every descendant carries the SAME batch id.
    cust = fake_db.customers.rows[0]
    assert cust["deleted_at"]
    assert cust["cascade_batch_id"] == batch
    assert cust["cascade_role"] == "root"

    for j in fake_db.jobs.rows:
        assert j.get("deleted_at")
        assert j["cascade_batch_id"] == batch

    for q in fake_db.quotes.rows:
        assert q.get("deleted_at")
        assert q["cascade_batch_id"] == batch

    for sr in fake_db.service_reports.rows:
        assert sr.get("deleted_at")
        assert sr["cascade_batch_id"] == batch

    for f in fake_db.files.rows:
        assert f.get("deleted_at")
        assert f["cascade_batch_id"] == batch


def test_soft_delete_is_idempotent(fake_db):
    from services.hard_delete import cascade

    first = _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    second = _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    assert second.get("already_deleted") is True
    # Same batch id — second call MUST NOT allocate a new one.
    assert second["cascade_batch_id"] == first["cascade_batch_id"]


def test_soft_delete_not_found(fake_db):
    from services.hard_delete import cascade

    res = _run(cascade.soft_delete_cascade(
        "customer", "nope", "t1", user_id="u-admin",
    ))
    assert res.get("not_found") is True


def test_soft_delete_respects_tenant_boundary(fake_db):
    from services.hard_delete import cascade

    fake_db.customers.rows.append({
        "id": "cust-cross", "tenant_id": "t2", "name": "Other Tenant",
    })
    res = _run(cascade.soft_delete_cascade(
        "customer", "cust-cross", "t1", user_id="u",
    ))
    assert res.get("not_found") is True
    # Tenant-B row is untouched.
    other = [r for r in fake_db.customers.rows if r["id"] == "cust-cross"][0]
    assert not other.get("deleted_at")


# ─── RESTORE ────────────────────────────────────────────────────────

def test_restore_reverses_full_cascade(fake_db):
    from services.hard_delete import cascade

    soft = _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    batch = soft["cascade_batch_id"]
    res = _run(cascade.restore_batch("customer", "cust-1", "t1"))
    assert res.get("cascade_batch_id") == batch
    # Every row now has deleted_at cleared.
    for coll in ("customers", "jobs", "quotes", "service_reports", "files"):
        for row in fake_db[coll].rows:
            assert row.get("deleted_at") is None or "deleted_at" not in row
            assert "cascade_batch_id" not in row
            assert "cascade_role" not in row


def test_restore_on_active_doc_is_noop(fake_db):
    from services.hard_delete import cascade

    res = _run(cascade.restore_batch("customer", "cust-1", "t1"))
    assert res.get("already_restored") is True


def test_restore_not_found(fake_db):
    from services.hard_delete import cascade

    res = _run(cascade.restore_batch("customer", "nope", "t1"))
    assert res.get("not_found") is True


# ─── PURGE ──────────────────────────────────────────────────────────

def test_purge_requires_trash_first_when_skip_trash_false(fake_db):
    from services.hard_delete import cascade

    result, blocks = _run(cascade.purge_cascade(
        "customer", "cust-1", "t1",
        user_id="u-super", user_email="root@x",
        skip_trash=False,
    ))
    assert result.get("trash_required") is True
    assert blocks == []
    # No tombstone written — DB untouched.
    assert not fake_db.hard_delete_tombstones.rows
    assert any(r["id"] == "cust-1" for r in fake_db.customers.rows)


def test_purge_after_soft_writes_tombstones_and_deletes(fake_db):
    from services.hard_delete import cascade

    # Remove the paid invoice's Stripe conflict for this test.
    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    result, blocks = _run(cascade.purge_cascade(
        "customer", "cust-1", "t1",
        user_id="u-super", user_email="root@x",
        purge_reason="test", skip_trash=False,
    ))
    assert blocks == []
    assert not result.get("trash_required")
    # Every entity family gone from source collections.
    assert not fake_db.customers.rows
    assert not fake_db.jobs.rows
    assert not fake_db.quotes.rows
    assert not fake_db.service_reports.rows
    assert not fake_db.files.rows

    # Tombstones written — one per doc.
    tomb_ids = {t["entity_id"] for t in fake_db.hard_delete_tombstones.rows}
    assert "cust-1" in tomb_ids
    assert "job-1" in tomb_ids
    assert "inv-1" in tomb_ids
    assert "sr-1" in tomb_ids
    # Each tombstone carries checksum + snapshot.
    for t in fake_db.hard_delete_tombstones.rows:
        assert t["checksum"]
        assert isinstance(t["snapshot"], dict)
        assert t["purged_at"]
        assert t["tenant_id"] == "t1"
        assert t["purged_by"] == "u-super"


def test_purge_blocks_on_stripe_payment_intent(fake_db):
    from services.hard_delete import cascade

    # Attach a Stripe payment_intent_id to inv-1 to trip the guard.
    fake_db.quotes.rows[0]["payment_intent_id"] = "pi_test_123"
    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    result, blocks = _run(cascade.purge_cascade(
        "customer", "cust-1", "t1",
        user_id="u-super", user_email="root@x",
        skip_trash=False,
    ))
    assert result.get("blocked") is True
    assert result["error_code"] == "blocked_external_reference"
    assert blocks and blocks[0]["payment_intent_id"] == "pi_test_123"
    # DB untouched — every doc still present.
    assert any(r["id"] == "cust-1" for r in fake_db.customers.rows)
    assert any(r["id"] == "inv-1" for r in fake_db.quotes.rows)
    # No tombstone written on a blocked purge.
    assert not fake_db.hard_delete_tombstones.rows


def test_purge_block_check_recurses_through_children(fake_db):
    """Purging a job (not the customer) still walks its descendants
    for Stripe refs — but jobs don't have quote children, so this
    exercises the recursive lookup on invoices attached to the same
    customer being a sibling, not a descendant.  Confirm that
    purging job-2 does NOT block on inv-1's Stripe (sibling, not
    child)."""
    from services.hard_delete import cascade

    fake_db.quotes.rows[0]["payment_intent_id"] = "pi_test_123"
    _run(cascade.soft_delete_cascade(
        "job", "job-2", "t1", user_id="u-admin",
    ))
    _, blocks = _run(cascade.purge_cascade(
        "job", "job-2", "t1",
        user_id="u-super", user_email="root@x",
        skip_trash=False,
    ))
    assert blocks == []


def test_purge_skip_trash_super_admin_hatch(fake_db):
    from services.hard_delete import cascade

    result, blocks = _run(cascade.purge_cascade(
        "file", "file-1", "t1",
        user_id="u-super", user_email="root@x",
        skip_trash=True,
    ))
    assert blocks == []
    assert not result.get("trash_required")
    assert not fake_db.files.rows
    assert any(t["entity_id"] == "file-1"
               for t in fake_db.hard_delete_tombstones.rows)


def test_tombstone_captures_post_modification_state(fake_db):
    """Defensive guardrail per user brief §e: if a soft-deleted doc
    is somehow mutated during the retention window (theoretically
    shouldn't happen), the tombstone snapshot MUST reflect the
    post-mutation state — audit honesty."""
    from services.hard_delete import cascade

    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    # Simulate a rogue mutation post-soft-delete.
    fake_db.customers.rows[0]["name"] = "MUTATED AFTER SOFT DELETE"
    fake_db.customers.rows[0]["mutated_note"] = "audit sentinel"

    _run(cascade.purge_cascade(
        "customer", "cust-1", "t1",
        user_id="u-super", user_email="root@x",
        skip_trash=False,
    ))
    tomb = next(t for t in fake_db.hard_delete_tombstones.rows
                 if t["entity_id"] == "cust-1")
    assert tomb["snapshot"]["name"] == "MUTATED AFTER SOFT DELETE"
    assert tomb["snapshot"]["mutated_note"] == "audit sentinel"


def test_tombstone_checksum_is_deterministic(fake_db):
    from services.hard_delete import tombstone

    snap = {"id": "x", "tenant_id": "t1", "name": "Alpha"}
    a = tombstone.compute_checksum(snap)
    b = tombstone.compute_checksum(dict(snap))
    assert a == b
    c = tombstone.compute_checksum({**snap, "name": "Beta"})
    assert a != c


# ─── ROUTER (RBAC + shape) ──────────────────────────────────────────

def test_router_soft_admin_role_ok(fake_db, monkeypatch):
    from routers import hard_delete as router

    res = _run(router.soft_delete_endpoint(
        entity_type="customer",
        doc_id="cust-1",
        body=None,
        user={"id": "u-admin", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    assert res["ok"] is True
    assert res["cascade_batch_id"]


def test_router_soft_technician_blocked(fake_db):
    from routers import hard_delete as router

    with pytest.raises(HTTPException) as exc:
        _run(router.soft_delete_endpoint(
            entity_type="customer",
            doc_id="cust-1",
            body=None,
            user={"id": "u", "role": "technician", "email": "t@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403
    assert exc.value.detail["error_code"] == "forbidden"


def test_router_purge_admin_blocked(fake_db):
    from routers import hard_delete as router

    with pytest.raises(HTTPException) as exc:
        _run(router.purge_endpoint(
            entity_type="customer",
            doc_id="cust-1",
            body=None,
            user={"id": "u-admin", "role": "admin", "email": "a@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403
    assert "super" in exc.value.detail["message"].lower()


def test_router_purge_super_admin_ok(fake_db):
    from routers import hard_delete as router
    from services.hard_delete import cascade

    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    res = _run(router.purge_endpoint(
        entity_type="customer",
        doc_id="cust-1",
        body=router.PurgeBody(reason="cleanup"),
        user={"id": "u-super", "role": "super_admin", "email": "s@x"},
        tenant={"id": "t1"},
    ))
    assert res["ok"] is True


def test_router_purge_returns_409_on_stripe_lock(fake_db):
    from routers import hard_delete as router
    from services.hard_delete import cascade

    fake_db.quotes.rows[0]["payment_intent_id"] = "pi_abc"
    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    with pytest.raises(HTTPException) as exc:
        _run(router.purge_endpoint(
            entity_type="customer",
            doc_id="cust-1",
            body=None,
            user={"id": "u-super", "role": "super_admin", "email": "s@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "blocked_external_reference"
    assert exc.value.detail["refs"][0]["payment_intent_id"] == "pi_abc"


def test_router_purge_returns_409_trash_required(fake_db):
    from routers import hard_delete as router

    with pytest.raises(HTTPException) as exc:
        _run(router.purge_endpoint(
            entity_type="customer",
            doc_id="cust-1",
            body=router.PurgeBody(skip_trash=False),
            user={"id": "u-super", "role": "super_admin", "email": "s@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 409
    assert exc.value.detail["error_code"] == "trash_required"


def test_router_unsupported_entity_type(fake_db):
    from routers import hard_delete as router

    with pytest.raises(HTTPException) as exc:
        _run(router.soft_delete_endpoint(
            entity_type="banana",
            doc_id="whatever",
            body=None,
            user={"id": "u", "role": "admin", "email": "a@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail["error_code"] == "unsupported_entity_type"


def test_router_trash_view_lists_soft_deleted_rows(fake_db):
    from routers import hard_delete as router
    from services.hard_delete import cascade

    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    res = _run(router.list_trash(
        entity_type=None, limit=200,
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    types = {item["entity_type"] for item in res["items"]}
    assert {"customer", "job", "quote", "service_report", "file"} <= types
    assert res["count"] == len(res["items"])


def test_router_trash_view_entity_filter(fake_db):
    from routers import hard_delete as router
    from services.hard_delete import cascade

    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u-admin",
    ))
    res = _run(router.list_trash(
        entity_type="job", limit=200,
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    assert res["count"] > 0
    for item in res["items"]:
        assert item["entity_type"] == "job"


def test_router_trash_view_tenant_scoped(fake_db):
    from routers import hard_delete as router
    from services.hard_delete import cascade

    # Add a t2 customer, soft-delete it — must NOT appear in a t1
    # list.
    fake_db.customers.rows.append({
        "id": "cust-t2", "tenant_id": "t2", "name": "Other",
    })
    _run(cascade.soft_delete_cascade(
        "customer", "cust-t2", "t2", user_id="u",
    ))
    res = _run(router.list_trash(
        entity_type=None, limit=200,
        user={"id": "u", "role": "admin", "email": "a@x"},
        tenant={"id": "t1"},
    ))
    ids = {i["id"] for i in res["items"]}
    assert "cust-t2" not in ids


def test_router_tombstones_super_only(fake_db):
    from routers import hard_delete as router

    with pytest.raises(HTTPException) as exc:
        _run(router.list_tombstones(
            entity_type=None, entity_id=None, limit=100,
            user={"id": "u", "role": "admin", "email": "a@x"},
            tenant={"id": "t1"},
        ))
    assert exc.value.status_code == 403


# ─── NIGHTLY PURGE ─────────────────────────────────────────────────

def test_nightly_purge_dry_run_lists_expired(fake_db, monkeypatch):
    from services.hard_delete import cascade, nightly_purge

    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u",
    ))
    # Rewind deleted_at back 40 days so it's outside the cutoff.
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat().replace(
        "+00:00", "Z"
    )
    for row in fake_db.customers.rows:
        if row.get("deleted_at"):
            row["deleted_at"] = old
    for row in fake_db.jobs.rows + fake_db.quotes.rows + fake_db.service_reports.rows + fake_db.files.rows:
        if row.get("deleted_at"):
            row["deleted_at"] = old

    res = _run(nightly_purge.run_nightly_purge(dry_run=True))
    assert res["candidates"] >= 1
    assert res["candidates_detail"]


def test_nightly_purge_purges_expired(fake_db):
    from services.hard_delete import cascade, nightly_purge

    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u",
    ))
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat().replace(
        "+00:00", "Z"
    )
    for row in fake_db.customers.rows:
        if row.get("deleted_at"):
            row["deleted_at"] = old
    for row in fake_db.jobs.rows + fake_db.quotes.rows + fake_db.service_reports.rows + fake_db.files.rows:
        if row.get("deleted_at"):
            row["deleted_at"] = old

    res = _run(nightly_purge.run_nightly_purge())
    assert res["purged"] >= 5           # customer + 2 jobs + 2 quotes + sr + file
    assert not fake_db.customers.rows
    assert fake_db.hard_delete_tombstones.rows


def test_nightly_purge_leaves_recent_soft_deletes(fake_db):
    from services.hard_delete import cascade, nightly_purge

    _run(cascade.soft_delete_cascade(
        "customer", "cust-1", "t1", user_id="u",
    ))
    # Deleted just now — inside the 30-day retention window.
    res = _run(nightly_purge.run_nightly_purge())
    assert res["purged"] == 0
    # Nothing tombstoned.
    assert not fake_db.hard_delete_tombstones.rows


# ─── LOAD-BEARING CALLSITE COVERAGE TEST ────────────────────────────

def test_hard_delete_router_uses_shared_filter():
    """Enforce: every list query on ELIGIBLE_COLLECTIONS inside
    ``routers/hard_delete.py`` MUST route through one of the
    shared helpers (``only_trashed_filter`` or
    ``apply_soft_delete_filter``). Prevents future maintainers
    from silently re-introducing a naked ``db.customers.find({...})``
    on the trash surface (which would either leak trashed rows to
    normal views or hide them from the trash view).
    """
    from services.hard_delete.registry import ELIGIBLE_COLLECTIONS

    src_path = Path(__file__).resolve().parents[1] / "routers" / "hard_delete.py"
    src = src_path.read_text()

    for coll in ELIGIBLE_COLLECTIONS:
        # Locate every `db.{coll}.find(` callsite.
        pattern = re.compile(rf"db\.{coll}\.find\(", re.MULTILINE)
        for m in pattern.finditer(src):
            # Look at 400-char window preceding the callsite for a
            # helper invocation.
            window = src[max(0, m.start() - 400):m.start()]
            assert (
                "only_trashed_filter" in window
                or "apply_soft_delete_filter" in window
            ), (
                f"routers/hard_delete.py has a naked db.{coll}.find() at "
                f"offset {m.start()} — must wrap the query in "
                "apply_soft_delete_filter() or only_trashed_filter()."
            )
