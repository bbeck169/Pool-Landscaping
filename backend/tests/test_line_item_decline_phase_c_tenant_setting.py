"""Feb-2026 · Phase C — tenant settings round-trip for
``require_signature_before_approve``. Admin-only PATCH + GET
via ``/api/tenants/mine/settings`` mirrors the Phase B toggle
pattern. Uses a live admin login (admin@aquaterra.com/password123
seeded on startup).
"""
from __future__ import annotations

from pathlib import Path

import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"


def _admin_headers() -> dict:
    r = requests.post(f"{API}/auth/login", json={
        "email": "admin@aquaterra.com",
        "password": "password123",
    }, timeout=10)
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _restore_initial_state(prior: bool | None) -> None:
    h = _admin_headers()
    body = {"require_signature_before_approve": bool(prior)}
    r = requests.patch(f"{API}/tenants/mine/settings",
                        json=body, headers=h, timeout=10)
    assert r.status_code == 200, r.text


def test_get_settings_surfaces_require_signature_default_false():
    h = _admin_headers()
    r = requests.get(f"{API}/tenants/mine/settings",
                      headers=h, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    # Field is always present (bool). Default is False for tenants
    # that never explicitly PATCHed it.
    assert "require_signature_before_approve" in body
    assert isinstance(body["require_signature_before_approve"], bool)


def test_patch_settings_round_trips_true_then_false():
    h = _admin_headers()

    # Snapshot prior so we can restore.
    prior = requests.get(f"{API}/tenants/mine/settings",
                          headers=h, timeout=10).json().get(
        "require_signature_before_approve", False)

    try:
        # Flip ON.
        r = requests.patch(f"{API}/tenants/mine/settings",
                            json={"require_signature_before_approve": True},
                            headers=h, timeout=10)
        assert r.status_code == 200, r.text

        r2 = requests.get(f"{API}/tenants/mine/settings",
                           headers=h, timeout=10)
        assert r2.json()["require_signature_before_approve"] is True

        # Flip OFF.
        r3 = requests.patch(f"{API}/tenants/mine/settings",
                             json={"require_signature_before_approve": False},
                             headers=h, timeout=10)
        assert r3.status_code == 200, r3.text
        r4 = requests.get(f"{API}/tenants/mine/settings",
                           headers=h, timeout=10)
        assert r4.json()["require_signature_before_approve"] is False
    finally:
        _restore_initial_state(prior)
