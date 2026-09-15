"""Phase J1 · Feb-2026 — checklist-kind priority chain.

Locks in that ``_derive_checklist_kind`` consults **Job Title / Service
Type** BEFORE the assigned tech's department, with an explicit override
still winning above everything.

Mirror suite: ``frontend/src/test/checklist-type-priority.test.js``.
"""

from routers.jobs import _derive_checklist_kind


def test_service_type_landscaping_beats_pool_tech_department():
    """Landscaping service_type + Pool-department tech → landscape."""
    job = {"service_type": "Lawn mow + trim"}
    assert _derive_checklist_kind(job, "pool") == "landscape"


def test_service_type_pool_beats_landscaping_tech_department():
    """Pool service_type + Landscaping-department tech → pool."""
    job = {"service_type": "Weekly pool chem service"}
    assert _derive_checklist_kind(job, "landscaping") == "pool"


def test_no_service_type_signal_falls_back_to_tech_department():
    """No keyword signal in job fields → tech department decides."""
    job = {"service_type": "General visit", "title": "Site walk"}
    assert _derive_checklist_kind(job, "landscaping") == "landscape"


def test_explicit_override_wins_over_service_type_and_department():
    """`checklist_kind_override` beats everything else."""
    job = {
        "checklist_kind_override": "pool",
        # Service type + tech both scream landscape — override still wins.
        "service_type": "landscape cleanup",
    }
    assert _derive_checklist_kind(job, "landscaping") == "pool"


def test_no_signals_uses_pool_fallback_default():
    """Empty job + empty department → pool (safe default preserved)."""
    assert _derive_checklist_kind({}, None) == "pool"
