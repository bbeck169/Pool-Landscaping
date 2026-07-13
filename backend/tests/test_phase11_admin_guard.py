"""Phase 11 admin-guard regression tests.

Verifies:
1. Primary 4 endpoints reject technician with 403 and accept admin.
2. Related endpoints in same routers are consistently admin-only.
3. Public digital-card endpoints remain unauthenticated.
"""
import os
import pytest
import requests

def _load_base_url():
    v = os.environ.get("REACT_APP_BACKEND_URL", "")
    if not v:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.strip().startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    return v.rstrip("/")

BASE_URL = _load_base_url()
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@aquaterra.com", "password": "password123"}
TECH = {"email": "mike@aquaterra.com", "password": "password123"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login(ADMIN)}"}


@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login(TECH)}"}


def _expect_403(r):
    assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:200]}"
    try:
        detail = r.json().get("detail", "")
    except Exception:
        detail = ""
    assert "Admin access required" in detail, f"unexpected detail: {detail}"


def _not_403(r):
    assert r.status_code != 403, f"admin got 403: {r.text[:200]}"


# ---------- PRIMARY 4 ----------

class TestPrimaryFourTechForbidden:
    def test_landscape_render_tech_403(self, tech_h):
        r = requests.post(f"{API}/landscape/render", json={"image_base64": "AAA"}, headers=tech_h, timeout=15)
        _expect_403(r)

    def test_property_lookup_tech_403(self, tech_h):
        r = requests.get(f"{API}/property/lookup", params={"address": "10840 W Saddlehorn Rd Peoria AZ"}, headers=tech_h, timeout=15)
        _expect_403(r)

    def test_designs_create_tech_403(self, tech_h):
        r = requests.post(f"{API}/designs", json={"name": "tech-test"}, headers=tech_h, timeout=15)
        _expect_403(r)

    def test_measurements_create_tech_403(self, tech_h):
        r = requests.post(f"{API}/measurements", json={"name": "tech-m", "area_sqft": 100}, headers=tech_h, timeout=15)
        _expect_403(r)


class TestPrimaryFourAdminAllowed:
    def test_landscape_render_admin_not_403(self, admin_h):
        # Use tiny bad base64 → provider will fail fast; we just verify auth passes.
        r = requests.post(f"{API}/landscape/render", json={"image_base64": "AAA"}, headers=admin_h, timeout=60)
        _not_403(r)
        # 502/400/424 are all acceptable — image gen may fail with bogus input.
        assert r.status_code in (200, 400, 424, 502), f"unexpected: {r.status_code} {r.text[:200]}"

    def test_property_lookup_admin_not_403(self, admin_h):
        # One real Zillow call — as instructed, limit to one.
        r = requests.get(f"{API}/property/lookup", params={"address": "10840 W Saddlehorn Rd Peoria AZ"}, headers=admin_h, timeout=40)
        _not_403(r)
        assert r.status_code in (200, 404, 424, 429), f"unexpected: {r.status_code} {r.text[:200]}"

    def test_designs_create_admin_ok(self, admin_h):
        r = requests.post(f"{API}/designs", json={"name": "TEST_admin_design"}, headers=admin_h, timeout=15)
        _not_403(r)
        assert r.status_code == 200, r.text
        did = r.json()["id"]
        # cleanup
        d = requests.delete(f"{API}/designs/{did}", headers=admin_h, timeout=15)
        assert d.status_code == 200

    def test_measurements_create_admin_ok(self, admin_h):
        r = requests.post(f"{API}/measurements", json={"name": "TEST_admin_m", "area_sqft": 100}, headers=admin_h, timeout=15)
        _not_403(r)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        d = requests.delete(f"{API}/measurements/{mid}", headers=admin_h, timeout=15)
        assert d.status_code == 200


# ---------- RELATED endpoints ----------

