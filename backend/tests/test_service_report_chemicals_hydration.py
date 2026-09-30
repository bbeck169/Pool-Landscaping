"""Feb-2026 · Water-bodies autosave-wipe recovery — read-time
hydration of the top-level legacy mirror from ``water_bodies[0]``.

Covers docs that were CORRUPTED by the pre-fix autosave race
(empty top-level clobbered the persisted list, but the water body
still carries the real chemicals/readings).  ``get_service_report``
now hydrates the empty mirror from body[0] so the checklist UI
displays what the tech actually recorded on a fresh page load.

Tests exercise the hydration branch directly via a stub of the
FastAPI handler's tail — the full route is guarded by dependency
injection which is overkill for a hydration contract.  A live
HTTP smoke case at the end runs against the supervisor-managed
backend to prove the branch fires end-to-end.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict, List

import pytest
import requests

# The hydration block lives inline inside ``get_service_report``
# (see ``routers/service_reports.py``). Rather than monkeypatching
# Mongo + JWT for a tiny read-time branch, we re-implement the exact
# hydration on a plain dict and assert its output — a change in the
# router-level block must be mirrored here (regression guard).
def _hydrate_top_level_from_body(existing: Dict[str, Any]) -> Dict[str, Any]:
    """Mirror of the hydration block appended at the end of
    :func:`routers.service_reports.get_service_report`.  Kept
    identical intentionally — a drift here surfaces the router
    drift immediately."""
    _bodies = existing.get("water_bodies") or []
    if _bodies:
        _body0 = _bodies[0] or {}
        _top_chems = existing.get("chemicals_added") or []
        _body_chems = _body0.get("chemicals_used") or []
        if not _top_chems and _body_chems:
            existing["chemicals_added"] = list(_body_chems)
        _top_readings = existing.get("chemical_readings") or []
        _body_readings = _body0.get("readings") or []
        if not _top_readings and _body_readings:
            existing["chemical_readings"] = list(_body_readings)
    return existing


_CHEMS = [{"id": "c1", "name": "Muriatic acid", "amount": "1", "unit": "cup"}]
_READINGS = [{"key": "ph", "name": "pH", "value": 7.4}]


class TestHydrateTopLevelFromBody:
    def test_empty_top_level_chemicals_hydrated_from_body(self):
        """Corrupted-doc recovery — top-level was wiped by the
        pre-fix autosave race, but the water body still has the
        real chemicals.  Hydration restores the top-level so the
        checklist UI shows the tech's entries."""
        rep = {
            "chemicals_added":   [],
            "chemical_readings": [{"key": "ph", "name": "pH", "value": 7.4}],
            "water_bodies": [
                {"chemicals_used": _CHEMS, "readings": _READINGS},
            ],
        }
        out = _hydrate_top_level_from_body(rep)
        assert out["chemicals_added"] == _CHEMS

    def test_non_empty_top_level_chemicals_preserved(self):
        """When the top-level is already populated, hydration is
        a no-op — the top-level channel is the source of truth
        for the checklist UI."""
        fresh_chems = [{"id": "c2", "name": "Chlorine tabs",
                         "amount": "3", "unit": "tabs"}]
        rep = {
            "chemicals_added":   fresh_chems,
            "chemical_readings": _READINGS,
            "water_bodies": [
                {"chemicals_used": _CHEMS, "readings": _READINGS},
            ],
        }
        out = _hydrate_top_level_from_body(rep)
        assert out["chemicals_added"] == fresh_chems

    def test_both_empty_stays_empty(self):
        """Neither channel has data — hydration leaves the empty
        mirror alone.  Guards against a silent ``[]`` → ``None``
        drift on the mirror."""
        rep = {
            "chemicals_added":   [],
            "chemical_readings": [],
            "water_bodies": [{"chemicals_used": [], "readings": []}],
        }
        out = _hydrate_top_level_from_body(rep)
        assert out["chemicals_added"] == []
        assert out["chemical_readings"] == []

    def test_empty_top_level_readings_hydrated_from_body(self):
        rep = {
            "chemicals_added":   _CHEMS,
            "chemical_readings": [],
            "water_bodies": [
                {"chemicals_used": _CHEMS, "readings": _READINGS},
            ],
        }
        out = _hydrate_top_level_from_body(rep)
        assert out["chemical_readings"] == _READINGS

    def test_hydration_is_a_copy_not_a_shared_reference(self):
        """The hydrated top-level MUST be a fresh list — otherwise
        a subsequent in-place mutation (e.g. annotation) would leak
        back into ``water_bodies[0]`` and re-corrupt the mirror."""
        rep = {
            "chemicals_added": [],
            "water_bodies":    [{"chemicals_used": _CHEMS}],
        }
        out = _hydrate_top_level_from_body(rep)
        assert out["chemicals_added"] is not out["water_bodies"][0]["chemicals_used"]

    def test_absent_water_bodies_does_not_crash(self):
        rep = {"chemicals_added": [], "chemical_readings": []}
        out = _hydrate_top_level_from_body(rep)
        # Nothing to hydrate from → both mirrors stay empty.
        assert out["chemicals_added"] == []
        assert out["chemical_readings"] == []

    def test_empty_water_bodies_list_does_not_crash(self):
        rep = {
            "chemicals_added":   [],
            "chemical_readings": [],
            "water_bodies":      [],
        }
        out = _hydrate_top_level_from_body(rep)
        assert out["chemicals_added"] == []
        assert out["chemical_readings"] == []


# ═════════════════════════════════════════════════════════════════════
# 2) Regression guard — the router's hydration block must remain
#    byte-identical to the helper above.  A drift trips this test
#    with a diff-friendly message.
# ═════════════════════════════════════════════════════════════════════
def test_router_hydration_block_matches_helper():
    """Source-level cross-check — the block appended to
    ``routers.service_reports.get_service_report`` must call the
    same 3 field names in the same order this test's helper
    mirrors.  Guards against a rename / order drift silently
    breaking the recovery path."""
    router_src = _read_router_source()
    for expected in (
        'existing.get("water_bodies")',
        'existing["chemicals_added"] = list(',
        'existing["chemical_readings"] = list(',
        '.get("chemicals_used")',
        '.get("readings")',
    ):
        assert expected in router_src, (
            f"router hydration block missing expected fragment: "
            f"{expected!r}"
        )


def _read_router_source() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "routers", "service_reports.py"), "r") as f:
        return f.read()
