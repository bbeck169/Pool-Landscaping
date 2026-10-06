"""NON-POOL-EMAIL-FIX · Feb-2026 — unit tests for the ``non_pool``
branch in ``routers.service_reports._compose_recap``.

Context: historically ``_compose_recap`` had only two branches —
pool (chemistry) and landscape (checklist).  Non-pool / non-
landscape service types (tree_service, hvac, pest_control,
irrigation, fencing, snow_removal) fell through to the pool
composition and surfaced as a mis-subjected "Your pool visit
recap" with empty chemistry blocks.

The NON-POOL-EMAIL-FIX extends the composer with a third generic
branch keyed on ``_recap_kind(job) == "non_pool"`` that renders:
  * ``"Your <company> service visit recap — <date>"`` subject
    (falls back to ``"Your service visit recap"`` on tenant
    without ``name``).
  * ``"Service type: <job.service_type>"`` line in the body (when
    the job carries a service type).
  * Completed checklist bullets (same ``_completed_checklist_labels``
    helper as the landscape branch).
  * Photos through ``_absolute_photo_url`` (reused).
  * No chemistry / water readings sections.

These tests are pure in-memory — no DB, no FastAPI TestClient, no
network.  Matches the LANDSCAPE-EMAIL-FIX test file posture.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from routers.service_reports import (
    _compose_recap,
    _recap_kind,
)


# ═════════════════════════════════════════════════════════════════
# Helper · _recap_kind
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
    # Unknown industry falls into non_pool via the catch-all branch
    # of ``_derive_checklist_kind`` (``if industry: ... non_pool``).
    ("unknown_type",   "non_pool"),
])
def test_recap_kind_classifies_industries_correctly(industry, expected):
    assert _recap_kind({"industry": industry}) == expected


def test_recap_kind_returns_non_pool_for_explicit_override():
    assert _recap_kind({"checklist_kind_override": "non_pool"}) == "non_pool"


def test_recap_kind_empty_job_falls_back_to_non_pool():
    # No signal at all → ``_derive_checklist_kind`` fallback is
    # ``"non_pool"`` (Phase P36.1 safe default).
    assert _recap_kind({}) == "non_pool"


# ═════════════════════════════════════════════════════════════════
# Composer · non_pool subject + body shape
# ═════════════════════════════════════════════════════════════════
def _non_pool_fixtures(industry: str, tenant_name: str | None = "Acme HVAC",
                       service_type: str | None = None):
    report = {
        "checklist_completed": [
            {"label": "Inspected unit", "done": True},
            {"label": "Replaced filter", "done": True},
            {"label": "Topped off refrigerant", "done": False},  # skipped
        ],
        "photos": [{"url": "/api/public/job-photo/jid-9/pid-9"}],
    }
    job = {"industry": industry,
           "service_type": service_type or f"{industry} visit",
           "scheduled_at": "2026-02-14T09:00:00Z"}
    cust = {"name": "Jamie"}
    tenant = {"name": tenant_name} if tenant_name else {}
    return report, job, cust, tenant


@pytest.mark.parametrize("industry", [
    "tree_service", "hvac", "pest_control",
    "irrigation",   "fencing", "snow_removal",
])
def test_non_pool_subject_includes_business_name(industry):
    report, job, cust, tenant = _non_pool_fixtures(industry)
    out = _compose_recap(report, job, cust, tech_name="Alex",
                          include_photos=True, next_visit=None,
                          tenant=tenant)
    assert out["subject"] == "Your Acme HVAC service visit recap — 2026-02-14"
    # Pool-coded subject MUST NOT leak to any non_pool email.
    assert "pool visit recap" not in out["subject"].lower()
    assert "pool visit recap" not in out["plain"].lower()
    # Landscape-coded subject MUST NOT leak either.
    assert "landscape visit recap" not in out["subject"].lower()


@pytest.mark.parametrize("industry", [
    "tree_service", "hvac", "pest_control",
    "irrigation",   "fencing", "snow_removal",
])
def test_non_pool_body_lists_completed_checklist(industry):
    report, job, cust, tenant = _non_pool_fixtures(industry)
    out = _compose_recap(report, job, cust, tech_name="Alex",
                          include_photos=False, next_visit=None,
                          tenant=tenant)
    assert "Completed:" in out["plain"]
    assert "• Inspected unit" in out["plain"]
    assert "• Replaced filter" in out["plain"]
    # Unchecked item must NOT appear.
    assert "Topped off refrigerant" not in out["plain"]
    assert "<li>Inspected unit</li>" in out["html"]
    assert "<li>Replaced filter</li>" in out["html"]
    assert "<li>Topped off refrigerant</li>" not in out["html"]


@pytest.mark.parametrize("industry", [
    "tree_service", "hvac", "pest_control",
    "irrigation",   "fencing", "snow_removal",
])
def test_non_pool_body_omits_chemistry(industry):
    report, job, cust, tenant = _non_pool_fixtures(industry)
    out = _compose_recap(report, job, cust, tech_name="Alex",
                          include_photos=False, next_visit=None,
                          tenant=tenant)
    assert "Chemicals added" not in out["plain"]
    assert "Water readings" not in out["plain"]
    assert "Chemicals added" not in out["html"]
    assert "Water readings" not in out["html"]


def test_non_pool_renders_service_type_line_when_present():
    report, job, cust, tenant = _non_pool_fixtures(
        "hvac", service_type="Annual AC Tune-up")
    out = _compose_recap(report, job, cust, tech_name="Alex",
                          include_photos=False, next_visit=None,
                          tenant=tenant)
    assert "Service type: Annual AC Tune-up" in out["plain"]
    assert "<p>Service type: Annual AC Tune-up</p>" in out["html"]


def test_non_pool_omits_service_type_line_when_missing():
    report, job, cust, tenant = _non_pool_fixtures("hvac")
    # Blank the service_type so the body-line is suppressed.
    job["service_type"] = ""
    job["job_type"] = ""
    out = _compose_recap(report, job, cust, tech_name="Alex",
                          include_photos=False, next_visit=None,
                          tenant=tenant)
    assert "Service type:" not in out["plain"]
    assert "Service type:" not in out["html"]


def test_non_pool_biz_name_fallback_when_tenant_has_no_name():
    """Subject falls back to the neutral ``"Your service visit recap"``
    literal when ``tenant.name`` is missing — must NOT leak the
    pool or landscape fallback copy."""
    report, job, cust, _ = _non_pool_fixtures("hvac", tenant_name=None)
    out = _compose_recap(report, job, cust, tech_name="",
                          include_photos=False, next_visit=None,
                          tenant={})
    assert out["subject"] == "Your service visit recap — 2026-02-14"
    assert "Your service" in out["plain"]
    assert "Your pool service" not in out["plain"]
    assert "Your landscape service" not in out["plain"]


def test_non_pool_photo_urls_promoted_to_absolute(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "https://app.plofv.com")
    import importlib
    import config as _config
    importlib.reload(_config)
    report, job, cust, tenant = _non_pool_fixtures("hvac")
    out = _compose_recap(report, job, cust, tech_name="Alex",
                          include_photos=True, next_visit=None,
                          tenant=tenant)
    assert out["photo_urls"] == [
        "https://app.plofv.com/api/public/job-photo/jid-9/pid-9",
    ]
    assert "https://app.plofv.com/api/public/job-photo/jid-9/pid-9" in out["plain"]
    assert '<img src="https://app.plofv.com/api/public/job-photo/jid-9/pid-9"' \
        in out["html"]


def test_non_pool_empty_checklist_still_ships_cleanly():
    """A non_pool job whose tech didn't check anything off must not
    blow up the composer and must not emit the ``Completed:``
    header on empty data."""
    report = {"photos": []}
    job = {"industry": "hvac", "service_type": "AC repair"}
    out = _compose_recap(report, job, {"name": "Jamie"}, tech_name="Alex",
                          include_photos=False, next_visit=None,
                          tenant={"name": "Acme HVAC"})
    assert out["subject"].startswith("Your Acme HVAC service visit recap")
    assert "Completed:" not in out["plain"]
    assert "<li>" not in out["html"]
    # Service-type line still renders.
    assert "Service type: AC repair" in out["plain"]


def test_non_pool_unknown_service_type_still_routes_safely():
    """An unknown / exotic industry still routes to the non_pool
    branch (via the ``_derive_checklist_kind`` catch-all) and
    renders without crashing."""
    report = {"checklist_completed": [{"label": "Did a thing", "done": True}],
              "photos": []}
    job = {"industry": "something_unusual",
           "service_type": "Unusual Service",
           "scheduled_at": "2026-02-14T09:00:00Z"}
    out = _compose_recap(report, job, {"name": "Jamie"}, tech_name="Alex",
                          include_photos=False, next_visit="2026-03-01",
                          tenant={"name": "Generic Co"})
    assert out["subject"] == "Your Generic Co service visit recap — 2026-02-14"
    assert "Service type: Unusual Service" in out["plain"]
    assert "• Did a thing" in out["plain"]
    assert "Next visit: 2026-03-01" in out["plain"]
    # Pool chemistry must still be suppressed.
    assert "Chemicals added" not in out["plain"]


# ═════════════════════════════════════════════════════════════════
# Regression — pool + landscape branches unchanged
# ═════════════════════════════════════════════════════════════════
def test_regression_pool_branch_unchanged():
    """The pool branch's subject + chemistry sections must stay
    exactly as they were pre-NON-POOL-EMAIL-FIX."""
    report = {
        "chemicals_added": [{"chemical": "Chlorine", "quantity": 2,
                              "unit": "tabs", "raw_label": "2 Tabs"}],
        "chemical_readings": [{"key": "ph", "name": "pH", "value": 7.4}],
        "photos": [],
    }
    job = {"service_type": "Pool Cleaning",
           "scheduled_at": "2026-02-14T09:00:00Z"}
    out = _compose_recap(report, job, {"name": "Pat"}, tech_name="Mike",
                          include_photos=True, next_visit=None,
                          tenant={"name": "Aqua Terra"})
    assert out["subject"] == "Your pool visit recap — 2026-02-14"
    assert "Chemicals added" in out["plain"]
    assert "Water readings" in out["plain"]
    assert "Completed:" not in out["plain"]
    # Service-type line is NON-POOL-only and must not surface on
    # the pool branch.
    assert "Service type:" not in out["plain"]


def test_regression_landscape_branch_unchanged():
    """The landscape branch stays landscape-specific — must not
    be rerouted into the generic non_pool branch."""
    report = {
        "checklist_completed": [{"label": "Mowed Grass", "done": True}],
        "photos": [],
    }
    job = {"service_type": "Landscaping — Weekly Groom",
           "scheduled_at": "2026-02-14T09:00:00Z"}
    out = _compose_recap(report, job, {"name": "Pat"}, tech_name="Carlos",
                          include_photos=False, next_visit=None,
                          tenant={"name": "Vistancia Landscaping"})
    # Landscape-specific subject (NOT the generic
    # ``"Your <Business> service visit recap"`` shape).
    assert out["subject"] == "Your landscape visit recap — 2026-02-14"
    assert "• Mowed Grass" in out["plain"]
    # Service-type line is NON-POOL-only and must not surface on
    # the landscape branch (keeps the landscape copy focused on
    # the completed-items list).
    assert "Service type:" not in out["plain"]
