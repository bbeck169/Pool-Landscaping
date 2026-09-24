"""P55 · Category sync orchestrator behavior tests (Feb-2026).

Coverage:

  1. Recurring template propagation
     * All linked unpaid invoices' line items updated in
       lockstep (6 fields per line).
     * Paid invoices hard-skipped (skipped_paid_count reports
       them; their line-items are BYTE-IDENTICAL after the sync).
     * Denormalized names on updated lines match the new id.
     * unit_price + subtotal + total on updated line items are
       UNCHANGED bit-for-bit (price protection).
     * Jobs are NOT updated (Q1/Option B).

  2. Idempotency — running the same sync twice yields
     updated_count == 0 on the second run.

  3. Tenant scoping — two tenants with parallel templates +
     jobs + invoices; editing tenant A's template updates only
     tenant A's rows.

  4. Pricebook writeback path — sync_invoice_line_to_pricebook
     writes 4 modern fields + legacy scalar ``category`` in
     lockstep on the target db.items row.

  5. Loop prevention (both directions)
     * origin='pricebook_writeback' short-circuits
       sync_invoice_line_to_pricebook → no db writes.
     * origin='recurring_template_edit' short-circuits
       sync_recurring_template_to_children → no db writes.
     Both assert via a write-spy on the fake db.

  6. Category-name lookup failure — non-existent category_id
     raises CategorySyncNameLookupError. NO silent null-write.

  7. Partial payload semantics — sync called with only
     service_category_id set → income pair on child docs is
     UNCHANGED.

  8. Price snapshot protection — introspect the actual SET
     clause passed to update_one and assert no forbidden field
     (unit_price / quantity / tax_amount / subtotal / total /
     discount_amount / *_snapshot) is present.

  9. None/clear direction (Q · policy)
     * test_template_clear_propagates_to_unpaid_invoices —
       template clear → invoice line items cleared to None.
     * test_invoice_line_clear_does_not_clear_pricebook —
       invoice line cleared → Pricebook row's category fields
       UNCHANGED.

Uses a self-contained fake-DB fixture — no Mongo dependency,
runs in <1s. Standard Motor operations are stubbed with
in-memory dict collections.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, Dict, List, Optional

import pytest


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════════
# Fake DB scaffolding
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
        # Spy — records every update_one / update_many call so
        # tests can introspect the SET clause.
        self.update_calls: List[Dict[str, Any]] = []
        self.insert_calls: List[Dict[str, Any]] = []

    # ── read ops ──
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

    async def distinct(self, key, filt=None):
        filt = filt or {}
        return list({r.get(key) for r in self.rows if _match(r, filt)})

    # ── write ops ──
    async def update_one(self, filt, update):
        self.update_calls.append(
            {"op": "update_one", "filter": filt, "update": update},
        )
        matched = 0
        modified = 0
        for r in self.rows:
            if _match(r, filt):
                matched = 1
                modified = _apply_update(r, update)
                break
        return _UpdateResult(matched=matched, modified=modified)

    async def update_many(self, filt, update):
        self.update_calls.append(
            {"op": "update_many", "filter": filt, "update": update},
        )
        matched = 0
        modified = 0
        for r in self.rows:
            if _match(r, filt):
                matched += 1
                if _apply_update(r, update):
                    modified += 1
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
                if op == "$nin" and actual in arg:
                    return False
                if op == "$exists":
                    present = k in doc
                    if bool(arg) != present:
                        return False
                if op == "$gte" and (actual is None or actual < arg):
                    return False
                if op == "$lte" and (actual is None or actual > arg):
                    return False
        else:
            if actual != v:
                return False
    return True


def _apply_update(doc: Dict[str, Any], update: Dict[str, Any]) -> int:
    modified = 0
    if "$set" in update:
        for k, v in update["$set"].items():
            # Handle dotted paths for line_items.{idx}.{field}
            if "." in k:
                parts = k.split(".")
                target = doc
                for p in parts[:-1]:
                    if p.isdigit():
                        target = target[int(p)]
                    else:
                        target = target.setdefault(p, {})
                last = parts[-1]
                if target.get(last) != v:
                    target[last] = v
                    modified = 1
            else:
                if doc.get(k) != v:
                    doc[k] = v
                    modified = 1
    if "$unset" in update:
        for k in update["$unset"].keys():
            if "." in k:
                parts = k.split(".")
                target = doc
                for p in parts[:-1]:
                    if p.isdigit():
                        target = target[int(p)]
                    else:
                        target = target.get(p, {})
                last = parts[-1]
                if last in target:
                    del target[last]
                    modified = 1
            else:
                if k in doc:
                    del doc[k]
                    modified = 1
    return modified


class _FakeDB:
    def __init__(self):
        self.jobs = _Coll()
        self.quotes = _Coll()
        self.items = _Coll()
        self.income_categories = _Coll()
        self.service_categories = _Coll()
        self.audit_logs = _Coll()

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _FakeDB()
    from services import category_sync as cs
    monkeypatch.setattr(cs, "db", fake)
    return fake


# ══════════════════════════════════════════════════════════════════
# Seed helpers
# ══════════════════════════════════════════════════════════════════
TID_A = "t-A"
TID_B = "t-B"
TPL_ID = "tpl-A-1"

INC_OLD = "inc-old-uuid"
INC_NEW = "inc-new-uuid"
SVC_OLD = "svc-old-uuid"
SVC_NEW = "svc-new-uuid"


def _seed_categories(fake: _FakeDB, *, tenant_id: str = TID_A) -> None:
    fake.income_categories.rows.extend([
        {"id": INC_OLD, "tenant_id": tenant_id,
          "name": "Old Income Cat", "is_archived": False},
        {"id": INC_NEW, "tenant_id": tenant_id,
          "name": "New Income Cat", "is_archived": False},
    ])
    fake.service_categories.rows.extend([
        {"id": SVC_OLD, "tenant_id": tenant_id,
          "name": "Old Service Cat", "is_archived": False},
        {"id": SVC_NEW, "tenant_id": tenant_id,
          "name": "New Service Cat", "is_archived": False},
    ])


def _seed_jobs(fake: _FakeDB, count: int, *,
               tenant_id: str = TID_A,
               tpl_id: str = TPL_ID) -> List[str]:
    ids = []
    for i in range(count):
        jid = f"job-{tpl_id}-{i}"
        fake.jobs.rows.append({
            "id": jid, "tenant_id": tenant_id,
            "recurring_template_id": tpl_id,
            "scheduled_date": "2026-03-01",
            "status": "scheduled",
        })
        ids.append(jid)
    return ids


def _line_item(
    idx: int,
    *,
    income_id: Optional[str] = INC_OLD,
    income_name: Optional[str] = "Old Income Cat",
    service_id: Optional[str] = SVC_OLD,
    service_name: Optional[str] = "Old Service Cat",
) -> Dict[str, Any]:
    """Line item pre-seeded with the six category fields set to
    'OLD' values plus a locked price/quantity block so tests can
    assert the price block is untouched byte-for-byte after sync.
    """
    return {
        "id": f"li-{idx}",
        # Modern income pair
        "income_category_id": income_id,
        "income_category_name": income_name,
        # Legacy income aliases (Q3 lockstep)
        "category": income_id,
        "category_name": income_name,
        # Modern service pair (no legacy alias)
        "service_category_id": service_id,
        "service_category_name": service_name,
        # Price block — MUST be untouched by the sync.
        "unit_price": 123.45,
        "quantity": 2,
        "subtotal": 246.90,
        "tax_amount": 20.35,
        "total": 267.25,
        "discount_amount": 0.0,
        "unit_price_snapshot": 123.45,
        # Pricebook FK for the invoice-line → pricebook sync test.
        "pricebook_item_id": "pb-1",
    }


def _seed_invoices(
    fake: _FakeDB,
    job_ids: List[str],
    *,
    tenant_id: str = TID_A,
    unpaid_per_job: int = 1,
    paid_per_job: int = 0,
    line_items_per_invoice: int = 1,
) -> None:
    for jid in job_ids:
        for i in range(unpaid_per_job):
            fake.quotes.rows.append({
                "id": f"inv-unpaid-{jid}-{i}",
                "tenant_id": tenant_id,
                "doc_type": "invoice",
                "job_id": jid,
                "payment_status": "unpaid",
                "line_items": [
                    _line_item(idx)
                    for idx in range(line_items_per_invoice)
                ],
            })
        for i in range(paid_per_job):
            fake.quotes.rows.append({
                "id": f"inv-paid-{jid}-{i}",
                "tenant_id": tenant_id,
                "doc_type": "invoice",
                "job_id": jid,
                "payment_status": "paid",
                "line_items": [
                    _line_item(idx)
                    for idx in range(line_items_per_invoice)
                ],
            })


def _seed_pricebook(
    fake: _FakeDB, pb_id: str = "pb-1",
    *, tenant_id: str = TID_A,
) -> None:
    fake.items.rows.append({
        "id": pb_id, "tenant_id": tenant_id,
        "name": "Test Item",
        "unit_price": 55.0,
        # Start with no modern taxonomy fields — Q2/Option A
        # says $set introduces them.
        "category": "Old",
    })


# ══════════════════════════════════════════════════════════════════
# 1. Recurring template propagation
# ══════════════════════════════════════════════════════════════════
def test_recurring_template_propagates_to_all_unpaid_invoices(fake_db):
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 5)
    # 3 unpaid + 2 paid (paid spread across two of the jobs).
    _seed_invoices(fake_db, job_ids[:3],
                   unpaid_per_job=1, paid_per_job=0)
    _seed_invoices(fake_db, job_ids[3:5],
                   unpaid_per_job=0, paid_per_job=1)

    result = _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin="recurring_template_edit_NOT_SELF",  # bypass loop
        service_category_id=SVC_NEW,
        income_category_id=INC_NEW,
    ))
    assert result.updated_count == 3, result
    assert result.skipped_paid_count == 2, result
    # 3 unpaid updated; on each, all 6 line-item fields must
    # match the NEW template values.
    for inv_id in ["inv-unpaid-job-tpl-A-1-0-0",
                   "inv-unpaid-job-tpl-A-1-1-0",
                   "inv-unpaid-job-tpl-A-1-2-0"]:
        inv = _first(fake_db.quotes, id=inv_id)
        assert inv is not None, inv_id
        li = inv["line_items"][0]
        assert li["income_category_id"] == INC_NEW
        assert li["income_category_name"] == "New Income Cat"
        assert li["category"] == INC_NEW               # legacy alias
        assert li["category_name"] == "New Income Cat"  # legacy alias
        assert li["service_category_id"] == SVC_NEW
        assert li["service_category_name"] == "New Service Cat"

    # Paid invoices UNTOUCHED — every single field byte-identical
    # to seed.
    for inv_id in ["inv-paid-job-tpl-A-1-3-0",
                   "inv-paid-job-tpl-A-1-4-0"]:
        inv = _first(fake_db.quotes, id=inv_id)
        assert inv is not None
        li = inv["line_items"][0]
        assert li["income_category_id"] == INC_OLD
        assert li["income_category_name"] == "Old Income Cat"
        assert li["category"] == INC_OLD
        assert li["category_name"] == "Old Income Cat"
        assert li["service_category_id"] == SVC_OLD
        assert li["service_category_name"] == "Old Service Cat"


def test_recurring_sync_preserves_price_fields_byte_for_byte(fake_db):
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 1)
    _seed_invoices(fake_db, job_ids, unpaid_per_job=1)

    _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin="recurring_template_edit_NOT_SELF",
        income_category_id=INC_NEW,
        service_category_id=SVC_NEW,
    ))
    inv = _first(fake_db.quotes, id="inv-unpaid-job-tpl-A-1-0-0")
    li = inv["line_items"][0]
    assert li["unit_price"] == 123.45
    assert li["quantity"] == 2
    assert li["subtotal"] == 246.90
    assert li["tax_amount"] == 20.35
    assert li["total"] == 267.25
    assert li["discount_amount"] == 0.0
    assert li["unit_price_snapshot"] == 123.45


def test_recurring_sync_does_not_update_jobs(fake_db):
    """Q1/Option B — Jobs are DELIBERATELY NOT updated. This
    test asserts db.jobs is READ but never WRITTEN."""
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 3)
    _seed_invoices(fake_db, job_ids)

    _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin="recurring_template_edit_NOT_SELF",
        income_category_id=INC_NEW,
    ))
    # Every job row is untouched — no category fields introduced.
    for j in fake_db.jobs.rows:
        assert "income_category_id" not in j
        assert "income_category_name" not in j
        assert "service_category_id" not in j
        assert "service_category_name" not in j
    # And no update_one / update_many was called on db.jobs.
    assert fake_db.jobs.update_calls == []


# ══════════════════════════════════════════════════════════════════
# 2. Idempotency
# ══════════════════════════════════════════════════════════════════
def test_recurring_sync_is_idempotent(fake_db):
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 2)
    _seed_invoices(fake_db, job_ids)

    first = _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin="recurring_template_edit_NOT_SELF",
        income_category_id=INC_NEW,
        service_category_id=SVC_NEW,
    ))
    assert first.updated_count == 2

    second = _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin="recurring_template_edit_NOT_SELF",
        income_category_id=INC_NEW,
        service_category_id=SVC_NEW,
    ))
    assert second.updated_count == 0, (
        "Idempotent re-run must yield 0 updates — Mongo "
        "modified_count semantics"
    )


# ══════════════════════════════════════════════════════════════════
# 3. Tenant scoping
# ══════════════════════════════════════════════════════════════════
def test_recurring_sync_never_crosses_tenant_boundary(fake_db):
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db, tenant_id=TID_A)
    _seed_categories(fake_db, tenant_id=TID_B)
    job_ids_a = _seed_jobs(fake_db, 2, tenant_id=TID_A, tpl_id="tpl-A")
    job_ids_b = _seed_jobs(fake_db, 2, tenant_id=TID_B, tpl_id="tpl-B")
    _seed_invoices(fake_db, job_ids_a, tenant_id=TID_A)
    _seed_invoices(fake_db, job_ids_b, tenant_id=TID_B)

    _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id="tpl-A",
        origin="recurring_template_edit_NOT_SELF",
        income_category_id=INC_NEW,
    ))
    # Tenant A invoices touched.
    for inv in fake_db.quotes.rows:
        if inv["tenant_id"] == TID_A:
            assert inv["line_items"][0]["income_category_id"] == INC_NEW
        else:
            # Tenant B invoices untouched.
            assert inv["line_items"][0]["income_category_id"] == INC_OLD


# ══════════════════════════════════════════════════════════════════
# 4. Pricebook writeback path
# ══════════════════════════════════════════════════════════════════
def test_invoice_line_to_pricebook_updates_master_row(fake_db):
    from services.category_sync import (
        sync_invoice_line_to_pricebook,
    )
    _seed_categories(fake_db)
    _seed_pricebook(fake_db, pb_id="pb-1")
    fake_db.quotes.rows.append({
        "id": "inv-1", "tenant_id": TID_A, "doc_type": "invoice",
        "line_items": [_line_item(0)],
    })
    result = _run(sync_invoice_line_to_pricebook(
        tenant_id=TID_A, invoice_id="inv-1", line_item_id="li-0",
        origin="invoice_line_edit",
        income_category_id=INC_NEW,
        service_category_id=SVC_NEW,
    ))
    assert result.updated_count == 1
    pb = _first(fake_db.items, id="pb-1")
    assert pb["income_category_id"] == INC_NEW
    assert pb["income_category_name"] == "New Income Cat"
    assert pb["service_category_id"] == SVC_NEW
    assert pb["service_category_name"] == "New Service Cat"
    # Legacy scalar in lockstep with income_category_id.
    assert pb["category"] == INC_NEW


# ══════════════════════════════════════════════════════════════════
# 5. Loop prevention
# ══════════════════════════════════════════════════════════════════
def test_pricebook_writeback_origin_short_circuits_invoice_sync(fake_db):
    from services.category_sync import sync_invoice_line_to_pricebook
    _seed_pricebook(fake_db)
    fake_db.quotes.rows.append({
        "id": "inv-1", "tenant_id": TID_A, "doc_type": "invoice",
        "line_items": [_line_item(0)],
    })
    r = _run(sync_invoice_line_to_pricebook(
        tenant_id=TID_A, invoice_id="inv-1", line_item_id="li-0",
        origin="pricebook_writeback",
        income_category_id=INC_NEW,
    ))
    assert r.skipped_loop_count == 1
    assert r.updated_count == 0
    # No writes to db.items happened.
    assert fake_db.items.update_calls == []
    # No audit row.
    assert fake_db.audit_logs.insert_calls == []


def test_template_self_origin_short_circuits_children_sync(fake_db):
    """The reserved self-loop sentinel short-circuits the entry
    point (loop-prevention contract). Uses the module-exported
    ``_RESERVED_SELF_LOOP`` marker — the string that populates
    the ``sync_recurring_template_to_children`` skip set post
    Commit 6 · Option C."""
    from services.category_sync import (
        sync_recurring_template_to_children,
        _RESERVED_SELF_LOOP,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 1)
    _seed_invoices(fake_db, job_ids)

    r = _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin=_RESERVED_SELF_LOOP,  # sentinel — always short-circuits
        income_category_id=INC_NEW,
    ))
    assert r.skipped_loop_count == 1
    assert r.updated_count == 0
    assert fake_db.quotes.update_calls == []
    assert fake_db.audit_logs.insert_calls == []


# ══════════════════════════════════════════════════════════════════
# 6. Category-name lookup failure
# ══════════════════════════════════════════════════════════════════
def test_name_lookup_failure_raises_no_silent_null_write(fake_db):
    from services.category_sync import (
        sync_recurring_template_to_children,
        CategorySyncNameLookupError,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 1)
    _seed_invoices(fake_db, job_ids)

    with pytest.raises(CategorySyncNameLookupError) as exc_info:
        _run(sync_recurring_template_to_children(
            tenant_id=TID_A, recurring_job_id=TPL_ID,
            origin="recurring_template_edit_NOT_SELF",
            income_category_id="does-not-exist-uuid",
        ))
    assert exc_info.value.category_id == "does-not-exist-uuid"
    assert exc_info.value.collection == "income_categories"
    # Verify NO writes reached the invoices — halt-and-report
    # fires BEFORE any child doc is touched.
    assert fake_db.quotes.update_calls == []


def test_name_lookup_failure_on_pricebook_sync_no_silent_write(fake_db):
    from services.category_sync import (
        sync_invoice_line_to_pricebook,
        CategorySyncNameLookupError,
    )
    _seed_pricebook(fake_db)
    fake_db.quotes.rows.append({
        "id": "inv-1", "tenant_id": TID_A, "doc_type": "invoice",
        "line_items": [_line_item(0)],
    })
    with pytest.raises(CategorySyncNameLookupError):
        _run(sync_invoice_line_to_pricebook(
            tenant_id=TID_A, invoice_id="inv-1",
            line_item_id="li-0",
            origin="invoice_line_edit",
            service_category_id="phantom-svc-uuid",
        ))
    # No write to db.items.
    assert fake_db.items.update_calls == []


# ══════════════════════════════════════════════════════════════════
# 7. Partial payload semantics
# ══════════════════════════════════════════════════════════════════
def test_partial_payload_only_service_leaves_income_unchanged(fake_db):
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 1)
    _seed_invoices(fake_db, job_ids)

    _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin="recurring_template_edit_NOT_SELF",
        service_category_id=SVC_NEW,  # only service set; income omitted
    ))
    inv = _first(fake_db.quotes, id="inv-unpaid-job-tpl-A-1-0-0")
    li = inv["line_items"][0]
    # Service updated.
    assert li["service_category_id"] == SVC_NEW
    assert li["service_category_name"] == "New Service Cat"
    # Income pair UNCHANGED — both modern and legacy alias.
    assert li["income_category_id"] == INC_OLD
    assert li["income_category_name"] == "Old Income Cat"
    assert li["category"] == INC_OLD
    assert li["category_name"] == "Old Income Cat"


# ══════════════════════════════════════════════════════════════════
# 8. Price snapshot protection — introspect SET clause
# ══════════════════════════════════════════════════════════════════
_FORBIDDEN_FIELD_SUBSTRINGS = [
    "unit_price", "quantity", "tax_amount", "subtotal",
    "total", "discount_amount",
]
_FORBIDDEN_SNAPSHOT_PATTERN = re.compile(r"_snapshot")


def test_recurring_sync_set_clause_excludes_price_and_snapshot_fields(fake_db):
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 1)
    _seed_invoices(fake_db, job_ids)

    _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin="recurring_template_edit_NOT_SELF",
        income_category_id=INC_NEW,
        service_category_id=SVC_NEW,
    ))
    for call in fake_db.quotes.update_calls:
        set_keys = list(call["update"].get("$set", {}).keys())
        for key in set_keys:
            for forbidden in _FORBIDDEN_FIELD_SUBSTRINGS:
                # We drop the ``line_items.{idx}.`` prefix for
                # the substring check.
                bare = key.rsplit(".", 1)[-1]
                assert forbidden not in bare, (
                    f"forbidden price field '{key}' appeared "
                    f"in SET clause: {set_keys}"
                )
            assert not _FORBIDDEN_SNAPSHOT_PATTERN.search(key), (
                f"forbidden *_snapshot field '{key}' appeared "
                f"in SET clause: {set_keys}"
            )


def test_pricebook_sync_set_clause_excludes_price_and_snapshot_fields(fake_db):
    from services.category_sync import (
        sync_invoice_line_to_pricebook,
    )
    _seed_categories(fake_db)
    _seed_pricebook(fake_db)
    fake_db.quotes.rows.append({
        "id": "inv-1", "tenant_id": TID_A, "doc_type": "invoice",
        "line_items": [_line_item(0)],
    })
    _run(sync_invoice_line_to_pricebook(
        tenant_id=TID_A, invoice_id="inv-1", line_item_id="li-0",
        origin="invoice_line_edit",
        income_category_id=INC_NEW,
    ))
    for call in fake_db.items.update_calls:
        set_keys = list(call["update"].get("$set", {}).keys())
        for key in set_keys:
            for forbidden in _FORBIDDEN_FIELD_SUBSTRINGS:
                assert forbidden not in key, (
                    f"forbidden price field '{key}' in Pricebook "
                    f"SET clause: {set_keys}"
                )
            assert not _FORBIDDEN_SNAPSHOT_PATTERN.search(key), (
                f"forbidden *_snapshot field '{key}' in Pricebook "
                f"SET clause: {set_keys}"
            )


# ══════════════════════════════════════════════════════════════════
# 9. None/clear direction policy (Q · additional policy call)
# ══════════════════════════════════════════════════════════════════
def test_template_clear_propagates_to_unpaid_invoices(fake_db):
    """Q · direction policy: template → invoices, None PROPAGATES
    as CLEAR (template is source of truth for the chain)."""
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 1)
    _seed_invoices(fake_db, job_ids)

    _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        origin="recurring_template_edit_NOT_SELF",
        income_category_id=None,   # explicit clear
        service_category_id=None,  # explicit clear
    ))
    inv = _first(fake_db.quotes, id="inv-unpaid-job-tpl-A-1-0-0")
    li = inv["line_items"][0]
    # All 6 fields cleared to None.
    assert li["income_category_id"] is None
    assert li["income_category_name"] is None
    assert li["category"] is None
    assert li["category_name"] is None
    assert li["service_category_id"] is None
    assert li["service_category_name"] is None


def test_invoice_line_clear_does_not_clear_pricebook(fake_db):
    """Q · direction policy: invoice line → Pricebook, None
    SKIPS the write (Pricebook is master; downstream ephemeral
    clears must NOT wipe the master row)."""
    from services.category_sync import (
        sync_invoice_line_to_pricebook,
    )
    # Seed Pricebook row WITH modern fields already set — the
    # sync must NOT clear them despite None being passed.
    fake_db.items.rows.append({
        "id": "pb-1", "tenant_id": TID_A,
        "name": "Test Item", "unit_price": 55.0,
        "category": INC_OLD,
        "income_category_id": INC_OLD,
        "income_category_name": "Old Income Cat",
        "service_category_id": SVC_OLD,
        "service_category_name": "Old Service Cat",
    })
    fake_db.quotes.rows.append({
        "id": "inv-1", "tenant_id": TID_A, "doc_type": "invoice",
        "line_items": [_line_item(0)],
    })
    r = _run(sync_invoice_line_to_pricebook(
        tenant_id=TID_A, invoice_id="inv-1", line_item_id="li-0",
        origin="invoice_line_edit",
        income_category_id=None,   # explicit clear
        service_category_id=None,  # explicit clear
    ))
    # No write happened.
    assert r.updated_count == 0
    assert fake_db.items.update_calls == []
    # Pricebook row's category fields still show OLD values.
    pb = _first(fake_db.items, id="pb-1")
    assert pb["income_category_id"] == INC_OLD
    assert pb["service_category_id"] == SVC_OLD


# ══════════════════════════════════════════════════════════════════
# 10. Regression guards — Feb-2026 shipping bug (Commit 7)
# ══════════════════════════════════════════════════════════════════
def test_entry_point_origin_is_not_in_skip_set():
    """Regression guard for the P55 shipping bug where the
    reserved self-loop skip slot for
    ``sync_recurring_template_to_children`` collided with the
    PATCH entry-point origin string, silently disabling the
    template → invoice fan-out.

    Contract: for every entry-point origin string passed by a
    real caller, that origin MUST NOT appear in
    ``_SKIP_TABLE[<its callee>]``. If it does, the entry-point
    call gets short-circuited by its own loop guard and the
    orchestrator never runs.

    Real caller inventory (grep-verified · Feb-2026):
      * ``backend/routers/recurring_jobs.py`` PATCH handler
        passes ``origin=\"recurring_template_edit\"`` when firing
        ``sync_recurring_template_to_children``.
      * ``backend/routers/income_categories.py`` recategorize
        handler passes ``origin=\"invoice_line_edit\"`` when
        firing ``sync_invoice_line_to_pricebook``.
    """
    from services import category_sync as cs
    real_entry_origins = {
        "sync_recurring_template_to_children": "recurring_template_edit",
        "sync_invoice_line_to_pricebook": "invoice_line_edit",
    }
    for callee, entry_origin in real_entry_origins.items():
        skip_set = cs._SKIP_TABLE.get(callee, set())
        assert entry_origin not in skip_set, (
            f"Entry-point origin {entry_origin!r} appears in "
            f"_SKIP_TABLE[{callee!r}]={skip_set!r} — this "
            f"silently disables the entry-point call. Either "
            f"rename the origin at the call site or replace the "
            f"skip-set entry with the _RESERVED_SELF_LOOP "
            f"sentinel."
        )


def test_recurring_template_patch_wire_actually_fires_sync(fake_db):
    """End-to-end behavioral guard: firing the orchestrator with
    the EXACT origin string the recurring-jobs PATCH handler
    uses in production must propagate the category change to
    linked unpaid invoices.

    Before Commit 6 · Option C this test would have failed —
    ``origin=\"recurring_template_edit\"`` was both the entry
    origin AND the reserved short-circuit marker, so
    ``updated_count`` would have been 0 (loop-prevention short
    circuit) and the invoice line's ``service_category_id``
    would have stayed at ``SVC_OLD``.
    """
    from services.category_sync import (
        sync_recurring_template_to_children,
    )
    _seed_categories(fake_db)
    job_ids = _seed_jobs(fake_db, 2)
    _seed_invoices(fake_db, job_ids)  # 2 unpaid invoices

    result = _run(sync_recurring_template_to_children(
        tenant_id=TID_A, recurring_job_id=TPL_ID,
        # The literal string the recurring-jobs PATCH handler
        # passes at runtime. Keep this in lockstep with
        # ``backend/routers/recurring_jobs.py`` — a rename there
        # without a rename here is exactly the class of bug this
        # test guards against.
        origin="recurring_template_edit",
        service_category_id=SVC_NEW,
        income_category_id=INC_NEW,
    ))
    assert result.updated_count == 2, (
        f"PATCH origin failed to propagate — "
        f"result={result}. Was the origin re-added to the "
        f"_SKIP_TABLE?"
    )
    assert result.skipped_loop_count == 0
    # Every unpaid invoice's line item picked up the new pair
    # (both modern + legacy income aliases and modern service).
    for inv in fake_db.quotes.rows:
        if inv["payment_status"] == "unpaid":
            li = inv["line_items"][0]
            assert li["income_category_id"] == INC_NEW
            assert li["income_category_name"] == "New Income Cat"
            assert li["category"] == INC_NEW
            assert li["category_name"] == "New Income Cat"
            assert li["service_category_id"] == SVC_NEW
            assert li["service_category_name"] == "New Service Cat"


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════
def _first(coll: _Coll, **kw) -> Optional[Dict[str, Any]]:
    for r in coll.rows:
        if all(r.get(k) == v for k, v in kw.items()):
            return r
    return None
