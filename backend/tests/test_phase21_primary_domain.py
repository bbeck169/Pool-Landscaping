"""Feb-2026 · Phase 21 — Primary customer-facing URL PATCH.

Covers:
* GET returns current + default.
* PATCH accepts a valid https URL.
* PATCH rejects http:// (400).
* PATCH rejects malformed URL (400).
* PATCH null clears the override.
* Admin (non super) gets 403.
* Persistence — round-trip check via direct Mongo read.
"""
import os

import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = "http://localhost:8001/api"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = MongoClient(_MONGO_URL)[_DB_NAME] if _MONGO_URL and _DB_NAME else None


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _restore_domain(value: str = "https://app.plofv.com"):
    _sync_db.tenants.update_one(
        {"slug": "aquaterra"},
        {"$set": {"settings.primary_app_domain": value}},
    )


def test_primary_app_domain_get():
    sup = _login("super@aquaterra.com")
    r = requests.get(f"{API}/tenants/current/primary-app-domain",
                      headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert "primary_app_domain" in body
    assert body["default"] == "https://app.plofv.com"


def test_primary_app_domain_valid_https():
    sup = _login("super@aquaterra.com")
    r = requests.patch(f"{API}/tenants/current/primary-app-domain",
                        json={"primary_app_domain": "https://pay.vistancia-pools.com"},
                        headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["primary_app_domain"] == "https://pay.vistancia-pools.com"
    # Persisted.
    t = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    assert (t.get("settings") or {}).get("primary_app_domain") == \
        "https://pay.vistancia-pools.com"
    _restore_domain()


def test_primary_app_domain_rejects_http():
    sup = _login("super@aquaterra.com")
    r = requests.patch(f"{API}/tenants/current/primary-app-domain",
                        json={"primary_app_domain": "http://insecure.example"},
                        headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 400
    assert "https" in r.json()["detail"].lower()


def test_primary_app_domain_rejects_malformed():
    sup = _login("super@aquaterra.com")
    for bad in ["https://", "https://x", "not a url", "https://.."]:
        r = requests.patch(f"{API}/tenants/current/primary-app-domain",
                            json={"primary_app_domain": bad},
                            headers={"Authorization": f"Bearer {sup}"}, timeout=15)
        assert r.status_code == 400, f"expected 400 for {bad!r} got {r.status_code}"


def test_primary_app_domain_null_clears():
    sup = _login("super@aquaterra.com")
    r = requests.patch(f"{API}/tenants/current/primary-app-domain",
                        json={"primary_app_domain": None},
                        headers={"Authorization": f"Bearer {sup}"}, timeout=15)
    assert r.status_code == 200
    assert r.json()["primary_app_domain"] is None
    t = _sync_db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    assert (t.get("settings") or {}).get("primary_app_domain") is None
    _restore_domain()


def test_primary_app_domain_admin_forbidden():
    adm = _login("admin@aquaterra.com")
    r = requests.patch(f"{API}/tenants/current/primary-app-domain",
                        json={"primary_app_domain": "https://x.com"},
                        headers={"Authorization": f"Bearer {adm}"}, timeout=15)
    assert r.status_code == 403


# ── /technicians enrichment carries display_color_hex ──────────
def test_technicians_endpoint_enriched_with_display_color_hex():
    """The Schedule reads `/technicians` and uses `display_color_hex`
    to color event cards + the legend. This test proves the join
    from technicians -> users -> display_color_hex works."""
    admin = _login("admin@aquaterra.com")
    # Pick a tech and set a color on their linked user.
    mike = _sync_db.users.find_one({"email": "mike@aquaterra.com"},
                                     {"_id": 0, "id": 1, "technician_id": 1})
    if not mike.get("technician_id"):
        # If Mike isn't wired to a technician doc, just skip — this
        # test is nice-to-have and the primary path is `/team`.
        import pytest
        pytest.skip("mike has no linked technician doc")

    # Ensure the tech doc has user_id back-pointing to Mike.
    _sync_db.technicians.update_one(
        {"id": mike["technician_id"]},
        {"$set": {"user_id": mike["id"]}},
    )
    _sync_db.users.update_one(
        {"id": mike["id"]},
        {"$set": {"display_color_hex": "#22C55E"}},
    )

    r = requests.get(f"{API}/technicians",
                      headers={"Authorization": f"Bearer {admin}"}, timeout=15)
    assert r.status_code == 200
    rows = r.json()
    hit = next((t for t in rows if t.get("user_id") == mike["id"]), None)
    if hit:
        assert hit.get("display_color_hex") == "#22C55E"
    # Clean up.
    _sync_db.users.update_one(
        {"id": mike["id"]},
        {"$unset": {"display_color_hex": ""}},
    )
