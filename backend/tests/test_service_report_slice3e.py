"""Feb-2026 · Slice 3E — Customer report hides unchecked checklist items.

Direct unit test over ``_redact_report_for_customer`` +
``_annotate_report_for_admin`` so we don't need a seeded live job to
prove the projection behaviour.
"""
from __future__ import annotations

from routers.service_reports import (
    _redact_report_for_customer,
    _annotate_report_for_admin,
)


def _make_report():
    return {
        "id": "rep-1",
        "chemical_readings": [
            {"key": "ph", "value": 7.4, "name": "pH"},
            {"key": "chlorine", "value": 3.0, "name": "Free Chlorine"},
        ],
        "checklist_items": [
            {"id": "c1", "label": "Skim surface", "checked": True},
            {"id": "c2", "label": "Brush walls", "checked": True},
            {"id": "c3", "label": "Vacuum floor", "checked": False},
            {"id": "c4", "label": "Backwash filter", "checked": False},
            {"id": "c5", "label": "Inspect pump", "checked": False},
        ],
        "notes": "All good.",
        "internal_notes": "Customer's dog was barking.",
        "photos": [
            {"url": "a.jpg", "tags": []},
            {"url": "b.jpg", "tags": ["internal"]},
        ],
    }


def test_customer_view_hides_unchecked_checklist_items():
    sr = _make_report()
    projected = _redact_report_for_customer(sr)
    items = projected["checklist_items"]
    assert len(items) == 2, f"expected 2 checked items, got {len(items)}"
    labels = {i["label"] for i in items}
    assert labels == {"Skim surface", "Brush walls"}
    # Every surviving item must have ``checked == True`` — belt and
    # suspenders, guards against a future refactor that flips the
    # boolean semantics.
    assert all(bool(i.get("checked")) for i in items)


def test_customer_view_still_strips_internal_and_labels_readings():
    sr = _make_report()
    projected = _redact_report_for_customer(sr)
    # 3C invariant — no raw numeric ``value`` on any reading.
    for r in projected.get("chemical_readings") or []:
        assert "value" not in r or r.get("value") is None
    # internal_notes gone, internal photo dropped
    assert "internal_notes" not in projected
    assert all(
        "internal" not in [str(t).lower() for t in (p.get("tags") or [])]
        for p in projected.get("photos") or []
    )


def test_admin_view_preserves_all_checklist_items():
    sr = _make_report()
    projected = _annotate_report_for_admin(sr)
    items = projected["checklist_items"]
    assert len(items) == 5, "admin must see all checklist items, even unchecked"
    # Check-state distribution must be preserved verbatim.
    assert [i["checked"] for i in items] == [True, True, False, False, False]
    # 3C admin annotation attaches the readings_label map alongside
    # the raw numeric readings.
    assert projected.get("readings_label") == {"ph": "average", "chlorine": "average"}
    # Admin retains raw numeric values.
    assert any(r.get("value") == 7.4 for r in projected["chemical_readings"])


def test_customer_view_empty_checklist_when_none_checked():
    sr = _make_report()
    for i in sr["checklist_items"]:
        i["checked"] = False
    projected = _redact_report_for_customer(sr)
    assert projected["checklist_items"] == [], (
        "when no items were checked, customer sees an empty checklist "
        "(the Section renders nothing, per portal UI)"
    )


def test_customer_view_survives_non_dict_checklist_entries():
    """The tech app has historically shipped either list-of-strings or
    list-of-dicts for checklist items. The projection must not crash
    on legacy shapes — non-dict entries are simply dropped."""
    sr = _make_report()
    sr["checklist_items"] = [
        {"id": "c1", "label": "Skim surface", "checked": True},
        "Brush walls",  # legacy shape — string
        None,
    ]
    projected = _redact_report_for_customer(sr)
    assert len(projected["checklist_items"]) == 1
    assert projected["checklist_items"][0]["label"] == "Skim surface"
