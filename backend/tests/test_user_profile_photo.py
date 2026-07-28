"""F2f · Feb-2026 — Staff profile photo endpoint tests."""
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE = (_FE.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or ""
DB_NAME = _BE.get("DB_NAME") or ""
assert BASE and MONGO_URL and DB_NAME

ADMIN = ("manager@aquaterra.com", "password123")
CUSTOMER = ("customer@aquaterra.com", "password123")


def _login(email, pw):
    r = requests.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    tok = r.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    # /auth/login returns a stripped user; use /auth/me for tenant_id.
    me = requests.get(f"{BASE}/api/auth/me", headers=h, timeout=15).json()
    return h, me


@pytest.fixture(scope="module")
def dbc():
    c = MongoClient(MONGO_URL); yield c[DB_NAME]; c.close()


def test_user_can_patch_own_profile_photo():
    h, u = _login(*CUSTOMER)
    url = "/api/files/test-file-abc/download"
    r = requests.patch(f"{BASE}/api/users/me", headers=h,
                          json={"profile_photo_url": url}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body.get("no_op") is not True
    assert body["user"]["profile_photo_url"] == url
    # Cleanup — set back to null.
    requests.patch(f"{BASE}/api/users/me", headers=h,
                     json={"profile_photo_url": None}, timeout=15)


def test_user_can_clear_profile_photo_with_null():
    h, _ = _login(*CUSTOMER)
    r = requests.patch(f"{BASE}/api/users/me", headers=h,
                          json={"profile_photo_url": None}, timeout=15)
    assert r.status_code == 200
    assert r.json()["user"].get("profile_photo_url") is None


def test_admin_can_patch_any_users_profile(dbc):
    h, admin_user = _login(*ADMIN)
    tenant_id = admin_user["tenant_id"]
    # Pick some user in the same tenant that isn't the admin.
    other = dbc.users.find_one(
        {"tenant_id": tenant_id, "id": {"$ne": admin_user["id"]}},
        {"_id": 0, "id": 1, "profile_photo_url": 1},
    )
    assert other
    url = "/api/files/admin-set-photo/download"
    r = requests.patch(f"{BASE}/api/admin/users/{other['id']}/profile",
                          headers=h, json={"profile_photo_url": url}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["profile_photo_url"] == url
    # Cleanup
    requests.patch(f"{BASE}/api/admin/users/{other['id']}/profile",
                     headers=h, json={"profile_photo_url": None}, timeout=15)


def test_non_admin_cannot_hit_admin_endpoint():
    h, _ = _login(*CUSTOMER)
    r = requests.patch(f"{BASE}/api/admin/users/anything/profile",
                          headers=h, json={"profile_photo_url": "x"}, timeout=15)
    assert r.status_code == 403, r.text


def test_admin_cross_tenant_returns_404(dbc):
    h, admin_user = _login(*ADMIN)
    # Seed a user in a different tenant.
    sunbelt = dbc.tenants.find_one({"slug": "sunbelt"})
    assert sunbelt
    fake_uid = f"foreign-user-{uuid.uuid4().hex[:8]}"
    dbc.users.insert_one({
        "id": fake_uid, "tenant_id": sunbelt["id"],
        "email": "x@sunbelt.test", "role": "customer",
    })
    try:
        r = requests.patch(f"{BASE}/api/admin/users/{fake_uid}/profile",
                              headers=h, json={"profile_photo_url": "x"}, timeout=15)
        assert r.status_code == 404, r.text
    finally:
        dbc.users.delete_one({"id": fake_uid})
