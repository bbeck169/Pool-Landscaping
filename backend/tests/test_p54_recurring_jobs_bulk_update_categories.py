"""P54 · Bulk-Update-Categories endpoint behaviour tests (Feb-2026).

Coverage:

  1. Partial-payload semantics — only the changed field is applied.
  2. Both-fields path.
  3. Payload validation:
       * neither field set          → HTTP 400 no_category_fields_set
       * unknown category id        → HTTP 422 <field>_invalid
       * batch cap breach           → HTTP 400 batch_too_large
  4. Cross-tenant policy — out-of-tenant ids appear in ``results``
     with ``status="failed", error="not_found"`` (Q2/A honest
     telemetry).
  5. P55 sync integration:
       * one fan-out per updated row with ``origin="bulk_recurring_edit"``
       * partial-apply on ``CategorySyncNameLookupError`` — the
         template write already landed, that row classifies as
         failed, remaining rows continue processing.
  6. Audit integration — one ``recurring_job.recategorize`` row per
     updated row via the reused ``_write_recurring_category_audit``
     writer.
  7. Regression guard — ``bulk_recurring_edit`` origin must NOT
     appear in ``_SKIP_TABLE`` for
     ``sync_recurring_template_to_children``.

Uses a self-contained fake-DB fixture identical in spirit to
``test_p55_category_sync.py`` — no Mongo dependency, runs in
under a second. The FastAPI handler is invoked directly (not via
HTTP) so tests are motor-loop-independent + xdist-safe.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════
# Fake DB scaffolding (mirrors test_p55_category_sync.py so any
# future refactor of the fake stays lockstep with the P55 suite).
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
        actual = doc.get(k)
        if isinstance(v, dict):
            for op, arg in v.items():
                if op == "$ne" and actual == arg:
                    return False
                if op == "$in" and actual not in arg:
                    return False
        else:
            if actual != v:
                return False
    return True


class _FakeDB:
    def __init__(self):
        self.recurring_job_templates = _Coll()
        self.income_categories = _Coll()
        self.service_categories = _Coll()
        self.audit_logs = _Coll()

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
        {"id": INC_ID, "tenant_id": tenant_id, "name": "Pool",
          "is_archived": False},
        {"id": INC_ID_2, "tenant_id": tenant_id, "name": "Landscape",
          "is_archived": False},
    ])
    fake.service_categories.rows.extend([
        {"id": SVC_ID, "tenant_id": tenant_id, "name": "Weekly Service",
          "is_archived": False},
        {"id": SVC_ID_2, "tenant_id": tenant_id, "name": "Monthly Service",
          "is_archived": False},
    ])


def _seed_templates(
    fake: _FakeDB,
    count: int = 3,
    *,
    tenant_id: str = TID_A,
    with_service: Optional[str] = None,
    with_income: Optional[str] = None,
    prefix: str = "tpl",
) -> List[str]:
    ids = []
    for i in range(count):
        tid = f"{prefix}-{tenant_id}-{i}"
        row: Dict[str, Any] = {
            "id": tid, "tenant_id": tenant_id,
            "customer_id": "c1", "service_type": "Weekly",
            "frequency": "weekly",
        }
        if with_service:
            row["service_category_id"] = with_service
            row["service_category_name"] = "Weekly Service"
        if with_income:
            row["income_category_id"] = with_income
            row["income_category_name"] = "Pool"
        fake.recurring_job_templates.rows.append(row)
        ids.append(tid)
    return ids


# ══════════════════════════════════════════════════════════════════
# Fixture
# ══════════════════════════════════════════════════════════════════
class _SyncSpy:
    """Records every call to
    ``sync_recurring_template_to_children`` so tests can assert
    call count + args + origin marker."""

    def __init__(self, raise_for_ids: Optional[List[str]] = None):
        self.calls: List[Dict[str, Any]] = []
        self.raise_for_ids = set(raise_for_ids or [])

    async def __call__(self, *, tenant_id, recurring_job_id,
                       origin, actor_id=None, **kwargs):
        self.calls.append({
            "tenant_id": tenant_id,
            "recurring_job_id": recurring_job_id,
            "origin": origin,
            "actor_id": actor_id,
            **kwargs,
        })
        if recurring_job_id in self.raise_for_ids:
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
    ``bulk_update_categories_recurring`` from
    ``routers.recurring_jobs``.
    """
    fake = _FakeDB()
    spy = _SyncSpy()
    from routers import recurring_jobs as rj
    from services import category_sync as cs
    monkeypatch.setattr(rj, "db", fake)
    monkeypatch.setattr(cs, "db", fake)
    # Patch the sync function on its origin module — the router
    # imports it fresh inside the handler so the patch site MUST be
    # ``services.category_sync``. Both the origin and the router-
    # side alias share the same reference after the setattr.
    monkeypatch.setattr(
        cs, "sync_recurring_template_to_children", spy,
    )
    return fake, spy, rj.bulk_update_categories_recurring


def _actor():
    return {"id": "u_admin", "role": "admin",
            "email": "a@x", "tenant_id": TID_A}


