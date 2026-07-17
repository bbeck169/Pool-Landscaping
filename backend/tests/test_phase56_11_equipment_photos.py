"""Phase 56.11 — Customer Equipment Photo Library backend tests.

Exercises the 4 endpoints via HTTP, covering the 4-photo cap, RBAC,
tenant isolation, tag validation, and the equipment-types enum.
"""
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values


_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE

ADMIN = ("admin@aquaterra.com", "password123")
SUPER_ADMIN = ("super@aquaterra.com", "password123")
TECH = ("landscaper@aquaterra.com", "password123")
CUSTOMER = ("customer@aquaterra.com", "password123")

TINY_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAA"
    "AC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _login(email, password):
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def h_super():
    return _login(*SUPER_ADMIN)


@pytest.fixture(scope="module")
def h_tech():
    return _login(*TECH)


@pytest.fixture(scope="module")
def h_customer():
    return _login(*CUSTOMER)


@pytest.fixture(scope="module")
def customer_id(h_admin):
    payload = {"name": "TEST_ Equip Photo Cust", "phone": "5551112222"}
    r = requests.post(f"{BASE}/api/customers", headers=h_admin, json=payload, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    yield cid
    try:
        requests.delete(f"{BASE}/api/customers/{cid}", headers=h_admin, timeout=15)
    except Exception:
        pass


def _post_photo(h, cid, equipment_type="Filter Pump", tags=None, caption=""):
    body = {"equipment_type": equipment_type, "photo": TINY_PNG, "caption": caption}
    if tags is not None:
        body["tags"] = tags
    return requests.post(
        f"{BASE}/api/customers/{cid}/equipment-photos",
        headers=h, json=body, timeout=15,
    )


class TestEquipmentTypesEnum:
    def test_endpoint_returns_11_types_in_order(self, h_admin):
        r = requests.get(f"{BASE}/api/equipment-types", headers=h_admin, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["types"] == [
            "Filter Pump", "Cleaning Pump", "Waterfall Pump", "Filter", "Heater",
            "Salt Cell", "Cleaning System", "Automation", "Heater Plumbing",
            "Check Valves", "Jandy Valves",
        ]
        assert d["photo_cap"] == 4
        assert set(d["allowed_tags"]) == {"algae_after", "algae_before", "general"}

    def test_customer_forbidden_from_types(self, h_customer):
        r = requests.get(f"{BASE}/api/equipment-types", headers=h_customer, timeout=15)
        assert r.status_code == 403


class TestUploadCap:
    def test_four_ok_fifth_rejected(self, h_admin, customer_id):
        # 4 photos succeed.
        for i in range(4):
            r = _post_photo(h_admin, customer_id, caption=f"TEST_ pic {i}")
            assert r.status_code == 201, r.text
        # 5th rejected.
        r = _post_photo(h_admin, customer_id, caption="TEST_ overflow")
        assert r.status_code == 400
        assert "Maximum of 4 photos" in r.text or "maximum" in r.text.lower()


class TestRbac:
    def test_customer_forbidden(self, h_customer, customer_id):
        r = requests.get(
            f"{BASE}/api/customers/{customer_id}/equipment-photos",
            headers=h_customer, timeout=15,
        )
        assert r.status_code == 403
        r = _post_photo(h_customer, customer_id)
        assert r.status_code == 403

    def test_tech_can_view_and_upload(self, h_tech, h_admin):
        payload = {"name": "TEST_ Tech Upload Cust", "phone": "5552221111"}
        cid = requests.post(f"{BASE}/api/customers", headers=h_admin,
                            json=payload, timeout=15).json()["id"]
        try:
            r = _post_photo(h_tech, cid, equipment_type="Heater",
                            caption="TEST_ tech upload")
            assert r.status_code == 201, r.text
            r = requests.get(f"{BASE}/api/customers/{cid}/equipment-photos",
                             headers=h_tech, timeout=15)
            assert r.status_code == 200
            assert len(r.json()["grouped"]["Heater"]) == 1
        finally:
            requests.delete(f"{BASE}/api/customers/{cid}",
                            headers=h_admin, timeout=15)

    def test_tech_cannot_delete(self, h_tech, h_admin):
        payload = {"name": "TEST_ Tech Delete Cust"}
        cid = requests.post(f"{BASE}/api/customers", headers=h_admin,
                            json=payload, timeout=15).json()["id"]
        try:
            photo = _post_photo(h_admin, cid).json()
            r = requests.delete(
                f"{BASE}/api/customers/{cid}/equipment-photos/{photo['id']}",
                headers=h_tech, timeout=15,
            )
            assert r.status_code == 403
            # Admin CAN delete.
            r = requests.delete(
                f"{BASE}/api/customers/{cid}/equipment-photos/{photo['id']}",
                headers=h_admin, timeout=15,
            )
            assert r.status_code == 200
        finally:
            requests.delete(f"{BASE}/api/customers/{cid}",
                            headers=h_admin, timeout=15)


class TestTenantIsolation:
    def test_cross_tenant_read_404(self, h_admin, customer_id):
        try:
            h_sun = _login("admin@sunbelt.com", "password123")
        except Exception:
            pytest.skip("sunbelt admin not seeded in this environment")
        r = requests.get(
            f"{BASE}/api/customers/{customer_id}/equipment-photos",
            headers=h_sun, timeout=15,
        )
        assert r.status_code == 404, r.text


class TestGroupedResponse:
    def test_all_types_present_in_grouped_response(self, h_admin, customer_id):
        # Fresh customer so we know the grouping is complete.
        payload = {"name": "TEST_ Grouped Response Cust"}
        cid = requests.post(f"{BASE}/api/customers", headers=h_admin,
                            json=payload, timeout=15).json()["id"]
        try:
            _post_photo(h_admin, cid, equipment_type="Filter")
            _post_photo(h_admin, cid, equipment_type="Salt Cell")
            r = requests.get(f"{BASE}/api/customers/{cid}/equipment-photos",
                             headers=h_admin, timeout=15)
            assert r.status_code == 200
            g = r.json()["grouped"]
            # Every enum type is present as a key, even when empty.
            expected = ["Filter Pump", "Cleaning Pump", "Waterfall Pump",
                        "Filter", "Heater", "Salt Cell", "Cleaning System",
                        "Automation", "Heater Plumbing", "Check Valves",
                        "Jandy Valves"]
            assert set(g.keys()) == set(expected)
            assert len(g["Filter"]) == 1 and len(g["Salt Cell"]) == 1
            assert len(g["Heater"]) == 0
        finally:
            requests.delete(f"{BASE}/api/customers/{cid}",
                            headers=h_admin, timeout=15)


class TestTagValidation:
    def test_allowed_tags_accepted(self, h_admin, customer_id):
        payload = {"name": "TEST_ Tag Val Cust"}
        cid = requests.post(f"{BASE}/api/customers", headers=h_admin,
                            json=payload, timeout=15).json()["id"]
        try:
            for tag in ("algae_before", "algae_after", "general"):
                r = _post_photo(h_admin, cid, equipment_type="Filter", tags=[tag])
                assert r.status_code == 201, r.text
                # DELETE so cap doesn't trip.
                requests.delete(
                    f"{BASE}/api/customers/{cid}/equipment-photos/{r.json()['id']}",
                    headers=h_admin, timeout=15,
                )
        finally:
            requests.delete(f"{BASE}/api/customers/{cid}",
                            headers=h_admin, timeout=15)

    def test_unknown_tag_rejected(self, h_admin, customer_id):
        payload = {"name": "TEST_ Bad Tag Cust"}
        cid = requests.post(f"{BASE}/api/customers", headers=h_admin,
                            json=payload, timeout=15).json()["id"]
        try:
            r = _post_photo(h_admin, cid, tags=["invalid_tag_xyz"])
            assert r.status_code == 400
            assert "Unknown tag" in r.text
        finally:
            requests.delete(f"{BASE}/api/customers/{cid}",
                            headers=h_admin, timeout=15)


class TestUnknownEquipmentType:
    def test_bad_equipment_type_rejected(self, h_admin, customer_id):
        r = _post_photo(h_admin, customer_id, equipment_type="Rocket Booster")
        assert r.status_code == 400


class TestOpenApiRegenerates:
    def test_openapi_includes_equipment_endpoints(self):
        r = requests.get(f"{BASE}/api/openapi.json", timeout=15)
        assert r.status_code == 200
        paths = r.json()["paths"]
        assert "/api/equipment-types" in paths
        assert "/api/customers/{customer_id}/equipment-photos" in paths
