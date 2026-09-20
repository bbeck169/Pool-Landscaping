"""Phase Feb-2026 · Warranty contracts · linked_type/linked_id tests.

Covers the schema extension, link validation, customer-scoped list
endpoints (admin + portal), and the link-options autopopulate feed.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
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
_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE
API = f"{BASE}/api"


def _login(email, password="password123"):
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_admin():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def h_customer():
    return _login("customer@aquaterra.com")


@pytest.fixture(scope="module")
def tenant_id(h_admin):
    r = requests.get(f"{API}/auth/me", headers=h_admin, timeout=15)
    return r.json()["tenant_id"]


@pytest.fixture(scope="module")
def customer_id(h_admin, tenant_id):
    cid = f"TEST_wty-{uuid.uuid4().hex[:8]}"
    _sync.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": f"TEST_wty_cust_{cid[-6:]}",
    })
    yield cid
    _sync.customers.delete_many({"id": cid})
    _sync.warranty_contracts.delete_many({"customer_id": cid})
    _sync.jobs.delete_many({"customer_id": cid})
    _sync.customer_equipment.delete_many({"customer_id": cid})


@pytest.fixture(scope="module")
def install_job(customer_id, tenant_id):
    jid = f"TEST_wty-job-{uuid.uuid4().hex[:8]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id, "customer_id": customer_id,
        "title": "TEST_wty New Pool Install",
        "service_type": "Pool Install",
        "scheduled_date": "2026-01-10",
        "status": "completed",
    })
    yield jid
    _sync.jobs.delete_many({"id": jid})


@pytest.fixture(scope="module")
def non_install_job(customer_id, tenant_id):
    jid = f"TEST_wty-job2-{uuid.uuid4().hex[:8]}"
    _sync.jobs.insert_one({
        "id": jid, "tenant_id": tenant_id, "customer_id": customer_id,
        "title": "TEST_wty routine service",
        "service_type": "Weekly Service",  # no "install" substring
        "scheduled_date": "2026-01-11",
    })
    yield jid
    _sync.jobs.delete_many({"id": jid})


@pytest.fixture(scope="module")
def equipment(customer_id, h_admin):
    r = requests.post(
        f"{API}/customer-equipment", headers=h_admin, timeout=15,
        json={
            "customer_id": customer_id,
            "equipment_type": "Filter Pump",
            "brand": "Pentair", "model": "IntelliFlo",
            "serial_number": "SN-warranty-42",
            "install_date": "2026-01-10",
        },
    )
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    yield eid
    requests.delete(
        f"{API}/customer-equipment/{eid}", headers=h_admin, timeout=15,
    )


@pytest.fixture(scope="module")
def plan_id(h_admin):
    r = requests.get(f"{API}/warranties/plans", headers=h_admin, timeout=15)
    assert r.status_code == 200
    return r.json()["items"][0]["id"]


def _create_contract(h, customer_id, plan_id, **overrides):
    body = {
        "plan_id": plan_id,
        "customer_id": customer_id,
        "start_date": "2026-02-01",
    }
    body.update(overrides)
    return requests.post(
        f"{API}/warranties/contracts", headers=h, json=body, timeout=15,
    )


# ═══════════════ Link validation ══════════════════════════════════
class TestLinkValidation:
    def test_install_link_valid(self, h_admin, customer_id, plan_id, install_job):
        r = _create_contract(
            h_admin, customer_id, plan_id,
            linked_type="install", linked_id=install_job,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["linked_type"] == "install"
        assert body["linked_id"] == install_job
        assert body["linked_summary"]["type"] == "install"
        assert "Install" in body["linked_summary"]["label"]

    def test_equipment_link_valid(self, h_admin, customer_id, plan_id, equipment):
        r = _create_contract(
            h_admin, customer_id, plan_id,
            linked_type="equipment", linked_id=equipment,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["linked_type"] == "equipment"
        assert body["linked_id"] == equipment
        assert body["linked_summary"]["type"] == "equipment"
        assert body["linked_summary"]["details"]["brand"] == "Pentair"

    def test_none_link_no_id(self, h_admin, customer_id, plan_id):
        r = _create_contract(h_admin, customer_id, plan_id)
        assert r.status_code == 200
        body = r.json()
        assert body["linked_type"] == "none"
        assert body["linked_id"] is None
        assert body["linked_summary"] is None

    def test_install_nonexistent_id_422(self, h_admin, customer_id, plan_id):
        r = _create_contract(
            h_admin, customer_id, plan_id,
            linked_type="install", linked_id="does-not-exist-xyz",
        )
        assert r.status_code == 422
        assert "install_not_found" in r.text

    def test_equipment_nonexistent_id_422(self, h_admin, customer_id, plan_id):
        r = _create_contract(
            h_admin, customer_id, plan_id,
            linked_type="equipment", linked_id="does-not-exist-abc",
        )
        assert r.status_code == 422
        assert "equipment_not_found" in r.text

    def test_none_with_id_422(self, h_admin, customer_id, plan_id):
        r = _create_contract(
            h_admin, customer_id, plan_id,
            linked_type="none", linked_id="anything",
        )
        assert r.status_code == 422
        assert "none_id_forbidden" in r.text

    def test_install_id_that_is_non_install_job_422(
        self, h_admin, customer_id, plan_id, non_install_job,
    ):
        # Job exists in tenant but service_type doesn't contain "install"
        r = _create_contract(
            h_admin, customer_id, plan_id,
            linked_type="install", linked_id=non_install_job,
        )
        assert r.status_code == 422
        assert "install_not_found" in r.text


# ═══════════════ Cross-tenant guard ═══════════════════════════════
class TestCrossTenantLinkGuard:
    def test_cross_tenant_job_422(self, h_admin, customer_id, plan_id):
        # Insert a job under a different tenant with an install service_type.
        other_jid = f"TEST_wty-xtenant-{uuid.uuid4().hex[:8]}"
        _sync.jobs.insert_one({
            "id": other_jid, "tenant_id": f"OTHER_{uuid.uuid4().hex[:6]}",
            "customer_id": customer_id, "service_type": "Pool Install",
            "scheduled_date": "2026-01-01",
        })
        try:
            r = _create_contract(
                h_admin, customer_id, plan_id,
                linked_type="install", linked_id=other_jid,
            )
            # 422 rather than 404 — the endpoint validates as "not in
            # this tenant's install workflow", not as "id malformed".
            assert r.status_code == 422
            assert "install_not_found" in r.text
        finally:
            _sync.jobs.delete_many({"id": other_jid})


# ═══════════════ Customer-scoped list endpoints ═══════════════════
class TestAdminCustomerWarranties:
    def test_returns_paginated_envelope_with_linked_summary(
        self, h_admin, customer_id, plan_id, equipment,
    ):
        # seed one linked + one unlinked contract
        _create_contract(h_admin, customer_id, plan_id)
        _create_contract(
            h_admin, customer_id, plan_id,
            linked_type="equipment", linked_id=equipment,
        )
        r = requests.get(
            f"{API}/customers/{customer_id}/warranties",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) >= {
            "items", "page", "page_size", "total", "total_pages",
        }
        assert body["page"] == 1
        assert body["total"] >= 2
        by_link = {(i.get("linked_type") or "none"): i for i in body["items"]}
        assert "equipment" in by_link
        assert by_link["equipment"]["linked_summary"] is not None
        assert by_link["equipment"]["linked_summary"]["type"] == "equipment"

    def test_unknown_customer_404(self, h_admin):
        r = requests.get(
            f"{API}/customers/does-not-exist/warranties",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 404

    def test_customer_role_gets_403(self, h_customer, customer_id):
        r = requests.get(
            f"{API}/customers/{customer_id}/warranties",
            headers=h_customer, timeout=15,
        )
        assert r.status_code == 403


class TestPortalCustomerMeWarranties:
    def test_customer_can_see_own_warranties(self, h_customer):
        r = requests.get(
            f"{API}/customers/me/warranties", headers=h_customer, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) >= {
            "items", "page", "page_size", "total", "total_pages",
        }
        # linked_summary field is present on each row (may be null).
        for row in body["items"]:
            assert "linked_summary" in row

    def test_admin_role_gets_403(self, h_admin):
        r = requests.get(
            f"{API}/customers/me/warranties", headers=h_admin, timeout=15,
        )
        assert r.status_code == 403


# ═══════════════ Link options autopopulate ════════════════════════
class TestLinkOptionsEndpoint:
    def test_install_options(self, h_admin, customer_id, install_job):
        r = requests.get(
            f"{API}/customers/{customer_id}/warranties/link-options",
            params={"type": "install"},
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["type"] == "install"
        ids = [o["id"] for o in body["options"]]
        assert install_job in ids

    def test_equipment_options(self, h_admin, customer_id, equipment):
        r = requests.get(
            f"{API}/customers/{customer_id}/warranties/link-options",
            params={"type": "equipment"},
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["type"] == "equipment"
        ids = [o["id"] for o in body["options"]]
        assert equipment in ids
        opt = next(o for o in body["options"] if o["id"] == equipment)
        assert opt["brand"] == "Pentair"

    def test_customer_role_gets_403(self, h_customer, customer_id):
        r = requests.get(
            f"{API}/customers/{customer_id}/warranties/link-options",
            params={"type": "install"},
            headers=h_customer, timeout=15,
        )
        assert r.status_code == 403

    def test_invalid_type_422(self, h_admin, customer_id):
        r = requests.get(
            f"{API}/customers/{customer_id}/warranties/link-options",
            params={"type": "bogus"},
            headers=h_admin, timeout=15,
        )
        # Pydantic Literal → 422 unprocessable entity
        assert r.status_code == 422


# ═══════════════ Patch re-validation ══════════════════════════════
class TestPatchRelink:
    def test_patch_can_add_link(self, h_admin, customer_id, plan_id, install_job):
        r = _create_contract(h_admin, customer_id, plan_id)
        cid = r.json()["id"]
        p = requests.patch(
            f"{API}/warranties/contracts/{cid}", headers=h_admin,
            json={"linked_type": "install", "linked_id": install_job},
            timeout=15,
        )
        assert p.status_code == 200, p.text
        body = p.json()
        assert body["linked_type"] == "install"
        assert body["linked_id"] == install_job
        assert body["linked_summary"]["type"] == "install"

    def test_patch_can_clear_link(self, h_admin, customer_id, plan_id, equipment):
        r = _create_contract(
            h_admin, customer_id, plan_id,
            linked_type="equipment", linked_id=equipment,
        )
        cid = r.json()["id"]
        p = requests.patch(
            f"{API}/warranties/contracts/{cid}", headers=h_admin,
            json={"linked_type": "none"}, timeout=15,
        )
        assert p.status_code == 200
        body = p.json()
        assert body["linked_type"] == "none"
        assert body["linked_id"] is None
        assert body["linked_summary"] is None

    def test_patch_bad_link_422(self, h_admin, customer_id, plan_id):
        r = _create_contract(h_admin, customer_id, plan_id)
        cid = r.json()["id"]
        p = requests.patch(
            f"{API}/warranties/contracts/{cid}", headers=h_admin,
            json={"linked_type": "install", "linked_id": "nope"},
            timeout=15,
        )
        assert p.status_code == 422
        assert "install_not_found" in p.text
