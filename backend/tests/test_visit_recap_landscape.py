"""LANDSCAPE-EMAIL-FIX · Feb-2026 — unit tests for the type branch in
``routers.service_reports._compose_recap``.

Context: historically ``POST /api/service-reports/{sr_id}/send-recap``
composed a pool-only body regardless of job type and hard-coded the
subject to ``"Your pool visit recap — <date>"``.  For a landscape
job this surfaced as a mis-subjected email with just the header
lines (chemistry/readings blocks were empty).

The fix branches on ``_derive_checklist_kind``:
  * landscape → ``"Your landscape visit recap"`` subject +
    completed-checklist bullet list + photos (no chemistry).
  * pool / non_pool → unchanged Phase-39 composition.

In addition, photo URLs are promoted to absolute URLs via
``APP_PUBLIC_URL`` so mail clients (which don't resolve relative
paths) can render ``/api/public/job-photo/...`` thumbs produced by
JOB-PHOTOS-FIX's serializer injection.

These are pure in-memory tests of the composer function — no DB,
no FastAPI TestClient, no network.  Keeps the test fast and
isolated from the live preview env.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from routers.service_reports import (
    _absolute_photo_url,
    _completed_checklist_labels,
    _compose_recap,
    _is_landscape_job,
)


# ═════════════════════════════════════════════════════════════════
# Helper · _absolute_photo_url
# ═════════════════════════════════════════════════════════════════
def test_absolute_url_with_app_public_url_prepends_base(monkeypatch):
    monkeypatch.setenv("APP_PUBLIC_URL", "https://app.plofv.com")
    # Force a fresh config read so the helper sees the patched env.
    import importlib
    import config as _config
    importlib.reload(_config)
    assert _absolute_photo_url("/api/public/job-photo/j1/p1") \
        == "https://app.plofv.com/api/public/job-photo/j1/p1"


def test_absolute_url_preserves_already_absolute():
    assert _absolute_photo_url("https://cdn.example.com/img.jpg") \
        == "https://cdn.example.com/img.jpg"
    assert _absolute_photo_url("http://localhost/img.jpg") \
        == "http://localhost/img.jpg"


def test_absolute_url_empty_input_returns_empty():
    assert _absolute_photo_url("") == ""
    assert _absolute_photo_url(None) == ""
    assert _absolute_photo_url("   ") == ""


def test_absolute_url_without_base_keeps_relative(monkeypatch):
    # When APP_PUBLIC_URL is empty we return the relative URL as-is
    # rather than mangling it; the Phase-39 pre-fix shape still ships
    # on dev environments without an explicit absolute base.
    import config as _config
    monkeypatch.setattr(_config, "APP_PUBLIC_URL", "", raising=False)
    assert _absolute_photo_url("/api/public/job-photo/j1/p1") \
        == "/api/public/job-photo/j1/p1"


# ═════════════════════════════════════════════════════════════════
# Helper · _completed_checklist_labels
# ═════════════════════════════════════════════════════════════════
def test_checklist_labels_accepts_done_shape():
    rep = {"checklist_completed": [
        {"label": "Mowed Grass", "done": True},
        {"label": "Edged Grass", "done": False},
        {"label": "Blow Property", "done": True},
    ]}
    assert _completed_checklist_labels(rep) == ["Mowed Grass", "Blow Property"]


def test_checklist_labels_accepts_checked_shape():
    rep = {"checklist_completed": [
        {"label": "Sprayed or Pulled Weeds", "checked": True},
        {"label": "Checked Irrigation", "checked": False},
    ]}
    assert _completed_checklist_labels(rep) \
        == ["Sprayed or Pulled Weeds"]


def test_checklist_labels_reads_legacy_checklist_items_key():
    rep = {"checklist_items": [
        {"label": "Trimmed Bushes", "done": True},
    ]}
    assert _completed_checklist_labels(rep) == ["Trimmed Bushes"]


def test_checklist_labels_handles_non_dict_entries():
    rep = {"checklist_completed": [None, "stringy", {"label": "x", "done": True}]}
    assert _completed_checklist_labels(rep) == ["x"]


def test_checklist_labels_empty_when_none_checked():
    rep = {"checklist_completed": [{"label": "x"}]}
    assert _completed_checklist_labels(rep) == []


# ═════════════════════════════════════════════════════════════════
# Helper · _is_landscape_job
# ═════════════════════════════════════════════════════════════════
def test_is_landscape_detects_service_type_keyword():
    assert _is_landscape_job({"service_type": "Landscaping Visit"}) is True
    assert _is_landscape_job({"service_type": "Lawn Mow"}) is True


def test_is_landscape_rejects_pool_service_type():
    assert _is_landscape_job({"service_type": "Pool Cleaning"}) is False


def test_is_landscape_rejects_empty_job():
    assert _is_landscape_job({}) is False


def test_is_landscape_respects_industry_field():
    assert _is_landscape_job({"industry": "landscaping"}) is True
    assert _is_landscape_job({"industry": "pool"}) is False


# ═════════════════════════════════════════════════════════════════
# Composer · pool branch (regression — must not change)
# ═════════════════════════════════════════════════════════════════
def _pool_fixtures():
    report = {
        "chemicals_added": [
            {"chemical": "Chlorine Tablets", "quantity": 3, "unit": "tabs",
             "raw_label": "3 Tabs"},
        ],
        "chemical_readings": [
            {"key": "ph", "name": "pH", "value": 7.4},
        ],
        "photos": [{"url": "https://cdn.example.com/p1.jpg"}],
    }
    job = {"service_type": "Pool Cleaning",
           "scheduled_at": "2026-02-14T09:00:00Z"}
    cust = {"name": "Jane"}
    tenant = {"name": "Aqua Terra Pools"}
    return report, job, cust, tenant


def test_pool_subject_unchanged():
    report, job, cust, tenant = _pool_fixtures()
    out = _compose_recap(report, job, cust, tech_name="Mike",
                          include_photos=True, next_visit="2026-02-21",
                          tenant=tenant)
    assert out["subject"] == "Your pool visit recap — 2026-02-14"


def test_pool_body_keeps_chemistry_and_readings():
    report, job, cust, tenant = _pool_fixtures()
    out = _compose_recap(report, job, cust, tech_name="Mike",
                          include_photos=True, next_visit=None,
                          tenant=tenant)
    assert "Chemicals added" in out["plain"]
    assert "Water readings" in out["plain"]
    assert "3 Tabs" in out["plain"]
    assert "pH" in out["plain"]
    # Pool branch does NOT inject the "Completed:" header even if
    # the report happens to carry a checklist — out of scope here.
    assert "Completed:" not in out["plain"]


# ═════════════════════════════════════════════════════════════════
# Composer · landscape branch (the bug fix)
# ═════════════════════════════════════════════════════════════════
def _landscape_fixtures():
    report = {
        "checklist_completed": [
            {"label": "Mowed Grass",     "done": True},
            {"label": "Edged Grass",     "done": True},
            {"label": "Blow Property",   "done": False},  # skipped
            {"label": "Sprayed or Pulled Weeds", "checked": True},
        ],
        # Landscape jobs ship photos but no chemistry.
        "photos": [
            {"url": "/api/public/job-photo/jid-1/pid-1"},
            {"url": "/api/public/job-photo/jid-1/pid-2"},
        ],
    }
    job = {"service_type": "Landscaping — Weekly Groom",
           "scheduled_at": "2026-02-14T09:00:00Z"}
    cust = {"name": "Pat"}
    tenant = {"name": "Vistancia Landscaping"}
    return report, job, cust, tenant


def test_landscape_subject_is_landscape_specific():
    report, job, cust, tenant = _landscape_fixtures()
    out = _compose_recap(report, job, cust, tech_name="Carlos",
                          include_photos=True, next_visit=None,
                          tenant=tenant)
    assert out["subject"] == "Your landscape visit recap — 2026-02-14"
    # Pool-coded subject must NOT appear anywhere in the payload.
    assert "pool visit recap" not in out["subject"]
    assert "pool visit recap" not in out["plain"].lower()


def test_landscape_body_lists_completed_checklist_items():
    report, job, cust, tenant = _landscape_fixtures()
    out = _compose_recap(report, job, cust, tech_name="Carlos",
                          include_photos=True, next_visit=None,
                          tenant=tenant)
    # Plain-text — bullet markers.
    assert "Completed:" in out["plain"]
    assert "• Mowed Grass" in out["plain"]
    assert "• Edged Grass" in out["plain"]
    assert "• Sprayed or Pulled Weeds" in out["plain"]
    # Unchecked item must NOT appear.
    assert "Blow Property" not in out["plain"]
    # HTML — <li> rows.
    assert "<li>Mowed Grass</li>" in out["html"]
    assert "<li>Edged Grass</li>" in out["html"]
    assert "<li>Blow Property</li>" not in out["html"]


def test_landscape_body_omits_pool_chemistry_sections():
    report, job, cust, tenant = _landscape_fixtures()
    out = _compose_recap(report, job, cust, tech_name="Carlos",
                          include_photos=True, next_visit=None,
                          tenant=tenant)
    # None of the pool-only section headers may land on the wire
    # for a landscape job.
    assert "Chemicals added" not in out["plain"]
    assert "Water readings" not in out["plain"]
    assert "Chemicals added" not in out["html"]
    assert "Water readings" not in out["html"]


def test_landscape_photo_urls_promoted_to_absolute(monkeypatch):
    """Relative ``/api/public/job-photo/...`` photo URLs must be
    rewritten to absolute (``APP_PUBLIC_URL`` + path) so mail
    clients can resolve them."""
    monkeypatch.setenv("APP_PUBLIC_URL", "https://app.plofv.com")
    import importlib
    import config as _config
    importlib.reload(_config)
    report, job, cust, tenant = _landscape_fixtures()
    out = _compose_recap(report, job, cust, tech_name="Carlos",
                          include_photos=True, next_visit=None,
                          tenant=tenant)
    expected = [
        "https://app.plofv.com/api/public/job-photo/jid-1/pid-1",
        "https://app.plofv.com/api/public/job-photo/jid-1/pid-2",
    ]
    assert out["photo_urls"] == expected
    for u in expected:
        assert u in out["plain"]
        assert f'<img src="{u}"' in out["html"]


def test_landscape_biz_name_fallback_is_landscape_not_pool():
    """Tenant without ``name`` must not leak the pool fallback
    (``"Your pool service"``) into a landscape email body."""
    report, job, cust, _ = _landscape_fixtures()
    out = _compose_recap(report, job, cust, tech_name="",
                          include_photos=False, next_visit=None,
                          tenant={})  # no tenant.name
    assert "Your landscape service" in out["plain"]
    assert "Your pool service" not in out["plain"]
    assert "Your landscape service" in out["html"]
    assert "Your pool service" not in out["html"]


def test_landscape_empty_checklist_still_ships_without_errors():
    """A landscape job whose tech didn't check anything off must
    not blow up the composer and must not emit the ``Completed:``
    header on empty data."""
    report = {"photos": []}
    job = {"service_type": "landscaping"}
    out = _compose_recap(report, job, {"name": "Pat"}, tech_name="Carlos",
                          include_photos=False, next_visit=None,
                          tenant={"name": "VL"})
    assert out["subject"].startswith("Your landscape visit recap")
    # No section header when there's nothing to render.
    assert "Completed:" not in out["plain"]
    assert "<li>" not in out["html"]
