"""Phase 25 · Tech Property Lookup tests."""
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status(); return r.json()

@pytest.fixture(scope="module")
def dbc(): return MongoClient(_BE["MONGO_URL"])[_BE["DB_NAME"]]

@pytest.fixture(scope="module")
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def tech_h():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')['access_token']}"}

@pytest.fixture(scope="module")
def customer_h():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')['access_token']}"}


ADDRESS = "742 Evergreen Terrace, Springfield, OR 97477"


@pytest.fixture(autouse=True)
def _reset_rate_limit(dbc, tech_h):
    """Wipe search history + cache before each test so rate limits and
    caching are deterministic."""
    from requests import get
    me = get(f"{API}/auth/me", headers=tech_h, timeout=10).json()
    dbc.property_search_history.delete_many({"user_id": me["id"]})
    dbc.property_lookup_cache.delete_many({})
    yield
    dbc.property_search_history.delete_many({"user_id": me["id"]})
    dbc.property_notes.delete_many({"user_id": me["id"]})


# ─── Basic search ───────────────────────────────────────────────────
def test_search_returns_payload_or_honest_mock(tech_h):
    r = requests.get(f"{API}/property/search",
                       params={"address": ADDRESS},
                       headers=tech_h, timeout=25)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "property" in body
    # We must NEVER silently mock — either mocked:true with reason or real.
    if body.get("mocked"):
        assert body.get("reason"), "mocked responses require an explicit reason"
    assert body["property"].get("address")


# ─── Cache hit ──────────────────────────────────────────────────────
def test_second_search_hits_cache(tech_h):
    r1 = requests.get(f"{API}/property/search",
                        params={"address": ADDRESS},
                        headers=tech_h, timeout=25).json()
    assert r1.get("cached") is False, "first hit should be cold"
    r2 = requests.get(f"{API}/property/search",
                        params={"address": ADDRESS},
                        headers=tech_h, timeout=25).json()
    assert r2.get("cached") is True, "second hit should be cached"
    assert r2.get("cached_at"), "cached response missing timestamp"


# ─── Rate limit ─────────────────────────────────────────────────────
def test_rate_limit_31st_call_returns_429(tech_h, dbc):
    for i in range(30):
        r = requests.get(f"{API}/property/search",
                           params={"address": f"{i} Rate Limit Rd"},
                           headers=tech_h, timeout=15)
        assert r.status_code in (200, 404), r.status_code
    # 31st call — should be blocked
    r31 = requests.get(f"{API}/property/search",
                         params={"address": "31 Blocked Rd"},
                         headers=tech_h, timeout=15)
    assert r31.status_code == 429, r31.text


# ─── History ────────────────────────────────────────────────────────
def test_history_returns_recent(tech_h):
    requests.get(f"{API}/property/search",
                    params={"address": ADDRESS},
                    headers=tech_h, timeout=25)
    r = requests.get(f"{API}/property/history",
                       headers=tech_h, timeout=10).json()
    assert r["total"] >= 1
    assert any(x["address"] == ADDRESS for x in r["items"])


# ─── Notes save + list ──────────────────────────────────────────────
def test_save_and_list_notes(tech_h):
    saved = requests.post(f"{API}/property/save-note", headers=tech_h,
                             json={"address": ADDRESS,
                                     "note": "Large backyard, needs quarterly",
                                     "tags": ["large-yard", "quarterly"]},
                             timeout=10).json()
    assert saved["id"]
    listed = requests.get(f"{API}/property/saved-notes",
                              params={"address": ADDRESS},
                              headers=tech_h, timeout=10).json()
    assert listed["total"] >= 1
    assert any(n["id"] == saved["id"] for n in listed["items"])
    assert "large-yard" in listed["items"][0]["tags"]


# ─── Role gating: customer 403 ──────────────────────────────────────
def test_customer_forbidden(customer_h):
    for path, params in [
        ("/property/search", {"address": ADDRESS}),
        ("/property/history", None),
        ("/property/saved-notes", None),
    ]:
        r = requests.get(f"{API}{path}", params=params,
                           headers=customer_h, timeout=10)
        assert r.status_code == 403, f"{path} → {r.status_code}"
    r2 = requests.post(f"{API}/property/save-note", headers=customer_h,
                         json={"address": ADDRESS, "note": "x"}, timeout=10)
    assert r2.status_code == 403


# ─── Admin also allowed ─────────────────────────────────────────────
def test_admin_allowed(admin_h):
    r = requests.get(f"{API}/property/search",
                       params={"address": ADDRESS},
                       headers=admin_h, timeout=15)
    assert r.status_code == 200


def test_save_note_accepts_address_normalized_alias(tech_h, dbc):
    """`POST /property/save-note` must accept `address_normalized` as an
    alias for `address` so mobile clients don't need to know the raw
    address string."""
    normalized = "  742 EVERGREEN Terrace, springfield, or 97477  "
    r = requests.post(f"{API}/property/save-note", headers=tech_h, json={
        "address_normalized": normalized,
        "note": "alias-test note",
        "tags": ["alias-test"],
    }, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"]
    # The saved doc's address_normalized should be the whitespace-collapsed
    # lower-cased form regardless of which alias the client used.
    assert body["address_normalized"] == \
        "742 evergreen terrace, springfield, or 97477"
    # And it should be listable when queried by that normalized address.
    listed = requests.get(f"{API}/property/saved-notes",
                              params={"address": normalized.strip()},
                              headers=tech_h, timeout=10).json()
    assert any(x["id"] == body["id"] for x in listed["items"])

    # If both are provided, `address` wins.
    r2 = requests.post(f"{API}/property/save-note", headers=tech_h, json={
        "address": "111 Preferred Ave",
        "address_normalized": "999 Ignored Rd",
        "note": "both-fields test",
    }, timeout=10)
    assert r2.status_code == 200
    assert r2.json()["address"] == "111 Preferred Ave"

    # Empty body → 422
    r3 = requests.post(f"{API}/property/save-note", headers=tech_h, json={
        "note": "no address",
    }, timeout=10)
    assert r3.status_code == 422

