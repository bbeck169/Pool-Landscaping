"""Feb-2026 · Customer PUT → primary-property address mirror.

The customer detail page reads its primary address from
``db.properties`` (see ``getPrimaryPropertyAddress`` in
``CustomerDetail.jsx``). Before this fix, editing a customer's
address only updated the customer doc — the property row stayed
stale, so the detail card appeared to "not save" the change.

This suite locks the mirror in place: after ``PUT /customers/{id}``
persists an address, the primary property's ``address.line1`` /
``city`` / ``state`` / ``postal_code`` reflect the new values.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)



_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
_FE_ENV = dotenv_values(
    Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
API = f"{BASE}/api"


def _login() -> dict:
    r = requests.post(f"{API}/auth/login",
                        json={"email": "admin@aquaterra.com",
                                "password": "password123"},
                        timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_admin():
    return _login()


@pytest.fixture()
def seeded_customer(h_admin):
    """Seed a fresh customer + one primary property, yield ids,
    delete everything on teardown."""
    cid = f"TEST_addr-c-{uuid.uuid4().hex[:8]}"
    pid = f"TEST_addr-p-{uuid.uuid4().hex[:8]}"
    r = requests.get(f"{API}/auth/me", headers=h_admin, timeout=15)
    tenant_id = r.json()["tenant_id"]
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "TEST_addr Customer",
        "first_name": "TEST_addr", "last_name": "Customer",
        "address": "111 Old St, Peoria, AZ, 85383",
        "address_line1": "111 Old St", "city": "Peoria",
        "state": "AZ", "postal_code": "85383",
        "service_address": {"street": "111 Old St",
                              "city": "Peoria", "state": "AZ",
                              "postal_code": "85383"},
        "is_active": True,
    })
    _sync.properties.insert_one({
        "id": pid, "tenant_id": tenant_id, "customer_id": cid,
        "label": "Main", "is_primary": True, "sort_order": 0,
        "active": True,
        "address": {"line1": "111 Old St", "city": "Peoria",
                     "state": "AZ", "postal_code": "85383",
                     "country": "US"},
    })
    yield {"cid": cid, "pid": pid, "tenant_id": tenant_id}
    _sync.customers.delete_one({"id": cid})
    _sync.properties.delete_one({"id": pid})


class TestPrimaryPropertyMirror:
    def test_put_customer_address_mirrors_to_primary_property(
        self, h_admin, seeded_customer,
    ):
        cid = seeded_customer["cid"]
        pid = seeded_customer["pid"]
        # PUT with new structured address fields
        body = {
            "name": "TEST_addr Customer",
            "first_name": "TEST_addr", "last_name": "Customer",
            "email": "", "phone": "",
            "address": "222 New Ave, Peoria, AZ, 85383",
            "address_line1": "222 New Ave",
            "city": "Peoria", "state": "AZ", "postal_code": "85383",
            "service_address": {"street": "222 New Ave",
                                  "city": "Peoria", "state": "AZ",
                                  "postal_code": "85383"},
            "is_active": True,
        }
        r = requests.put(f"{API}/customers/{cid}", json=body,
                            headers=h_admin, timeout=15)
        assert r.status_code == 200, r.text
        # Primary property must now carry the new street
        p = _sync.properties.find_one({"id": pid}, {"_id": 0})
        assert p["address"]["line1"] == "222 New Ave", (
            f"property.address.line1 did not update — still "
            f"{p['address']['line1']!r}"
        )
        assert p["address"]["city"] == "Peoria"
        assert p["address"]["state"] == "AZ"
        assert p["address"]["postal_code"] == "85383"

    def test_put_with_freeform_address_only(
        self, h_admin, seeded_customer,
    ):
        """Callers that only send the composed ``address`` string
        (no structured fields) still trigger the mirror via the
        free-form parser fallback."""
        cid = seeded_customer["cid"]
        pid = seeded_customer["pid"]
        body = {
            "name": "TEST_addr Customer",
            "first_name": "TEST_addr", "last_name": "Customer",
            "email": "", "phone": "",
            "address": "333 Freeform Rd, Peoria, AZ 85383",
            "is_active": True,
        }
        r = requests.put(f"{API}/customers/{cid}", json=body,
                            headers=h_admin, timeout=15)
        assert r.status_code == 200, r.text
        p = _sync.properties.find_one({"id": pid}, {"_id": 0})
        assert p["address"]["line1"] == "333 Freeform Rd"
        assert p["address"]["city"] == "Peoria"
        assert p["address"]["state"] == "AZ"
        assert p["address"]["postal_code"] == "85383"

    def test_put_without_address_change_leaves_property_alone(
        self, h_admin, seeded_customer,
    ):
        """When the PUT doesn't mutate the address (e.g. only the
        notes changed) the primary property row must NOT be
        touched — no re-geocode fan-out, no updated_at churn."""
        cid = seeded_customer["cid"]
        pid = seeded_customer["pid"]
        before = _sync.properties.find_one({"id": pid}, {"_id": 0})
        body = {
            "name": "TEST_addr Customer",
            "first_name": "TEST_addr", "last_name": "Customer",
            "email": "", "phone": "",
            "address": "111 Old St, Peoria, AZ, 85383",
            "address_line1": "111 Old St", "city": "Peoria",
            "state": "AZ", "postal_code": "85383",
            "service_address": {"street": "111 Old St",
                                  "city": "Peoria", "state": "AZ",
                                  "postal_code": "85383"},
            "notes": "unrelated tweak",
            "is_active": True,
        }
        r = requests.put(f"{API}/customers/{cid}", json=body,
                            headers=h_admin, timeout=15)
        assert r.status_code == 200, r.text
        after = _sync.properties.find_one({"id": pid}, {"_id": 0})
        # Address block byte-identical.
        assert after["address"] == before["address"]


class TestCorruptedRecordRegressionGuard:
    """Regression guard — the reported ``LorealLoreal10616 W Carlota Ln``
    corruption came from a one-off DB write, NOT the PUT handler.
    This test posts an address containing a repeat-prefix substring
    to prove the PUT handler does NOT amplify it on save."""

    def test_repeat_prefix_address_does_not_get_doubled(
        self, h_admin, seeded_customer,
    ):
        cid = seeded_customer["cid"]
        pid = seeded_customer["pid"]
        # Contrived edge — literal "Loreal" appears once in the
        # source. The mirror MUST persist it verbatim, not doubled.
        tricky = "Loreal10616 W Carlota Ln"
        body = {
            "name": "TEST_addr Customer",
            "first_name": "TEST_addr", "last_name": "Customer",
            "email": "", "phone": "",
            "address": f"{tricky}, Peoria, AZ, 85383",
            "address_line1": tricky,
            "city": "Peoria", "state": "AZ", "postal_code": "85383",
            "service_address": {"street": tricky,
                                  "city": "Peoria", "state": "AZ",
                                  "postal_code": "85383"},
            "is_active": True,
        }
        r = requests.put(f"{API}/customers/{cid}", json=body,
                            headers=h_admin, timeout=15)
        assert r.status_code == 200, r.text
        p = _sync.properties.find_one({"id": pid}, {"_id": 0})
        # NEVER doubled to "LorealLoreal..."
        assert p["address"]["line1"] == tricky, (
            f"property.address.line1 mutated: {p['address']['line1']!r}"
        )
        assert "LorealLoreal" not in p["address"]["line1"]
