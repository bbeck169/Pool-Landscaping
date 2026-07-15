"""Phase 34d — pool_gallons field on Customer (create/read/update/validate)."""
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH  = {"email": "mike@aquaterra.com",  "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def tech_tok():
    return _login(TECH)


def _mk_name():
    return f"TEST-poolgal-{uuid.uuid4().hex[:8]}"


def _cleanup(tok, cid):
    if cid:
        requests.delete(f"{API}/customers/{cid}", headers=_auth(tok), timeout=15)


def test_create_with_pool_gallons_roundtrips(admin_tok):
    body = {"name": _mk_name(), "pool_gallons": 20000}
    r = requests.post(f"{API}/customers", json=body, headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    cid = j["id"]
    try:
        assert j.get("pool_gallons") == 20000, j
        # GET must also return the field.
        g = requests.get(f"{API}/customers/{cid}", headers=_auth(admin_tok), timeout=15).json()
        assert g.get("pool_gallons") == 20000, g
    finally:
        _cleanup(admin_tok, cid)


def test_create_without_pool_gallons_returns_null(admin_tok):
    body = {"name": _mk_name()}
    r = requests.post(f"{API}/customers", json=body, headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    try:
        g = requests.get(f"{API}/customers/{cid}", headers=_auth(admin_tok), timeout=15).json()
        assert "pool_gallons" in g, g
        assert g["pool_gallons"] is None, g
    finally:
        _cleanup(admin_tok, cid)


def test_update_sets_pool_gallons(admin_tok):
    """PUT is the full-body update endpoint for customers (no PATCH exists).
    Sending a full CustomerIn body with pool_gallons must persist the value."""
    r = requests.post(f"{API}/customers",
                       json={"name": _mk_name()},
                       headers=_auth(admin_tok), timeout=15)
    cid = r.json()["id"]
    try:
        upd = {"name": r.json()["name"], "pool_gallons": 15500}
        r2 = requests.put(f"{API}/customers/{cid}", json=upd,
                           headers=_auth(admin_tok), timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["pool_gallons"] == 15500
    finally:
        _cleanup(admin_tok, cid)


def test_update_to_null(admin_tok):
    r = requests.post(f"{API}/customers",
                       json={"name": _mk_name(), "pool_gallons": 12000},
                       headers=_auth(admin_tok), timeout=15)
    cid = r.json()["id"]
    try:
        upd = {"name": r.json()["name"], "pool_gallons": None}
        r2 = requests.put(f"{API}/customers/{cid}", json=upd,
                           headers=_auth(admin_tok), timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["pool_gallons"] is None
    finally:
        _cleanup(admin_tok, cid)


@pytest.mark.parametrize("bad", [-1, 0, 500001, "abc", 1.5, [], {}])
def test_invalid_pool_gallons_rejected(admin_tok, bad):
    body = {"name": _mk_name(), "pool_gallons": bad}
    r = requests.post(f"{API}/customers", json=body,
                       headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 422, (bad, r.status_code, r.text)


def test_boundaries_accepted(admin_tok):
    """1 and 500000 are the inclusive bounds."""
    for v in (1, 500000):
        r = requests.post(f"{API}/customers",
                           json={"name": _mk_name(), "pool_gallons": v},
                           headers=_auth(admin_tok), timeout=15)
        assert r.status_code == 200, (v, r.text)
        cid = r.json()["id"]
        try:
            assert r.json()["pool_gallons"] == v
        finally:
            _cleanup(admin_tok, cid)


def test_tech_cannot_create_customer(tech_tok):
    """RBAC unchanged: /customers create/update still admin-only.
    Techs get 403 regardless of pool_gallons payload."""
    r = requests.post(f"{API}/customers",
                       json={"name": _mk_name(), "pool_gallons": 20000},
                       headers=_auth(tech_tok), timeout=15)
    assert r.status_code == 403, r.text


def test_list_customers_includes_pool_gallons(admin_tok):
    """GET /api/customers must not project the field away."""
    r = requests.post(f"{API}/customers",
                       json={"name": _mk_name(), "pool_gallons": 33000},
                       headers=_auth(admin_tok), timeout=15)
    cid = r.json()["id"]
    try:
        rows = requests.get(f"{API}/customers", headers=_auth(admin_tok), timeout=15).json()
        row = next((x for x in rows if x.get("id") == cid), None)
        assert row is not None
        assert row.get("pool_gallons") == 33000, row
    finally:
        _cleanup(admin_tok, cid)


# ═══════════════════════════════════════════════════════════════════════
# Phase 34d-follow — is_vip flag on Customer + surfaced on job payloads
# ═══════════════════════════════════════════════════════════════════════

def test_create_with_is_vip_true(admin_tok):
    r = requests.post(f"{API}/customers",
                       json={"name": _mk_name(), "is_vip": True},
                       headers=_auth(admin_tok), timeout=15)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    try:
        assert r.json()["is_vip"] is True
        g = requests.get(f"{API}/customers/{cid}", headers=_auth(admin_tok), timeout=15).json()
        assert g["is_vip"] is True
    finally:
        _cleanup(admin_tok, cid)


def test_default_is_vip_false(admin_tok):
    """Omitting is_vip on create defaults to False (never missing on POST echo)."""
    r = requests.post(f"{API}/customers",
                       json={"name": _mk_name()},
                       headers=_auth(admin_tok), timeout=15)
    cid = r.json()["id"]
    try:
        # POST echo comes straight from body.dict() so has the field.
        assert r.json().get("is_vip") is False
    finally:
        _cleanup(admin_tok, cid)


def test_toggle_is_vip_via_put(admin_tok):
    """Full-body PUT (customers has no PATCH) toggles is_vip in both directions."""
    r = requests.post(f"{API}/customers",
                       json={"name": _mk_name(), "is_vip": True},
                       headers=_auth(admin_tok), timeout=15)
    cid = r.json()["id"]
    name = r.json()["name"]
    try:
        # Flip to False.
        r2 = requests.put(f"{API}/customers/{cid}",
                           json={"name": name, "is_vip": False},
                           headers=_auth(admin_tok), timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["is_vip"] is False
        # And back to True.
        r3 = requests.put(f"{API}/customers/{cid}",
                           json={"name": name, "is_vip": True},
                           headers=_auth(admin_tok), timeout=15)
        assert r3.status_code == 200
        assert r3.json()["is_vip"] is True
    finally:
        _cleanup(admin_tok, cid)


def test_jobs_endpoint_surfaces_customer_is_vip(admin_tok):
    """GET /api/jobs must include `customer_is_vip` on every job so schedule
    cards can render the badge without a second roundtrip."""
    # Seed a VIP customer + a job for them.
    c = requests.post(f"{API}/customers",
                       json={"name": _mk_name(), "is_vip": True},
                       headers=_auth(admin_tok), timeout=15).json()
    cid = c["id"]
    j = requests.post(f"{API}/jobs",
                       json={"title": "VIP test visit",
                              "customer_id": cid,
                              "scheduled_date": "2026-02-20"},
                       headers=_auth(admin_tok), timeout=15)
    assert j.status_code == 200, j.text
    jid = j.json()["id"]
    try:
        rows = requests.get(f"{API}/jobs", headers=_auth(admin_tok), timeout=15).json()
        row = next((x for x in rows if x.get("id") == jid), None)
        assert row is not None, "seeded job missing from /jobs"
        assert row.get("customer_is_vip") is True, row
        # Non-VIP jobs must still carry the field (as False) so client code
        # can treat it as always-present.
        non_vip_row = next((x for x in rows if x.get("id") != jid and x.get("customer_id")), None)
        if non_vip_row:
            assert "customer_is_vip" in non_vip_row, non_vip_row
    finally:
        requests.delete(f"{API}/jobs/{jid}", headers=_auth(admin_tok), timeout=15)
        _cleanup(admin_tok, cid)
