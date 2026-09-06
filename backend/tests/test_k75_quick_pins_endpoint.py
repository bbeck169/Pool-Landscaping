"""Phase K75 · Step B · Feb-2026 — /api/users/me/quick-pins contract.

Covers:
    • GET returns [] for a fresh user (no seed auto-write).
    • PUT roundtrip persists ``{to, label, iconKey}`` and returns
      the normalized array.
    • Cap: PUT with 16 pins → 400 ``pin_cap_exceeded``.
    • Foreign route: PUT with a path missing the leading ``/`` →
      400 ``foreign_route``.
    • Wrong-role route: technician trying to pin ``/admin/...`` →
      400 ``wrong_role_route``.
    • Icon whitelist: PUT with a stale iconKey → 400
      ``icon_not_whitelisted``.
    • Duplicate ``to``: PUT with the same route twice → 400
      ``duplicate_pin``.
    • Label validation: empty / > 40 char → 400 ``label_invalid``.
    • Unauthenticated: no bearer → 401.
    • Cross-user isolation: user A's PUT does NOT surface on
      user B's GET.
    • Icon whitelist source parity — the Python + JS whitelists
      contain the same keys (grep-lock so they can't drift).
"""
import os
import re
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


SUPER = ("super@aquaterra.com", "password123")
ADMIN = ("manager@aquaterra.com", "password123")
TECH = ("mike@aquaterra.com", "password123")
CUSTOMER = ("customer@aquaterra.com", "password123")


def _login(email, pw):
    r = requests.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    tok = r.json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    me = requests.get(f"{BASE}/api/auth/me", headers=h, timeout=15).json()
    return h, me


@pytest.fixture(scope="module")
def dbc():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(autouse=True)
def _reset_pins(dbc):
    """Wipe test users' pin lists before + after each test so the
    contract runs against a known starting state and never leaks
    into a neighbor test."""
    emails = [e for (e, _p) in (SUPER, ADMIN, TECH, CUSTOMER)]
    dbc.users.update_many({"email": {"$in": emails}},
                             {"$unset": {"preferences.quickPins": ""}})
    yield
    dbc.users.update_many({"email": {"$in": emails}},
                             {"$unset": {"preferences.quickPins": ""}})