def _tenant():
    return {"id": TID_A}


# ══════════════════════════════════════════════════════════════════
# 1. Partial-payload semantics
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_service_only_income_unchanged(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 2,
                          with_service=SVC_ID, with_income=INC_ID)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(ids=ids, service_category_id=SVC_ID_2)
    result = _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert result["updated"] == 2
    assert result["failed"] == 0
    # Every template's service_category_id now points at SVC_ID_2.
    # income_category_id UNCHANGED (still INC_ID).
    for tpl in fake.recurring_job_templates.rows:
        assert tpl["service_category_id"] == SVC_ID_2
        assert tpl["service_category_name"] == "Monthly Service"
        assert tpl["income_category_id"] == INC_ID
        assert tpl["income_category_name"] == "Pool"


def test_bulk_update_income_only_service_unchanged(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 2,
                          with_service=SVC_ID, with_income=INC_ID)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(ids=ids, income_category_id=INC_ID_2)
    result = _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert result["updated"] == 2
    for tpl in fake.recurring_job_templates.rows:
        assert tpl["income_category_id"] == INC_ID_2
        assert tpl["income_category_name"] == "Landscape"
        assert tpl["service_category_id"] == SVC_ID
        assert tpl["service_category_name"] == "Weekly Service"


def test_bulk_update_both_fields(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 2,
                          with_service=SVC_ID, with_income=INC_ID)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(
        ids=ids,
        service_category_id=SVC_ID_2, income_category_id=INC_ID_2,
    )
    result = _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert result["updated"] == 2
    for tpl in fake.recurring_job_templates.rows:
        assert tpl["service_category_id"] == SVC_ID_2
        assert tpl["income_category_id"] == INC_ID_2


# ══════════════════════════════════════════════════════════════════
# 2. Payload validation
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_neither_field_returns_400(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 1)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(ids=ids)  # neither field set
    with pytest.raises(HTTPException) as exc_info:
        _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "no_category_fields_set"
    # No row was written; no sync fired.
    assert fake.recurring_job_templates.update_calls == []
    assert spy.calls == []


def test_bulk_update_unknown_category_id_returns_422(env):
    """P54 mirrors the single-item PATCH shape (Q3/A) — HTTP 422
    with ``{code, field, attempted, collection}``. Spec wrote 400
    but the grep-first mandate overrides."""
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 1)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(
        ids=ids, service_category_id="does-not-exist-uuid",
    )
    with pytest.raises(HTTPException) as exc_info:
        _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert detail["code"] == "service_category_invalid"
    assert detail["field"] == "service_category_id"
    assert detail["attempted"] == "does-not-exist-uuid"
    assert detail["collection"] == "service_categories"


def test_bulk_update_more_than_100_ids_returns_400(env):
    """Q1/A · _BULK_UPDATE_CATEGORIES_MAX = 100 (mirrors
    _BULK_ACTIVATE_MAX). Spec had 400 — grep overrode."""
    fake, spy, handler = env
    _seed_categories(fake)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    ids = [f"tpl-{i}" for i in range(101)]
    body = _BulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,
    )
    with pytest.raises(HTTPException) as exc_info:
        _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"] == "batch_too_large"
    assert exc_info.value.detail["max"] == 100
    assert exc_info.value.detail["received"] == 101


# ══════════════════════════════════════════════════════════════════
# 3. Cross-tenant policy — Q2 (renamed per user amendment)
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_cross_tenant_ids_appear_in_failed_results(env):
    """Q2/A honest-telemetry — mirrors bulk-activate: cross-tenant
    ids land in ``results`` as ``status='failed', error='not_found'``,
    NOT silently filtered."""
    fake, spy, handler = env
    _seed_categories(fake, tenant_id=TID_A)
    _seed_categories(fake, tenant_id=TID_B)
    a_ids = _seed_templates(fake, 2, tenant_id=TID_A, prefix="tpl-a")
    b_ids = _seed_templates(fake, 2, tenant_id=TID_B, prefix="tpl-b")
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(
        ids=a_ids + b_ids,  # 2 same-tenant + 2 cross-tenant
        service_category_id=SVC_ID,
    )
    result = _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert result["updated"] == 2
    assert result["failed"] == 2
    # Both b_ids appear in results with status=failed / error=not_found.
    failed_rows = [r for r in result["results"] if r["status"] == "failed"]
    failed_ids = {r["id"] for r in failed_rows}
    assert failed_ids == set(b_ids)
    for row in failed_rows:
        assert row["error"] == "not_found"
    # Cross-tenant rows are UNTOUCHED on disk.
    for tpl in fake.recurring_job_templates.rows:
        if tpl["tenant_id"] == TID_B:
            assert "service_category_id" not in tpl
    # Sync fired ONLY for the same-tenant updates.
    assert len(spy.calls) == 2
    assert {c["recurring_job_id"] for c in spy.calls} == set(a_ids)