class TestRelatedTechForbidden:
    def test_list_renders(self, tech_h):
        _expect_403(requests.get(f"{API}/landscape/renders", headers=tech_h, timeout=15))

    def test_delete_render(self, tech_h):
        _expect_403(requests.delete(f"{API}/landscape/renders/nonexistent-id", headers=tech_h, timeout=15))

    def test_property_save(self, tech_h):
        _expect_403(requests.post(f"{API}/property/save", json={"address": "123 Main St"}, headers=tech_h, timeout=15))

    def test_property_saved(self, tech_h):
        _expect_403(requests.get(f"{API}/property/saved", headers=tech_h, timeout=15))

    def test_property_saved_delete(self, tech_h):
        _expect_403(requests.delete(f"{API}/property/saved/nonexistent-id", headers=tech_h, timeout=15))

    def test_designs_list(self, tech_h):
        _expect_403(requests.get(f"{API}/designs", headers=tech_h, timeout=15))

    def test_designs_get(self, tech_h):
        _expect_403(requests.get(f"{API}/designs/nonexistent-id", headers=tech_h, timeout=15))

    def test_designs_put(self, tech_h):
        _expect_403(requests.put(f"{API}/designs/nonexistent-id", json={"name": "x"}, headers=tech_h, timeout=15))

    def test_designs_delete(self, tech_h):
        _expect_403(requests.delete(f"{API}/designs/nonexistent-id", headers=tech_h, timeout=15))

    def test_measurements_list(self, tech_h):
        _expect_403(requests.get(f"{API}/measurements", headers=tech_h, timeout=15))

    def test_measurements_delete(self, tech_h):
        _expect_403(requests.delete(f"{API}/measurements/nonexistent-id", headers=tech_h, timeout=15))


class TestRelatedAdminAllowed:
    def test_list_renders(self, admin_h):
        r = requests.get(f"{API}/landscape/renders", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text

    def test_delete_render_nonexistent(self, admin_h):
        r = requests.delete(f"{API}/landscape/renders/nonexistent-id", headers=admin_h, timeout=15)
        _not_403(r)
        assert r.status_code in (200, 404)

    def test_property_saved(self, admin_h):
        r = requests.get(f"{API}/property/saved", headers=admin_h, timeout=15)
        assert r.status_code == 200

    def test_property_save_and_delete(self, admin_h):
        r = requests.post(f"{API}/property/save", json={"address": "TEST_addr Phase11"}, headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        pid = r.json()["property"]["id"]
        d = requests.delete(f"{API}/property/saved/{pid}", headers=admin_h, timeout=15)
        assert d.status_code == 200

    def test_designs_list(self, admin_h):
        r = requests.get(f"{API}/designs", headers=admin_h, timeout=15)
        assert r.status_code == 200

    def test_designs_get_missing(self, admin_h):
        r = requests.get(f"{API}/designs/nonexistent-id", headers=admin_h, timeout=15)
        _not_403(r)
        assert r.status_code == 404

    def test_measurements_list(self, admin_h):
        r = requests.get(f"{API}/measurements", headers=admin_h, timeout=15)
        assert r.status_code == 200


# ---------- PUBLIC card endpoints ----------

class TestPublicCards:
    slug = "alex-admin"

    @classmethod
    def _ensure_card(cls, admin_h):
        # Seed card via admin so public endpoints have something to fetch.
        payload = {
            "slug": cls.slug,
            "name": "Alex Admin",
            "title": "General Manager",
            "phone": "555-0000",
            "email": "alex@aquaterra.com",
        }
        r = requests.post(f"{API}/cards", json=payload, headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text

    def test_public_card_no_auth(self, admin_h):
        self._ensure_card(admin_h)
        r = requests.get(f"{API}/public/cards/{self.slug}", timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("slug") == self.slug

    def test_public_vcard_no_auth(self, admin_h):
        self._ensure_card(admin_h)
        r = requests.get(f"{API}/public/cards/{self.slug}/vcard", timeout=15)
        assert r.status_code == 200, r.text
        assert r.text.startswith("BEGIN:VCARD"), r.text[:80]

    def test_cleanup(self, admin_h):
        requests.delete(f"{API}/cards/{self.slug}", headers=admin_h, timeout=15)


# ---------- REGRESSION: Phase 9 flows still work for admin ----------

class TestRegression:
    def test_notifications_admin(self, admin_h):
        r = requests.get(f"{API}/notifications", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text

    def test_ai_ops_employees(self, admin_h):
        r = requests.get(f"{API}/ai-ops/employees", headers=admin_h, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # tolerate wrapper shapes
        items = data if isinstance(data, list) else (data.get("employees") or data.get("items") or [])
        assert len(items) >= 8, f"expected >=8 personas, got {len(items)}"
