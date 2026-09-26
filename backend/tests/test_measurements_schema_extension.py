"""M1 · Feb-2026 — measurements schema extension + tech write access.

Covers the changes shipped alongside the M1 manual-measurements
Customer Detail tab:
  * ``type`` + ``unit`` added to ``MeasurementIn`` (additive-nullable).
  * ``POST /measurements`` opened from ``require_admin`` to
    ``require_tech_or_above``.
  * Server auto-attaches ``technician_id``, ``technician_name``,
    ``created_at``, ``tenant_id`` — cannot be spoofed by the client
    (Pydantic strips unknown keys).
  * Cross-tenant hardening on ``customer_id`` / ``lead_id`` — techs
    cannot POST measurements against other tenants' customer rows.

HTTP-integration style matches ``test_material_calculator_endpoint.py``.
"""
from __future__ import annotations
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

API = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
TIMEOUT = 20

_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "meas_ext_"


# ═══ auth helpers ════════════════════════════════════════════════════
def _login(email: str, pwd: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pwd},
                      timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("access_token") or r.json().get("token")


def _me(tok: str) -> dict:
    r = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def tech_tok():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def customer_tok():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def tech_identity(tech_tok):
    return _me(tech_tok)


# ═══ DB fixture — customer in caller tenant + a second-tenant fake ═══
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def scenario(dbc, tech_identity):
    tid = tech_identity["tenant_id"]
    fake_tid = f"{TAG}other-tenant-{uuid.uuid4().hex[:8]}"
    ids = {
        "customers":     [],
        "leads":         [],
        "measurements":  [],
        "other_tenant":  fake_tid,
        "caller_tenant": tid,
    }

    # 1 · in-tenant customer + lead (tech is allowed to POST against)
    my_cid = f"{TAG}mycust-{uuid.uuid4().hex[:8]}"
    my_lid = f"{TAG}mylead-{uuid.uuid4().hex[:8]}"
    dbc.customers.insert_one({
        "id": my_cid, "tenant_id": tid,
        "name": "Tech Test Customer",
    })
    dbc.leads.insert_one({
        "id": my_lid, "tenant_id": tid,
        "name": "Tech Test Lead",
    })
    ids["customers"].append(my_cid)
    ids["leads"].append(my_lid)
    ids["my_cid"] = my_cid
    ids["my_lid"] = my_lid

    # 2 · out-of-tenant customer + lead (tech must NOT be able to POST against)
    ot_cid = f"{TAG}othercust-{uuid.uuid4().hex[:8]}"
    ot_lid = f"{TAG}otherlead-{uuid.uuid4().hex[:8]}"
    dbc.customers.insert_one({
        "id": ot_cid, "tenant_id": fake_tid,
        "name": "Other-Tenant Customer",
    })
    dbc.leads.insert_one({
        "id": ot_lid, "tenant_id": fake_tid,
        "name": "Other-Tenant Lead",
    })
    ids["customers"].append(ot_cid)
    ids["leads"].append(ot_lid)
    ids["other_cid"] = ot_cid
    ids["other_lid"] = ot_lid

    yield ids

    # teardown — drop everything this test seeded
    dbc.customers.delete_many({"id": {"$in": ids["customers"]}})
    dbc.leads.delete_many({"id": {"$in": ids["leads"]}})
    if ids["measurements"]:
        dbc.measurements.delete_many({"id": {"$in": ids["measurements"]}})


def _post(tok: str, body: dict) -> requests.Response:
    return requests.post(f"{API}/measurements",
                         json=body, headers=_h(tok), timeout=TIMEOUT)


