"""Iteration 47 — Landscape AI (Gemini Nano Banana) endpoint tests.

Covers:
- POST /api/landscape/render — admin/technician success (returns id, output_image, created_at)
- POST /api/landscape/render — customer role forbidden (403)
- POST /api/landscape/render — empty image_base64 -> 400
- GET  /api/landscape/renders — list newest-first, with customer_id / lead_id filters
- DELETE /api/landscape/renders/{id} — removes the render

The render call hits real Gemini; allow up to 120s and skip gracefully if the
upstream image model is temporarily unavailable (502 from our endpoint).
"""
import base64
import io
import os
import time
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

# A tiny valid PNG (10x10 red) so Gemini has real image bytes.
# Generated once here to keep the test self-contained.
def _tiny_png_b64() -> str:
    # 1x1 red PNG (67 bytes) — smallest valid PNG we can send.
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="
    )
    return base64.b64encode(raw).decode()


# --- Fixtures ----------------------------------------------------------------
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(api, creds):
    r = api.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token(api):
    return _login(api, ADMIN)


@pytest.fixture(scope="module")
def tech_token(api):
    return _login(api, TECH)


@pytest.fixture(scope="module")
def customer_token(api):
    return _login(api, CUSTOMER)


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


# --- Tests -------------------------------------------------------------------
class TestLandscapeRBAC:
    def test_customer_forbidden(self, api, customer_token):
        r = api.post(
            f"{BASE_URL}/api/landscape/render",
            json={"image_base64": _tiny_png_b64(), "style": "Modern", "elements": []},
            headers=_hdr(customer_token),
            timeout=30,
        )
        assert r.status_code == 403, f"expected 403 for customer, got {r.status_code}: {r.text[:200]}"

    def test_list_customer_forbidden(self, api, customer_token):
        r = api.get(f"{BASE_URL}/api/landscape/renders", headers=_hdr(customer_token), timeout=15)
        assert r.status_code == 403

    def test_unauth_forbidden(self, api):
        r = api.post(
            f"{BASE_URL}/api/landscape/render",
            json={"image_base64": _tiny_png_b64()},
            timeout=15,
        )
        assert r.status_code in (401, 403)


