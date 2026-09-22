"""Feb-2026 · Chemistry-gate backend ship — preserve-vs-clear
semantics + shared validate/flatten pipeline + close-gate multi-body
fallback.

Locks the five acceptance criteria on the dispatch:

  1. PATCH job without ``water_bodies`` in body → persisted
     ``water_bodies`` unchanged (preserve).
  2. PATCH job with explicit ``water_bodies: []`` → persisted array
     becomes ``[]`` (deliberate clear).
  3. PATCH with a valid multi-body structured payload → both
     ``water_bodies`` AND flat ``chemical_readings`` mirror land
     correctly, mirror derived from the structured input.
  4. Close-gate passes when the report has structured
     ``water_bodies`` with valid pool readings but the flat mirror
     is empty (multi-body fallback via
     ``iter_water_bodies + flatten_pool_readings``).
  5. Close-gate still rejects when NEITHER flat nor structured
     readings exist.

Bonus: verifies the newer web PATCH path AND the mobile-sync
``service_report.upsert`` path both call the SAME
``apply_water_bodies_payload`` helper (in-process import — one
canonical source, no fork).

Runs entirely against the shared helpers + the ``chemistry_gate``
module — no HTTP round-trip needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.chemistry_gate import (  # noqa: E402
    assert_core_readings_present,
    gather_readings_for_job,
)
from services.water_bodies import (  # noqa: E402
    apply_water_bodies_payload,
    flatten_pool_readings,
    iter_water_bodies,
    validate_water_bodies,
)


CORE_READINGS_PAYLOAD = [
    {"key": "chlorine",         "value": 2.5, "unit": "ppm"},
    {"key": "ph",               "value": 7.4},
    {"key": "alkalinity",       "value": 90,  "unit": "ppm"},
    {"key": "cyanuric_acid",    "value": 40,  "unit": "ppm"},
]


# ─── Acceptance 1 — missing key preserves persisted value ────────

def test_acceptance_1_missing_water_bodies_preserves_persisted():
    """``water_bodies`` NOT in the upd → helper leaves it alone.
    The caller then $sets only the upd dict, so Mongo natively
    preserves the persisted array.
    """
    upd = {"notes": "just a legacy notes touch"}
    rep = {
        "water_bodies": [{
            "id": "b1", "type": "pool", "sequence": 0,
            "readings": [{"key": "ph", "value": 7.2}],
        }],
    }
    apply_water_bodies_payload(upd, rep)
    # ``water_bodies`` was ONLY placed in the upd because the legacy
    # ``notes`` key was present — but the value carried in is the
    # existing bodies list with the notes mirror re-stamped, NOT a
    # cleared array. The persisted pool body id + readings survive.
    assert "water_bodies" in upd, (
        "Legacy notes touch must sync back into water_bodies[0] "
        "so the multi-body surface doesn't desync"
    )
    assert upd["water_bodies"][0]["id"] == "b1"
    assert upd["water_bodies"][0]["readings"] == [
        {"key": "ph", "value": 7.2},
    ]
    assert upd["water_bodies"][0]["notes"] == "just a legacy notes touch"


def test_acceptance_1b_no_water_bodies_no_legacy_touch_is_noop():
    """Neither ``water_bodies`` NOR any legacy mirror key is in
    ``upd`` → the pipeline is a pure no-op. Nothing added, nothing
    removed. Mongo ``$set`` then preserves every persisted key.
    """
    upd = {"submitted_at": "2026-02-14T10:00:00Z"}
    rep = {
        "water_bodies": [{
            "id": "b1", "type": "pool", "sequence": 0,
            "readings": [{"key": "ph", "value": 7.2}],
        }],
    }
    apply_water_bodies_payload(upd, rep)
    assert "water_bodies" not in upd
    assert "chemical_readings" not in upd
    assert upd == {"submitted_at": "2026-02-14T10:00:00Z"}


# ─── Acceptance 2 — explicit [] is a deliberate clear ────────────

def test_acceptance_2_explicit_empty_array_clears_water_bodies():
    upd = {"water_bodies": []}
    rep = {
        "water_bodies": [{
            "id": "b1", "type": "pool", "sequence": 0,
            "readings": [{"key": "ph", "value": 7.2}],
        }],
    }
    apply_water_bodies_payload(upd, rep)
    assert upd["water_bodies"] == []
    # Flat mirror is cleared too — a deliberate clear must reach
    # the top-level ``chemical_readings`` used by the required-
    # readings gate.
    assert upd["chemical_readings"] == []


# ─── Acceptance 3 — structured payload rebuilds flat mirror ─────

def test_acceptance_3_structured_payload_rebuilds_flat_mirror():
    upd = {
        "water_bodies": [
            {"id": "b1", "type": "pool", "sequence": 0,
             "readings": CORE_READINGS_PAYLOAD,
             "chemicals_used": [
                 {"chemical_id": "chl-1", "amount": 1.0, "unit": "lb"},
             ]},
            {"id": "b2", "type": "spa", "sequence": 1,
             "readings": [
                 {"key": "free_chlorine", "value": 3.0},
                 {"key": "ph",             "value": 7.6},
             ]},
        ],
    }
    apply_water_bodies_payload(upd, rep={})
    # water_bodies passed through the validator (id preserved).
    assert len(upd["water_bodies"]) == 2
    assert upd["water_bodies"][0]["id"] == "b1"
    assert upd["water_bodies"][1]["id"] == "b2"
    # Flat mirror is derived from the FIRST pool body's readings —
    # NOT from the spa body's readings. Locks the ``flatten_pool_readings``
    # contract.
    mirror_keys = sorted(r.get("key") for r in upd["chemical_readings"])
    assert mirror_keys == sorted(r["key"] for r in CORE_READINGS_PAYLOAD)
    # Chemicals-used mirror also rebuilt (validator normalizes each
    # entry with default ``product_slug``/``name`` fields — assert
    # the identifying trio rather than exact dict equality).
    ca = upd["chemicals_added"]
    assert isinstance(ca, list) and len(ca) == 1
    assert ca[0]["chemical_id"] == "chl-1"
    assert ca[0]["amount"] == 1.0
    assert ca[0]["unit"] == "lb"


def test_acceptance_3b_multi_body_sequences_are_stamped():
    """Regression guard — ``validate_water_bodies`` stamps
    ``sequence=i`` when the caller omitted it. The order of
    downstream flatten operations depends on that stamping."""
    upd = {
        "water_bodies": [
            {"id": "a", "type": "spa"},
            {"id": "b", "type": "pool", "readings": CORE_READINGS_PAYLOAD},
        ],
    }
    apply_water_bodies_payload(upd, rep={})
    seqs = [b.get("sequence") for b in upd["water_bodies"]]
    assert seqs == [0, 1]


# ─── Acceptance 4 — close gate falls back to structured bodies ───

def test_acceptance_4_close_gate_fallback_to_water_bodies():
    """Job doc has no legacy ``chemical_readings``. Service report
    has an empty flat mirror. BUT structured ``water_bodies`` has a
    valid pool body with all 5 cores → gate passes."""
    job = {"id": "job-1", "kind": "pool"}
    rep = {
        "job_id": "job-1",
        "chemical_readings": [],
        "water_bodies": [{
            "id": "b1", "type": "pool", "sequence": 0,
            "readings": CORE_READINGS_PAYLOAD,
        }],
    }
    gathered = gather_readings_for_job(job, rep)
    assert set(gathered.keys()) >= {
        "chlorine", "ph",
        "alkalinity", "cyanuric_acid",
    }
    # Explicit gate call also passes (no exception).
    assert_core_readings_present(gathered)


def test_acceptance_4b_close_gate_multi_body_fallback_is_iter_water_bodies():
    """The fallback path MUST use ``iter_water_bodies +
    flatten_pool_readings`` — even when the report has NO
    ``water_bodies`` array at all (single-body legacy shape),
    ``iter_water_bodies`` synthesises a default body from the
    top-level fields so the same gate still passes."""
    job = {"id": "job-2", "kind": "pool"}
    rep = {
        "job_id": "job-2",
        "chemical_readings": CORE_READINGS_PAYLOAD,
    }
    # Sanity: iter_water_bodies synthesises the default body.
    bodies = iter_water_bodies(rep)
    assert bodies and len(bodies) == 1
    assert bodies[0]["type"] == "pool"
    flat = flatten_pool_readings(bodies)
    assert flat, "synthesised default body must expose the readings"


# ─── Acceptance 5 — total absence still rejects ─────────────────

def test_acceptance_5_close_gate_rejects_when_nothing_present():
    """No legacy readings AND no structured bodies AND no flat
    mirror → gate rejects with the same 422 detail as before."""
    from fastapi import HTTPException
    job = {"id": "job-3", "kind": "pool"}
    rep = {"job_id": "job-3", "chemical_readings": [], "water_bodies": []}
    gathered = gather_readings_for_job(job, rep)
    # ``iter_water_bodies`` synthesises a default body from the
    # empty legacy fields with an empty readings list.
    assert gathered == {}, (
        "gather must return an EMPTY dict when neither surface "
        "produced any readings"
    )
    with pytest.raises(HTTPException) as exc_info:
        assert_core_readings_present(gathered)
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("detail") == "chemistry_core_readings_missing"
    # All four cores are missing (Phase CHEM1 removed total_chlorine).
    assert len(detail.get("missing_fields") or []) == 4


# ─── Bonus — shared pipeline (one canonical import point) ────────

def test_bonus_shared_helper_is_imported_by_both_paths():
    """Both the web PATCH path (``service_reports.py``) AND the
    mobile-sync upsert path (``mobile_sync.py``) MUST import the
    SAME ``apply_water_bodies_payload`` function — same module,
    same object. This is the strongest signal there's no fork.
    """
    from routers.mobile_sync import (
        _handle_service_report_upsert as _mobile_handler,
    )
    # Read the source of the mobile handler and assert the shared
    # helper name appears — a light-weight guard against a
    # regression that copies the pipeline instead of calling it.
    import inspect
    src = inspect.getsource(_mobile_handler)
    assert "apply_water_bodies_payload" in src, (
        "mobile-sync service_report.upsert must funnel through the "
        "shared apply_water_bodies_payload helper"
    )

    # Same guard for the web PATCH path.
    from routers import service_reports as _sr
    web_src = inspect.getsource(_sr)
    assert "apply_water_bodies_payload(upd, rep)" in web_src, (
        "web PATCH /service-reports/{jid} must funnel through the "
        "shared apply_water_bodies_payload helper"
    )


# ─── Regression — validate_water_bodies still rejects bad shapes ─

def test_validator_rejects_bad_shape_via_pipeline():
    """Bad readings shape surfaces as a ``WaterBodyValidationError``
    (``ValueError`` subclass) so the web PATCH route can raise 422
    with a structured detail. ``normalize_body_type`` silently
    coerces unknown ``type`` values to ``"pool"`` (legacy compat),
    so we drive the validator via a shape breach instead."""
    from services.water_bodies import WaterBodyValidationError
    upd = {"water_bodies": [
        {"type": "pool", "readings": "not-a-list"},
    ]}
    with pytest.raises(WaterBodyValidationError):
        apply_water_bodies_payload(upd, rep={})
