"""Admin editor for service_report_templates."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")


def _login(email, password="password123"):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def sunbelt_admin_h():
    return {"Authorization": f"Bearer {_login('admin@sunbelt.com')['access_token']}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}


@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


@pytest.fixture(autouse=True)
def _clean(dbc):
    """Reset any customization the previous test left behind (before AND after)."""
    for slug in ("aquaterra", "sunbelt"):
        t = dbc.tenants.find_one({"slug": slug})
        if t:
            dbc.service_report_templates.delete_many({"tenant_id": t["id"]})
    yield
    for slug in ("aquaterra", "sunbelt"):
        t = dbc.tenants.find_one({"slug": slug})
        if t:
            dbc.service_report_templates.delete_many({"tenant_id": t["id"]})


def test_admin_put_and_read_back(admin_h):
    payload = {
        "kind": "pool",
        "checklist_items": [
            {"id": "c1", "label": "TEST_ Skim surface", "required": True},
            {"id": "c2", "label": "TEST_ Brush walls", "required": False},
        ],
        "chemical_units": ["gal", "oz"],
    }
    r = requests.put(f"{API}/settings/service-templates", headers=admin_h,
                     json=payload, timeout=15)
    assert r.status_code == 200, r.text
    got = requests.get(f"{API}/settings/service-templates", headers=admin_h, timeout=15).json()
    pool = got["pool"]
    labels = [ (c if isinstance(c, str) else c.get("label")) for c in pool["checklist_items"] ]
    assert "TEST_ Skim surface" in labels
    assert pool["chemical_units"] == ["gal", "oz"]


def test_tech_and_customer_forbidden(tech_h, customer_h):
    payload = {"kind": "pool", "checklist_items": [{"label": "TEST_ nope"}]}
    r1 = requests.put(f"{API}/settings/service-templates", headers=tech_h,
                     json=payload, timeout=15)
    r2 = requests.put(f"{API}/settings/service-templates", headers=customer_h,
                     json=payload, timeout=15)
    r3 = requests.get(f"{API}/settings/service-templates", headers=tech_h, timeout=15)
    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403


def test_tenant_isolation(admin_h, sunbelt_admin_h):
    # aquaterra edits pool.chemical_units
    r = requests.put(f"{API}/settings/service-templates", headers=admin_h, json={
        "kind": "pool", "chemical_units": ["only_aquaterra_unit"],
    }, timeout=15)
    assert r.status_code == 200
    # sunbelt admin still sees the defaults
    got = requests.get(f"{API}/settings/service-templates",
                       headers=sunbelt_admin_h, timeout=15).json()
    assert "only_aquaterra_unit" not in got["pool"]["chemical_units"]
    assert "gal" in got["pool"]["chemical_units"]


def test_reset_defaults_restores_builtin(admin_h):
    # First customize
    requests.put(f"{API}/settings/service-templates", headers=admin_h, json={
        "kind": "landscape", "checklist_items": [{"label": "TEST_ only mow"}],
    }, timeout=15)
    got_edit = requests.get(f"{API}/settings/service-templates",
                            headers=admin_h, timeout=15).json()
    labels = [(c if isinstance(c, str) else c.get("label")) for c in got_edit["landscape"]["checklist_items"]]
    assert labels == ["TEST_ only mow"]
    # Then reset
    r = requests.post(f"{API}/settings/service-templates/landscape/reset-defaults",
                      headers=admin_h, timeout=15)
    assert r.status_code == 200
    # Defaults are back
    got = requests.get(f"{API}/settings/service-templates",
                       headers=admin_h, timeout=15).json()
    labels = [(c if isinstance(c, str) else c.get("label")) for c in got["landscape"]["checklist_items"]]
    assert any("Mow" in l or "mow" in l for l in labels)
    assert "TEST_ only mow" not in labels


def test_validation_rejects_bad_payload(admin_h):
    # min > max
    r = requests.put(f"{API}/settings/service-templates", headers=admin_h, json={
        "kind": "pool", "chemical_reading_fields": [
            {"key": "ph", "name": "pH", "type": "number", "min": 10, "max": 5},
        ],
    }, timeout=15)
    assert r.status_code == 422
    assert "min > max" in r.text
    # duplicate key
    r = requests.put(f"{API}/settings/service-templates", headers=admin_h, json={
        "kind": "pool", "chemical_reading_fields": [
            {"key": "ph", "name": "pH", "type": "number"},
            {"key": "ph", "name": "pH duplicate", "type": "number"},
        ],
    }, timeout=15)
    assert r.status_code == 422
    assert "duplicate key" in r.text
    # select type without options
    r = requests.put(f"{API}/settings/service-templates", headers=admin_h, json={
        "kind": "pool", "chemical_reading_fields": [
            {"key": "ph", "name": "pH", "type": "select"},
        ],
    }, timeout=15)
    assert r.status_code == 422
    assert "options required" in r.text
    # missing name
    r = requests.put(f"{API}/settings/service-templates", headers=admin_h, json={
        "kind": "pool", "chemicals_catalog": [{"default_unit": "gal"}],
    }, timeout=15)
    assert r.status_code == 422


def test_edit_affects_next_service_report(admin_h, tech_h, dbc):
    """After the admin customizes the pool checklist, the next fresh service
    report bootstrap must reflect the change."""
    requests.put(f"{API}/settings/service-templates", headers=admin_h, json={
        "kind": "pool",
        "checklist_items": [
            {"label": "TEST_ Edited: verify skimmer basket"},
            {"label": "TEST_ Edited: log Cl reading"},
        ],
    }, timeout=15)
    # Seed a job for Mike using the dev hook.
    seed = requests.post(f"{API}/workforce/_test/seed-in-window-job",
                        headers=tech_h, timeout=15).json()
    jid = seed["job_id"]
    try:
        rep = requests.get(f"{API}/jobs/{jid}/service-report",
                          headers=tech_h, timeout=15).json()
        labels = [c["label"] for c in rep["checklist_items"]]
        assert any("Edited" in l for l in labels)
    finally:
        dbc.jobs.delete_one({"id": jid})
        dbc.service_reports.delete_many({"job_id": jid})