# ══════════════════════════════════════════════════════════════════
# 4. P55 sync integration
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_fires_p55_sync_per_row(env):
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 3)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID, income_category_id=INC_ID,
    )
    result = _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert result["updated"] == 3
    # One sync call per updated template.
    assert len(spy.calls) == 3
    # Every call carried the P54 origin marker (Q4-adjacent grep
    # invariant enforced by the test_bulk_edit_origin_not_in_skip_set
    # guard below).
    for call in spy.calls:
        assert call["origin"] == "bulk_recurring_edit"
        assert call["tenant_id"] == TID_A
        assert call["service_category_id"] == SVC_ID
        assert call["income_category_id"] == INC_ID
        assert call["actor_id"] == "u_admin"
    # Aggregate summary reflects the spy's per-call SyncResults
    # (each returned updated_count=2 → 3 rows × 2 = 6 child invoices).
    assert result["sync_result_summary"]["child_invoices_updated"] == 6


def test_bulk_update_partial_apply_on_p55_sync_failure(env, monkeypatch):
    """When ``sync_recurring_template_to_children`` raises
    ``CategorySyncNameLookupError`` on one row, the endpoint must
    NOT abort the batch. That row classifies as ``failed`` (the
    template write already landed); remaining rows continue."""
    fake, _, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 3)
    # Replace the spy with one that raises for the middle id only.
    from services import category_sync as cs
    poison_spy = _SyncSpy(raise_for_ids=[ids[1]])
    monkeypatch.setattr(
        cs, "sync_recurring_template_to_children", poison_spy,
    )
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,
    )
    result = _run(handler(body=body, user=_actor(), tenant=_tenant()))
    # 2 updated + 1 failed (the sync raise). Batch did NOT abort.
    assert result["updated"] == 2
    assert result["failed"] == 1
    failed_row = next(r for r in result["results"]
                      if r["status"] == "failed")
    assert failed_row["id"] == ids[1]
    assert "category_deleted_after_source_write" in failed_row["error"]
    # All 3 sync attempts were made — the raise didn't short-circuit
    # the loop.
    assert len(poison_spy.calls) == 3
    # The offending row's TEMPLATE write still landed — this is
    # the "partial apply" state the caller sees.
    tpl_middle = next(t for t in fake.recurring_job_templates.rows
                      if t["id"] == ids[1])
    assert tpl_middle["service_category_id"] == SVC_ID


# ══════════════════════════════════════════════════════════════════
# 5. Audit integration
# ══════════════════════════════════════════════════════════════════
def test_bulk_update_writes_audit_row_per_updated_item(env):
    fake, _, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 3)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,
    )
    result = _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert result["updated"] == 3
    audits = fake.audit_logs.insert_calls
    assert len(audits) == 3
    for audit in audits:
        doc = audit["doc"]
        assert doc["event"] == "recurring_job.recategorize"
        assert doc["tenant_id"] == TID_A
        assert doc["actor_id"] == "u_admin"
        assert doc["recurring_template_id"] in ids
        assert "service_category_id" in doc["diff"]
        assert doc["diff"]["service_category_id"]["after"] == SVC_ID


def test_bulk_update_already_current_writes_no_audit(env):
    """Idempotent no-op — templates already at the target value
    must not write an audit row, per the writer's own no-op guard
    and the ``already_current`` telemetry contract."""
    fake, spy, handler = env
    _seed_categories(fake)
    ids = _seed_templates(fake, 2,
                          with_service=SVC_ID, with_income=INC_ID)
    from routers.recurring_jobs import _BulkUpdateCategoriesIn
    body = _BulkUpdateCategoriesIn(
        ids=ids, service_category_id=SVC_ID,  # same as current
    )
    result = _run(handler(body=body, user=_actor(), tenant=_tenant()))
    assert result["updated"] == 0
    assert result["already_current"] == 2
    assert result["failed"] == 0
    assert fake.audit_logs.insert_calls == []
    # No sync fired for already-current rows either.
    assert spy.calls == []


# ══════════════════════════════════════════════════════════════════
# 6. Regression guard — origin string must not be in _SKIP_TABLE
# ══════════════════════════════════════════════════════════════════
def test_bulk_edit_origin_not_in_skip_set():
    """Mirrors ``test_entry_point_origin_is_not_in_skip_set`` from
    the P55 test suite. Ensures the P54 origin marker
    ``bulk_recurring_edit`` cannot be silently short-circuited by
    a future edit to ``_SKIP_TABLE``."""
    from services import category_sync as cs
    real_entry_origins = {
        "sync_recurring_template_to_children": "bulk_recurring_edit",
    }
    for callee, entry_origin in real_entry_origins.items():
        skip_set = cs._SKIP_TABLE.get(callee, set())
        assert entry_origin not in skip_set, (
            f"P54 entry-point origin {entry_origin!r} appears in "
            f"_SKIP_TABLE[{callee!r}]={skip_set!r} — this silently "
            f"disables the bulk endpoint's fan-out. Rename the "
            f"origin or replace the skip-set entry with "
            f"_RESERVED_SELF_LOOP."
        )
