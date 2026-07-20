"""AE — RBAC guardrail — Feb-2026.

Every AI-Employees + AI-Credits endpoint must be admin-only.
Non-admin roles (technician, customer) must receive 401/403 on every
route, on every verb — never a 200. Anonymous requests must fail too.

If any of these tests turn red, an AI-employee surface has leaked
outside the admin cohort and the frontend dock guard is no longer
sufficient on its own.
"""
import os
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

FAKE_ID = "00000000-0000-0000-0000-000000000000"
FORBIDDEN = {401, 403}


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


# ─── Endpoint catalog ─────────────────────────────────────────────────
# (method, path, body-or-None). Path IDs are stubbed — auth check must
# short-circuit BEFORE the handler looks up the row, so a fake UUID is
# fine.

AI_EMPLOYEE_ROUTES = [
    ("GET",   f"/ai-employees",                                       None),
    ("GET",   f"/ai-employees/actions",                               None),
    ("GET",   f"/ai-employees/{FAKE_ID}",                             None),
    ("PATCH", f"/ai-employees/{FAKE_ID}",                             {"is_active": False}),
    ("GET",   f"/brand-brain",                                        None),
    ("PATCH", f"/brand-brain",                                        {"tone": "warm"}),
    ("GET",   f"/ai-employees/{FAKE_ID}/conversations",               None),
    ("POST",  f"/ai-employees/{FAKE_ID}/conversations",               {"title": "x"}),
    ("GET",   f"/ai-employees/{FAKE_ID}/conversations/{FAKE_ID}/messages", None),
    ("POST",  f"/ai-employees/{FAKE_ID}/conversations/{FAKE_ID}/messages", {"text": "hi"}),
    ("GET",   f"/ai-employees/actions/{FAKE_ID}",                     None),
    ("POST",  f"/ai-employees/actions/{FAKE_ID}/approve",             {}),
    ("POST",  f"/ai-employees/actions/{FAKE_ID}/reject",              {}),
]

AI_CREDITS_ROUTES = [
    ("GET",   f"/ai-credits/balance",                                 None),
    ("GET",   f"/ai-credits/transactions",                            None),
    ("POST",  f"/ai-credits/topup",                                   {"amount": 100}),
    ("PATCH", f"/ai-credits/plan",                                    {"plan": "starter"}),
]

ALL_ROUTES = AI_EMPLOYEE_ROUTES + AI_CREDITS_ROUTES


def _call(method, path, headers, body):
    url = f"{API}{path}"
    if method == "GET":
        return requests.get(url, headers=headers, timeout=20)
    if method == "POST":
        return requests.post(url, headers=headers, json=(body or {}), timeout=20)
    if method == "PATCH":
        return requests.patch(url, headers=headers, json=(body or {}), timeout=20)
    raise AssertionError(f"unknown verb {method}")


# ─── Tech role ────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", ALL_ROUTES,
                          ids=[f"{m}:{p}" for m, p, _ in ALL_ROUTES])
def test_tech_role_forbidden_on_all_ai_routes(tech_headers, method, path, body):
    r = _call(method, path, tech_headers, body)
    assert r.status_code in FORBIDDEN, (
        f"tech reached {method} {path} with {r.status_code}: {r.text[:200]}"
    )


# ─── Customer role ────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", ALL_ROUTES,
                          ids=[f"{m}:{p}" for m, p, _ in ALL_ROUTES])
def test_customer_role_forbidden_on_all_ai_routes(customer_headers, method, path, body):
    r = _call(method, path, customer_headers, body)
    assert r.status_code in FORBIDDEN, (
        f"customer reached {method} {path} with {r.status_code}: {r.text[:200]}"
    )


# ─── Anonymous ────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,body", ALL_ROUTES,
                          ids=[f"{m}:{p}" for m, p, _ in ALL_ROUTES])
def test_anonymous_forbidden_on_all_ai_routes(method, path, body):
    r = _call(method, path, {}, body)
    assert r.status_code in FORBIDDEN, (
        f"anonymous reached {method} {path} with {r.status_code}: {r.text[:200]}"
    )
