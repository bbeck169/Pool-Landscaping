"""Feb-2026 · Track 3 — regression tests for the per-line ``total``
fallback in ``routers.estimate_viewer._build_payload``.

Background: historical quote write paths (``routers/quotes.py``,
``routers/estimator.py``) do NOT persist per-line ``total`` or
``line_total``. The admin React UI survived this by computing
``qty × unit_price`` client-side; the customer-facing
``EstimateView`` ungrouped table read ``li.total`` bare and
rendered blank cells. The serializer now injects a computed
``total`` BEFORE the ``as_customer`` branch so both admin and
public payloads carry a numeric value, mirroring the customer PDF
``_lt_raw`` fallback.

These tests exercise ``_build_payload`` directly with handcrafted
``est`` / ``tenant`` dicts to avoid the DB fixture overhead.
Mongodb lookups inside the helper are mocked so the test is pure.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mk_est(line_items):
    return {
        "id": "q-test-tot",
        "tenant_id": "t-x",
        "customer_id": "c-x",
        "doc_type": "quote",
        "status": "sent",
        "subtotal": 150.0,
        "tax": 0.0,
        "total": 150.0,
        "line_items": line_items,
    }


def test_total_fallback_emits_qty_times_unit_price_when_null():
    """When stored ``total`` and ``line_total`` are both null the
    serializer must emit a numeric ``total = round(qty * unit_price, 2)``
    on EVERY line item — on both admin and public payloads."""
    from routers import estimate_viewer

    lines = [
        {"description": "Skimmer", "quantity": 1,   "unit_price": 100.0,
         "total": None, "line_total": None},
        {"description": "Chems",   "quantity": 2.5, "unit_price": 50.0,
         "total": None, "line_total": None},
        {"description": "Bush",    "quantity": 3,   "unit_price": 25.33,
         "total": None, "line_total": None},
    ]
    est = _mk_est(lines)
    tenant = {"id": "t-x", "name": "Test"}

    # Patch Mongo and helpers inline
    with (
        patch("routers.estimate_viewer._load_company", new=AsyncMock(return_value={})),
        patch("routers.estimate_viewer._load_customer", new=AsyncMock(return_value={})),
        patch.object(estimate_viewer, "db") as _db_mock,
        patch("services.quotes.customer_view.build_customer_view_payload",
              return_value={"groups": []}),
        patch("services.quotes.totals.recompute_customer_adjusted_totals",
              return_value={
                  "original_subtotal": 0, "original_discount_value": 0,
                  "original_tax": 0, "original_total": 0,
                  "adjusted_subtotal": 0, "adjusted_discount_value": 0,
                  "adjusted_tax": 0, "adjusted_total": 0,
                  "has_declined_lines": False, "declined_line_count": 0,
              }),
    ):
        # service_categories.find(...).to_list(...) → empty list
        _db_mock.service_categories.find.return_value.to_list = AsyncMock(return_value=[])
        _db_mock.properties.find_one = AsyncMock(return_value=None)
        _db_mock.files.find.return_value.to_list = AsyncMock(return_value=[])

        public = _run(estimate_viewer._build_payload(est, tenant, as_customer=True))
        admin  = _run(estimate_viewer._build_payload(est, tenant, as_customer=False))

    # Expected: 1*100=100.0, 2.5*50=125.0, 3*25.33=75.99
    expected = [100.0, 125.0, 75.99]
    for i, exp in enumerate(expected):
        assert public["line_items"][i]["total"] == exp, (
            f"public[{i}].total = {public['line_items'][i].get('total')!r}, expected {exp}"
        )
        assert admin["line_items"][i]["total"] == exp, (
            f"admin[{i}].total = {admin['line_items'][i].get('total')!r}, expected {exp}"
        )


def test_total_fallback_preserves_stored_total_when_set():
    """A pre-existing ``total`` must NOT be overwritten by the
    fallback. This guards against double-compute if a future write
    path starts persisting totals."""
    from routers import estimate_viewer

    lines = [
        # Pre-set total takes priority
        {"description": "A", "quantity": 1, "unit_price": 100.0, "total": 99.99},
        # line_total is set but total is null — fallback must NOT fire
        {"description": "B", "quantity": 2, "unit_price": 50.0,
         "total": None, "line_total": 101.0},
    ]
    est = _mk_est(lines)
    tenant = {"id": "t-x", "name": "Test"}

    with (
        patch("routers.estimate_viewer._load_company", new=AsyncMock(return_value={})),
        patch("routers.estimate_viewer._load_customer", new=AsyncMock(return_value={})),
        patch.object(estimate_viewer, "db") as _db_mock,
        patch("services.quotes.customer_view.build_customer_view_payload",
              return_value={"groups": []}),
        patch("services.quotes.totals.recompute_customer_adjusted_totals",
              return_value={
                  "original_subtotal": 0, "original_discount_value": 0,
                  "original_tax": 0, "original_total": 0,
                  "adjusted_subtotal": 0, "adjusted_discount_value": 0,
                  "adjusted_tax": 0, "adjusted_total": 0,
                  "has_declined_lines": False, "declined_line_count": 0,
              }),
    ):
        _db_mock.service_categories.find.return_value.to_list = AsyncMock(return_value=[])
        _db_mock.properties.find_one = AsyncMock(return_value=None)
        _db_mock.files.find.return_value.to_list = AsyncMock(return_value=[])

        public = _run(estimate_viewer._build_payload(est, tenant, as_customer=True))

    # Row 0 must keep the pre-set 99.99 (not 100.0)
    assert public["line_items"][0]["total"] == 99.99
    # Row 1 must keep total=None (fallback only fires when BOTH are null;
    # line_total being set means the stored path is still authoritative)
    assert public["line_items"][1].get("total") is None
    assert public["line_items"][1].get("line_total") == 101.0


def test_total_fallback_zero_quantity_emits_zero_not_null():
    """Degenerate numeric cells (qty=0 or unit_price=0) must emit
    0.0, not None — the frontend ``??`` fallback trusts non-null
    numeric values and a null here would cascade to a blank cell."""
    from routers import estimate_viewer

    lines = [
        {"description": "Freebie", "quantity": 0, "unit_price": 50.0,
         "total": None, "line_total": None},
        {"description": "No-price", "quantity": 3, "unit_price": None,
         "total": None, "line_total": None},
    ]
    est = _mk_est(lines)
    tenant = {"id": "t-x", "name": "Test"}

    with (
        patch("routers.estimate_viewer._load_company", new=AsyncMock(return_value={})),
        patch("routers.estimate_viewer._load_customer", new=AsyncMock(return_value={})),
        patch.object(estimate_viewer, "db") as _db_mock,
        patch("services.quotes.customer_view.build_customer_view_payload",
              return_value={"groups": []}),
        patch("services.quotes.totals.recompute_customer_adjusted_totals",
              return_value={
                  "original_subtotal": 0, "original_discount_value": 0,
                  "original_tax": 0, "original_total": 0,
                  "adjusted_subtotal": 0, "adjusted_discount_value": 0,
                  "adjusted_tax": 0, "adjusted_total": 0,
                  "has_declined_lines": False, "declined_line_count": 0,
              }),
    ):
        _db_mock.service_categories.find.return_value.to_list = AsyncMock(return_value=[])
        _db_mock.properties.find_one = AsyncMock(return_value=None)
        _db_mock.files.find.return_value.to_list = AsyncMock(return_value=[])

        public = _run(estimate_viewer._build_payload(est, tenant, as_customer=True))

    assert public["line_items"][0]["total"] == 0.0
    assert public["line_items"][1]["total"] == 0.0
