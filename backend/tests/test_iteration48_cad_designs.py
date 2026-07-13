"""Iteration 48 — Design Studio (CAD) backend tests.

Covers:
- POST /api/designs — admin & technician create; customer -> 403; unauth -> 401/403
- GET /api/designs — newest-first list; OMITS `elements` & `boundary`; includes
  name/area_sqft/thumbnail; ?customer_id= and ?lead_id= filters work
- GET /api/designs/{id} — returns full doc including elements & boundary
- PUT /api/designs/{id} — updates fields
- DELETE /api/designs/{id} — {ok:true} and disappears from list
"""
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

# --- Base URL / creds ---------------------------------------------------------
_FRONTEND_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_FE_ENV = dotenv_values(_FRONTEND_ENV)
BASE_URL = (
    _FE_ENV.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or ""
).rstrip("/")

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}
CUSTOMER = {"email": "customer@aquaterra.com", "password": "password123"}


# --- Helpers ------------------------------------------------------------------
def _login(creds: dict) -> str:
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login(ADMIN)


@pytest.fixture(scope="module")
def tech_token() -> str:
    return _login(TECH)


@pytest.fixture(scope="module")
def customer_token() -> str:
    return _login(CUSTOMER)


def _sample_payload(name: str = "TEST_CAD_Design", **overrides) -> dict:
    body = {
        "name": name,
        "canvas_w_ft": 60,
        "canvas_h_ft": 40,
        "boundary": [
            {"x": 0.1, "y": 0.1},
            {"x": 0.9, "y": 0.1},
            {"x": 0.9, "y": 0.9},
            {"x": 0.1, "y": 0.9},
        ],
        "elements": [
            {"id": "e1", "kind": "pool", "label": "Pool",
             "x": 0.3, "y": 0.3, "w": 0.34, "h": 0.42,
             "rotation": 0, "color": "#38BDF8", "icon": "water"},
        ],
        "area_sqft": 1920.0,
        "perimeter_ft": 176.0,
        "thumbnail": None,
    }
    body.update(overrides)
    return body


# Track created ids for teardown
_CREATED: list[tuple[str, str]] = []  # (id, admin_token)


def _cleanup(admin_token: str):
    for did, tok in _CREATED:
        try:
            requests.delete(f"{BASE_URL}/api/designs/{did}", headers=_auth(tok), timeout=10)
        except Exception:
            pass


# --- Auth guard ---------------------------------------------------------------
class TestAuth:
    def test_unauth_post_designs(self):
        r = requests.post(f"{BASE_URL}/api/designs", json=_sample_payload(), timeout=15)
        assert r.status_code in (401, 403), f"Expected 401/403 got {r.status_code}"

    def test_unauth_get_designs(self):
        r = requests.get(f"{BASE_URL}/api/designs", timeout=15)
        assert r.status_code in (401, 403)

    def test_customer_role_forbidden(self, customer_token):
        r = requests.post(f"{BASE_URL}/api/designs", json=_sample_payload("TEST_CAD_forbidden"),
                          headers=_auth(customer_token), timeout=15)
        assert r.status_code == 403, f"Expected 403 got {r.status_code} {r.text}"

    def test_customer_cannot_list(self, customer_token):
        r = requests.get(f"{BASE_URL}/api/designs", headers=_auth(customer_token), timeout=15)
        assert r.status_code == 403


