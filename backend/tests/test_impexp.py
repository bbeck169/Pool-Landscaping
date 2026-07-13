"""Backend tests for CSV Import/Export (customers + price-book items)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://pool-app-mobile.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ------------------ Export ------------------
class TestExport:
    def test_export_customers_admin(self, admin_headers):
        r = requests.get(f"{API}/export/customers", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(data.keys()) >= {"filename", "content", "count"}
        assert data["filename"].endswith(".csv")
        assert isinstance(data["content"], str) and data["content"].splitlines()[0].startswith("name,email,phone")
        assert isinstance(data["count"], int)

    def test_export_items_admin(self, admin_headers):
        r = requests.get(f"{API}/export/items", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        header = data["content"].splitlines()[0]
        assert header == "name,category,unit,unit_price,taxable"
        assert data["filename"] == "pricebook.csv"

    def test_export_customers_technician_403(self, tech_headers):
        r = requests.get(f"{API}/export/customers", headers=tech_headers, timeout=30)
        assert r.status_code == 403

    def test_export_items_technician_403(self, tech_headers):
        r = requests.get(f"{API}/export/items", headers=tech_headers, timeout=30)
        assert r.status_code == 403

    def test_export_customers_customer_403(self, customer_headers):
        r = requests.get(f"{API}/export/customers", headers=customer_headers, timeout=30)
        assert r.status_code == 403

    def test_export_items_customer_403(self, customer_headers):
        r = requests.get(f"{API}/export/items", headers=customer_headers, timeout=30)
        assert r.status_code == 403


# ------------------ Import items upsert ------------------
class TestImportItems:
    CSV_TEST = "name,category,unit,unit_price,taxable\nTEST_ImpexpChem,Material,bucket,49.99,true\n"

    def test_import_items_create_then_update(self, admin_headers):
        # 1st import → created
        r1 = requests.post(f"{API}/import/items", headers=admin_headers, json={"csv": self.CSV_TEST}, timeout=30)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["created"] == 1, d1
        assert d1["updated"] == 0
        assert d1["skipped"] == 0

        # 2nd import → updated (matched by name)
        r2 = requests.post(f"{API}/import/items", headers=admin_headers, json={"csv": self.CSV_TEST}, timeout=30)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["created"] == 0
        assert d2["updated"] == 1

        # Verify via GET /api/items
        items = requests.get(f"{API}/items", headers=admin_headers, timeout=30).json()
        matches = [i for i in items if i.get("name") == "TEST_ImpexpChem"]
        assert len(matches) == 1
        it = matches[0]
        assert abs(float(it["unit_price"]) - 49.99) < 1e-6
        assert it["taxable"] is True
        assert it["category"] == "Material"
        assert it["unit"] == "bucket"

    def test_import_items_technician_403(self, tech_headers):
        r = requests.post(f"{API}/import/items", headers=tech_headers, json={"csv": "name\nX\n"}, timeout=30)
        assert r.status_code == 403


# ------------------ Import customers upsert ------------------
class TestImportCustomers:
    CSV_TEST = "name,email,phone\nTEST_CSV Person,test_csvperson@example.com,5551234567\n"

    def test_import_customers_create_then_update(self, admin_headers):
        r1 = requests.post(f"{API}/import/customers", headers=admin_headers, json={"csv": self.CSV_TEST}, timeout=30)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["created"] == 1
        assert d1["updated"] == 0

        r2 = requests.post(f"{API}/import/customers", headers=admin_headers, json={"csv": self.CSV_TEST}, timeout=30)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["created"] == 0
        assert d2["updated"] == 1

        # Verify persistence
        customers = requests.get(f"{API}/customers", headers=admin_headers, timeout=30).json()
        matches = [c for c in customers if (c.get("email") or "").lower() == "test_csvperson@example.com"]
        assert len(matches) == 1
        assert matches[0]["phone"] == "5551234567"

    def test_import_customers_customer_403(self, customer_headers):
        r = requests.post(f"{API}/import/customers", headers=customer_headers,
                          json={"csv": "name,email\nX,x@x.com\n"}, timeout=30)
        assert r.status_code == 403


# ------------------ Missing-name skip / errors ------------------
class TestImportSkip:
    def test_import_customers_skip_missing_name(self, admin_headers):
        csv_text = "name,email\n,test_noname@example.com\n"
        r = requests.post(f"{API}/import/customers", headers=admin_headers, json={"csv": csv_text}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["created"] == 0
        assert data["updated"] == 0
        assert data["skipped"] >= 1
        assert isinstance(data.get("errors"), list) and len(data["errors"]) >= 1
        assert "missing name" in data["errors"][0].lower()


# ------------------ Cleanup ------------------
@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_headers):
    yield
    # remove test rows
    try:
        items = requests.get(f"{API}/items", headers=admin_headers, timeout=30).json()
        for it in items:
            if it.get("name", "").startswith("TEST_"):
                requests.delete(f"{API}/items/{it['id']}", headers=admin_headers, timeout=30)
        customers = requests.get(f"{API}/customers", headers=admin_headers, timeout=30).json()
        for c in customers:
            name = (c.get("name") or "")
            email = (c.get("email") or "").lower()
            if name.startswith("TEST_") or email == "test_csvperson@example.com":
                requests.delete(f"{API}/customers/{c['id']}", headers=admin_headers, timeout=30)
    except Exception as e:
        print(f"cleanup warning: {e}")
