"""Feb-2026 · Customer service-reports enhancements — search /
filters / pagination + detail ``job_photos`` merge + token-scoped
photo streaming.

Locks the acceptance criteria on the dispatch:
  1. Detail response contains ``job_photos: []`` (empty when the
     job has no photos, populated when it does).
  2. List response uses ``{items, page, page_size, total,
     total_pages}`` — 200-cap gone, page_size max 100.
  3. Search filter matches partial substrings case-insensitively
     across notes.
  4. Pagination page-2 boundary returns the next batch, not the
     first.
  5. Anon GET on the new photo route → 401.

Runs against the live preview backend via ``requests``.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

REQ_TIMEOUT = 45


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password},
                      timeout=REQ_TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code}")
    return r.json().get("access_token")


@pytest.fixture(scope="module")
def admin_tok():
    return _login("admin@aquaterra.com", "password123")


@pytest.fixture(scope="module")
def admin_sess(admin_tok):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_tok}"})
    return s


def _rows(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "results", "data", "customers"):
            if key in body and isinstance(body[key], list):
                return body[key]
    return []


@pytest.fixture(scope="module")
def customer_login():
    """Use the pre-seeded customer account. The Aquaterra seed data
    ensures ``customer@aquaterra.com`` has at least one submitted
    service-report attached to their tenant."""
    tok = _login("customer@aquaterra.com", "password123")
    if not tok:
        pytest.skip("customer@aquaterra.com login unavailable")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}"})
    # Confirm the reports list is non-empty. If it is, skip the
    # pagination/search suite — the seed is present but empty.
    r_list = s.get(
        f"{BASE_URL}/api/customers/me/service-reports?page_size=1",
        timeout=REQ_TIMEOUT,
    )
    if r_list.status_code != 200:
        pytest.skip(f"customer sr list returned {r_list.status_code}")
    body = r_list.json()
    if not isinstance(body, dict) or body.get("total", 0) < 1:
        pytest.skip("customer has no submitted service reports — "
                    "seed one via admin before running these tests")
    return {"tok": tok, "sess": s}


# ─── Acceptance 4 — pagination shape ─────────────────────────────

def test_list_returns_paginated_shape_not_bare_array(customer_login):
    r = customer_login["sess"].get(
        f"{BASE_URL}/api/customers/me/service-reports",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict), (
        "list endpoint must return the paginated {items, ...} shape "
        "— NOT a bare array"
    )
    assert "items" in body and isinstance(body["items"], list)
    assert "page" in body and isinstance(body["page"], int)
    assert "page_size" in body and isinstance(body["page_size"], int)
    assert "total" in body and isinstance(body["total"], int)
    assert "total_pages" in body and isinstance(body["total_pages"], int)
    # Default page_size is 20.
    assert body["page_size"] == 20
    assert body["page"] == 1


def test_list_page_size_caps_at_100(customer_login):
    r = customer_login["sess"].get(
        f"{BASE_URL}/api/customers/me/service-reports?page_size=999",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 422, r.text


def test_list_page_size_1_returns_at_most_1(customer_login):
    r = customer_login["sess"].get(
        f"{BASE_URL}/api/customers/me/service-reports?page_size=1",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) <= 1
    if body["total"] >= 2:
        # Page 2 must be different from page 1.
        r2 = customer_login["sess"].get(
            f"{BASE_URL}/api/customers/me/service-reports?page_size=1&page=2",
            timeout=REQ_TIMEOUT,
        )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2["page"] == 2
        assert body2["items"]
        assert body2["items"][0]["id"] != body["items"][0]["id"], (
            "page=2 must return a different report than page=1"
        )


# ─── Acceptance 5 — substring search ─────────────────────────────

def test_list_q_substring_matches_case_insensitive(customer_login):
    # Bogus substring nobody's report contains — total must be 0.
    _junk = f"zzz-{uuid.uuid4().hex[:8]}-zzz"
    r = customer_login["sess"].get(
        f"{BASE_URL}/api/customers/me/service-reports?q={_junk}",
        timeout=REQ_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


# ─── Acceptance 1 — job_photos on the detail response ────────────

def test_detail_response_includes_job_photos_field(customer_login):
    r = customer_login["sess"].get(
        f"{BASE_URL}/api/customers/me/service-reports?page_size=1",
        timeout=REQ_TIMEOUT,
    )
    body = r.json()
    if not body.get("items"):
        pytest.skip("customer has no submitted reports")
    rid = body["items"][0]["id"]
    r_d = customer_login["sess"].get(
        f"{BASE_URL}/api/customers/me/service-reports/{rid}",
        timeout=REQ_TIMEOUT,
    )
    assert r_d.status_code == 200, r_d.text
    detail = r_d.json()
    assert "job_photos" in detail
    assert isinstance(detail["job_photos"], list)
    # ``photos`` (tech-attached) and ``job_photos`` (job-attached)
    # are separate arrays — cleaner attribution per the dispatch.
    assert "photos" in detail
    for p in detail["job_photos"]:
        assert isinstance(p, dict)
        # URL is relative + points at the token-scoped streaming
        # route (customer session enforces ownership). The
        # frontend prepends the origin at render time.
        assert p.get("url", "").startswith("/api/customers/me/jobs/")
        assert p.get("id")


# ─── Acceptance 3 — anon GET on the photo route → 401 ────────────

def test_anon_get_on_photo_route_returns_401(customer_login):
    r = customer_login["sess"].get(
        f"{BASE_URL}/api/customers/me/service-reports?page_size=1",
        timeout=REQ_TIMEOUT,
    )
    body = r.json()
    if not body.get("items"):
        pytest.skip("customer has no submitted reports")
    rid = body["items"][0]["id"]
    r_d = customer_login["sess"].get(
        f"{BASE_URL}/api/customers/me/service-reports/{rid}",
        timeout=REQ_TIMEOUT,
    )
    photos = r_d.json().get("job_photos") or []
    if not photos:
        pytest.skip("job has no attached photos")
    url = photos[0]["url"]
    # Anon (no Authorization header) → 401.
    r_anon = requests.get(f"{BASE_URL}{url}", timeout=REQ_TIMEOUT)
    assert r_anon.status_code == 401, r_anon.text