# --- Create / Read / List -----------------------------------------------------
class TestCreateAndList:
    def test_admin_can_create(self, admin_token):
        payload = _sample_payload("TEST_CAD_admin_1")
        r = requests.post(f"{BASE_URL}/api/designs", json=payload,
                          headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("id"), "response missing id"
        assert d["name"] == "TEST_CAD_admin_1"
        assert d["canvas_w_ft"] == 60
        assert d["canvas_h_ft"] == 40
        assert isinstance(d["elements"], list) and len(d["elements"]) == 1
        assert isinstance(d["boundary"], list) and len(d["boundary"]) == 4
        assert d["area_sqft"] == 1920.0
        assert d["perimeter_ft"] == 176.0
        assert "_id" not in d, "MongoDB _id must not leak"
        _CREATED.append((d["id"], admin_token))

    def test_technician_can_create(self, tech_token, admin_token):
        payload = _sample_payload("TEST_CAD_tech_1")
        r = requests.post(f"{BASE_URL}/api/designs", json=payload,
                          headers=_auth(tech_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["created_by_name"], "created_by_name should be populated"
        _CREATED.append((d["id"], admin_token))

    def test_list_omits_heavy_fields_and_is_newest_first(self, admin_token):
        # create one with a distinctive thumbnail so list preview check works
        p = _sample_payload("TEST_CAD_thumb", thumbnail="data:image/png;base64,AAAA")
        c = requests.post(f"{BASE_URL}/api/designs", json=p,
                         headers=_auth(admin_token), timeout=15)
        assert c.status_code == 200
        cid = c.json()["id"]
        _CREATED.append((cid, admin_token))

        r = requests.get(f"{BASE_URL}/api/designs", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 3

        # each row must OMIT elements/boundary, INCLUDE name/area_sqft/thumbnail key
        for row in arr:
            assert "elements" not in row, "list must omit `elements`"
            assert "boundary" not in row, "list must omit `boundary`"
            assert "name" in row
            assert "area_sqft" in row
            assert "thumbnail" in row  # key present (value may be None)
            assert "_id" not in row

        # newest-first: our just-created cid should appear before earlier ones
        ids_in_order = [row["id"] for row in arr]
        first_created = _CREATED[0][0]
        assert ids_in_order.index(cid) < ids_in_order.index(first_created), \
            "list not newest-first"

        # thumbnail preserved in list for that row
        row = next(r for r in arr if r["id"] == cid)
        assert row["thumbnail"] == "data:image/png;base64,AAAA"

    def test_get_by_id_returns_full_doc(self, admin_token):
        did = _CREATED[0][0]
        r = requests.get(f"{BASE_URL}/api/designs/{did}", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == did
        assert isinstance(d["elements"], list) and len(d["elements"]) == 1
        assert isinstance(d["boundary"], list) and len(d["boundary"]) == 4
        assert d["elements"][0]["kind"] == "pool"
        assert "_id" not in d

    def test_get_missing_returns_404(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/designs/does-not-exist-xyz",
                         headers=_auth(admin_token), timeout=15)
        assert r.status_code == 404


# --- Filters ------------------------------------------------------------------
class TestFilters:
    def test_customer_id_and_lead_id_filters(self, admin_token):
        # Create 2 designs: one attached to customer_id=CUST_TEST_1, one to lead LEAD_TEST_1
        p1 = _sample_payload("TEST_CAD_cust_attach", customer_id="CUST_TEST_1")
        p2 = _sample_payload("TEST_CAD_lead_attach", lead_id="LEAD_TEST_1")
        r1 = requests.post(f"{BASE_URL}/api/designs", json=p1, headers=_auth(admin_token), timeout=15)
        r2 = requests.post(f"{BASE_URL}/api/designs", json=p2, headers=_auth(admin_token), timeout=15)
        assert r1.status_code == 200 and r2.status_code == 200
        id1, id2 = r1.json()["id"], r2.json()["id"]
        _CREATED.extend([(id1, admin_token), (id2, admin_token)])

        # customer_id filter
        rc = requests.get(f"{BASE_URL}/api/designs?customer_id=CUST_TEST_1",
                          headers=_auth(admin_token), timeout=15)
        assert rc.status_code == 200
        cust_ids = [x["id"] for x in rc.json()]
        assert id1 in cust_ids and id2 not in cust_ids

        # lead_id filter
        rl = requests.get(f"{BASE_URL}/api/designs?lead_id=LEAD_TEST_1",
                          headers=_auth(admin_token), timeout=15)
        assert rl.status_code == 200
        lead_ids = [x["id"] for x in rl.json()]
        assert id2 in lead_ids and id1 not in lead_ids


# --- Update / Delete ----------------------------------------------------------
class TestUpdateDelete:
    def test_put_updates_fields(self, admin_token):
        p = _sample_payload("TEST_CAD_to_update")
        c = requests.post(f"{BASE_URL}/api/designs", json=p, headers=_auth(admin_token), timeout=15)
        assert c.status_code == 200
        did = c.json()["id"]
        _CREATED.append((did, admin_token))

        upd = _sample_payload("TEST_CAD_updated_name",
                              canvas_w_ft=80, canvas_h_ft=50,
                              area_sqft=3200.0, perimeter_ft=220.0)
        upd["elements"] = []
        upd["boundary"] = []
        r = requests.put(f"{BASE_URL}/api/designs/{did}", json=upd,
                         headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "TEST_CAD_updated_name"
        assert d["canvas_w_ft"] == 80
        assert d["canvas_h_ft"] == 50
        assert d["area_sqft"] == 3200.0
        assert d["elements"] == []
        assert d["boundary"] == []

        # Verify via GET
        g = requests.get(f"{BASE_URL}/api/designs/{did}", headers=_auth(admin_token), timeout=15)
        assert g.status_code == 200
        assert g.json()["name"] == "TEST_CAD_updated_name"

    def test_delete_returns_ok_and_removes_from_list(self, admin_token):
        p = _sample_payload("TEST_CAD_to_delete")
        c = requests.post(f"{BASE_URL}/api/designs", json=p, headers=_auth(admin_token), timeout=15)
        did = c.json()["id"]

        r = requests.delete(f"{BASE_URL}/api/designs/{did}", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        # No longer in list
        lst = requests.get(f"{BASE_URL}/api/designs", headers=_auth(admin_token), timeout=15).json()
        assert did not in [x["id"] for x in lst]

        # GET by id -> 404
        g = requests.get(f"{BASE_URL}/api/designs/{did}", headers=_auth(admin_token), timeout=15)
        assert g.status_code == 404


# --- Teardown -----------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def _teardown(admin_token):
    yield
    _cleanup(admin_token)
