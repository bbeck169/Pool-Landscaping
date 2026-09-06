"""Phase K71 · Feb-2026 — Estimate Line Item Edit + Description +
Service/Income Categories.

Coverage:
  1. income_categories.ensure_defaults_for_tenant additive merge
     (K71 switched from "only if empty" to case-insensitive merge).
  2. service_categories.ensure_defaults_for_tenant seed includes
     the K71 additive names.
  3. validate_line_item_k71_categories:
     * Legacy line (no K71 fields) passes.
     * K71-touched line missing service_category_id raises 400
       ``k71_service_category_required``.
     * K71-touched line missing income_category_id raises 400
       ``k71_income_category_required``.
     * K71-touched line with unknown ids raises 400 ``_invalid``.
     * K71-touched line with both valid ids passes.
  4. check_line_items_k71_gaps read-side helper flags K71-touched
     lines with missing pairs, ignores legacy items.
  5. LineItem Pydantic model accepts long_description +
     service_category_id and enforces via router 500-char cap.

Uses ephemeral tenant scoping — no prod-tenant contamination.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient


load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_LOOP = asyncio.new_event_loop()
_MOTOR = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
_DB = _MOTOR[os.environ["DB_NAME"]]


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture
def k71_db(monkeypatch):
    """Rebind ``config.db`` to the shared test loop so the routers'
    module-level ``db`` symbol resolves to our loop-bound client."""
    import config as _config_mod
    monkeypatch.setattr(_config_mod, "db", _DB)
    # income_categories and service_categories both import ``db`` at
    # module scope from config — patch each so their references
    # follow.
    from routers import income_categories as _ic
    from routers import service_categories as _sc
    monkeypatch.setattr(_ic, "db", _DB)
    monkeypatch.setattr(_sc, "db", _DB)
    yield _DB


@pytest.fixture
def k71_tenant(k71_db):
    tid = f"test_k71_{uuid.uuid4().hex[:8]}"
    yield tid
    # Cleanup — remove any inserted seed rows so subsequent tests
    # can re-seed cleanly.
    _run(_DB.income_categories.delete_many({"tenant_id": tid}))
    _run(_DB.service_categories.delete_many({"tenant_id": tid}))


# ═════════════════════════════════════════════════════════════════
# 1 · Additive seed
# ═════════════════════════════════════════════════════════════════
def test_income_categories_additive_seed(k71_tenant):
    from routers.income_categories import ensure_defaults_for_tenant

    _run(_DB.income_categories.insert_one(
        {"id": str(uuid.uuid4()), "name": "Pool", "tenant_id": k71_tenant,
         "is_archived": False}))
    _run(ensure_defaults_for_tenant(k71_tenant))
    rows = _run(_DB.income_categories.find(
        {"tenant_id": k71_tenant}, {"_id": 0, "name": 1}).to_list(500))
    names = {r["name"].lower() for r in rows}
    # Pre-existing "Pool" survived + K71 defaults added.
    assert "pool" in names
    assert "service revenue" in names
    assert "recurring maintenance" in names
    assert "labor income" in names
    # Case-insensitive dedupe: only one "Pool".
    assert sum(1 for r in rows if r["name"].lower() == "pool") == 1


def test_service_categories_seed_includes_k71_names(k71_tenant):
    from routers.service_categories import ensure_defaults_for_tenant
    _run(ensure_defaults_for_tenant(k71_tenant))
    rows = _run(_DB.service_categories.find(
        {"tenant_id": k71_tenant}, {"_id": 0, "name": 1}).to_list(500))
    names = {r["name"].lower() for r in rows}
    for n in ("equipment install", "chemical treatment", "inspection",
              "landscape", "hardscape", "lighting", "other"):
        assert n in names, f"missing K71 seed: {n}"


# ═════════════════════════════════════════════════════════════════
# 2 · K71 validation
# ═════════════════════════════════════════════════════════════════
def _seed_tenant_categories(tenant_id):
    """Insert one active svc + income category and return their ids."""
    svc_id = str(uuid.uuid4())
    inc_id = str(uuid.uuid4())
    _run(_DB.service_categories.insert_one(
        {"id": svc_id, "name": "K71 Svc", "tenant_id": tenant_id,
         "is_archived": False}))
    _run(_DB.income_categories.insert_one(
        {"id": inc_id, "name": "K71 Inc", "tenant_id": tenant_id,
         "is_archived": False}))
    return svc_id, inc_id


def test_k71_legacy_line_passes(k71_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    # Legacy line — no K71 fields, ``category`` legacy string present.
    line = {"description": "Legacy line", "quantity": 1,
            "unit_price": 10.0, "category": "Pool"}
    # Should NOT raise.
    _run(validate_line_item_k71_categories(k71_tenant, [line]))


def test_k71_missing_service_category_raises(k71_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    _, inc_id = _seed_tenant_categories(k71_tenant)
    line = {"description": "New K71 line", "quantity": 1,
            "unit_price": 10.0,
            "service_category_id": "",
            "income_category_id": inc_id}
    with pytest.raises(HTTPException) as exc:
        _run(validate_line_item_k71_categories(k71_tenant, [line]))
    assert exc.value.status_code == 400
    assert exc.value.detail["error_code"] == "k71_service_category_required"


def test_k71_missing_income_category_raises(k71_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    svc_id, _ = _seed_tenant_categories(k71_tenant)
    line = {"description": "New K71 line", "quantity": 1,
            "unit_price": 10.0,
            "service_category_id": svc_id,
            "income_category_id": ""}
    with pytest.raises(HTTPException) as exc:
        _run(validate_line_item_k71_categories(k71_tenant, [line]))
    assert exc.value.status_code == 400
    assert exc.value.detail["error_code"] == "k71_income_category_required"


def test_k71_invalid_service_id_raises(k71_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    _, inc_id = _seed_tenant_categories(k71_tenant)
    line = {"description": "Bogus", "quantity": 1, "unit_price": 5,
            "service_category_id": "nonexistent-uuid",
            "income_category_id": inc_id}
    with pytest.raises(HTTPException) as exc:
        _run(validate_line_item_k71_categories(k71_tenant, [line]))
    assert exc.value.status_code == 400
    assert exc.value.detail["error_code"] == "k71_service_category_invalid"


def test_k71_valid_pair_passes(k71_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    svc_id, inc_id = _seed_tenant_categories(k71_tenant)
    line = {"description": "Good", "quantity": 2, "unit_price": 25,
            "service_category_id": svc_id,
            "income_category_id": inc_id}
    _run(validate_line_item_k71_categories(k71_tenant, [line]))  # no raise


# ═════════════════════════════════════════════════════════════════
# 3 · Gap detection (send/approve/convert gate)
# ═════════════════════════════════════════════════════════════════
def test_k71_gap_detection_flags_touched_missing():
    from routers.income_categories import check_line_items_k71_gaps
    lines = [
        # 0: legacy line — no K71 fields — should be ignored.
        {"description": "Legacy", "quantity": 1, "unit_price": 5},
        # 1: K71-touched, missing income — should be flagged.
        {"description": "Half-set", "quantity": 1, "unit_price": 5,
         "service_category_id": "svc-1", "income_category_id": ""},
        # 2: K71-touched, complete — should not flag.
        {"description": "OK", "quantity": 1, "unit_price": 5,
         "service_category_id": "svc-1", "income_category_id": "inc-1"},
        # 3: K71-touched via income only, missing service.
        {"description": "Half-set-2", "quantity": 1, "unit_price": 5,
         "income_category_id": "inc-1"},
    ]
    gaps = check_line_items_k71_gaps(lines)
    assert gaps == [1, 3]


# ═════════════════════════════════════════════════════════════════
# 4 · LineItem model accepts K71 fields
# ═════════════════════════════════════════════════════════════════
def test_line_item_model_accepts_k71_fields():
    from models import LineItem
    li = LineItem(description="Test", quantity=1, unit_price=10,
                  long_description="Multi-line detail",
                  service_category_id="svc-uuid",
                  income_category_id="inc-uuid")
    assert li.long_description == "Multi-line detail"
    assert li.service_category_id == "svc-uuid"
    assert li.income_category_id == "inc-uuid"


def test_line_item_model_defaults_grandfather():
    from models import LineItem
    li = LineItem(description="Legacy", quantity=1, unit_price=10)
    assert li.long_description is None
    assert li.service_category_id is None
    assert li.income_category_id is None


# ═════════════════════════════════════════════════════════════════
# 5 · invoice_edit long_description 500-char cap
# ═════════════════════════════════════════════════════════════════
def test_invoice_edit_long_description_500_char_cap():
    from routers.invoice_edit import _validate_line_items
    items = [{"description": "OK", "quantity": 1, "unit_price": 5,
              "long_description": "a" * 501}]
    with pytest.raises(HTTPException) as exc:
        _validate_line_items(items)
    assert exc.value.status_code == 400
    assert "500" in str(exc.value.detail)


def test_invoice_edit_long_description_accepts_500_chars():
    from routers.invoice_edit import _validate_line_items
    items = [{"description": "OK", "quantity": 1, "unit_price": 5,
              "long_description": "a" * 500}]
    cleaned = _validate_line_items(items)
    assert cleaned[0]["long_description"] == "a" * 500