# ─── 1. GET returns [] for a fresh user (no auto-write) ─────────────
def test_get_empty_for_fresh_user(dbc):
    h, u = _login(*ADMIN)
    r = requests.get(f"{BASE}/api/users/me/quick-pins",
                       headers=h, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json() == {"pins": []}
    # Ensure GET did NOT auto-write a default seed into the doc.
    doc = dbc.users.find_one({"id": u["id"]},
                                 {"_id": 0, "preferences": 1})
    assert (doc.get("preferences") or {}).get("quickPins") is None


# ─── 2. PUT roundtrip ────────────────────────────────────────────────
def test_put_roundtrip_persists(dbc):
    h, u = _login(*ADMIN)
    body = {"pins": [
        {"to": "/schedule",  "label": "Schedule",  "iconKey": "calendar_days"},
        {"to": "/customers", "label": "Customers", "iconKey": "users"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert len(j["pins"]) == 2
    assert j["pins"][0]["to"] == "/schedule"

    # GET reflects the PUT.
    r2 = requests.get(f"{BASE}/api/users/me/quick-pins",
                        headers=h, timeout=15)
    assert r2.status_code == 200
    assert r2.json() == {"pins": body["pins"]}

    # Mongo doc reflects the PUT.
    doc = dbc.users.find_one({"id": u["id"]},
                                 {"_id": 0, "preferences": 1})
    assert doc["preferences"]["quickPins"] == body["pins"]
    assert "quickPins_updated_at" in doc["preferences"]


# ─── 3. Cap enforcement ─────────────────────────────────────────────
def test_put_cap_enforced_at_15():
    h, _ = _login(*ADMIN)
    over_cap = [
        {"to": f"/customers?tab={i}", "label": f"Tab {i}", "iconKey": "users"}
        for i in range(16)
    ]
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json={"pins": over_cap}, timeout=15)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("code") == "pin_cap_exceeded"
    assert detail.get("cap") == 15


def test_put_exactly_15_succeeds():
    h, _ = _login(*ADMIN)
    at_cap = [
        {"to": f"/customers?tab={i}", "label": f"Tab {i}", "iconKey": "users"}
        for i in range(15)
    ]
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json={"pins": at_cap}, timeout=15)
    assert r.status_code == 200, r.text
    assert len(r.json()["pins"]) == 15


# ─── 4. Foreign route ──────────────────────────────────────────────
def test_put_foreign_route_rejected():
    h, _ = _login(*ADMIN)
    body = {"pins": [
        {"to": "no-leading-slash", "label": "Bad", "iconKey": "star"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 400
    assert (r.json().get("detail") or {}).get("code") == "foreign_route"


def test_put_traversal_rejected():
    h, _ = _login(*ADMIN)
    body = {"pins": [
        {"to": "/../etc/passwd", "label": "Nope", "iconKey": "star"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 400
    assert (r.json().get("detail") or {}).get("code") == "foreign_route"


def test_put_external_url_rejected():
    h, _ = _login(*ADMIN)
    body = {"pins": [
        {"to": "https://evil.example.com/steal", "label": "Bad",
         "iconKey": "external_link"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 400
    assert (r.json().get("detail") or {}).get("code") == "foreign_route"


# ─── 5. Wrong-role route ───────────────────────────────────────────
def test_put_wrong_role_tech_pinning_admin_route():
    h, _ = _login(*TECH)
    body = {"pins": [
        {"to": "/admin/impersonate", "label": "Impersonate",
         "iconKey": "shield_check"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 400, r.text
    assert (r.json().get("detail") or {}).get("code") == "wrong_role_route"


def test_put_tech_valid_route_accepted():
    """Tech pinning a route in the tech allow-list succeeds."""
    h, _ = _login(*TECH)
    body = {"pins": [
        {"to": "/schedule", "label": "Schedule", "iconKey": "calendar_days"},
        {"to": "/d2d",      "label": "D2D",      "iconKey": "door_open"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 200, r.text


# ─── 6. Icon whitelist ─────────────────────────────────────────────
def test_put_stale_icon_key_rejected():
    h, _ = _login(*ADMIN)
    body = {"pins": [
        {"to": "/schedule", "label": "Schedule",
         "iconKey": "not_a_real_icon_key"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 400
    assert (r.json().get("detail") or {}).get("code") == "icon_not_whitelisted"


# ─── 7. Duplicate pin ──────────────────────────────────────────────
def test_put_duplicate_route_rejected():
    h, _ = _login(*ADMIN)
    body = {"pins": [
        {"to": "/schedule", "label": "S1", "iconKey": "calendar_days"},
        {"to": "/schedule", "label": "S2", "iconKey": "calendar_days"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 400
    assert (r.json().get("detail") or {}).get("code") == "duplicate_pin"


# ─── 8. Label validation ───────────────────────────────────────────
def test_put_empty_label_rejected():
    h, _ = _login(*ADMIN)
    body = {"pins": [
        {"to": "/schedule", "label": "   ", "iconKey": "calendar_days"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 400
    assert (r.json().get("detail") or {}).get("code") == "label_invalid"


def test_put_over_max_label_rejected():
    h, _ = _login(*ADMIN)
    body = {"pins": [
        {"to": "/schedule", "label": "X" * 41, "iconKey": "calendar_days"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h, json=body, timeout=15)
    assert r.status_code == 400
    assert (r.json().get("detail") or {}).get("code") == "label_invalid"


# ─── 9. Auth ───────────────────────────────────────────────────────
def test_get_unauthenticated_401():
    r = requests.get(f"{BASE}/api/users/me/quick-pins", timeout=15)
    assert r.status_code in (401, 403)


def test_put_unauthenticated_401():
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       json={"pins": []}, timeout=15)
    assert r.status_code in (401, 403)


# ─── 10. Cross-user isolation ──────────────────────────────────────
def test_cross_user_isolation():
    # Admin A writes pins.
    h_admin, _ = _login(*ADMIN)
    body_a = {"pins": [
        {"to": "/schedule", "label": "Admin A Schedule",
         "iconKey": "calendar_days"},
    ]}
    r = requests.put(f"{BASE}/api/users/me/quick-pins",
                       headers=h_admin, json=body_a, timeout=15)
    assert r.status_code == 200

    # Tech reads his own pins — should NOT see admin's pins.
    h_tech, _ = _login(*TECH)
    r2 = requests.get(f"{BASE}/api/users/me/quick-pins",
                        headers=h_tech, timeout=15)
    assert r2.status_code == 200
    tech_pins = r2.json()["pins"]
    assert not any(p.get("label") == "Admin A Schedule" for p in tech_pins)
    # Tech pin list is either empty (fresh user) or its own defaults
    # customization — never the admin's.


# ─── 11. Icon whitelist source parity (Python ↔ JS) ────────────────
def test_icon_whitelist_source_parity():
    """The Python ``ICON_WHITELIST`` and the JS ``ICON_MAP`` MUST
    contain the exact same key set — the K75 spec bakes this
    into both files so a pin serialized on the frontend always
    validates on the backend."""
    from routers.quick_pins import ICON_WHITELIST as PY_WHITELIST

    js_path = Path(__file__).resolve().parents[2] / "frontend" / "src" / "nav" / "lucideIcons.js"
    src = js_path.read_text(encoding="utf-8")
    # Grep every ``some_key:`` line inside the exported ``ICON_MAP``
    # object literal.
    start = src.index("export const ICON_MAP")
    end = src.index("};", start)
    body = src[start:end]
    js_keys = set(re.findall(r"^\s*([a-z_0-9]+):\s*\w+,?\s*$", body, re.M))
    assert js_keys, "JS icon whitelist parse returned no keys"
    assert js_keys == set(PY_WHITELIST), (
        f"Icon whitelist drift.\n  JS only: {js_keys - set(PY_WHITELIST)}\n"
        f"  PY only: {set(PY_WHITELIST) - js_keys}"
    )
