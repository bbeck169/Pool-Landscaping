"""Phase 27 · Feb 2026 — merge tag catalog + validator + service-report
content tags + public portal shape.

Covers:

* 5 previously-broken uppercase merge tags now resolve correctly:
    CUSTOMER_ADDRESS · EVENT_NOTES · EVENT_TITLE · JOB_DATE · JOB_TIME
* 3 new service-report tags render HTML from ``ctx['service_report']``:
    CHEMICALS_ADDED · CHEMICAL_READINGS · CHECKLIST
* All 8 lowercase-snake aliases are registered in
  ``services.comm_tokens.AVAILABLE_TOKENS`` so the template-builder
  validator stops flagging them as unknown.
* Public portal endpoint (``GET /api/public/service/{uuid}``) exposes
  chemicals + readings + checklist arrays and NEVER leaks customer
  PII.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from pymongo import MongoClient

_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync = MongoClient(_MONGO_URL)[_DB_NAME]


def _mk(prefix: str) -> str:
    return f"TEST_{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _env():
    os.environ["APP_PUBLIC_URL"] = "https://example.test"
    yield


# ═══════════ Merge-tag renderer coverage ═══════════════════════════════
def test_customer_address_full_line():
    from services.marketing.merge_tags import render_template, render_context
    ctx = render_context(customer={
        "address_line_1": "18420 W. Cactus Bloom Ln.",
        "city": "Peoria",
        "state": "AZ",
        "zip": "85383",
    })
    out, _ = render_template("{{CUSTOMER_ADDRESS}}", ctx)
    assert out == "18420 W. Cactus Bloom Ln., Peoria, AZ 85383"


def test_customer_address_fallback_to_legacy_address_field():
    from services.marketing.merge_tags import render_template, render_context
    ctx = render_context(customer={"address": "1 Main St", "city": "Testville"})
    out, _ = render_template("{{CUSTOMER_ADDRESS}}", ctx)
    assert "1 Main St" in out
    assert "Testville" in out


def test_event_notes_and_title():
    from services.marketing.merge_tags import render_template, render_context
    ctx = render_context(event={"notes": "Skim heavy today", "title": "Weekly Pool"})
    a, _ = render_template("{{EVENT_NOTES}}", ctx)
    b, _ = render_template("{{EVENT_TITLE}}", ctx)
    assert a == "Skim heavy today"
    assert b == "Weekly Pool"


def test_job_date_includes_year():
    from services.marketing.merge_tags import render_template, render_context
    ctx = render_context(job={"scheduled_date": "2026-01-15"})
    out, _ = render_template("{{JOB_DATE}}", ctx)
    assert out == "Thu, Jan 15, 2026"


def test_job_time_renders_window_when_start_and_end_present():
    from services.marketing.merge_tags import render_template, render_context
    ctx = render_context(job={
        "scheduled_at": "2026-01-15T09:00:00-07:00",
        "scheduled_end": "2026-01-15T11:00:00-07:00",
    }, tenant={"timezone": "America/Phoenix"})
    out, _ = render_template("{{JOB_TIME}}", ctx)
    assert " – " in out
    assert "9:00 AM" in out
    assert "11:00 AM" in out


def test_job_time_falls_back_to_start_only():
    from services.marketing.merge_tags import render_template, render_context
    ctx = render_context(job={"scheduled_at": "2026-01-15T14:00:00-07:00"},
                          tenant={"timezone": "America/Phoenix"})
    out, _ = render_template("{{JOB_TIME}}", ctx)
    assert "2:00 PM" in out
    assert "–" not in out


def test_chemicals_added_renders_html_ul():
    from services.marketing.merge_tags import render_template, render_context
    sr = {"chemicals_added": [
        {"chemical": "Liquid Chlorine", "quantity": 1, "unit": "gal"},
        {"chemical": "Muriatic Acid",   "quantity": 8, "unit": "oz"},
    ]}
    ctx = render_context(service_report=sr)
    out, _ = render_template("{{CHEMICALS_ADDED}}", ctx)
    assert out.startswith("<ul")
    assert "Liquid Chlorine" in out and "1 gal" in out
    assert "Muriatic Acid" in out and "8 oz" in out


def test_chemicals_added_empty_when_no_entries():
    from services.marketing.merge_tags import render_template, render_context
    ctx = render_context(service_report={"chemicals_added": []})
    out, _ = render_template("A{{CHEMICALS_ADDED}}B", ctx)
    assert out == "AB"


def test_chemical_readings_renders_html_table():
    from services.marketing.merge_tags import render_template, render_context
    sr = {"chemical_readings": [
        {"key": "ph", "name": "pH", "value": 7.5},
        {"key": "chlorine", "name": "Free Chlorine", "value": 2.1, "unit": "ppm"},
        {"key": "salt", "name": "Salt", "value": None},  # skipped — null
    ]}
    ctx = render_context(service_report=sr)
    out, _ = render_template("{{CHEMICAL_READINGS}}", ctx)
    assert out.startswith("<table")
    assert "pH" in out and "7.5" in out
    assert "Free Chlorine" in out and "2.1 ppm" in out
    assert "Salt" not in out


def test_checklist_renders_only_checked_items():
    from services.marketing.merge_tags import render_template, render_context
    sr = {"checklist_items": [
        {"label": "Skim surface", "checked": True},
        {"label": "Empty pump basket", "checked": True},
        {"label": "Vacuum floor", "checked": False},
    ]}
    ctx = render_context(service_report=sr)
    out, _ = render_template("{{CHECKLIST}}", ctx)
    assert "Skim surface" in out
    assert "Empty pump basket" in out
    assert "Vacuum floor" not in out


def test_checklist_empty_when_all_unchecked():
    from services.marketing.merge_tags import render_template, render_context
    sr = {"checklist_items": [
        {"label": "Skim surface", "checked": False},
    ]}
    ctx = render_context(service_report=sr)
    out, _ = render_template("A{{CHECKLIST}}B", ctx)
    assert out == "AB"


def test_new_tags_registered_in_catalog():
    from services.marketing.merge_tags import catalog_grouped
    tokens = {t["token"] for group in catalog_grouped().values() for t in group}
    for tok in ("CUSTOMER_ADDRESS", "EVENT_NOTES", "EVENT_TITLE",
                 "JOB_DATE", "JOB_TIME", "CHEMICALS_ADDED",
                 "CHEMICAL_READINGS", "CHECKLIST"):
        assert tok in tokens


def test_template_validator_recognizes_aliases():
    """The template-builder validator uses ``AVAILABLE_TOKENS`` — every
    uppercase-snake tag must have a lowercase-snake alias in that map
    so the validator stops flagging them as unknown."""
    from services.comm_tokens import AVAILABLE_TOKENS
    for alias in ("customer_address", "event_notes", "event_title",
                   "job_date", "job_time", "chemicals_added",
                   "chemical_readings", "checklist",
                   "service_record_images"):
        assert alias in AVAILABLE_TOKENS, f"missing alias: {alias}"


# ═══════════ Public portal — new sections ══════════════════════════════
@pytest.fixture()
def tenant_row():
    tid = _mk("tenant")
    doc = {"id": tid, "name": "TEST_ AquaTerra",
           "settings": {"business_card": {"company_name": "TEST_ AquaTerra"}}}
    _sync.tenants.insert_one(dict(doc))
    yield doc
    _sync.tenants.delete_one({"id": tid})


@pytest.fixture()
def job_row(tenant_row):
    jid = _mk("job")
    doc = {"id": jid, "tenant_id": tenant_row["id"],
           "title": "TEST_ Weekly Pool",
           "service_type": "Pool Service",
           "scheduled_at": "2026-02-10T14:00:00Z",
           "customer_name": "TEST_ Jane Homeowner",   # PII — must not leak
           "customer_phone": "555-0100",
           "customer_email": "jane@example.test"}
    _sync.jobs.insert_one(dict(doc))
    yield doc
    _sync.jobs.delete_one({"id": jid})


@pytest.fixture()
def report_row(tenant_row, job_row):
    rid = _mk("rep")
    pub = uuid.uuid4().hex
    doc = {"id": rid, "tenant_id": tenant_row["id"],
           "job_id": job_row["id"], "tech_id": "TEST_tech",
           "public_uuid": pub, "template": "pool",
           "submitted_at": "2026-02-10T15:22:11Z",
           "photos": [{"url": "https://cdn.test/p1.jpg", "id": "p1"}],
           "videos": [],
           "chemicals_added": [
               {"chemical": "Liquid Chlorine", "quantity": 1, "unit": "gal"},
           ],
           "chemical_readings": [
               {"key": "ph", "name": "pH", "value": 7.4},
               {"key": "chlorine", "name": "Free Chlorine", "value": 2.5, "unit": "ppm"},
           ],
           "checklist_items": [
               {"label": "Skim surface", "checked": True},
               {"label": "Vacuum floor", "checked": False},
           ]}
    _sync.service_reports.insert_one(dict(doc))
    yield doc
    _sync.service_reports.delete_one({"id": rid})


@pytest.fixture(scope="module")
def api_base():
    # Prefer the preview REACT_APP_BACKEND_URL so tests exercise the
    # real ingress + supervisor-managed backend (matches every other
    # test file in this suite).
    from pathlib import Path as _P
    _react_env = _P(__file__).resolve().parents[2] / "frontend" / ".env"
    react = dotenv_values(_react_env) if _react_env.is_file() else {}
    public = (react.get("REACT_APP_BACKEND_URL")
              or os.environ.get("REACT_APP_BACKEND_URL"))
    return ((public.rstrip("/") + "/api") if public else
            "http://localhost:8001/api")


def test_portal_returns_new_sections(api_base, tenant_row, job_row, report_row):
    import requests
    r = requests.get(
        f"{api_base}/public/service/{report_row['public_uuid']}", timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # chemicals
    assert body["chemicals_added"], "chemicals missing"
    assert body["chemicals_added"][0]["name"] == "Liquid Chlorine"
    # readings — null-value rows dropped
    names = [r["name"] for r in body["chemical_readings"]]
    assert "pH" in names and "Free Chlorine" in names
    # checklist — only checked items
    labels = [c["label"] for c in body["checklist"]]
    assert "Skim surface" in labels
    assert "Vacuum floor" not in labels
    # videos array present (empty is fine)
    assert isinstance(body["videos"], list)


def test_portal_never_leaks_pii_with_new_sections(api_base, tenant_row,
                                                       job_row, report_row):
    import requests
    r = requests.get(
        f"{api_base}/public/service/{report_row['public_uuid']}", timeout=15)
    raw = r.text.lower()
    for leak in ("jane", "homeowner", "555-0100", "jane@example.test"):
        assert leak.lower() not in raw, f"PII leak: {leak}"


# ═══════════ Media router — cap enforcement (unit-level) ═══════════════
def test_media_router_source_declares_expected_caps():
    """Source-level assertion — the media router's constants must match
    the Phase 27 brief: 10 photos, 3 videos, 60s duration cap."""
    from routers import service_report_media as m
    assert m.MAX_PHOTOS_PER_REPORT == 10
    assert m.MAX_VIDEOS_PER_REPORT == 3
    assert m.MAX_VIDEO_DURATION_S == 60.0
