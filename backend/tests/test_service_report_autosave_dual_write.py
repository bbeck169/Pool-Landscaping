"""P0 fix · Feb-2026 — Chemistry-zeroing regression.

The web checklist autosave sends BOTH ``water_bodies`` (stale mirror
from ``report.water_bodies[0]``) AND the tech's freshly-edited
top-level ``chemical_readings`` / ``chemicals_added`` in the same
PATCH.  Before the fix, ``apply_water_bodies_payload`` treated
``water_bodies`` as authoritative and REBUILT the fresh top-level
keys from the stale mirror — silently discarding the tech's newest
keystroke on every 800ms autosave.

These tests simulate the exact video-based scenario:

1. Tech types a chlorine value → top-level ``chemical_readings``
   is fresh; ``water_bodies[0].readings`` is stale.
2. Autosave PATCHes both.
3. After the pipeline runs, the fresh value MUST survive AND
   ``water_bodies[0].readings`` MUST be updated to match, so the
   next autosave doesn't re-zero it.

Also covers the ``chemicals_added`` twin channel + a mixed
type=spa multi-body case (spa body untouched by pool-only edits).
"""
from __future__ import annotations

from services.water_bodies import apply_water_bodies_payload


def _rep(bodies):
    return {"id": "r1", "tenant_id": "t1", "water_bodies": bodies}


def _pool_body(*, readings, chemicals_used=None):
    return {
        "id": "b-pool", "type": "pool", "sequence": 0,
        "label": "Pool", "readings": readings,
        "chemicals_used": chemicals_used or [], "media": [],
        "notes": "",
    }


def test_fresh_top_level_chemical_readings_win_over_stale_mirror():
    """The exact reported bug — tech types a fresh chlorine reading
    while the water_bodies mirror still carries the OLD value."""
    stale_wb = [_pool_body(readings=[
        {"key": "free_chlorine", "name": "FC", "value": 0, "unit": "ppm"},
        {"key": "ph", "name": "pH", "value": 7.2, "unit": ""},
    ])]
    fresh_top = [
        {"key": "free_chlorine", "name": "FC", "value": 3.5, "unit": "ppm"},
        {"key": "ph", "name": "pH", "value": 7.2, "unit": ""},
    ]
    upd = {
        "water_bodies": stale_wb,
        "chemical_readings": fresh_top,
    }
    apply_water_bodies_payload(upd, _rep(stale_wb))
    # The tech's fresh FC value MUST survive on the top-level mirror.
    fc = next(r for r in upd["chemical_readings"] if r.get("key") == "free_chlorine")
    assert fc["value"] == 3.5, upd["chemical_readings"]
    # And it MUST also land inside water_bodies[0].readings so the
    # NEXT autosave doesn't reintroduce the stale value.
    wb0_fc = next(
        r for r in upd["water_bodies"][0]["readings"]
        if r.get("key") == "free_chlorine"
    )
    assert wb0_fc["value"] == 3.5


def test_fresh_top_level_chemicals_added_win_over_stale_mirror():
    """Twin channel — freshly-added chlorine tablets must not be
    zeroed by a stale ``water_bodies[0].chemicals_used`` mirror."""
    stale_wb = [_pool_body(
        readings=[],
        chemicals_used=[],   # empty on the stale mirror
    )]
    fresh_chems = [
        {"id": "x", "name": "Chlorine tabs", "amount": "3", "unit": "tabs"},
    ]
    upd = {
        "water_bodies": stale_wb,
        "chemicals_added": fresh_chems,
    }
    apply_water_bodies_payload(upd, _rep(stale_wb))
    assert upd["chemicals_added"] == fresh_chems, upd["chemicals_added"]
    assert upd["water_bodies"][0]["chemicals_used"] == fresh_chems


def test_both_channels_fresh_survive_simultaneously():
    """Real-world autosave — tech edited BOTH pH and chlorine dose
    before the debounce fired."""
    stale_wb = [_pool_body(
        readings=[{"key": "ph", "name": "pH", "value": 7.0}],
        chemicals_used=[],
    )]
    upd = {
        "water_bodies": stale_wb,
        "chemical_readings": [{"key": "ph", "name": "pH", "value": 7.6}],
        "chemicals_added": [
            {"id": "y", "name": "Muriatic acid", "amount": "1", "unit": "gal"},
        ],
    }
    apply_water_bodies_payload(upd, _rep(stale_wb))
    assert upd["chemical_readings"][0]["value"] == 7.6
    assert upd["chemicals_added"][0]["name"] == "Muriatic acid"
    assert upd["water_bodies"][0]["readings"][0]["value"] == 7.6
    assert upd["water_bodies"][0]["chemicals_used"][0]["name"] == "Muriatic acid"


def test_autosave_without_top_level_keys_preserves_water_bodies_intent():
    """Regression guard — when the FE deliberately sends water_bodies
    alone (mobile multi-body edit, no legacy mirror keys), the mirror
    IS the source of truth and gets flattened as before."""
    wb = [_pool_body(
        readings=[{"key": "ph", "name": "pH", "value": 7.4}],
        chemicals_used=[{"id": "z", "name": "Salt", "amount": "40", "unit": "lbs"}],
    )]
    upd = {"water_bodies": wb}   # no legacy keys → mirror wins
    apply_water_bodies_payload(upd, _rep(wb))
    assert upd["chemical_readings"][0]["value"] == 7.4
    assert upd["chemicals_added"][0]["name"] == "Salt"


def test_multi_body_pool_plus_spa_only_pool_readings_flow_from_top_level():
    """Multi-body correctness — the pool-body flatten still returns
    the pool's readings; spa body is unaffected by a top-level
    ``chemical_readings`` edit (which the FE always aims at body[0])."""
    stale_wb = [
        _pool_body(readings=[{"key": "ph", "name": "pH", "value": 7.0}]),
        {"id": "b-spa", "type": "spa", "sequence": 1,
          "label": "Spa",
          "readings": [{"key": "ph", "name": "pH", "value": 6.8}],
          "chemicals_used": [], "media": [], "notes": ""},
    ]
    upd = {
        "water_bodies": stale_wb,
        "chemical_readings": [{"key": "ph", "name": "pH", "value": 7.6}],
    }
    apply_water_bodies_payload(upd, _rep(stale_wb))
    # Fresh top-level lands on pool (body[0]) and flattens back
    # through ``flatten_pool_readings`` which returns the pool
    # readings — spa is left alone.
    assert upd["chemical_readings"][0]["value"] == 7.6
    assert upd["water_bodies"][0]["readings"][0]["value"] == 7.6
    # Spa body is UNTOUCHED — the legacy top-level channel never
    # aimed at it.
    assert upd["water_bodies"][1]["readings"][0]["value"] == 6.8


def test_explicit_empty_water_bodies_still_clears_top_level():
    """The Feb-2026 "deliberate clear" branch (``water_bodies: []``)
    must keep working — it clears the top-level mirror even if the
    tech somehow also sent legacy keys in the same request."""
    upd = {
        "water_bodies": [],
        "chemical_readings": [{"key": "ph", "value": 7.6}],
    }
    apply_water_bodies_payload(upd, _rep([]))
    # Explicit clear wins over the legacy mirror on the same call —
    # the FE cannot both wipe water_bodies AND keep readings.
    assert upd["water_bodies"] == []
    assert upd["chemical_readings"] == []
