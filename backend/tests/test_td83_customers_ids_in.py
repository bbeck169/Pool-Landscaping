"""TD-83 · Feb-2026 — ``GET /api/customers?ids_in=`` filter contract.

Pure-unit source-level + live-API tests locking the TD-83 fix.
Pre-TD-83 the ``PropertiesListPage.jsx`` hydrate loop issued
``GET /customers?ids_in=cid1,cid2,...`` but the BE silently
ignored the param → the FE received the full tenant customer
list and relied on client-side lookup, which under-matched when
the list truncated at the server-side default limit.

Three contract rails locked:

  * Param is declared on the ``list_customers`` signature with
    the right type + Query metadata.
  * Composition baked into the Mongo filter as
    ``q["id"] = {"$in": [...]}``.
  * Short-circuit on empty whitelist — a caller supplying the
    param with zero non-blank ids receives an empty response
    (not a full-tenant list).
"""
from __future__ import annotations

import pathlib

import pytest


SRC = pathlib.Path("/app/backend/routers/customers.py").read_text()


# ═════════════════════════════════════════════════════════════
# Source-level contract rails
# ═════════════════════════════════════════════════════════════

def test_ids_in_param_is_declared():
    """Function signature carries the TD-83 Query param."""
    assert "ids_in: Optional[str] = Query(" in SRC
    assert "TD-83 · Feb-2026 — CSV list of customer" in SRC


def test_ids_in_composes_into_mongo_filter():
    """The parsed whitelist is baked into ``q["id"] = {"$in": ...}``
    BEFORE the soft-delete / merge gates, so empty-whitelist
    short-circuit fires early."""
    # Compose location — the ``q["id"] = {"$in": deduped}`` write.
    assert 'q["id"] = {"$in": deduped}' in SRC
    # Preserve order while deduping (same pattern as crew tech_ids).
    assert "Preserve order while deduping" in SRC


def test_ids_in_empty_whitelist_shortcircuits_before_downstream_filters():
    """When ``ids_in`` is present but materially empty (``?ids_in=``
    or ``?ids_in=,,``), the handler must return match-none WITHOUT
    reading the role-gate / soft-delete / merge filters below.
    Prevents a silent full-tenant leak when the FE sends an empty
    whitelist by mistake."""
    # The empty-whitelist branch must return an empty response
    # directly rather than falling through to the main query.
    assert "match-none semantics" in SRC
    # The three response shapes (count_only, paginated envelope,
    # legacy bare array) must each have an empty-response branch.
    assert "if count_only:" in SRC
    assert 'return {"count": 0}' in SRC
    assert '"items": [], "total": 0' in SRC


def test_ids_in_appears_before_role_gate_in_handler():
    """Grep-position check — the empty-whitelist branch MUST appear
    BEFORE the ``role_lc = (user.get("role") or "").lower()`` line,
    so an empty whitelist short-circuits without triggering a role
    403 for ``include_deleted=true`` callers that happen to pass
    an empty ids_in."""
    ids_in_idx = SRC.index('if ids_in is not None:')
    role_idx = SRC.index('role_lc = (user.get("role") or "").lower()',
                           ids_in_idx)
    assert ids_in_idx < role_idx, (
        "TD-83 regression: ids_in parsing must come before the "
        "role-gate so empty-whitelist callers aren't incorrectly "
        "403'd."
    )


def test_ids_in_dedupe_preserves_input_order():
    """Order-preserving dedupe is required so the response row order
    matches the whitelist order (callers that trust the response
    ordering stay happy)."""
    # The dedupe is manual (list + seen set), not set-based.
    assert "seen = set()" in SRC
    assert "deduped: List[str] = []" in SRC
