"""Feb-2026 · Item 7 — Customer tour first-login gating.

Tests:
* Admin+tech cannot call ``POST /users/me/mark-tour-seen`` → 403.
* Customer can call it → 200 and flag flips.
* Admin can reset another customer's flag via ``POST /users/{id}/reset-tour``.
* Non-admin cannot call reset-tour → 403.
* ``/auth/me`` includes ``has_seen_customer_tour``.
"""
import os
import requests

API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001") + "/api"
if API.startswith("http://localhost") or "backend" in os.environ.get("PYTEST_MODE", ""):
    API = "http://localhost:8001/api"


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _me(tok: str) -> dict:
    r = requests.get(f"{API}/auth/me",
                      headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    r.raise_for_status()
    return r.json()


def test_auth_me_exposes_flag_for_customer():
    tok = _login("customer@aquaterra.com")
    me = _me(tok)
    assert me["role"] == "customer"
    assert "has_seen_customer_tour" in me


def test_admin_and_tech_cannot_mark_tour_seen():
    for email in ["admin@aquaterra.com", "mike@aquaterra.com"]:
        tok = _login(email)
        r = requests.post(f"{API}/users/me/mark-tour-seen",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={}, timeout=15)
        assert r.status_code == 403, f"{email} got {r.status_code}"


def test_customer_can_mark_and_admin_can_reset():
    ctok = _login("customer@aquaterra.com")
    atok = _login("admin@aquaterra.com")
    cust_uid = _me(ctok)["id"]

    # Reset first so we know start state.
    r = requests.post(f"{API}/users/{cust_uid}/reset-tour",
                       headers={"Authorization": f"Bearer {atok}"},
                       json={}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["has_seen_customer_tour"] is False

    # Customer marks it seen.
    r = requests.post(f"{API}/users/me/mark-tour-seen",
                       headers={"Authorization": f"Bearer {ctok}"},
                       json={}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["has_seen_customer_tour"] is True

    # /auth/me reflects the new flag.
    assert _me(ctok)["has_seen_customer_tour"] is True

    # Admin resets it — should flip back.
    r = requests.post(f"{API}/users/{cust_uid}/reset-tour",
                       headers={"Authorization": f"Bearer {atok}"},
                       json={}, timeout=15)
    assert r.status_code == 200, r.text
    assert _me(ctok)["has_seen_customer_tour"] is False


def test_non_admin_cannot_reset():
    ctok = _login("customer@aquaterra.com")
    cust_uid = _me(ctok)["id"]
    r = requests.post(f"{API}/users/{cust_uid}/reset-tour",
                       headers={"Authorization": f"Bearer {ctok}"},
                       json={}, timeout=15)
    assert r.status_code == 403


def test_top_questions_endpoint_admin_only():
    atok = _login("admin@aquaterra.com")
    r = requests.get(f"{API}/ai/copilot/top-questions?days=30",
                      headers={"Authorization": f"Bearer {atok}"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)
    # Non-admin should 403.
    ctok = _login("customer@aquaterra.com")
    r = requests.get(f"{API}/ai/copilot/top-questions?days=30",
                      headers={"Authorization": f"Bearer {ctok}"}, timeout=15)
    assert r.status_code == 403
