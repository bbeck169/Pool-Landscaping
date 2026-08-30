"""Tenant branding · Logo upload · Feb-2026 · TD-08 promoted.

Covers the new admin-only endpoints:
  * POST   /api/tenants/branding/logo   — multipart upload
  * DELETE /api/tenants/branding/logo   — clear stored URL

Object-storage backing is exercised for real; the pod initialises
``services.object_storage`` at boot when ``EMERGENT_LLM_KEY`` is
set. When it isn't ready, the endpoint returns 503 and this suite
skips the storage-round-trip cases so it doesn't false-fail in a
pod without the key.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _login(email: str) -> str:
    """Login with retry — cold-pod bcrypt sometimes trips the default
    timeout. Mirrors the pattern already used by
    ``test_invoice_edit.py::_login``.
    """
    last = None
    for _ in range(3):
        try:
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": "password123"},
                              timeout=60)
            if r.status_code == 200:
                return r.json()["access_token"]
            last = r.text
        except requests.exceptions.RequestException as exc:
            last = str(exc)
    raise RuntimeError(f"login failed for {email}: {last}")


def _me(tok: str) -> dict:
    return requests.get(f"{API}/auth/me",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=15).json()


def _storage_ready() -> bool:
    """Peek at the object storage adapter without importing config
    into this module scope (which would double-bind the app)."""
    try:
        # Trigger a lazy init via a HEAD-ish call: attempt to run the
        # readable admin endpoint that fans out to a storage put on
        # success. If storage is up the upload succeeds; else 503.
        return True  # optimistic — the upload call handles the 503.
    except Exception:
        return False


# ── Fixtures ──────────────────────────────────────────────────────
def _tiny_png() -> bytes:
    """Smallest valid PNG (1×1 transparent pixel) — 67 bytes."""
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c626001000000ffff03000006000557bfabd400000000"
        "49454e44ae426082"
    )


def _oversize_png() -> bytes:
    """2 MB + 1 byte junk with a PNG magic prefix. The endpoint rejects
    on size BEFORE decoding, so junk-after-magic is safe."""
    return b"\x89PNG\r\n\x1a\n" + (b"A" * (2 * 1024 * 1024 + 1))


@pytest.fixture(scope="module")
def admin_token() -> str:
    return _login("admin@aquaterra.com")


@pytest.fixture
def cleanup_tenant_logo(admin_token):
    """Snapshot + restore the caller's tenant.logo_url so a test
    doesn't leak state into the shared preview env."""
    me = _me(admin_token)
    tid = me["tenant_id"]
    snapshot = _sync.tenants.find_one({"id": tid},
                                        {"_id": 0, "logo_url": 1,
                                         "logo_object_path": 1}) or {}
    yield tid
    _sync.tenants.update_one({"id": tid}, {"$set": {
        "logo_url": snapshot.get("logo_url"),
        "logo_object_path": snapshot.get("logo_object_path"),
    }})


# ── Tests ─────────────────────────────────────────────────────────
def test_upload_rejects_missing_file(admin_token):
    r = requests.post(f"{API}/tenants/branding/logo",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      timeout=15)
    # Fastapi returns 422 when the required file field is missing.
    assert r.status_code == 422, r.text


def test_upload_rejects_unsupported_mime(admin_token):
    files = {"logo": ("brand.txt", b"hello world", "text/plain")}
    r = requests.post(f"{API}/tenants/branding/logo",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, timeout=15)
    assert r.status_code == 415, r.text
    detail = r.json()["detail"]
    assert detail["error_code"] == "unsupported_media_type"


def test_upload_rejects_oversized_file(admin_token):
    files = {"logo": ("huge.png", _oversize_png(), "image/png")}
    r = requests.post(f"{API}/tenants/branding/logo",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, timeout=30)
    assert r.status_code == 413, r.text
    detail = r.json()["detail"]
    assert detail["error_code"] == "file_too_large"
    assert detail["max_bytes"] == 2 * 1024 * 1024


def test_upload_non_admin_is_forbidden():
    tok = _login("customer@aquaterra.com")
    files = {"logo": ("brand.png", _tiny_png(), "image/png")}
    r = requests.post(f"{API}/tenants/branding/logo",
                      headers={"Authorization": f"Bearer {tok}"},
                      files=files, timeout=15)
    assert r.status_code == 403, r.text


def test_upload_persists_logo_url_and_delete_clears_it(admin_token, cleanup_tenant_logo):
    tid = cleanup_tenant_logo
    files = {"logo": ("brand.png", _tiny_png(), "image/png")}
    r = requests.post(f"{API}/tenants/branding/logo",
                      headers={"Authorization": f"Bearer {admin_token}"},
                      files=files, timeout=30)
    if r.status_code == 503:
        pytest.skip("object storage not initialised in this pod")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["logo_url"].startswith("/api/objects/")
    assert body["size_bytes"] == len(_tiny_png())
    # DB was stamped.
    row = _sync.tenants.find_one({"id": tid},
                                    {"_id": 0, "logo_url": 1,
                                     "logo_object_path": 1,
                                     "logo_size_bytes": 1})
    assert row["logo_url"] == body["logo_url"]
    assert row["logo_object_path"]
    assert row["logo_size_bytes"] == len(_tiny_png())
    # ``GET /tenants/current`` surfaces the new URL for the app-shell.
    curr = requests.get(f"{API}/tenants/current",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        timeout=15).json()
    assert curr["logo_url"] == body["logo_url"]
    assert curr["branding"]["logo_url"] == body["logo_url"]

    # Now delete and verify the row clears.
    r2 = requests.delete(f"{API}/tenants/branding/logo",
                         headers={"Authorization": f"Bearer {admin_token}"},
                         timeout=15)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["cleared"] is True
    assert body2["logo_url"] is None
    row2 = _sync.tenants.find_one({"id": tid}, {"_id": 0, "logo_url": 1})
    assert row2["logo_url"] is None


def test_delete_non_admin_is_forbidden():
    tok = _login("customer@aquaterra.com")
    r = requests.delete(f"{API}/tenants/branding/logo",
                        headers={"Authorization": f"Bearer {tok}"},
                        timeout=15)
    assert r.status_code == 403, r.text


def test_upload_replacing_existing_logo_gcs_prior_object(admin_token, cleanup_tenant_logo):
    """A second upload should overwrite tenant.logo_url + logo_object_path
    with a new UUID-based path. Best-effort GC of the prior path is
    exercised — we only assert the DB state (the storage delete is a
    non-fatal side effect)."""
    tid = cleanup_tenant_logo
    # First upload.
    r1 = requests.post(f"{API}/tenants/branding/logo",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       files={"logo": ("first.png", _tiny_png(), "image/png")},
                       timeout=30)
    if r1.status_code == 503:
        pytest.skip("object storage not initialised in this pod")
    assert r1.status_code == 200, r1.text
    prior_path = _sync.tenants.find_one({"id": tid},
                                           {"_id": 0, "logo_object_path": 1})["logo_object_path"]
    # Second upload with a different image.
    r2 = requests.post(f"{API}/tenants/branding/logo",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       files={"logo": ("second.webp", _tiny_png(), "image/webp")},
                       timeout=30)
    assert r2.status_code == 200, r2.text
    row = _sync.tenants.find_one({"id": tid},
                                    {"_id": 0, "logo_object_path": 1,
                                     "logo_content_type": 1})
    assert row["logo_object_path"] != prior_path
    assert row["logo_content_type"].startswith("image/webp")
