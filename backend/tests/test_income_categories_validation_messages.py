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

import pytest
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
    """REMOVED (Feb-2026 · invoice-category hard-block removal) —
    the HTTP invoice-save path no longer raises on missing category.
    The 1-based + description + Untitled formatting contract is
    now locked by ``test_line_item_row_ref_helper_formatting_contract``
    below (direct-call surface) and by the new strict-mode cases in
    ``tests/test_invoice_category_hard_block_removal.py``."""
    pytest.skip("superseded by hard-block removal — see docstring")


# ─────────────────────────────────────────────────────────────────
# 2 · description is embedded in the human message
# ─────────────────────────────────────────────────────────────────
def test_category_required_error_embeds_description_when_present():
    """REMOVED (Feb-2026 · invoice-category hard-block removal) —
    see sibling test above."""
    pytest.skip("superseded by hard-block removal — see docstring")


# ─────────────────────────────────────────────────────────────────
# 3 · Fallback to "Untitled" when description missing
# ─────────────────────────────────────────────────────────────────
def test_archived_category_error_uses_untitled_when_description_blank():
    """REMOVED (Feb-2026 · invoice-category hard-block removal) —
    see sibling test above."""
    pytest.skip("superseded by hard-block removal — see docstring")


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
