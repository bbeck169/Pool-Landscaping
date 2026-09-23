"""Phase P40 · Feb-2026 — Line-item category validation guard
(upstream cure for the "UUIDs in Income by Category" bug).

The K71 write path already validates line_items[].service_category_id
and line_items[].income_category_id via
``validate_line_item_k71_categories`` in routers/income_categories.py.
Phase P40 augments its error payloads with the P40 response contract:

  * ``code`` (alias for ``error_code``) — stable client-side switch
    key ``"invalid_line_item_category"`` for all four branches so
    the FE can consolidate its error handler.
  * ``invalid_value`` — the offending id/string so the FE can show
    it verbatim to the operator.
  * ``available_categories`` — active tenant category names, so the
    FE can render a picker prefilled with valid options without a
    second round-trip.

Backward-compat: ``error_code`` and ``attempted`` keys remain in the
payload; existing tests + FE consumers keep working.

Uses the same ephemeral-tenant fixture as
``test_k71_line_item_edit_categories.py`` so no prod-tenant seed is
touched. Every test cleans up via the ``k71_tenant`` fixture.
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
def p40_db(monkeypatch):
    """Rebind ``config.db`` to the shared test loop-bound client so
    the router's module-level ``db`` symbol resolves to our
    fixture-owned collections."""
    import config as _config_mod
    monkeypatch.setattr(_config_mod, "db", _DB)
    from routers import income_categories as _ic
    from routers import service_categories as _sc
    monkeypatch.setattr(_ic, "db", _DB)
    monkeypatch.setattr(_sc, "db", _DB)
    yield _DB


@pytest.fixture
def p40_tenant(p40_db):
    tid = f"test_p40_{uuid.uuid4().hex[:8]}"
    yield tid
    _run(_DB.income_categories.delete_many({"tenant_id": tid}))
    _run(_DB.service_categories.delete_many({"tenant_id": tid}))


@pytest.fixture
def p40_other_tenant(p40_db):
    """Second tenant to prove no cross-tenant leakage in
    ``available_categories``."""
    tid = f"test_p40_other_{uuid.uuid4().hex[:8]}"
    yield tid
    _run(_DB.income_categories.delete_many({"tenant_id": tid}))
    _run(_DB.service_categories.delete_many({"tenant_id": tid}))


def _seed_active_pair(tenant_id, inc_name="P40 Income", svc_name="P40 Service"):
    """Insert one active svc + income category, return their ids."""
    svc_id = str(uuid.uuid4())
    inc_id = str(uuid.uuid4())
    _run(_DB.service_categories.insert_one(
        {"id": svc_id, "name": svc_name, "tenant_id": tenant_id,
         "is_archived": False}))
    _run(_DB.income_categories.insert_one(
        {"id": inc_id, "name": inc_name, "tenant_id": tenant_id,
         "is_archived": False}))
    return svc_id, inc_id


# ═════════════════════════════════════════════════════════════════
# Test 1 — Valid categories → validator does not raise (200 path).
# ═════════════════════════════════════════════════════════════════
def test_save_invoice_with_valid_categories_returns_200(p40_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    svc_id, inc_id = _seed_active_pair(p40_tenant)
    line = {"description": "OK", "quantity": 1, "unit_price": 10.0,
            "service_category_id": svc_id, "income_category_id": inc_id}
    # No raise = the router keeps going and would 200 the request.
    _run(validate_line_item_k71_categories(p40_tenant, [line]))


# ═════════════════════════════════════════════════════════════════
# Test 2 — Unresolvable UUID → 422-shaped error (400 in this API's
# convention) WITH ``available_categories`` listing active names.
# ═════════════════════════════════════════════════════════════════
def test_save_invoice_with_uuid_shaped_category_returns_422_with_available_list(
    p40_tenant,
):
    from routers.income_categories import validate_line_item_k71_categories
    svc_id, _inc_id = _seed_active_pair(
        p40_tenant, inc_name="Pool P40", svc_name="Service P40")
    # Bogus UUID that never existed.
    bad_uuid = "48cd653e-afc6-4864-a59b-47b7a0953b5c"
    line = {"description": "Bad", "quantity": 1, "unit_price": 25.0,
            "service_category_id": svc_id,
            "income_category_id": bad_uuid}
    with pytest.raises(HTTPException) as exc:
        _run(validate_line_item_k71_categories(p40_tenant, [line]))
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert detail["code"] == "invalid_line_item_category"
    assert detail["error_code"] == "k71_income_category_invalid"
    assert detail["invalid_value"] == bad_uuid
    # attempted alias preserved for backward compat.
    assert detail["attempted"] == bad_uuid
    assert isinstance(detail["available_categories"], list)
    assert "Pool P40" in detail["available_categories"]


# ═════════════════════════════════════════════════════════════════
# Test 3 — Archived (soft-deleted-equivalent) category rejected.
# ═════════════════════════════════════════════════════════════════
def test_save_invoice_with_deleted_category_returns_422(p40_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    svc_id, _inc_id = _seed_active_pair(p40_tenant)
    # Insert an ARCHIVED income category — validator MUST reject it.
    archived_id = str(uuid.uuid4())
    _run(_DB.income_categories.insert_one({
        "id": archived_id, "name": "Old Bucket",
        "tenant_id": p40_tenant, "is_archived": True,
    }))
    line = {"description": "Stale", "quantity": 1, "unit_price": 15,
            "service_category_id": svc_id,
            "income_category_id": archived_id}
    with pytest.raises(HTTPException) as exc:
        _run(validate_line_item_k71_categories(p40_tenant, [line]))
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert detail["code"] == "invalid_line_item_category"
    assert detail["invalid_value"] == archived_id
    # Archived category name MUST NOT appear in available list.
    assert "Old Bucket" not in detail["available_categories"]


# ═════════════════════════════════════════════════════════════════
# Test 4 — Contract shape assertion for the P40 handoff to the FE.
# ═════════════════════════════════════════════════════════════════
def test_error_response_shape_matches_contract(p40_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    svc_id, _ = _seed_active_pair(p40_tenant)
    line = {"description": "X", "quantity": 1, "unit_price": 1,
            "service_category_id": svc_id,
            "income_category_id": "not-a-real-id"}
    with pytest.raises(HTTPException) as exc:
        _run(validate_line_item_k71_categories(p40_tenant, [line]))
    detail = exc.value.detail
    # Every field in the P40 contract must be present.
    for key in ("code", "field", "invalid_value",
                "available_categories", "message", "line_index"):
        assert key in detail, f"missing contract key: {key!r} ({detail})"
    assert detail["field"] == "line_items[0].income_category_id"
    assert detail["line_index"] == 0
    assert isinstance(detail["available_categories"], list)


# ═════════════════════════════════════════════════════════════════
# Test 5 — Multiple invalid rows: router pattern = "raise on first",
# so the response reports the FIRST invalid row's context. Assert
# both the ``line_index`` AND that ``available_categories`` is
# present so the FE can render a picker for that row.
# ═════════════════════════════════════════════════════════════════
def test_multiple_invalid_categories_return_first_with_list(p40_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    svc_id, inc_id = _seed_active_pair(p40_tenant)
    good = {"description": "OK", "quantity": 1, "unit_price": 10,
            "service_category_id": svc_id, "income_category_id": inc_id}
    bad1 = {"description": "Bad1", "quantity": 1, "unit_price": 5,
            "service_category_id": svc_id,
            "income_category_id": "bogus-1"}
    bad2 = {"description": "Bad2", "quantity": 1, "unit_price": 5,
            "service_category_id": svc_id,
            "income_category_id": "bogus-2"}
    with pytest.raises(HTTPException) as exc:
        _run(validate_line_item_k71_categories(
            p40_tenant, [good, bad1, bad2]))
    detail = exc.value.detail
    # First invalid row is index 1 (bad1).
    assert detail["line_index"] == 1
    assert detail["invalid_value"] == "bogus-1"
    assert detail["code"] == "invalid_line_item_category"
    assert isinstance(detail["available_categories"], list)


# ═════════════════════════════════════════════════════════════════
# Test 6 — A pure legacy line (neither K71 field present, only a
# free-text ``category``) must pass this specific K71 validator so
# grandfathered invoices are not blocked at save time. Backward-compat.
# ═════════════════════════════════════════════════════════════════
def test_empty_category_still_passes(p40_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    _seed_active_pair(p40_tenant)
    legacy = {"description": "Legacy", "quantity": 1, "unit_price": 8,
              "category": "Pool"}  # no service_category_id, no income_category_id
    # No raise — legacy grandfathered.
    _run(validate_line_item_k71_categories(p40_tenant, [legacy]))


# ═════════════════════════════════════════════════════════════════
# Test 7 — Tenant scoping: tenant A's active list must NEVER include
# tenant B's category names. Regression against a resolver that
# forgot to scope the .find({"tenant_id": ...}) query.
# ═════════════════════════════════════════════════════════════════
def test_tenant_scoping_categories_list(p40_tenant, p40_other_tenant):
    from routers.income_categories import validate_line_item_k71_categories
    svc_a, _inc_a = _seed_active_pair(
        p40_tenant, inc_name="Tenant A Pool", svc_name="Tenant A Service")
    # Seed tenant B with a distinct-named category so we can detect
    # cross-tenant leakage in the error payload.
    _seed_active_pair(
        p40_other_tenant,
        inc_name="Tenant B Landscaping",
        svc_name="Tenant B Service B",
    )
    # Save an invoice for tenant A with a bogus income id → the
    # 400 response's available_categories must only list tenant A
    # names, never tenant B.
    line = {"description": "X", "quantity": 1, "unit_price": 1,
            "service_category_id": svc_a,
            "income_category_id": "no-such-id"}
    with pytest.raises(HTTPException) as exc:
        _run(validate_line_item_k71_categories(p40_tenant, [line]))
    avail = exc.value.detail["available_categories"]
    assert "Tenant A Pool" in avail
    assert "Tenant B Landscaping" not in avail, (
        f"cross-tenant leakage detected: {avail}"
    )
