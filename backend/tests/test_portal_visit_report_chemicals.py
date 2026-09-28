"""CHEM-LOCK · Feb-2026 — Portal visit-report chemicals.

The public portal endpoint ``GET /api/portal/service/{public_uuid}``
(routers/public_service_images.py) is the ONE customer-facing HTTP
surface for a service-report view. Its ``chemicals_added`` extractor
(:func:`_public_chemicals_added`) was already CHEM-aware (accepted
either ``quantity`` or ``amount``); this suite pins that contract
in place so a future refactor doesn't regress the shape.

The extractor is unit-testable — no HTTP layer needed. This mirrors
the ``auto_visit_email`` regression pattern.
"""
from __future__ import annotations

from routers.public_service_images import _public_chemicals_added


# ─── The core CHEM-LOCK case — amount-only row must render ───────
def test_amount_only_row_renders():
    """A pre-CHEM-LOCK ``amount``-only row (as written by the tech
    app FE) still surfaces on the public portal."""
    rows = _public_chemicals_added({
        "chemicals_added": [
            {"name": "Liquid Chlorine", "amount": "1.5", "unit": "gal"},
        ],
    })
    assert len(rows) == 1
    assert rows[0]["name"] == "Liquid Chlorine"
    assert rows[0]["quantity"] == "1.5"
    assert rows[0]["unit"] == "gal"


def test_quantity_only_row_renders():
    """A post-CHEM-LOCK ``quantity``-only row surfaces without
    change."""
    rows = _public_chemicals_added({
        "chemicals_added": [
            {"name": "Muriatic Acid", "quantity": "0.25", "unit": "gal"},
        ],
    })
    assert len(rows) == 1
    assert rows[0]["quantity"] == "0.25"


def test_both_fields_prefers_quantity():
    """When both are present, ``quantity`` wins."""
    rows = _public_chemicals_added({
        "chemicals_added": [
            {"name": "Cal Hypo", "quantity": "2", "amount": "999",
             "unit": "lb"},
        ],
    })
    assert len(rows) == 1
    assert rows[0]["quantity"] == "2"


def test_blank_row_skipped():
    """A row with no name / raw_label is skipped even if it has a
    numeric value — the portal viewer would render an unlabeled
    row otherwise."""
    rows = _public_chemicals_added({
        "chemicals_added": [
            {},                                      # skip
            {"name": ""},                            # skip (no name)
            {"amount": 0},                           # skip
            {"name": "Chlorine", "amount": "1"},     # keep
        ],
    })
    assert len(rows) == 1
    assert rows[0]["name"] == "Chlorine"


def test_chemical_key_as_name_fallback():
    """The legacy ``chemical`` field is honoured as the name."""
    rows = _public_chemicals_added({
        "chemicals_added": [
            {"chemical": "Stabilizer", "amount": "1", "unit": "lb"},
        ],
    })
    assert len(rows) == 1
    assert rows[0]["name"] == "Stabilizer"


def test_raw_label_preserved():
    """Freeform tech-typed labels round-trip to the portal."""
    rows = _public_chemicals_added({
        "chemicals_added": [
            {"raw_label": "1/2 cup stabilizer", "amount": "0.5"},
        ],
    })
    assert len(rows) == 1
    assert rows[0]["raw_label"] == "1/2 cup stabilizer"


def test_multiple_rows_in_order():
    """List order preserved — the portal renders chemicals in
    the order the tech logged them."""
    rows = _public_chemicals_added({
        "chemicals_added": [
            {"name": "Chlorine", "amount": "1"},
            {"name": "Acid", "quantity": "0.5"},
            {"name": "Algaecide", "amount": "0.2"},
        ],
    })
    assert [r["name"] for r in rows] == ["Chlorine", "Acid", "Algaecide"]


def test_missing_chemicals_added_returns_empty():
    """No key → empty list, never a crash."""
    assert _public_chemicals_added({}) == []
    assert _public_chemicals_added({"chemicals_added": None}) == []
    assert _public_chemicals_added({"chemicals_added": []}) == []
