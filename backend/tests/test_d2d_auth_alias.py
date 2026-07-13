"""D2D authorization regression + outcome->disposition alias verification."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://poolscape-audit.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_token():
    return _login("mike@aquaterra.com", "password123")


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# --- AUTH REGRESSION: sold-leads ------------------------------------------

def test_sold_leads_tech_forbidden(tech_token):
    r = requests.get(f"{API}/d2d/sold-leads", params={"zip": "85383"}, headers=_h(tech_token), timeout=60)
    assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:400]}"
    assert "Admin access required" in r.text, r.text[:400]


def test_sold_leads_admin_ok(admin_token):
    r = requests.get(f"{API}/d2d/sold-leads", params={"zip": "85383"}, headers=_h(admin_token), timeout=90)
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
    body = r.json()
    assert "count" in body
    assert "properties" in body
    assert isinstance(body["properties"], list)


# --- FIELD ALIAS on POST /d2d/knocks ---------------------------------------

_created_knock_ids = []


def test_knock_outcome_alias_maps_to_disposition(admin_token):
    r = requests.post(f"{API}/d2d/knocks",
                      json={"address": "alias-test-1", "outcome": "interested", "notes": "test"},
                      headers=_h(admin_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
    body = r.json()
    assert body.get("disposition") == "interested", body
    if body.get("id"):
        _created_knock_ids.append(body["id"])


def test_knock_disposition_backward_compat(admin_token):
    r = requests.post(f"{API}/d2d/knocks",
                      json={"address": "alias-test-2", "disposition": "sold", "notes": "test"},
                      headers=_h(admin_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
    body = r.json()
    assert body.get("disposition") == "sold", body
    if body.get("id"):
        _created_knock_ids.append(body["id"])


def test_knock_default_disposition(admin_token):
    r = requests.post(f"{API}/d2d/knocks",
                      json={"address": "alias-test-3", "notes": "no disposition or outcome"},
                      headers=_h(admin_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
    body = r.json()
    assert body.get("disposition") == "not_home", body
    if body.get("id"):
        _created_knock_ids.append(body["id"])


# --- AUTHORIZATION AUDIT ---------------------------------------------------

def test_report_tech_forbidden(tech_token):
    r = requests.get(f"{API}/d2d/report", headers=_h(tech_token), timeout=30)
    assert r.status_code == 403, f"{r.status_code} {r.text[:200]}"


def test_report_admin_ok(admin_token):
    r = requests.get(f"{API}/d2d/report", headers=_h(admin_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    body = r.json()
    assert "totals" in body
    assert "reps" in body


def test_knocks_list_tech_ok(tech_token):
    r = requests.get(f"{API}/d2d/knocks", headers=_h(tech_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    assert isinstance(r.json(), list)


def test_leaderboard_tech_ok(tech_token):
    r = requests.get(f"{API}/d2d/leaderboard", headers=_h(tech_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    assert isinstance(r.json(), list)


def test_open_leads_tech_ok(tech_token):
    r = requests.get(f"{API}/d2d/open-leads", headers=_h(tech_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    body = r.json()
    assert "count" in body and "leads" in body


def test_post_knock_tech_ok(tech_token):
    r = requests.post(f"{API}/d2d/knocks",
                      json={"address": "tech-knock", "disposition": "not_home"},
                      headers=_h(tech_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
    body = r.json()
    if body.get("id"):
        _created_knock_ids.append(body["id"])


# --- REGRESSION: skip / unskip Zillow pin as technician --------------------

def test_skip_zillow_pin_tech(tech_token):
    r = requests.post(f"{API}/d2d/skip/95101886", headers=_h(tech_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"


def test_unskip_zillow_pin_tech(tech_token):
    r = requests.delete(f"{API}/d2d/skip/95101886", headers=_h(tech_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"


# --- Cleanup ---------------------------------------------------------------

def test_zz_cleanup_created_knocks(admin_token):
    failures = []
    for kid in _created_knock_ids:
        try:
            r = requests.delete(f"{API}/d2d/knocks/{kid}", headers=_h(admin_token), timeout=30)
            if r.status_code not in (200, 204, 404):
                failures.append((kid, r.status_code, r.text[:120]))
        except Exception as e:
            failures.append((kid, "exc", str(e)))
    assert not failures, f"cleanup failures: {failures}"
