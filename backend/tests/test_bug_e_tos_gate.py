"""Feb-2026 · BUG E — Terms of Service gate tests.

Covers:
* GET /api/legal/tos (public) returns the active version + markdown.
* POST /api/users/me/accept-tos success path stamps the user doc and
  clears must_accept_tos.
* Version mismatch → 409.
* super_admin is exempt end-to-end (endpoint returns exempt sentinel;
  /auth/me never reports must_accept_tos=True).
* Idempotency — repeated acceptance is a no-op.
* Role scoping — customer, admin, technician all gate/ungate properly.
* auth_response payload (from login) exposes must_accept_tos.
"""
import os

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = "http://localhost:8001/api"

# Sync mongo client for test setup — Motor's event-loop binding
# breaks across multiple ``asyncio.run`` calls in the same pytest
# process, so use pymongo directly for the clear-flag helper.
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_client = MongoClient(_MONGO_URL) if _MONGO_URL else None
_sync_db = _sync_client[_DB_NAME] if (_sync_client and _DB_NAME) else None


def _clear_tos_flags(email: str) -> None:
    assert _sync_db is not None, "Mongo URL/name not configured for tests"
    _sync_db.users.update_one(
        {"email": email},
        {"$unset": {"tos_accepted_at": "", "tos_version_accepted": ""}},
    )


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _login_full(email: str, password: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()


def _me(tok: str) -> dict:
    r = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    r.raise_for_status()
    return r.json()


def _accept(tok: str, version: str):
    return requests.post(
        f"{API}/users/me/accept-tos",
        json={"version": version},
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )


async def _clear_tos_flags_async(email: str) -> None:
    """Kept only so an async-consuming helper stays available; the tests
    themselves call the sync ``_clear_tos_flags`` directly."""
    _clear_tos_flags(email)


# ── PUBLIC — /api/legal/tos ──────────────────────────────────────
def test_legal_tos_public_returns_active_version():
    r = requests.get(f"{API}/legal/tos", timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("version") == "1.0.0"
    assert body.get("effective_date")
    assert isinstance(body.get("markdown"), str)
    assert len(body["markdown"]) > 200


# ── ROOT-CAUSE — auth_response + /auth/me expose must_accept_tos ─
def test_login_payload_exposes_must_accept_tos_flag_for_customer():
    payload = _login_full("customer@aquaterra.com")
    u = payload.get("user") or {}
    assert "must_accept_tos" in u, "auth_response must expose must_accept_tos"
    assert "tos_version_accepted" in u


def test_auth_me_includes_must_accept_tos():
    tok = _login("customer@aquaterra.com")
    me = _me(tok)
    assert "must_accept_tos" in me


# ── SUPER_ADMIN EXEMPTION ────────────────────────────────────────
def test_super_admin_never_gated_via_me():
    tok = _login("super@aquaterra.com")
    me = _me(tok)
    assert me.get("role") == "super_admin"
    assert me.get("must_accept_tos") is False


def test_super_admin_accept_endpoint_is_no_op_sentinel():
    tok = _login("super@aquaterra.com")
    r = _accept(tok, "1.0.0")
    assert r.status_code == 200
    body = r.json()
    assert body.get("must_accept_tos") is False
    # Sentinel exempt payload — no DB write.
    assert body.get("tos_version_accepted") is None
    assert body.get("tos_accepted_at") is None
    assert "super_admin" in (body.get("note") or "")


# ── CUSTOMER GATE + ACCEPT ────────────────────────────────────────
def test_customer_gate_flow_end_to_end():
    _clear_tos_flags("customer@aquaterra.com")
    tok = _login("customer@aquaterra.com")
    me = _me(tok)
    assert me.get("must_accept_tos") is True, "cleared customer must be gated"
    assert me.get("tos_version_accepted") in (None,)

    r = _accept(tok, "1.0.0")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert body.get("must_accept_tos") is False
    assert body.get("tos_version_accepted") == "1.0.0"
    assert body.get("tos_accepted_at")

    # /auth/me now reflects it.
    me2 = _me(tok)
    assert me2.get("must_accept_tos") is False
    assert me2.get("tos_version_accepted") == "1.0.0"


def test_customer_accept_is_idempotent():
    tok = _login("customer@aquaterra.com")
    r1 = _accept(tok, "1.0.0")
    r2 = _accept(tok, "1.0.0")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json().get("must_accept_tos") is False


# ── VERSION MISMATCH ─────────────────────────────────────────────
def test_version_mismatch_returns_409():
    tok = _login("customer@aquaterra.com")
    r = _accept(tok, "9.9.9")
    assert r.status_code == 409, r.text
    detail = (r.json() or {}).get("detail", "")
    assert "version" in detail.lower() or "reload" in detail.lower()


# ── ROLE SCOPING — admin + technician are gated on missing fields ─
def test_admin_gated_when_fields_missing():
    _clear_tos_flags("admin@aquaterra.com")
    tok = _login("admin@aquaterra.com")
    me = _me(tok)
    assert me.get("role") == "admin"
    assert me.get("must_accept_tos") is True

    r = _accept(tok, "1.0.0")
    assert r.status_code == 200
    assert r.json().get("must_accept_tos") is False
    assert _me(tok).get("must_accept_tos") is False


def test_technician_gated_when_fields_missing():
    _clear_tos_flags("mike@aquaterra.com")
    tok = _login("mike@aquaterra.com")
    me = _me(tok)
    assert me.get("role") == "technician"
    assert me.get("must_accept_tos") is True

    r = _accept(tok, "1.0.0")
    assert r.status_code == 200
    assert _me(tok).get("must_accept_tos") is False


# ── AUTH REQUIRED ────────────────────────────────────────────────
def test_accept_endpoint_requires_auth():
    r = requests.post(f"{API}/users/me/accept-tos",
                       json={"version": "1.0.0"}, timeout=15)
    assert r.status_code in (401, 403), r.text


# ── HELPER FN unit — compute_must_accept_tos ─────────────────────
def test_compute_must_accept_tos_helper():
    from config_tos import compute_must_accept_tos, CURRENT_TOS_VERSION
    assert compute_must_accept_tos(
        {"role": "super_admin"}) is False
    assert compute_must_accept_tos(
        {"role": "super_admin", "tos_version_accepted": "0.0.1"}) is False
    assert compute_must_accept_tos(
        {"role": "customer"}) is True
    assert compute_must_accept_tos(
        {"role": "customer", "tos_version_accepted": "0.9"}) is True
    assert compute_must_accept_tos(
        {"role": "customer", "tos_version_accepted": CURRENT_TOS_VERSION}) is False
    assert compute_must_accept_tos(
        {"role": "admin", "tos_version_accepted": CURRENT_TOS_VERSION}) is False
    assert compute_must_accept_tos(
        {"role": "technician"}) is True
    assert compute_must_accept_tos({}) is False  # falsy user → skip
