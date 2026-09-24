"""P56 · Pricebook Bulk-Update-Categories endpoint behaviour tests
(Feb-2026).

Coverage matches the P54 test matrix (partial-payload semantics,
payload validation, cross-tenant policy, P55 sync integration,
audit integration, regression guard) plus the P56-specific
service+income policy test (Q5/A per-row honest telemetry).

Uses the same self-contained fake-DB fixture pattern as the P54
suite — no Mongo dependency, runs in under a second, motor-loop
independent. The FastAPI handler is invoked directly (not via
HTTP) so tests are xdist-safe.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════
# Fake DB scaffolding — same shape as test_p55_category_sync.py's
# fake so any future refactor stays lockstep.
# ══════════════════════════════════════════════════════════════════
class _Cursor:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = list(rows)

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, length=None):
        return list(self._rows)


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

    async def insert_one(self, doc):
        self.insert_calls.append({"op": "insert_one", "doc": dict(doc)})
        self.rows.append(dict(doc))
        return type("Ins", (), {"inserted_id": doc.get("id")})()


def _match(doc: Dict[str, Any], filt: Dict[str, Any]) -> bool:
    for k, v in filt.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_match(doc, sub) for sub in v):
                return False
            continue
        actual = doc.get(k)
        if isinstance(v, dict):
            for op, arg in v.items():
                if op == "$eq" and actual != arg:
                    return False
                if op == "$ne" and actual == arg:
                    return False
                if op == "$in" and actual not in arg:
                    return False
                if op == "$exists":
                    present = k in doc
                    if bool(arg) != present:
                        return False
        else:
            if actual != v:
                return False
    return True


class _FakeDB:
    def __init__(self):
        self.items = _Coll()
        self.income_categories = _Coll()
        self.service_categories = _Coll()
        self.audit_log = _Coll()          # singular — matches items.py wire
        # For the fake-monkeypatched sync spy (no real Mongo touch).

    def __getitem__(self, name):
        return getattr(self, name)


# ══════════════════════════════════════════════════════════════════
# Seed helpers
# ══════════════════════════════════════════════════════════════════
TID_A = "t-A"
TID_B = "t-B"
INC_ID = "inc-uuid-1"
INC_ID_2 = "inc-uuid-2"
SVC_ID = "svc-uuid-1"
SVC_ID_2 = "svc-uuid-2"


def _seed_categories(fake: _FakeDB, tenant_id: str = TID_A) -> None:
    fake.income_categories.rows.extend([
        {"id": INC_ID, "tenant_id": tenant_id,
          "name": "Pool", "is_archived": False},
        {"id": INC_ID_2, "tenant_id": tenant_id,
          "name": "Landscape", "is_archived": False},
    ])
    fake.service_categories.rows.extend([
        {"id": SVC_ID, "tenant_id": tenant_id,
          "name": "Weekly Service", "is_archived": False},
        {"id": SVC_ID_2, "tenant_id": tenant_id,
          "name": "Monthly Service", "is_archived": False},
    ])


def _seed_items(
    fake: _FakeDB,
    count: int = 3,
    *,
    tenant_id: str = TID_A,
    item_type: str = "product",
    with_service: Optional[str] = None,
    with_income: Optional[str] = None,
    prefix: str = "pb",
) -> List[str]:
    ids = []
    for i in range(count):
        iid = f"{prefix}-{tenant_id}-{i}"
        row: Dict[str, Any] = {
            "id": iid, "tenant_id": tenant_id,
            "name": f"Item {i}", "unit_price": 55.0,
            "item_type": item_type,
        }
        if with_service:
            row["service_category_id"] = with_service
            row["service_category_name"] = "Weekly Service"
        if with_income:
            row["income_category_id"] = with_income
            row["income_category_name"] = "Pool"
            row["category"] = with_income        # legacy alias
        fake.items.rows.append(row)
        ids.append(iid)
    return ids


# ══════════════════════════════════════════════════════════════════
# Sync spy
# ══════════════════════════════════════════════════════════════════
class _SyncSpy:
    """Records every call to
    ``sync_pricebook_to_invoice_lines`` so tests can assert call
    count + args + origin marker."""

    def __init__(self, raise_for_ids: Optional[List[str]] = None):
        self.calls: List[Dict[str, Any]] = []
        self.raise_for_ids = set(raise_for_ids or [])

    async def __call__(self, *, tenant_id, item_id,
                       origin, actor_id=None, **kwargs):
        self.calls.append({
            "tenant_id": tenant_id, "item_id": item_id,
            "origin": origin, "actor_id": actor_id,
            **kwargs,
        })
        if item_id in self.raise_for_ids:
            from services.category_sync import CategorySyncNameLookupError
            raise CategorySyncNameLookupError(
                category_id="phantom", collection="income_categories",
            )
        from services.category_sync import SyncResult
        return SyncResult(updated_count=2, skipped_paid_count=0)


@pytest.fixture()
def env(monkeypatch):
    """Wire the fake DB + a sync spy into the router module.

    Returns ``(fake_db, sync_spy, handler)`` — the handler is
    ``bulk_update_categories_pricebook`` from ``routers.items``.
    """
    fake = _FakeDB()
    spy = _SyncSpy()
    from routers import items as it
    from services import category_sync as cs
    monkeypatch.setattr(it, "db", fake)
    monkeypatch.setattr(cs, "db", fake)
    monkeypatch.setattr(
        cs, "sync_pricebook_to_invoice_lines", spy,
    )
    return fake, spy, it.bulk_update_categories_pricebook


def _actor():
    return {"id": "u_admin", "role": "admin",
            "email": "a@x", "tenant_id": TID_A}


# ══════════════════════════════════════════════════════════════════
# 1. Partial-payload semantics
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_service_only_income_unchanged(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 2,
                      with_service=SVC_ID, with_income=INC_ID)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID_2,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 2
    assert result["failed"] == 0
    for item in fake.items.rows:
        assert item["service_category_id"] == SVC_ID_2
        assert item["service_category_name"] == "Monthly Service"
        # income UNCHANGED
        assert item["income_category_id"] == INC_ID
        assert item["income_category_name"] == "Pool"
        assert item["category"] == INC_ID          # legacy alias untouched


def test_bulk_update_income_only_service_unchanged(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 2,
                      with_service=SVC_ID, with_income=INC_ID)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, income_category_id=INC_ID_2,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 2
    for item in fake.items.rows:
        assert item["income_category_id"] == INC_ID_2
        assert item["income_category_name"] == "Landscape"
        # legacy scalar in lockstep with income
        assert item["category"] == INC_ID_2
        # service UNCHANGED
        assert item["service_category_id"] == SVC_ID


def test_bulk_update_both_fields(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 2,
                      with_service=SVC_ID, with_income=INC_ID)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids,
        service_category_id=SVC_ID_2, income_category_id=INC_ID_2,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 2
    for item in fake.items.rows:
        assert item["service_category_id"] == SVC_ID_2
        assert item["income_category_id"] == INC_ID_2


# ══════════════════════════════════════════════════════════════════
# 2. Payload validation
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_neither_field_returns_400(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 1)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(ids=ids)
    with pytest.raises(HTTPException) as exc_info:
        _run(handler(body=body, user=_actor()))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "no_category_fields_set"
    assert fake.items.update_calls == []
    assert spy.calls == []


def test_bulk_update_unknown_category_id_returns_422(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 1)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, service_category_id="does-not-exist-uuid",
    )
    with pytest.raises(HTTPException) as exc_info:
        _run(handler(body=body, user=_actor()))
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert detail["code"] == "service_category_invalid"
    assert detail["field"] == "service_category_id"
    assert detail["attempted"] == "does-not-exist-uuid"
    assert detail["collection"] == "service_categories"


def test_bulk_update_more_than_100_ids_returns_400(env):
    fake, spy, handler = env
    _seed_categories(fake)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    ids = [f"pb-{i}" for i in range(101)]
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,
    )
    with pytest.raises(HTTPException) as exc_info:
        _run(handler(body=body, user=_actor()))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "batch_too_large"
    assert exc_info.value.detail["max"] == 100
    assert exc_info.value.detail["received"] == 101


def test_bulk_update_empty_ids_returns_400(env):
    fake, spy, handler = env
    _seed_categories(fake)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=[], service_category_id=SVC_ID,
    )
    with pytest.raises(HTTPException) as exc_info:
        _run(handler(body=body, user=_actor()))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "ids_empty"


# ══════════════════════════════════════════════════════════════════
# 3. Cross-tenant policy — Q2/A honest telemetry
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_cross_tenant_ids_appear_in_failed_results(env):
    fake, spy, handler = env
    _seed_categories(fake, tenant_id=TID_A)
    _seed_categories(fake, tenant_id=TID_B)
    a_ids = _seed_items(fake, 2, tenant_id=TID_A, prefix="pb-a")
    b_ids = _seed_items(fake, 2, tenant_id=TID_B, prefix="pb-b")
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=a_ids + b_ids,
        service_category_id=SVC_ID,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 2
    assert result["failed"] == 2
    failed_rows = [r for r in result["results"] if r["status"] == "failed"]
    assert {r["id"] for r in failed_rows} == set(b_ids)
    for row in failed_rows:
        assert row["error"] == "not_found"
    # Tenant B rows untouched on disk.
    for item in fake.items.rows:
        if item["tenant_id"] == TID_B:
            assert "service_category_id" not in item
    # Sync fired only for same-tenant updates.
    assert len(spy.calls) == 2
    assert {c["item_id"] for c in spy.calls} == set(a_ids)


# ══════════════════════════════════════════════════════════════════
# 4. Q5/A · Service+income policy — per-row failure
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_mixed_service_product_batch_with_income_id(env):
    """When the batch mixes service + product items AND the
    payload carries ``income_category_id``, service items land
    in ``results`` with a specific error; products in the same
    batch proceed normally."""
    fake, spy, handler = env
    _seed_categories(fake)
    prod_ids = _seed_items(fake, 2, item_type="product",
                            prefix="pb-prod")
    svc_ids = _seed_items(fake, 2, item_type="service",
                            prefix="pb-svc")
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=prod_ids + svc_ids,
        income_category_id=INC_ID,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 2, result
    assert result["failed"] == 2, result
    failed_rows = [r for r in result["results"] if r["status"] == "failed"]
    assert {r["id"] for r in failed_rows} == set(svc_ids)
    for row in failed_rows:
        assert row["error"] == "services_cannot_have_income_category_id"
    # Products still landed the update + fired the sync.
    for item in fake.items.rows:
        if item["item_type"] == "product":
            assert item["income_category_id"] == INC_ID
        else:  # service — untouched
            assert item.get("income_category_id") is None
    assert len(spy.calls) == 2
    assert {c["item_id"] for c in spy.calls} == set(prod_ids)


def test_bulk_update_service_items_with_service_id_only_succeeds(env):
    """Q5/A guardrail — the service-rejection only fires when
    ``income_category_id`` is in the payload. A service item with
    only a ``service_category_id`` update succeeds."""
    fake, spy, handler = env
    _seed_categories(fake)
    svc_ids = _seed_items(fake, 2, item_type="service",
                            prefix="pb-svc")
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=svc_ids, service_category_id=SVC_ID,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 2
    assert result["failed"] == 0


# ══════════════════════════════════════════════════════════════════
# 5. P55 sync integration
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_fires_p55_sync_per_row(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 3)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID, income_category_id=INC_ID,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 3
    assert len(spy.calls) == 3
    for call in spy.calls:
        assert call["origin"] == "bulk_pricebook_edit"
        assert call["tenant_id"] == TID_A
        assert call["service_category_id"] == SVC_ID
        assert call["income_category_id"] == INC_ID
        assert call["actor_id"] == "u_admin"
    # Aggregate reflects per-call SyncResults (3 × 2 = 6).
    assert result["sync_result_summary"]["child_invoices_updated"] == 6


def test_bulk_update_partial_apply_on_p55_sync_failure(env, monkeypatch):
    fake, _, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 3)
    from services import category_sync as cs
    poison_spy = _SyncSpy(raise_for_ids=[ids[1]])
    monkeypatch.setattr(
        cs, "sync_pricebook_to_invoice_lines", poison_spy,
    )
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 2
    assert result["failed"] == 1
    failed_row = next(r for r in result["results"]
                        if r["status"] == "failed")
    assert failed_row["id"] == ids[1]
    assert "category_deleted_after_source_write" in failed_row["error"]
    # All 3 sync attempts were made.
    assert len(poison_spy.calls) == 3
    # The offending row's item write still landed (partial apply).
    middle = next(t for t in fake.items.rows if t["id"] == ids[1])
    assert middle["service_category_id"] == SVC_ID


# ══════════════════════════════════════════════════════════════════
# 6. Audit integration
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_writes_audit_row_per_updated_item(env):
    fake, _, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 3)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 3
    audits = fake.audit_log.insert_calls
    assert len(audits) == 3
    for audit in audits:
        doc = audit["doc"]
        assert doc["action"] == "pricebook.patch"
        assert doc["actor_user_id"] == "u_admin"
        assert doc["target_id"] in ids
        assert "service_category_id" in doc["changed_fields"]
        assert "service_category_name" in doc["changed_fields"]


def test_bulk_update_already_current_writes_no_audit(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 2,
                      with_service=SVC_ID, with_income=INC_ID)
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,  # already matches
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 0
    assert result["already_current"] == 2
    assert result["failed"] == 0
    assert fake.audit_log.insert_calls == []
    assert spy.calls == []


# ══════════════════════════════════════════════════════════════════
# 7. Q6/yes · Tenant scoping — soft-deleted items excluded
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_soft_deleted_items_appear_in_failed(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_items(fake, 2)
    # Soft-delete one of them.
    fake.items.rows[0]["deleted_at"] = "2026-02-01T00:00:00Z"
    from routers.items import _PricebookBulkUpdateCategoriesIn
    body = _PricebookBulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,
    )
    result = _run(handler(body=body, user=_actor()))
    assert result["updated"] == 1
    assert result["failed"] == 1
    failed_row = next(r for r in result["results"] if r["status"] == "failed")
    assert failed_row["error"] == "not_found"


# ══════════════════════════════════════════════════════════════════
# 8. Regression guard — origin must not be in _SKIP_TABLE
# ══════════════════════════════════════════════════════════════════
def test_bulk_pricebook_edit_origin_not_in_skip_set():
    """Mirrors ``test_bulk_edit_origin_not_in_skip_set`` from the
    P54 suite. Ensures the P56 origin marker
    ``bulk_pricebook_edit`` cannot be silently short-circuited by
    a future edit to ``_SKIP_TABLE``."""
    from services import category_sync as cs
    real_entry_origins = {
        "sync_pricebook_to_invoice_lines": "bulk_pricebook_edit",
    }
    for callee, entry_origin in real_entry_origins.items():
        skip_set = cs._SKIP_TABLE.get(callee, set())
        assert entry_origin not in skip_set, (
            f"P56 entry-point origin {entry_origin!r} appears in "
            f"_SKIP_TABLE[{callee!r}]={skip_set!r} — this silently "
            f"disables the bulk endpoint's fan-out. Rename the "
            f"origin or replace the skip-set entry with "
            f"_RESERVED_SELF_LOOP."
        )
