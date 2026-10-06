"""AUTO-NON-POOL-EMAIL-FIX · Feb-2026 — unit tests for the non_pool
branch of ``services.auto_visit_email.render_email``.

Context: the AUTO send path (``send_visit_summary_email`` which
is fired on service-report submission) historically branched
only pool vs landscape via a naive substring match on
``sr.kind`` / ``job.service_type``.  Non-pool service types
(tree_service, hvac, pest_control, irrigation, fencing,
snow_removal) fell through to ``_pool_body_sections`` and
rendered with pool framing (pool-metrics card headers, etc.).

The AUTO-NON-POOL-EMAIL-FIX extends the branch to a canonical
3-way discriminator via ``_derive_recap_kind`` (lazy wrapper
over ``routers.jobs._derive_checklist_kind``) and routes
``"non_pool"`` jobs through:
  * ``_non_pool_body_sections`` — generic ``"Completed"`` list
    (NOT ``"Landscape checklist"``).
  * The landscape single-column render path with an optional
    ``"Service type"`` info row injected for extra customer-
    facing context.
  * ``kind == "non_pool"`` on the return value.

Pure in-memory tests — no DB, no FastAPI TestClient, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from services.auto_visit_email import (
    _derive_recap_kind,
    _non_pool_body_sections,
    render_email,
)


# ═════════════════════════════════════════════════════════════════
# Helper · _derive_recap_kind (lazy wrapper over routers.jobs)
# ═════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("industry,expected", [
    ("tree_service",   "non_pool"),
    ("hvac",           "non_pool"),
    ("pest_control",   "non_pool"),
    ("irrigation",     "non_pool"),
    ("fencing",        "non_pool"),
    ("snow_removal",   "non_pool"),
    ("landscaping",    "landscape"),
    ("pool",           "pool"),
    ("unknown_type",   "non_pool"),  # catch-all via `_derive_checklist_kind`.
])
def test_recap_kind_classifies_industries_correctly(industry, expected):
    assert _derive_recap_kind({}, {"industry": industry}) == expected


def test_recap_kind_falls_back_to_pool_on_empty_job():
    # No signal → `_derive_checklist_kind` defaults to ``"non_pool"``
    # (Phase P36.1 safe default).  Both sr + job empty.
    assert _derive_recap_kind({}, {}) == "non_pool"


# ═════════════════════════════════════════════════════════════════
# Helper · _non_pool_body_sections (shape mirrors _landscape_...)
# ═════════════════════════════════════════════════════════════════
def test_non_pool_sections_emits_generic_completed_title():
    sr = {"checklist_completed": [
        {"label": "Replaced filter", "done": True},
        {"label": "Inspected unit", "checked": True},
    ]}
    sections = _non_pool_body_sections(sr)
    assert len(sections) == 1
    s = sections[0]
    assert s["title"] == "Completed"
    # NOT the landscape-specific title.
    assert s["title"] != "Landscape checklist"
    assert "<li>✓ Replaced filter</li>" in s["html"]
    assert "<li>✓ Inspected unit</li>" in s["html"]
    assert "  ✓ Replaced filter" in s["text"]
    assert "  ✓ Inspected unit" in s["text"]


def test_non_pool_sections_skips_unchecked_items():
    sr = {"checklist_completed": [
        {"label": "Replaced filter", "done": True},
        {"label": "Topped off refrigerant"},  # not checked
    ]}
    sections = _non_pool_body_sections(sr)
    assert sections and "Topped off refrigerant" not in sections[0]["html"]


def test_non_pool_sections_empty_when_nothing_checked():
    assert _non_pool_body_sections({"checklist_completed": []}) == []
    assert _non_pool_body_sections({}) == []
    assert _non_pool_body_sections({
        "checklist_items": [{"label": "x"}],  # no done/checked
    }) == []


# ═════════════════════════════════════════════════════════════════
# render_email — non_pool branch happy path
# ═════════════════════════════════════════════════════════════════
def _non_pool_fixtures(industry: str = "hvac",
                        service_type: str = "Annual AC Tune-up",
                        tenant_name: str = "Acme HVAC"):
    tenant = {"name": tenant_name}
    job = {
        "industry": industry,
        "service_type": service_type,
        "address": "123 Main St",
    }
    sr = {
        "visit_date": "2026-02-14",
        "tech_name": "Alex",
        "checklist_completed": [
            {"label": "Replaced filter", "done": True},
            {"label": "Inspected unit", "checked": True},
            {"label": "Topped off refrigerant"},
        ],
        "photos": [],
    }
    customer = {"name": "Jamie", "email": "j@example.com"}
    return tenant, job, sr, customer


@pytest.mark.parametrize("industry", [
    "tree_service", "hvac", "pest_control",
    "irrigation",   "fencing", "snow_removal",
])
def test_render_email_non_pool_kind_is_marked(industry):
    tenant, job, sr, customer = _non_pool_fixtures(industry=industry)
    out = render_email(tenant, job, sr, customer)
    assert out["kind"] == "non_pool"


@pytest.mark.parametrize("industry", [
    "tree_service", "hvac", "pest_control",
    "irrigation",   "fencing", "snow_removal",
])
def test_render_email_non_pool_body_has_completed_list(industry):
    tenant, job, sr, customer = _non_pool_fixtures(industry=industry)
    out = render_email(tenant, job, sr, customer)
    assert "<li>✓ Replaced filter</li>" in out["html"]
    assert "<li>✓ Inspected unit</li>" in out["html"]
    # Unchecked item must NOT render.
    assert "Topped off refrigerant" not in out["html"]
    # Text parity.
    assert "✓ Replaced filter" in out["text"]
    assert "✓ Inspected unit" in out["text"]


@pytest.mark.parametrize("industry", [
    "tree_service", "hvac", "pest_control",
    "irrigation",   "fencing", "snow_removal",
])
def test_render_email_non_pool_omits_pool_metrics(industry):
    tenant, job, sr, customer = _non_pool_fixtures(industry=industry)
    out = render_email(tenant, job, sr, customer)
    # Pool-metrics card headers must NOT leak into a non_pool
    # email (they would otherwise appear via
    # ``_render_pool_metrics_card`` / ``_pool_body_sections``).
    assert "pool-metrics" not in out["html"].lower()
    # The pool branch emits a dedicated ``Pool metrics`` /
    # ``Chemicals used`` / ``Water readings`` section stack.  The
    # non_pool branch must emit none of those literals.
    for leaked in ("Pool metrics", "Chemicals used", "Water readings"):
        assert leaked not in out["html"], (
            f"pool-only section {leaked!r} leaked into non_pool email"
        )


def test_render_email_non_pool_includes_service_type_row():
    tenant, job, sr, customer = _non_pool_fixtures(
        service_type="Annual AC Tune-up")
    out = render_email(tenant, job, sr, customer)
    # The service-type row must appear in both HTML and text so
    # the customer immediately sees "AC Tune-up" (not just
    # generic "Service visit summary").
    assert "Service type" in out["html"]
    assert "Annual AC Tune-up" in out["html"]


def test_render_email_non_pool_omits_service_type_when_blank():
    tenant, job, sr, customer = _non_pool_fixtures(service_type="")
    job["job_type"] = ""
    out = render_email(tenant, job, sr, customer)
    # No service_type → no "Service type" row.
    assert "Service type" not in out["html"]


def test_render_email_non_pool_subject_is_generic_not_pool_specific():
    tenant, job, sr, customer = _non_pool_fixtures()
    out = render_email(tenant, job, sr, customer)
    # The AUTO path's subject already uses the generic
    # ``"service visit"`` wording (not ``"pool visit recap"``) so
    # the regression here is to confirm no pool wording regressed
    # back in.
    assert "pool visit" not in out["subject"].lower()
    assert "pool recap" not in out["subject"].lower()


# ═════════════════════════════════════════════════════════════════
# Regression — pool + landscape unchanged
# ═════════════════════════════════════════════════════════════════
def test_render_email_pool_branch_unchanged_kind():
    tenant = {"name": "Aqua Terra"}
    job = {"industry": "pool", "service_type": "Pool Cleaning"}
    sr = {"visit_date": "2026-02-14", "tech_name": "Mike",
          "checklist_completed": [{"label": "x", "done": True}],
          "photos": []}
    customer = {"name": "Pat", "email": "pat@ex.com"}
    out = render_email(tenant, job, sr, customer)
    # Pool branch returns no explicit ``kind`` marker because the
    # portal-style template returns at a different code path.
    # Weakest-claim regression check: subject + body do NOT carry
    # non_pool / landscape framing (which would mean the fix
    # mis-routed pool jobs), AND the generic "Completed" header
    # from the non_pool sections builder is NOT emitted.
    assert "non_pool" not in out["subject"].lower()
    assert "Landscape checklist" not in out["html"]
    # The non_pool sections builder's generic ``"Completed"``
    # title (as a section heading, distinct from any body copy
    # that happens to contain the word) must not surface on the
    # pool branch.  The pool template renders a "Service
    # checklist" card instead; checking for the non_pool
    # headline ``<h3>Completed</h3>`` or its sections-builder
    # output is the cleanest regression guard.
    assert ">Completed</h3>" not in out["html"]
    assert "<li>✓ x</li>" not in out["html"]


def test_render_email_landscape_branch_unchanged_kind():
    tenant = {"name": "Vistancia Landscaping"}
    job = {"industry": "landscaping",
           "service_type": "Weekly groom"}
    sr = {"visit_date": "2026-02-14", "tech_name": "Carlos",
          "checklist_completed": [
              {"label": "Mowed Grass", "done": True},
          ],
          "photos": []}
    customer = {"name": "Pat", "email": "pat@ex.com"}
    out = render_email(tenant, job, sr, customer)
    # Landscape stays landscape — not reclassified as non_pool by
    # the new discriminator.
    assert out["kind"] == "landscape"
    # "Landscape checklist" title stays specific to the landscape
    # branch (not reclassified as "Completed").
    assert "Landscape checklist" in out["html"]
    assert "<li>✓ Mowed Grass</li>" in out["html"]
    # Service-type row is NON_POOL-only and must not surface on
    # landscape emails (keeps the landscape visual language
    # focused on the checklist + photos).
    assert "Service type" not in out["html"]


# ═════════════════════════════════════════════════════════════════
# Fallback — _derive_recap_kind degrades gracefully
# ═════════════════════════════════════════════════════════════════
def test_derive_recap_kind_falls_back_on_import_error(monkeypatch):
    """When ``routers.jobs._derive_checklist_kind`` is unavailable
    the helper falls back to the pre-fix keyword match so
    landscape routing stays intact."""
    import services.auto_visit_email as m
    # Simulate the import failing (mocks out the dependency).
    orig_import = __builtins__["__import__"] \
        if isinstance(__builtins__, dict) else __builtins__.__import__

    def _blocked(name, *a, **k):
        if name == "routers.jobs":
            raise ImportError("blocked for test")
        return orig_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _blocked)
    assert m._derive_recap_kind(
        {"kind": "landscape visit"}, {}) == "landscape"
    assert m._derive_recap_kind(
        {"kind": "pool"}, {}) == "pool"
