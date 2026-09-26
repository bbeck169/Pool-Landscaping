"""Feb-2026 · income_categories validation-message tests.

Focused coverage for the 1-based row number + line-item description
prefix added to every ``HTTPException`` message emitted by the two
category validators
(:func:`routers.income_categories.validate_line_item_categories` and
:func:`routers.income_categories.validate_line_item_k71_categories`).

Contract locked here:

* Human ``message`` uses **1-based** row numbers matching what the
  operator sees in the inline editor (``line_items[1]`` renders as
  ``Line Item 2``).
* Human ``message`` embeds the line item's ``description`` in
  parentheses; missing / blank / non-string descriptions fall back
  to the codebase-standard ``Untitled`` sentinel.
* Machine-parseable ``field`` / ``line_index`` payload keys stay
  **0-based** so Pydantic-style ``loc`` consumers on the frontend
  keep working unchanged.

The three tests here exercise the ``category_required`` +
``archived_category`` branches of the first validator via the same
HTTP round-trip pattern already used by ``test_income_categories.py``.
A fourth test hits the direct-call surface of both validators via
the shared row-ref helper so the ``Line Item {N+1} (Untitled)``
formatting contract is proven at the smallest surface too.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from tests._shared_mongo import shared_db as _shared_db
from tests.test_income_categories import (
    _CACHE,
    _cleanup_tenant,
    _seed_admin_for,
    _seed_customer,
    _seed_isolated_tenant,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_db = _shared_db()


def _trigger_seed(tok: str) -> None:
    """Force the tenant's income_categories default seed. Category
    enforcement short-circuits on empty available lists so the test
    payload must ride on top of the seeded default set."""
    requests.get(
        f"{API}/income-categories",
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    )


# ─────────────────────────────────────────────────────────────────
# 1 · 1-based row numbers on validation-required errors
# ─────────────────────────────────────────────────────────────────
def test_category_required_error_uses_one_based_row_on_second_row():
    """Row at ``line_items[1]`` (0-based) must render as
    ``Line Item 2`` in the human message. Backend-facing keys
    (``field`` / ``line_index``) stay 0-based."""
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    cid = _seed_customer(tid)
    try:
        _trigger_seed(tok)
        # Row 0 valid (has a valid category name from the seed);
        # row 1 has an explicit empty category so validation
        # complains about the SECOND row — the row the operator
        # sees as "Line Item 2" in the editor.
        payload = {
            "customer_id": cid,
            "title": "TEST_row_num_2",
            "doc_type": "invoice",
            "tax_rate": 0,
            "line_items": [
                {"description": "Weekly pool service",
                 "quantity": 1, "unit_price": 100,
                 "category": "Pool"},
                {"description": "Second row broken",
                 "quantity": 1, "unit_price": 50,
                 "category": ""},
            ],
        }
        r = requests.post(
            f"{API}/quotes", json=payload,
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "category_required"
        # Human-facing message MUST use 1-based row number.
        assert "Line Item 2" in detail["message"], detail["message"]
        # Machine-parseable payload MUST stay 0-based.
        assert detail["field"] == "line_items[1].category"
        assert detail["line_index"] == 1
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────────────────────────────────────────────────────────
# 2 · description is embedded in the human message
# ─────────────────────────────────────────────────────────────────
def test_category_required_error_embeds_description_when_present():
    """When the offending row has a ``description``, the human
    message must include it in parentheses so an operator with
    many line items can pinpoint the exact row."""
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    cid = _seed_customer(tid)
    try:
        _trigger_seed(tok)
        payload = {
            "customer_id": cid,
            "title": "TEST_desc_in_msg",
            "doc_type": "invoice",
            "tax_rate": 0,
            "line_items": [
                {"description": "Chlorine tabs delivery",
                 "quantity": 1, "unit_price": 40,
                 "category": ""},
            ],
        }
        r = requests.post(
            f"{API}/quotes", json=payload,
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        # Row 0 → user-facing "Line Item 1".
        assert "Line Item 1" in detail["message"], detail["message"]
        # Description embedded in parentheses.
        assert "(Chlorine tabs delivery)" in detail["message"], (
            detail["message"]
        )
        # Machine-parseable key stays 0-based.
        assert detail["field"] == "line_items[0].category"
        assert detail["line_index"] == 0
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────────────────────────────────────────────────────────
# 3 · Fallback to "Untitled" when description missing
# ─────────────────────────────────────────────────────────────────
def test_archived_category_error_uses_untitled_when_description_blank():
    """Row with an empty / whitespace-only / missing description
    falls back to the codebase-standard ``Untitled`` sentinel. Also
    proves the fallback lands on the archived/unknown-category
    branch (``error_code=archived_category``), NOT only on the
    missing-category branch."""
    tid = _seed_isolated_tenant()
    uid, email, tok = _seed_admin_for(tid)
    cid = _seed_customer(tid)
    try:
        _trigger_seed(tok)
        payload = {
            "customer_id": cid,
            "title": "TEST_untitled_fallback",
            "doc_type": "invoice",
            "tax_rate": 0,
            "line_items": [
                # Description explicit blank string → the helper
                # falls back to ``Untitled``. Category is a
                # nonsense string so we hit the archived/unknown
                # branch, not the missing branch.
                # (An OMITTED description is rejected by the
                # LineItem Pydantic model with a 422 before our
                # validator even runs, so the fallback contract is
                # exercised via the explicit-blank case here.)
                {"description": "",
                 "quantity": 1, "unit_price": 50,
                 "category": "nonsense-category-xyz"},
            ],
        }
        r = requests.post(
            f"{API}/quotes", json=payload,
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert detail["error_code"] == "archived_category", detail
        assert "Line Item 1" in detail["message"], detail["message"]
        assert "(Untitled)" in detail["message"], detail["message"]
        # Machine-parseable key stays 0-based.
        assert detail["field"] == "line_items[0].category"
        assert detail["line_index"] == 0
    finally:
        _db.users.delete_one({"id": uid})
        _CACHE.pop(f"tok:{email}", None)
        _cleanup_tenant(tid)


# ─────────────────────────────────────────────────────────────────
# 4 · Direct-call surface — _line_item_row_ref helper
# ─────────────────────────────────────────────────────────────────
def test_line_item_row_ref_helper_formatting_contract():
    """Direct-call proof for the row-ref helper so any future
    refactor keeps the 1-based + Untitled fallback contract."""
    from routers.income_categories import _line_item_row_ref
    # idx=0 → row 1
    assert _line_item_row_ref(0, {"description": "Pool cleaning"}) == (
        "Line Item 1 (Pool cleaning)"
    )
    # idx=4 → row 5 (proves 1-based conversion holds beyond 0/1)
    assert _line_item_row_ref(4, {"description": "Extra visit"}) == (
        "Line Item 5 (Extra visit)"
    )
    # Description omitted → Untitled.
    assert _line_item_row_ref(1, {}) == "Line Item 2 (Untitled)"
    # Description explicit blank / whitespace-only → Untitled.
    assert _line_item_row_ref(2, {"description": ""}) == (
        "Line Item 3 (Untitled)"
    )
    assert _line_item_row_ref(3, {"description": "   "}) == (
        "Line Item 4 (Untitled)"
    )
    # Description explicit None → Untitled.
    assert _line_item_row_ref(0, {"description": None}) == (
        "Line Item 1 (Untitled)"
    )
    # Non-string description (defensive) → Untitled — the raw
    # payload never survives Pydantic validation this deep, but the
    # helper stays defensive so a mis-typed field never crashes the
    # error-message builder.
    assert _line_item_row_ref(0, {"description": 42}) == (
        "Line Item 1 (Untitled)"
    )
    # None li dict (defensive against callers passing None instead
    # of the raw payload) → Untitled + still 1-based.
    assert _line_item_row_ref(0, None) == "Line Item 1 (Untitled)"