# ═══ Legal (type, unit) combinations ═════════════════════════════════
class TestLegalTypeUnitCombos:
    def test_linear_ft(self, tech_tok, scenario):
        r = _post(tech_tok, {
            "name": "Linear ft fence",
            "type": "linear", "unit": "ft",
            "distance_ft": 42.0,
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 200, r.text
        j = r.json()
        scenario["measurements"].append(j["id"])
        assert j["type"] == "linear"
        assert j["unit"] == "ft"
        assert j["distance_ft"] == 42.0

    def test_area_sqft(self, tech_tok, scenario):
        r = _post(tech_tok, {
            "name": "Area sqft patio",
            "type": "area", "unit": "sqft",
            "area_sqft": 250.0,
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 200, r.text
        j = r.json()
        scenario["measurements"].append(j["id"])
        assert j["type"] == "area"
        assert j["unit"] == "sqft"
        assert j["area_sqft"] == 250.0

    def test_perimeter_yd(self, tech_tok, scenario):
        r = _post(tech_tok, {
            "name": "Perimeter yd fence",
            "type": "perimeter", "unit": "yd",
            "perimeter_ft": 84.0,
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 200, r.text
        j = r.json()
        scenario["measurements"].append(j["id"])
        assert j["type"] == "perimeter"
        assert j["unit"] == "yd"


# ═══ Illegal (type, unit) combinations → 422 ═════════════════════════
class TestIllegalTypeUnitCombos:
    def test_linear_with_sqft_rejected(self, tech_tok, scenario):
        r = _post(tech_tok, {
            "type": "linear", "unit": "sqft",
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 422
        assert "unit" in r.text and "linear" in r.text

    def test_area_with_ft_rejected(self, tech_tok, scenario):
        r = _post(tech_tok, {
            "type": "area", "unit": "ft",
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 422
        assert "unit" in r.text and "area" in r.text

    def test_perimeter_with_sqft_rejected(self, tech_tok, scenario):
        r = _post(tech_tok, {
            "type": "perimeter", "unit": "sqft",
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 422

    def test_type_without_unit_rejected(self, tech_tok, scenario):
        r = _post(tech_tok, {
            "type": "linear",
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 422
        assert "unit" in r.text


# ═══ Backward compatibility with the satellite POST ══════════════════
class TestSatelliteBackwardCompat:
    def test_post_without_type_and_unit_still_accepted(self, tech_tok, scenario):
        # Legacy satellite POST — no type / unit at all.  Row lands
        # with type=None / unit=None so the M1 tab can filter it out.
        r = _post(tech_tok, {
            "name": "Legacy satellite trace",
            "mode": "area",
            "points": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "area_sqft": 1.0,
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 200, r.text
        j = r.json()
        scenario["measurements"].append(j["id"])
        assert j["type"] is None
        assert j["unit"] is None


# ═══ RBAC · POST tech-open, other roles blocked ══════════════════════
class TestPostRbac:
    def test_technician_role_now_allowed(self, tech_tok, scenario):
        # Pre-Feb-2026 this returned 403.  Post-fix: 200.
        r = _post(tech_tok, {
            "type": "linear", "unit": "ft",
            "distance_ft": 10.0,
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 200, r.text
        scenario["measurements"].append(r.json()["id"])

    def test_admin_still_allowed(self, admin_tok, scenario):
        r = _post(admin_tok, {
            "type": "area", "unit": "sqft",
            "area_sqft": 1.0,
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 200, r.text
        scenario["measurements"].append(r.json()["id"])

    def test_customer_role_blocked(self, customer_tok, scenario):
        r = _post(customer_tok, {
            "type": "area", "unit": "sqft",
            "area_sqft": 1.0,
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 403

    def test_unauthed_blocked(self, scenario):
        r = requests.post(f"{API}/measurements",
                          json={"type": "area", "unit": "sqft"},
                          timeout=TIMEOUT)
        assert r.status_code in (401, 403)


# ═══ Server auto-fields · cannot be spoofed by the client ════════════
class TestServerAutoFields:
    def test_technician_and_tenant_fields_pinned_to_authed_user(
        self, tech_tok, tech_identity, scenario,
    ):
        r = _post(tech_tok, {
            "type": "linear", "unit": "ft",
            "distance_ft": 12.0,
            "customer_id": scenario["my_cid"],
        })
        assert r.status_code == 200, r.text
        j = r.json()
        scenario["measurements"].append(j["id"])
        # tenant_id + technician_id come from the auth context,
        # not the payload.
        assert j["tenant_id"] == tech_identity["tenant_id"]
        assert j["technician_id"] == tech_identity["id"]
        assert j["technician_name"] == tech_identity.get("name", "")
        assert isinstance(j["created_at"], str) and len(j["created_at"]) > 0
        # Legacy created_by mirror fields still populated for
        # backward-compat with older readers.
        assert j["created_by"] == tech_identity["id"]

    def test_client_supplied_technician_fields_are_ignored(
        self, tech_tok, tech_identity, scenario,
    ):
        # Every attribution-related key that a malicious client
        # might try to smuggle in via the JSON body — Pydantic
        # strips them (they are not on ``MeasurementIn``).
        spoof_tid = "SPOOFED-TENANT"
        spoof_uid = "SPOOFED-USER"
        r = _post(tech_tok, {
            "type": "linear", "unit": "ft",
            "distance_ft": 5.0,
            "customer_id": scenario["my_cid"],
            "tenant_id":      spoof_tid,
            "technician_id":  spoof_uid,
            "technician_name": "MalloryMcSpoof",
            "created_by":     spoof_uid,
            "created_by_name": "MalloryMcSpoof",
            "created_at":     "1970-01-01T00:00:00+00:00",
        })
        assert r.status_code == 200, r.text
        j = r.json()
        scenario["measurements"].append(j["id"])
        # Every spoofed value MUST NOT survive the round-trip.
        assert j["tenant_id"] != spoof_tid
        assert j["tenant_id"] == tech_identity["tenant_id"]
        assert j["technician_id"] != spoof_uid
        assert j["technician_id"] == tech_identity["id"]
        assert j["technician_name"] != "MalloryMcSpoof"
        assert j["created_by"] != spoof_uid
        assert j["created_at"] != "1970-01-01T00:00:00+00:00"


# ═══ Cross-tenant hardening on customer_id / lead_id ═════════════════
class TestCrossTenantHardening:
    def test_tech_cannot_post_against_other_tenant_customer_id(
        self, tech_tok, scenario,
    ):
        # scenario["other_cid"] belongs to scenario["other_tenant"],
        # NOT the tech's tenant.  Server must reject.
        r = _post(tech_tok, {
            "type": "linear", "unit": "ft",
            "distance_ft": 1.0,
            "customer_id": scenario["other_cid"],
        })
        assert r.status_code == 403
        assert "customer_id" in r.text

    def test_tech_cannot_post_against_other_tenant_lead_id(
        self, tech_tok, scenario,
    ):
        r = _post(tech_tok, {
            "type": "linear", "unit": "ft",
            "distance_ft": 1.0,
            "lead_id": scenario["other_lid"],
        })
        assert r.status_code == 403
        assert "lead_id" in r.text

    def test_tech_can_post_no_customer_no_lead(
        self, tech_tok, scenario,
    ):
        # Free-standing measurement (not yet attached to a
        # customer / lead) remains legal.
        r = _post(tech_tok, {
            "type": "area", "unit": "sqft",
            "area_sqft": 42.0,
        })
        assert r.status_code == 200, r.text
        scenario["measurements"].append(r.json()["id"])
