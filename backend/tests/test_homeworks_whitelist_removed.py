"""TD-homeworks-connection-remove-audit · R4 · Feb-2026 — guard
tests for the removal of the ``slug == "homeworks"`` whitelist
branches from ``routers/suppliers.py``.

Pre-R4 the suppliers router had two escape hatches that let the
retired Phase 55-b Homeworks (Copilot CRM) importer piggyback on
the wholesale-supplier session-upload plumbing:

  1. ``_assert_handoff_supported("homeworks")`` returned early.
  2. ``POST /suppliers/{slug}/sessions`` skipped
     ``_get_supplier_or_404`` when ``slug == "homeworks"``.

Both branches are dead post-K55.b (the importer that used them was
removed) and lingered as unreachable code.  R4 removed the branches
so a request with ``slug="homeworks"`` now falls through to the
standard unknown-supplier path and returns 404.  These tests lock
that behavior.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException


# ─── _assert_handoff_supported must now 404 on "homeworks" ──────────
def test_assert_handoff_supported_homeworks_now_returns_404():
    """R4 regression lock — ``homeworks`` is no longer a whitelist.

    Before R4 this call returned ``None`` (early-exit on the
    whitelist branch).  After R4 the function falls through to the
    ``CONNECTORS.get(slug) is None`` branch and raises 404.
    """
    from routers.suppliers import _assert_handoff_supported

    with pytest.raises(HTTPException) as ex:
        _assert_handoff_supported("homeworks")
    assert ex.value.status_code == 404
    assert ex.value.detail["error"] == "unknown_supplier"
    assert ex.value.detail["supplier_slug"] == "homeworks"


# ─── Source-shape lock on the two removed branches ─────────────────
def test_homeworks_whitelist_branches_are_gone_from_source():
    """Defense-in-depth: assert the pre-R4 escape hatches are not
    sneakily restored in a future commit.  The branches were:

      * ``if slug == "homeworks": return`` in ``_assert_handoff_supported``
      * ``if slug != "homeworks": await _get_supplier_or_404(…)`` in
        ``POST /suppliers/{slug}/sessions``
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent
           / "routers" / "suppliers.py").read_text()

    # No literal string match for either whitelist branch pattern.
    assert 'if slug == "homeworks":' not in src, (
        "R4 regression — _assert_handoff_supported() whitelist for "
        "'homeworks' has been restored.  This slug must 404 post-K55.b."
    )
    assert 'if slug != "homeworks":' not in src, (
        "R4 regression — POST /suppliers/{slug}/sessions ``!= 'homeworks'`` "
        "escape hatch has been restored.  All slugs must now hit "
        "_get_supplier_or_404()."
    )
