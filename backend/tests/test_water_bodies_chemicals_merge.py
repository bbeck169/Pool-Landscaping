"""Feb-2026 · Water-bodies autosave-wipe fix — merge-guard tests.

Locks the contract that an EMPTY or ABSENT top-level
``chemical_readings`` / ``chemicals_added`` MUST NOT overwrite the
water-body's non-empty persisted list.

Regression scenario the guard closes:
    * Web checklist autosave fires with a stale top-level
      ``chemicals_added: []`` (initial mount, or a re-render that
      hadn't yet re-read the freshly-loaded state) while the on-
      disk water body carries the real chemicals.
    * Before the fix, ``apply_water_bodies_payload`` set
      ``body0["chemicals_used"] = []`` from the empty legacy key,
      then ``flatten_chemicals_used`` rebuilt the top-level from
      the now-wiped body → both channels persisted as ``[]``.
    * After the fix, the empty legacy key is a no-op; the water
      body's chemicals survive.  Explicit clears still work when
      the caller sends ``water_bodies: []`` (Path A short-circuit)
      or dual-writes an empty body[0].chemicals_used alongside the
      top-level (the frontend's ``buildFlushSavePayload`` guarantee).
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from services.water_bodies import apply_water_bodies_payload


# ═════════════════════════════════════════════════════════════════════
# Fixtures — minimal shapes matching the FE autosave payload.
# ═════════════════════════════════════════════════════════════════════
def _pool_body(*, readings: List[Dict[str, Any]] | None = None,
               chemicals_used: List[Dict[str, Any]] | None = None,
               ) -> Dict[str, Any]:
    return {
        "id":            "b-pool",
        "type":          "pool",
        "sequence":      0,
        "label":         "Pool",
        "readings":      readings or [],
        "chemicals_used": chemicals_used or [],
        "media":         [],
        "notes":         "",
    }


def _rep(bodies: List[Dict[str, Any]] | None = None,
         *,
         chem_added: List[Dict[str, Any]] | None = None,
         chem_readings: List[Dict[str, Any]] | None = None,
         ) -> Dict[str, Any]:
    return {
        "water_bodies":       bodies or [],
        "chemicals_added":    chem_added or [],
        "chemical_readings":  chem_readings or [],
        "notes":              "",
    }


def _chem_ids(chems: List[Dict[str, Any]]) -> List[str]:
    """Extract chemical row IDs — the validator normalizes rows in
    place (adds ``product_slug: None``, coerces ``name``), so deep-
    equality against the raw fixture rows fails on the extra key.
    IDs + length are the stable identity."""
    return [c.get("id") for c in chems]


def _reading_keys(readings: List[Dict[str, Any]]) -> List[str]:
    return [r.get("key") for r in readings]


_CHEMS = [
    {"id": "c1", "name": "Muriatic acid", "amount": "1", "unit": "cup"},
    {"id": "c2", "name": "Chlorine tabs", "amount": "3", "unit": "tabs"},
]
_READINGS = [
    {"key": "ph", "name": "pH", "value": 7.4},
    {"key": "chlorine", "name": "Free Cl", "value": 3.0},
]


# ═════════════════════════════════════════════════════════════════════
# Path A — ``water_bodies`` IS in upd (structured write).
# ═════════════════════════════════════════════════════════════════════
class TestPathAEmptyChemicalsAddedPreservesBody:
    def test_empty_top_level_chemicals_added_does_not_wipe_body(self):
        """Regression guard — empty legacy top-level MUST NOT
        overwrite a non-empty water-body chemicals list."""
        fresh_wb = [_pool_body(chemicals_used=_CHEMS)]
        upd = {
            "water_bodies":    fresh_wb,
            "chemicals_added": [],  # ← the wipe trigger before the fix
        }
        apply_water_bodies_payload(upd, _rep(fresh_wb))
        # Body[0] chemicals survive (compare on stable IDs — the
        # validator normalizes rows with an extra ``product_slug``).
        assert _chem_ids(upd["water_bodies"][0]["chemicals_used"]) == ["c1", "c2"]
        # Flatten rebuilds the top-level from the (surviving) body.
        assert _chem_ids(upd["chemicals_added"]) == ["c1", "c2"]

    def test_missing_top_level_chemicals_added_does_not_touch_body(self):
        """When ``chemicals_added`` isn't in the payload at all, the
        body's list is left untouched — mirrors the ``"key not in upd"``
        semantics of the underlying merge."""
        fresh_wb = [_pool_body(chemicals_used=_CHEMS)]
        upd = {"water_bodies": fresh_wb}  # ← no legacy key
        apply_water_bodies_payload(upd, _rep(fresh_wb))
        assert _chem_ids(upd["water_bodies"][0]["chemicals_used"]) == ["c1", "c2"]
        assert _chem_ids(upd["chemicals_added"]) == ["c1", "c2"]

    def test_non_empty_top_level_chemicals_added_still_wins(self):
        """Regression guard for the existing autosave dual-write
        contract — the FRESH legacy top-level must still overwrite
        a stale water-body mirror."""
        stale_wb = [_pool_body(chemicals_used=[])]
        fresh_chems = list(_CHEMS)
        upd = {
            "water_bodies":    stale_wb,
            "chemicals_added": fresh_chems,
        }
        apply_water_bodies_payload(upd, _rep(stale_wb))
        assert _chem_ids(upd["water_bodies"][0]["chemicals_used"]) == ["c1", "c2"]
        assert _chem_ids(upd["chemicals_added"]) == ["c1", "c2"]

    def test_none_top_level_chemicals_added_does_not_wipe(self):
        """A legacy top-level of ``None`` is a legacy-shape mistake;
        treat identically to ``[]`` and preserve the body."""
        fresh_wb = [_pool_body(chemicals_used=_CHEMS)]
        upd = {
            "water_bodies":    fresh_wb,
            "chemicals_added": None,
        }
        apply_water_bodies_payload(upd, _rep(fresh_wb))
        assert _chem_ids(upd["water_bodies"][0]["chemicals_used"]) == ["c1", "c2"]


class TestPathAEmptyChemicalReadingsPreservesBody:
    def test_empty_top_level_chemical_readings_does_not_wipe_body(self):
        fresh_wb = [_pool_body(readings=_READINGS)]
        upd = {
            "water_bodies":      fresh_wb,
            "chemical_readings": [],
        }
        apply_water_bodies_payload(upd, _rep(fresh_wb))
        assert _reading_keys(upd["water_bodies"][0]["readings"]) == ["ph", "chlorine"]
        assert _reading_keys(upd["chemical_readings"]) == ["ph", "chlorine"]

    def test_missing_top_level_chemical_readings_does_not_touch_body(self):
        fresh_wb = [_pool_body(readings=_READINGS)]
        upd = {"water_bodies": fresh_wb}
        apply_water_bodies_payload(upd, _rep(fresh_wb))
        assert _reading_keys(upd["water_bodies"][0]["readings"]) == ["ph", "chlorine"]

    def test_non_empty_top_level_chemical_readings_still_wins(self):
        stale_wb = [_pool_body(readings=[])]
        fresh_readings = list(_READINGS)
        upd = {
            "water_bodies":      stale_wb,
            "chemical_readings": fresh_readings,
        }
        apply_water_bodies_payload(upd, _rep(stale_wb))
        assert _reading_keys(upd["water_bodies"][0]["readings"]) == ["ph", "chlorine"]
        assert _reading_keys(upd["chemical_readings"]) == ["ph", "chlorine"]


# ═════════════════════════════════════════════════════════════════════
# Path A — Explicit-clear semantics still work.
# ═════════════════════════════════════════════════════════════════════
class TestPathAExplicitClearSemantics:
    def test_deliberate_clear_via_empty_water_bodies_still_wipes_top_level(self):
        """Regression guard — ``water_bodies: []`` remains the sole
        deliberate-clear channel and must clear the flat mirrors."""
        upd = {"water_bodies": []}
        apply_water_bodies_payload(upd, _rep([_pool_body(chemicals_used=_CHEMS)]))
        assert upd["water_bodies"] == []
        assert upd["chemical_readings"] == []

    def test_deliberate_clear_via_body_zero_chemicals_used_persists(self):
        """When the FE dual-writes an explicit clear on BOTH channels
        (body[0].chemicals_used=[] AND chemicals_added=[]), the body-
        level clear IS honored because the top-level guard is a no-op
        against an empty top-level."""
        cleared_wb = [_pool_body(chemicals_used=[])]
        upd = {
            "water_bodies":    cleared_wb,
            "chemicals_added": [],
        }
        apply_water_bodies_payload(upd, _rep(cleared_wb))
        assert _chem_ids(upd["water_bodies"][0]["chemicals_used"]) == []
        assert _chem_ids(upd["chemicals_added"]) == []

    def test_deliberate_clear_via_body_zero_readings_persists(self):
        cleared_wb = [_pool_body(readings=[])]
        upd = {
            "water_bodies":      cleared_wb,
            "chemical_readings": [],
        }
        apply_water_bodies_payload(upd, _rep(cleared_wb))
        assert _reading_keys(upd["water_bodies"][0]["readings"]) == []
        assert _reading_keys(upd["chemical_readings"]) == []


# ═════════════════════════════════════════════════════════════════════
# Path B — legacy-only writes (``water_bodies`` NOT in upd).
# ═════════════════════════════════════════════════════════════════════
class TestPathBEmptyLegacyPreservesBody:
    def test_empty_legacy_chemicals_added_does_not_wipe_body(self):
        """Path B is the legacy-only channel.  Mirrors Path A's
        guard: an empty top-level ``chemicals_added`` is a stale-
        autosave shape and MUST NOT overwrite the persisted body."""
        persisted = _rep([_pool_body(chemicals_used=_CHEMS)])
        upd = {"chemicals_added": []}
        apply_water_bodies_payload(upd, persisted)
        # ``water_bodies`` is materialised from the persisted doc
        # so the read-side hydration can find the chemicals.
        assert _chem_ids(upd["water_bodies"][0]["chemicals_used"]) == ["c1", "c2"]

    def test_empty_legacy_chemical_readings_does_not_wipe_body(self):
        persisted = _rep([_pool_body(readings=_READINGS)])
        upd = {"chemical_readings": []}
        apply_water_bodies_payload(upd, persisted)
        assert _reading_keys(upd["water_bodies"][0]["readings"]) == ["ph", "chlorine"]

    def test_non_empty_legacy_chemicals_added_still_writes_to_body(self):
        persisted = _rep([_pool_body(chemicals_used=[])])
        fresh_chems = list(_CHEMS)
        upd = {"chemicals_added": fresh_chems}
        apply_water_bodies_payload(upd, persisted)
        assert _chem_ids(upd["water_bodies"][0]["chemicals_used"]) == ["c1", "c2"]

    def test_notes_overwrites_even_when_empty_string(self):
        """Regression guard — ``notes`` keeps its overwrite semantics.
        The autosave-wipe guard is scoped to list channels only; a
        blank notes string is a legit user intent (clearing the field)."""
        persisted = _rep([_pool_body(chemicals_used=_CHEMS)])
        persisted["water_bodies"][0]["notes"] = "prior"
        upd = {"notes": ""}
        apply_water_bodies_payload(upd, persisted)
        assert upd["water_bodies"][0]["notes"] == ""
        # And the chemicals list is UNTOUCHED by a notes-only patch.
        assert _chem_ids(upd["water_bodies"][0]["chemicals_used"]) == ["c1", "c2"]
