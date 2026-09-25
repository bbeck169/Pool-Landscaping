"""Feb-2026 · Batch follow-up B — checklist key normaliser.

Pre-existing bug: the branded template's four checklist filters
all looked for ``item.get("done")`` but the customer-safe redact
pipeline (routers.service_reports._redact_report_for_customer)
stamps the tech-portal shape ``{"label": "...", "checked": True}``.
On every seeded service_report the SERVICE CHECKLIST card was
silently dropped from the customer email.

The fix introduces a narrow ``_checklist_is_done`` helper that
accepts BOTH keys. This suite pins:

* the helper handles both shapes + non-dict inputs;
* all four render sites (pool sections composer, landscape
  composer, branded ``_render_checklist_card``, and the
  end-to-end ``render_email`` checklist_labels list) honor the
  ``checked`` shape;
* an item with neither key is NOT rendered as complete.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from services.auto_visit_email import (
    _checklist_is_done,
    _pool_body_sections,
    _landscape_body_sections,
    _render_checklist_card,
    render_email,
)


# ═════════════════════════════════════════════════════════════════
# Helper unit tests
# ═════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("item,expected", [
    ({"label": "Skim surface", "checked": True},           True),
    ({"label": "Skim surface", "done": True},              True),
    ({"label": "Skim surface", "checked": True, "done": False}, True),
    ({"label": "Skim surface", "checked": False},          False),
    ({"label": "Skim surface", "done": False},             False),
    ({"label": "Skim surface"},                             False),
    ({},                                                    False),
    (None,                                                  False),
    ("not-a-dict",                                          False),
    (["also-not-a-dict"],                                   False),
])
def test_checklist_is_done_accepts_both_keys(item, expected):
    assert _checklist_is_done(item) is expected


# ═════════════════════════════════════════════════════════════════
# Pool body sections composer (line 442-451) — legacy text branch
# ═════════════════════════════════════════════════════════════════
def _palette() -> Dict[str, str]:
    return {"primary": "#0B4A6F", "secondary": "#0369A1",
            "accent": "#2563EB"}


def test_pool_body_sections_picks_up_checked_key_items():
    sr = {
        "id": "sr", "kind": "pool",
        "chemical_readings": [],
        "checklist_items": [
            {"label": "Skim surface",  "checked": True},
            {"label": "Brush walls",   "checked": True},
            {"label": "Vacuum floor",  "checked": False},
        ],
    }
    sections = _pool_body_sections(sr, _palette())
    completed = [s for s in sections if s["title"] == "Completed"]
    assert completed, "Completed section missing"
    html = completed[0]["html"]
    assert "Skim surface" in html
    assert "Brush walls" in html
    assert "Vacuum floor" not in html


# ═════════════════════════════════════════════════════════════════
# Landscape composer (line 465-475)
# ═════════════════════════════════════════════════════════════════
def test_landscape_body_sections_picks_up_checked_key_items():
    sr = {
        "kind": "landscape",
        "checklist_items": [
            {"label": "Mow front lawn",      "checked": True},
            {"label": "Edge driveway",       "checked": True},
            {"label": "Trim hedges (skip)",  "checked": False},
        ],
    }
    sections = _landscape_body_sections(sr)
    assert len(sections) == 1
    assert sections[0]["title"] == "Landscape checklist"
    assert "Mow front lawn" in sections[0]["html"]
    assert "Edge driveway" in sections[0]["html"]
    assert "Trim hedges" not in sections[0]["html"]


# ═════════════════════════════════════════════════════════════════
# Branded checklist card (line 826-861)
# ═════════════════════════════════════════════════════════════════
def test_render_checklist_card_picks_up_checked_key_items():
    sr = {
        "id": "sr", "kind": "pool",
        "checklist_items": [
            {"label": "Skim surface",  "checked": True},
            {"label": "Vacuum floor",  "checked": True},
        ],
    }
    card = _render_checklist_card(sr)
    assert card, "checklist card should render"
    assert "SERVICE CHECKLIST" in card
    assert "Skim surface" in card
    assert "Vacuum floor" in card


def test_render_checklist_card_empty_when_none_completed():
    """Preserve the historical contract — no done items → no card."""
    sr = {
        "checklist_items": [
            {"label": "Skim surface", "checked": False},
        ],
    }
    assert _render_checklist_card(sr) == ""


# ═════════════════════════════════════════════════════════════════
# End-to-end render_email — checklist_labels list (line ~1197)
# ═════════════════════════════════════════════════════════════════
def test_branded_template_checklist_renders_with_checked_key():
    """The regression case the user hit: a service report whose
    checklist_items use ``{"label": "...", "checked": True}`` and
    NO ``done`` key at all — the SERVICE CHECKLIST heading must
    appear in both HTML and plain-text and every checked item is
    listed."""
    tenant = {"name": "Aquaterra",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j-c-1", "customer_id": "c-1", "address": "x",
           "service_type": "pool"}
    sr = {
        "id": "sr-c-1", "kind": "pool",
        "chemical_readings": [],
        "checklist_items": [
            {"id": "a", "label": "Skim surface and empty baskets",
             "checked": True},
            {"id": "b", "label": "Brush walls and steps",
             "checked": True},
            {"id": "c", "label": "Vacuum floor",
             "checked": True},
            {"id": "d", "label": "Test water chemistry",
             "checked": False},
        ],
    }
    out = render_email(tenant, job, sr, {"email": "c@x.com",
                                          "name": "Chris Customer"})
    html = out["html"]
    text = out["text"]

    # HTML — branded SERVICE CHECKLIST card fires.
    assert "SERVICE CHECKLIST" in html
    assert "Skim surface and empty baskets" in html
    assert "Brush walls and steps" in html
    assert "Vacuum floor" in html
    # Unchecked item stays out of the customer email.
    assert "Test water chemistry" not in html

    # Plain-text sibling — parity.
    assert "SERVICE CHECKLIST" in text
    assert "Skim surface and empty baskets" in text
    assert "Brush walls and steps" in text
    assert "Vacuum floor" in text
    assert "Test water chemistry" not in text


def test_branded_template_checklist_accepts_legacy_done_key_too():
    """The historical ``done`` key must still work — the redact
    pipeline is not the only writer.  Belt-and-suspenders coverage."""
    tenant = {"name": "Aquaterra",
              "settings": {"auto_visit_email": {"enabled": True}}}
    job = {"id": "j-c-2", "customer_id": "c-2", "address": "x",
           "service_type": "pool"}
    sr = {
        "id": "sr-c-2", "kind": "pool",
        "chemical_readings": [],
        "checklist_items": [
            {"label": "Legacy item A", "done": True},
            {"label": "Legacy item B", "done": True},
        ],
    }
    out = render_email(tenant, job, sr, {"email": "c@x.com"})
    assert "Legacy item A" in out["html"]
    assert "Legacy item B" in out["html"]
    assert "SERVICE CHECKLIST" in out["html"]
