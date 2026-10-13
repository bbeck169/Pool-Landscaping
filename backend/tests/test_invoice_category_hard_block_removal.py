"""Feb-2026 - invoice-category hard-block removal.

Covers the backend contract shift:
  * ``validate_line_item_categories`` + ``validate_line_item_k71_categories``
    accept a ``strict=False`` kwarg that demotes 400 raises to
    ``logger.info`` lines.
  * ``check_line_items_k71_gaps`` keeps returning line indices
    for status-change / approve / convert sites but the gate
    sites no longer raise - they log + audit.
  * ``scan_line_item_category_warnings`` buckets rows into
    uncategorized vs inactive-category counts for the audit row.
  * ``write_category_warnings_audit`` writes one
    ``audit_logs`` row with ``action="invoices.saved_with_category_warnings"``
    when (and only when) warnings exist. No-op on clean saves.

Unit-tested with asyncio.run + a FakeDB that honours the ops
the helpers use (``find.to_list`` for the categories lookup +
``audit_logs.insert_one``).  Live-server integration (POST
/api/quotes etc.) is covered by the existing phase-26b suite.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

from services.invoices.line_item_category_audit import (  # noqa: E402
    scan_line_item_category_warnings,
    write_category_warnings_audit,
)


# ═════════════════════════════════════════════════════════════
# Tiny FakeDB — just enough to exercise the validators + the
# audit writer without a live Mongo.
# ═════════════════════════════════════════════════════════════
class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted: list = []
        self.updated: list = []

    def find(self, *_args, **_kwargs):
        rows = list(self.rows)

        class _Cursor:
            def __init__(self_cur, rows):
                self_cur.rows = rows

            async def to_list(self_cur, _limit):
                return list(self_cur.rows)

            def __aiter__(self_cur):
                self_cur._it = iter(self_cur.rows)
                return self_cur

            async def __anext__(self_cur):
                try:
                    return next(self_cur._it)
                except StopIteration:
                    raise StopAsyncIteration

        return _Cursor(rows)

    async def find_one(self, *_a, **_kw):
        return self.rows[0] if self.rows else None

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return type("_Res", (), {"inserted_id": doc.get("id")})()


class _FakeDB:
    def __init__(self, *, income=None, service=None, migrations=None):
        self.income_categories = _FakeCollection(income or [])
        self.service_categories = _FakeCollection(service or [])
        self.audit_logs = _FakeCollection()
        self.migrations = _FakeCollection(migrations or [])


# ═════════════════════════════════════════════════════════════
# scan_line_item_category_warnings - pure function tests
# ═════════════════════════════════════════════════════════════
def test_scan_zero_warnings_on_fully_populated_line_items():
    scan = scan_line_item_category_warnings(
        [{
            "service_category_id": "svc-1",
            "income_category_id": "inc-1",
            "description": "ok",
        }],
        inc_active_ids={"inc-1"}, inc_active_names=set(),
        svc_active_ids={"svc-1"}, svc_active_names=set(),
    )
    assert scan["uncategorized_count"] == 0
    assert scan["inactive_category_line_item_count"] == 0
    assert scan["uncategorized_line_indices"] == []
    assert scan["inactive_category_line_indices"] == []


def test_scan_buckets_missing_k71_as_uncategorized():
    scan = scan_line_item_category_warnings(
        [
            {"service_category_id": "", "income_category_id": "",
              "description": "missing both"},
            {"service_category_id": "svc-1", "income_category_id": "",
              "description": "missing inc only"},
        ],
        inc_active_ids={"inc-1"}, inc_active_names=set(),
        svc_active_ids={"svc-1"}, svc_active_names=set(),
    )
    assert scan["uncategorized_count"] == 2
    assert scan["uncategorized_line_indices"] == [0, 1]
    assert scan["inactive_category_line_item_count"] == 0


def test_scan_buckets_unknown_service_or_income_as_inactive():
    scan = scan_line_item_category_warnings(
        [
            {"service_category_id": "svc-ARCHIVED",
              "income_category_id": "inc-1",
              "description": "archived svc"},
            {"service_category_id": "svc-1",
              "income_category_id": "inc-ARCHIVED",
              "description": "archived inc"},
        ],
        inc_active_ids={"inc-1"}, inc_active_names=set(),
        svc_active_ids={"svc-1"}, svc_active_names=set(),
    )
    assert scan["inactive_category_line_item_count"] == 2
    assert scan["inactive_category_line_indices"] == [0, 1]
    assert scan["uncategorized_count"] == 0


def test_scan_legacy_single_taxonomy_row_missing_category():
    scan = scan_line_item_category_warnings(
        [{"category": "", "description": "legacy empty"}],
        inc_active_ids={"chemicals"}, inc_active_names={"chemicals"},
    )
    assert scan["uncategorized_count"] == 1


def test_scan_auto_mapped_cleared_row_counted_uncategorized():
    scan = scan_line_item_category_warnings(
        [{
            "service_category_id": "", "income_category_id": "",
            "category_auto_mapped": True,
            "description": "auto-mapped post-archive",
        }],
        inc_active_ids={"inc-1"}, svc_active_ids={"svc-1"},
    )
    assert scan["uncategorized_count"] == 1


# ═════════════════════════════════════════════════════════════
# write_category_warnings_audit - no-op when clean
# ═════════════════════════════════════════════════════════════
def test_audit_noop_when_no_warnings():
    db = _FakeDB()
    asyncio.run(write_category_warnings_audit(
        db, tenant_id="t1", actor_id="u1", invoice_id="inv1",
        scan={
            "uncategorized_count": 0,
            "inactive_category_line_item_count": 0,
            "uncategorized_line_indices": [],
            "inactive_category_line_indices": [],
        },
        source="invoice_create",
    ))
    assert db.audit_logs.inserted == []


def test_audit_writes_one_row_with_correct_payload():
    db = _FakeDB()
    asyncio.run(write_category_warnings_audit(
        db, tenant_id="t1", actor_id="u1", invoice_id="inv1",
        scan={
            "uncategorized_count": 2,
            "inactive_category_line_item_count": 1,
            "uncategorized_line_indices": [0, 3],
            "inactive_category_line_indices": [2],
        },
        source="invoice_create",
    ))
    assert len(db.audit_logs.inserted) == 1
    row = db.audit_logs.inserted[0]
    assert row["action"] == "invoices.saved_with_category_warnings"
    assert row["tenant_id"] == "t1"
    assert row["actor_id"] == "u1"
    assert row["invoice_id"] == "inv1"
    assert row["source"] == "invoice_create"
    assert row["uncategorized_line_item_count"] == 2
    assert row["inactive_category_line_item_count"] == 1
    assert row["uncategorized_line_indices"] == [0, 3]
    assert row["inactive_category_line_indices"] == [2]
    assert "created_at" in row


# ═════════════════════════════════════════════════════════════
# validate_line_item_k71_categories - strict kwarg behavior
# ═════════════════════════════════════════════════════════════
async def _patch_validator_db(fake_db, monkeypatch):
    """The validator reads the module-level ``db`` -- patch it."""
    import routers.income_categories as m
    monkeypatch.setattr(m, "db", fake_db)
    # ensure_defaults sentinel-checks m.db.migrations; stub it out.
    async def _ensure_defaults(_tid):
        return None
    monkeypatch.setattr(m, "ensure_defaults_for_tenant", _ensure_defaults)
    import routers.service_categories as sm
    monkeypatch.setattr(sm, "ensure_defaults_for_tenant", _ensure_defaults)


def test_k71_validator_raises_on_missing_service_when_strict(monkeypatch):
    from routers.income_categories import validate_line_item_k71_categories
    fake = _FakeDB(
        income=[{"id": "inc-1", "name": "Chemicals"}],
        service=[{"id": "svc-1", "name": "Service"}],
    )
    asyncio.run(_patch_validator_db(fake, monkeypatch))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(validate_line_item_k71_categories(
            "t1", [{"service_category_id": "", "income_category_id": "inc-1",
                      "description": "x"}],
            strict=True,
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "service_category_required"


def test_k71_validator_lenient_logs_but_does_not_raise(monkeypatch, caplog):
    from routers.income_categories import validate_line_item_k71_categories
    fake = _FakeDB(
        income=[{"id": "inc-1", "name": "Chemicals"}],
        service=[{"id": "svc-1", "name": "Service"}],
    )
    asyncio.run(_patch_validator_db(fake, monkeypatch))
    with caplog.at_level("INFO"):
        asyncio.run(validate_line_item_k71_categories(
            "t1",
            [
                {"service_category_id": "", "income_category_id": "inc-1",
                  "description": "missing svc"},
                {"service_category_id": "svc-1", "income_category_id": "",
                  "description": "missing inc"},
                {"service_category_id": "svc-X", "income_category_id": "inc-1",
                  "description": "unknown svc"},
            ],
            strict=False,
        ))
    # No raise -> we got here. Check the lenient log line fired.
    assert any(
        "invoices.category_warning" in r.message
        for r in caplog.records
    )


# ═════════════════════════════════════════════════════════════
# validate_line_item_categories - legacy single-tax strict kwarg
# ═════════════════════════════════════════════════════════════
def test_legacy_validator_raises_on_missing_category_when_strict(monkeypatch):
    from routers.income_categories import validate_line_item_categories
    fake = _FakeDB(income=[{"id": "inc-1", "name": "Chemicals"}])
    asyncio.run(_patch_validator_db(fake, monkeypatch))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(validate_line_item_categories(
            "t1", [{"category": "", "description": "missing"}],
            strict=True,
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "category_required"


def test_legacy_validator_lenient_does_not_raise(monkeypatch):
    from routers.income_categories import validate_line_item_categories
    fake = _FakeDB(income=[{"id": "inc-1", "name": "Chemicals"}])
    asyncio.run(_patch_validator_db(fake, monkeypatch))
    # No raise -> success.
    asyncio.run(validate_line_item_categories(
        "t1", [{"category": "", "description": "missing"}],
        strict=False,
    ))


# ═════════════════════════════════════════════════════════════
# check_line_items_k71_gaps - unchanged behaviour (helper used
# by status-change / approve / convert sites). Smoke test to
# lock the shape the audit path reuses.
# ═════════════════════════════════════════════════════════════
def test_check_line_items_k71_gaps_returns_indices_for_missing_pair():
    from routers.income_categories import check_line_items_k71_gaps
    gaps = check_line_items_k71_gaps([
        {"service_category_id": "svc-1", "income_category_id": "inc-1"},
        {"service_category_id": "", "income_category_id": "inc-1"},
        {"service_category_id": "svc-1", "income_category_id": ""},
    ])
    assert gaps == [1, 2]


def test_check_line_items_k71_gaps_empty_for_legacy_rows():
    from routers.income_categories import check_line_items_k71_gaps
    # Neither K71 field present -> legacy, grandfathered.
    assert check_line_items_k71_gaps([
        {"description": "pre-K71", "category": "Chemicals"},
    ]) == []
