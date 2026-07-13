"""
Bug fix verification: draft forms must not accept public submissions.
Also verifies new admin-only /api/forms/{fid}/preview endpoint.
"""
import os
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE}/api"


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def tech_token():
    return _login("mike@aquaterra.com", "password123")


def _create_form(admin_token, status):
    body = {
        "name": f"TEST_pool_audit_{status}",
        "slug": "poolscape-audit",
        "status": status,
        "fields": [
            {"key": "name", "label": "Name", "type": "text", "required": True},
            {"key": "email", "label": "Email", "type": "email", "required": True},
        ],
        "destination": "lead",
    }
    r = requests.post(
        f"{API}/forms", json=body,
        headers={"Authorization": f"Bearer {admin_token}"}, timeout=20,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _delete_form(admin_token, fid):
    requests.delete(f"{API}/forms/{fid}", headers={"Authorization": f"Bearer {admin_token}"}, timeout=20)


class TestDraftFormGate:
    def test_draft_public_get_returns_404(self, admin_token):
        form = _create_form(admin_token, "draft")
        try:
            r = requests.get(f"{API}/public/forms/poolscape-audit", timeout=20)
            assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"
        finally:
            _delete_form(admin_token, form["id"])

    def test_draft_public_submit_returns_404(self, admin_token):
        form = _create_form(admin_token, "draft")
        try:
            r = requests.post(
                f"{API}/public/forms/poolscape-audit/submit",
                json={"values": {"email": "x@example.com"}},
                timeout=20,
            )
            assert r.status_code == 404, f"expected 404 (bug fix), got {r.status_code}: {r.text}"
        finally:
            _delete_form(admin_token, form["id"])

    def test_draft_preview_admin_200(self, admin_token):
        form = _create_form(admin_token, "draft")
        try:
            r = requests.get(
                f"{API}/forms/{form['id']}/preview",
                headers={"Authorization": f"Bearer {admin_token}"}, timeout=20,
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assert "fields" in data and isinstance(data["fields"], list)
            assert len(data["fields"]) >= 1
        finally:
            _delete_form(admin_token, form["id"])

    def test_draft_preview_tech_403(self, admin_token, tech_token):
        form = _create_form(admin_token, "draft")
        try:
            r = requests.get(
                f"{API}/forms/{form['id']}/preview",
                headers={"Authorization": f"Bearer {tech_token}"}, timeout=20,
            )
            assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
        finally:
            _delete_form(admin_token, form["id"])


class TestPublishedFormBehavior:
    def test_published_public_get_200(self, admin_token):
        form = _create_form(admin_token, "published")
        try:
            r = requests.get(f"{API}/public/forms/poolscape-audit", timeout=20)
            assert r.status_code == 200, r.text
            data = r.json()
            assert "fields" in data
            assert "notify_emails" not in data
        finally:
            _delete_form(admin_token, form["id"])

    def test_published_public_submit_200(self, admin_token):
        form = _create_form(admin_token, "published")
        try:
            r = requests.post(
                f"{API}/public/forms/poolscape-audit/submit",
                json={"values": {"name": "TEST_lead", "email": "test@example.com"}},
                timeout=20,
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data.get("ok") is True
        finally:
            _delete_form(admin_token, form["id"])
