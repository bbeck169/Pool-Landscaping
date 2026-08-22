"""Backend tests · Feb-2026 — Check-in AI Description Rewrite.

Covers:
  * Happy path — endpoint returns 200 + rewritten + original.
  * Empty draft → 400 ``{"error": "empty_draft"}``.
  * Rate limit → 429 after > 10 calls in the same rolling hour.
  * Auth required — no token → 401/403.
  * Pure-function unit tests for the prompt builder + rate limiter.

The HTTP tests exercise the running FastAPI server on :8001 and DO
hit the real Emergent LLM (each call is ~2 s). The full sweep is
~30 s. In-process unit tests cover rate-limit edge cases without
touching the network.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

# ── Public URL used by the pytest sweep (mirrors other suites). ──
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
_ENV = dotenv_values(_BACKEND_ENV)
_REACT_ENV = Path(__file__).resolve().parents[2] / "frontend" / ".env"
_REACT = dotenv_values(_REACT_ENV) if _REACT_ENV.is_file() else {}
_PUBLIC_URL = _REACT.get("REACT_APP_BACKEND_URL") or os.environ.get(
    "REACT_APP_BACKEND_URL")
API = os.environ.get("BACKEND_API_URL") or "http://localhost:8001/api"

# ── Import the module under test for in-process unit tests. ──
_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from routers import checkin_rewrite  # noqa: E402


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_login('manager@aquaterra.com')}"}


def _server_up() -> bool:
    try:
        requests.get(f"{API}/", timeout=2)
        return True
    except Exception:
        return False


needs_server = pytest.mark.skipif(
    not _server_up(), reason="backend server not reachable on :8001")


# ══════════════════════════════════════════════════════════════════
# HTTP integration
# ══════════════════════════════════════════════════════════════════
@needs_server
def test_happy_path_returns_200_with_rewritten_text():
    headers = _admin_headers()
    r = requests.post(
        f"{API}/checkins/rewrite-description",
        headers=headers,
        json={
            "draft_description": "worked on pump, replaced filter",
            "context": {
                "service_category": "Pool Equipment Installs",
                "business_name": "AquaTerra Pool & Landscape",
                "address": "Phoenix, AZ",
            },
        },
        timeout=45,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("original") == "worked on pump, replaced filter"
    rewritten = body.get("rewritten") or ""
    assert isinstance(rewritten, str) and len(rewritten) > 20


@needs_server
def test_empty_draft_returns_400():
    headers = _admin_headers()
    r = requests.post(
        f"{API}/checkins/rewrite-description",
        headers=headers,
        json={"draft_description": "   "},
        timeout=15,
    )
    assert r.status_code == 400
    detail = r.json().get("detail") or {}
    assert detail.get("error") == "empty_draft"


@needs_server
def test_auth_required_returns_401_or_403():
    r = requests.post(
        f"{API}/checkins/rewrite-description",
        json={"draft_description": "hi"},
        timeout=15,
    )
    assert r.status_code in (401, 403)


@needs_server
@pytest.mark.slow
def test_rate_limit_returns_429_after_10_calls():
    """The limiter is process-local — since the app runs in one
    server process, sending 11 real calls in a row is the shortest
    way to prove the wire from a black-box perspective.
    """
    headers = _admin_headers()
    body = {"draft_description": "quick note", "context": {}}
    saw_429 = False
    last_status = None
    for i in range(12):
        r = requests.post(
            f"{API}/checkins/rewrite-description",
            headers=headers, json=body, timeout=45,
        )
        last_status = r.status_code
        if r.status_code == 429:
            detail = r.json().get("detail") or {}
            assert detail.get("error") == "rate_limited"
            saw_429 = True
            break
    assert saw_429, f"expected a 429 within 12 calls, last={last_status}"


# ══════════════════════════════════════════════════════════════════
# Pure-function units (no network / no LLM)
# ══════════════════════════════════════════════════════════════════
def test_unit_build_prompt_includes_context_bits():
    ctx = checkin_rewrite.RewriteContext(
        service_category="Pool Cleaning",
        customer_name="Jane Doe",
        address="Phoenix, AZ",
        business_name="AquaTerra",
    )
    sys_p, user_p = checkin_rewrite._build_prompt("cleaned filter", ctx)
    assert "professional copywriter" in sys_p.lower()
    assert "Pool Cleaning" in user_p
    assert "AquaTerra" in user_p
    # Feb-2026 · P22 — customer name is intentionally NOT interpolated
    # into the LLM prompt (Privacy Policy §4). The city-level location
    # hint IS preserved for SEO keyword density.
    assert "Phoenix" in user_p
    assert "Jane Doe" not in user_p
    assert "cleaned filter" in user_p


def test_unit_build_prompt_drops_exact_street_address():
    # P22 pin — a specific residential street address must not
    # appear in the LLM prompt; only the coarse "city, state" hint.
    ctx = checkin_rewrite.RewriteContext(
        service_category="Pool Cleaning",
        customer_name="Jane Doe",
        address="16165 N 83rd Ave, Peoria, AZ 85382",
        business_name="AquaTerra",
    )
    _sys_p, user_p = checkin_rewrite._build_prompt("filter swap", ctx)
    assert "16165" not in user_p
    assert "83rd Ave" not in user_p
    # But coarse "Peoria, AZ" hint survives for SEO keyword density.
    assert "Peoria" in user_p


def test_unit_build_prompt_no_context_still_valid():
    sys_p, user_p = checkin_rewrite._build_prompt("just a draft", None)
    assert "(no additional context)" in user_p
    assert "just a draft" in user_p


def test_unit_rate_check_allows_then_blocks_and_resets():
    uid = f"TEST_{uuid.uuid4()}"
    for _ in range(checkin_rewrite._RATE_MAX):
        assert checkin_rewrite._rate_check(uid) is True
    assert checkin_rewrite._rate_check(uid) is False
    # 11th call still blocked without a reset
    assert checkin_rewrite._rate_check(uid) is False
    checkin_rewrite._rate_reset(uid)
    assert checkin_rewrite._rate_check(uid) is True


def test_unit_rate_check_isolates_per_user():
    a = f"TEST_a_{uuid.uuid4()}"
    b = f"TEST_b_{uuid.uuid4()}"
    for _ in range(checkin_rewrite._RATE_MAX):
        checkin_rewrite._rate_check(a)
    assert checkin_rewrite._rate_check(a) is False
    # user B is independent
    assert checkin_rewrite._rate_check(b) is True
    checkin_rewrite._rate_reset(a)
    checkin_rewrite._rate_reset(b)
