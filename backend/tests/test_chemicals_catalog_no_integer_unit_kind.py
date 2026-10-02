"""Feb-2026 · Chemicals catalog audit — ``unit_kind`` must never be
``"integer"``.

The frontend readings form derives its ``<input step="…" />`` mask
from each catalog entry's ``unit_kind``: ``"integer"`` → ``step="1"``
(no fractional dosing possible), everything else → ``step="0.01"``.
Flipping the two historic integer entries (``chlorine_tabs``,
``salt``) to ``"decimal"`` unblocks the UI so users can enter
fractional dosing values. This test locks the invariant so no
future addition sneaks ``"integer"`` back in by accident.
"""
from __future__ import annotations

import pytest

from config_chemicals import CHEMICALS_CATALOG


def test_no_integer_unit_kind_entries():
    offenders = [e for e in CHEMICALS_CATALOG if e.get("unit_kind") == "integer"]
    assert offenders == [], (
        f"Chemicals catalog has {len(offenders)} integer-unit_kind "
        f"entries: {[e.get('slug') or e.get('name') for e in offenders]}"
    )


def test_all_entries_have_known_unit_kind():
    known_values = {"decimal"}
    bad = [
        (e.get("slug") or e.get("name"), e.get("unit_kind"))
        for e in CHEMICALS_CATALOG
        if e.get("unit_kind") not in known_values
    ]
    assert bad == [], (
        f"Chemicals catalog has entries with unknown unit_kind: {bad}"
    )
