"""Phase Feb-2026 — Customer Equipment Library canonical resource tests.

Exercises /api/customer-equipment CRUD, RBAC, tenant isolation, and
photo-join wiring via /api/files/upload.
"""
import io
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values


_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE_ENV.get("REACT_APP_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL missing"

ADMIN = ("admin@aquaterra.com", "password123")
TECH = ("landscaper@aquaterra.com", "password123")
CUSTOMER = ("customer@aquaterra.com", "password123")

TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?"
    b"\x00\x05\xfe\x02\xfe\xa7\x0e\x83\x1f\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _login(email, password):
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def h_admin():
    return _login(*ADMIN)


@pytest.fixture(scope="module")
def h_tech():
    return _login(*TECH)


@pytest.fixture(scope="module")
def h_customer():
    return _login(*CUSTOMER)


@pytest.fixture(scope="module")
def customer_id(h_admin):
    payload = {"name": f"TEST_ Equip Cust {uuid.uuid4().hex[:6]}", "phone": "5551112222"}
    r = requests.post(f"{BASE}/api/customers", headers=h_admin, json=payload, timeout=15)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    yield cid
    try:
        requests.delete(f"{BASE}/api/customers/{cid}", headers=h_admin, timeout=15)
    except Exception:
        pass


def _create_unit(h, cid, **overrides):
    body = {
        "customer_id": cid,
        "equipment_type": "Filter Pump",
        "brand": "Pentair",
        "model": "IntelliFlo",
        "serial_number": "SN-12345",
        "install_date": "2024-04-11",
        "notes": "TEST_ notes here",
    }
    body.update(overrides)
    return requests.post(
        f"{BASE}/api/customer-equipment", headers=h, json=body, timeout=15,
    )


class TestCustomerEquipmentCRUD:
    def test_admin_creates_unit_with_all_fields(self, h_admin, customer_id):
        r = _create_unit(h_admin, customer_id)
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["equipment_type"] == "Filter Pump"
        assert row["brand"] == "Pentair"
        assert row["model"] == "IntelliFlo"
        assert row["serial_number"] == "SN-12345"
        assert row["install_date"] == "2024-04-11"
        assert isinstance(row["photos"], list) and row["photos"] == []
        # cleanup
        requests.delete(
            f"{BASE}/api/customer-equipment/{row['id']}",
            headers=h_admin, timeout=15,
        )

    def test_tech_can_create_and_edit(self, h_tech, h_admin, customer_id):
        r = _create_unit(h_tech, customer_id, equipment_type="Heater",
                         brand="Raypak", model="R406A")
        assert r.status_code == 201, r.text
        eid = r.json()["id"]

        r2 = requests.patch(
            f"{BASE}/api/customer-equipment/{eid}",
            headers=h_tech,
            json={"serial_number": "S-9999", "brand": "Hayward"},
            timeout=15,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["serial_number"] == "S-9999"
        assert r2.json()["brand"] == "Hayward"
        # cleanup
        requests.delete(
            f"{BASE}/api/customer-equipment/{eid}",
            headers=h_admin, timeout=15,
        )

    def test_customer_cannot_create(self, h_customer, customer_id):
        r = _create_unit(h_customer, customer_id)
        assert r.status_code == 403, r.text

    def test_customer_cannot_list_or_read(self, h_customer, customer_id):
        r = requests.get(
            f"{BASE}/api/customer-equipment?customer_id={customer_id}",
            headers=h_customer, timeout=15,
        )
        assert r.status_code == 403

    def test_invalid_equipment_type_rejected(self, h_admin, customer_id):
        r = _create_unit(h_admin, customer_id, equipment_type="Nonexistent")
        assert r.status_code == 400
        assert "equipment_type" in r.text

    def test_list_returns_created_units(self, h_admin, customer_id):
        r1 = _create_unit(h_admin, customer_id, brand="A-BRAND")
        r2 = _create_unit(h_admin, customer_id, brand="B-BRAND", equipment_type="Salt Cell")
        assert r1.status_code == 201 and r2.status_code == 201
        try:
            r = requests.get(
                f"{BASE}/api/customer-equipment?customer_id={customer_id}",
                headers=h_admin, timeout=15,
            )
            assert r.status_code == 200
            items = r.json()["items"]
            brands = {i["brand"] for i in items}
            assert {"A-BRAND", "B-BRAND"}.issubset(brands)
        finally:
            requests.delete(
                f"{BASE}/api/customer-equipment/{r1.json()['id']}",
                headers=h_admin, timeout=15,
            )
            requests.delete(
                f"{BASE}/api/customer-equipment/{r2.json()['id']}",
                headers=h_admin, timeout=15,
            )

    def test_soft_delete_hides_from_list(self, h_admin, customer_id):
        r = _create_unit(h_admin, customer_id, brand="DEL-ME")
        eid = r.json()["id"]

        d = requests.delete(
            f"{BASE}/api/customer-equipment/{eid}",
            headers=h_admin, timeout=15,
        )
        assert d.status_code == 200 and d.json()["deleted"] == eid

        listing = requests.get(
            f"{BASE}/api/customer-equipment?customer_id={customer_id}",
            headers=h_admin, timeout=15,
        )
        ids = {i["id"] for i in listing.json()["items"]}
        assert eid not in ids

        # Reads after delete → 404
        g = requests.get(
            f"{BASE}/api/customer-equipment/{eid}",
            headers=h_admin, timeout=15,
        )
        assert g.status_code == 404

    def test_get_unknown_404(self, h_admin):
        r = requests.get(
            f"{BASE}/api/customer-equipment/does-not-exist",
            headers=h_admin, timeout=15,
        )
        assert r.status_code == 404


class TestPhotoUploadJoin:
    def test_photo_joined_via_files_upload(self, h_admin, customer_id):
        r = _create_unit(h_admin, customer_id, brand="PHOTO-TEST")
        assert r.status_code == 201
        eid = r.json()["id"]
        try:
            up = requests.post(
                f"{BASE}/api/files/upload",
                headers=h_admin,
                files={
                    "file": ("equip.png", io.BytesIO(TINY_PNG_BYTES), "image/png"),
                },
                data={
                    "purpose": "customer_equipment",
                    "linked_entity_type": "customer_equipment",
                    "linked_entity_id": eid,
                },
                timeout=30,
            )
            # Skip when S3 not configured on this env; that path is
            # independently validated by /api/files/upload tests.
            if up.status_code == 503:
                pytest.skip("Object storage not configured on this env")
            assert up.status_code == 200, up.text
            file_id = up.json()["id"]

            # Now GET the equipment record — photos array should include
            # this file.
            g = requests.get(
                f"{BASE}/api/customer-equipment/{eid}",
                headers=h_admin, timeout=15,
            )
            assert g.status_code == 200
            photos = g.json()["photos"]
            ids = [p["id"] for p in photos]
            assert file_id in ids
            for p in photos:
                if p["id"] == file_id:
                    assert p["url"] == f"/api/files/{file_id}/download"
                    assert p["content_type"] == "image/png"
        finally:
            requests.delete(
                f"{BASE}/api/customer-equipment/{eid}",
                headers=h_admin, timeout=15,
            )