class TestLandscapeValidation:
    def test_empty_image_400(self, api, admin_token):
        r = api.post(
            f"{BASE_URL}/api/landscape/render",
            json={"image_base64": "", "style": "Modern", "elements": ["Fire pit"]},
            headers=_hdr(admin_token),
            timeout=30,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"

    def test_data_uri_prefix_still_400_when_empty(self, api, admin_token):
        # only the data: prefix, no payload after comma
        r = api.post(
            f"{BASE_URL}/api/landscape/render",
            json={"image_base64": "data:image/png;base64,"},
            headers=_hdr(admin_token),
            timeout=30,
        )
        assert r.status_code == 400


class TestLandscapeRenderAndList:
    """Full happy path: render → list → filter → delete → confirm."""

    _created_id = None

    def test_admin_render_success(self, api, admin_token):
        payload = {
            "image_base64": _tiny_png_b64(),
            "style": "Modern",
            "elements": ["Paver patio", "Outdoor lighting"],
            "prompt": "TEST_iter47 low-maintenance drought tolerant",
        }
        r = api.post(
            f"{BASE_URL}/api/landscape/render",
            json=payload,
            headers=_hdr(admin_token),
            timeout=180,  # Gemini can be slow
        )
        if r.status_code == 502:
            pytest.skip(f"Upstream Gemini render failed (502): {r.text[:200]}")
        assert r.status_code == 200, f"render failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        assert "id" in data and isinstance(data["id"], str) and data["id"]
        assert "output_image" in data and isinstance(data["output_image"], str) and len(data["output_image"]) > 100
        assert "created_at" in data
        TestLandscapeRenderAndList._created_id = data["id"]

    def test_list_returns_newest_first_and_contains_new(self, api, admin_token):
        if not TestLandscapeRenderAndList._created_id:
            pytest.skip("no render created")
        r = api.get(f"{BASE_URL}/api/landscape/renders", headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 1
        ids = [d["id"] for d in arr]
        assert TestLandscapeRenderAndList._created_id in ids
        # newest first: created_at should be non-increasing
        created = [d.get("created_at", "") for d in arr]
        assert created == sorted(created, reverse=True)
        # no mongo _id leakage
        assert all("_id" not in d for d in arr)

    def test_delete_render(self, api, admin_token):
        rid = TestLandscapeRenderAndList._created_id
        if not rid:
            pytest.skip("no render created")
        r = api.delete(f"{BASE_URL}/api/landscape/renders/{rid}", headers=_hdr(admin_token), timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_deleted_render_gone_from_list(self, api, admin_token):
        rid = TestLandscapeRenderAndList._created_id
        if not rid:
            pytest.skip("no render created")
        r = api.get(f"{BASE_URL}/api/landscape/renders", headers=_hdr(admin_token), timeout=30)
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        assert rid not in ids


class TestLandscapeFilters:
    """Verify customer_id and lead_id filter parameters. Uses a lightweight admin render tagged to a customer."""

    _cust_render_id = None
    _lead_render_id = None
    _cust_id = None
    _lead_id = None

    def test_render_attached_to_customer(self, api, admin_token):
        # Pick any customer
        cr = api.get(f"{BASE_URL}/api/customers", headers=_hdr(admin_token), timeout=15)
        assert cr.status_code == 200 and cr.json(), "no customers found"
        TestLandscapeFilters._cust_id = cr.json()[0]["id"]

        payload = {
            "image_base64": _tiny_png_b64(),
            "style": "Tropical",
            "elements": ["Palm trees"],
            "customer_id": TestLandscapeFilters._cust_id,
        }
        r = api.post(
            f"{BASE_URL}/api/landscape/render",
            json=payload,
            headers=_hdr(admin_token),
            timeout=180,
        )
        if r.status_code == 502:
            pytest.skip("upstream 502")
        assert r.status_code == 200
        TestLandscapeFilters._cust_render_id = r.json()["id"]

    def test_filter_by_customer(self, api, admin_token):
        cid = TestLandscapeFilters._cust_id
        rid = TestLandscapeFilters._cust_render_id
        if not (cid and rid):
            pytest.skip("prereq render not created")
        r = api.get(
            f"{BASE_URL}/api/landscape/renders",
            params={"customer_id": cid},
            headers=_hdr(admin_token),
            timeout=30,
        )
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 1
        assert all(d.get("customer_id") == cid for d in arr)
        assert rid in [d["id"] for d in arr]

    def test_render_attached_to_lead_and_filter(self, api, admin_token, tech_token):
        # Try to find a lead; if none, skip.
        lr = api.get(f"{BASE_URL}/api/leads", headers=_hdr(admin_token), timeout=15)
        if lr.status_code != 200 or not lr.json():
            pytest.skip("no leads to attach to")
        TestLandscapeFilters._lead_id = lr.json()[0]["id"]

        # Use technician token to also cover technician role on render.
        payload = {
            "image_base64": _tiny_png_b64(),
            "style": "Desert / Xeriscape",
            "elements": ["Gravel / rock"],
            "lead_id": TestLandscapeFilters._lead_id,
        }
        rr = api.post(
            f"{BASE_URL}/api/landscape/render",
            json=payload,
            headers=_hdr(tech_token),
            timeout=180,
        )
        if rr.status_code == 502:
            pytest.skip("upstream 502")
        assert rr.status_code == 200, f"tech render failed: {rr.status_code} {rr.text[:200]}"
        TestLandscapeFilters._lead_render_id = rr.json()["id"]

        fr = api.get(
            f"{BASE_URL}/api/landscape/renders",
            params={"lead_id": TestLandscapeFilters._lead_id},
            headers=_hdr(admin_token),
            timeout=30,
        )
        assert fr.status_code == 200
        arr = fr.json()
        assert all(d.get("lead_id") == TestLandscapeFilters._lead_id for d in arr)
        assert TestLandscapeFilters._lead_render_id in [d["id"] for d in arr]

    def test_cleanup(self, api, admin_token):
        for rid in [TestLandscapeFilters._cust_render_id, TestLandscapeFilters._lead_render_id]:
            if rid:
                api.delete(f"{BASE_URL}/api/landscape/renders/{rid}", headers=_hdr(admin_token), timeout=15)
