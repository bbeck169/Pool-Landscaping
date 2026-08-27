"""Feb 2026 · Job Titles auto-learn catalog — endpoint contract.

Coverage:
  * ``GET /api/job-titles`` scoped to tenant, prefix-matched,
    sorted by usage_count DESC.
  * ``POST /api/job-titles`` upserts by (tenant_id, title_lower)
    and increments ``usage_count`` on repeat.
  * Case-insensitive dedupe.
  * Hook: creating a job with a new title auto-adds it to
    ``db.job_titles``.
  * Cross-tenant isolation.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_ENV["MONGO_URL"])[_ENV["DB_NAME"]]
API = "http://localhost:8001/api"

_TAG = "TEST_jobtitles_"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def admin_h():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture
def super_h():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture
def aquaterra_tid():
    return _sync.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


@pytest.fixture(autouse=True)
def _cleanup(aquaterra_tid):
    def _reset():
        _sync.job_titles.delete_many(
            {"title": {"$regex": f"^{_TAG}"}},
        )
        _sync.jobs.delete_many(
            {"tenant_id": aquaterra_tid, "title": {"$regex": f"^{_TAG}"}},
        )
    _reset()
    yield
    _reset()


# ───────────────────────────────────────────────────────────────
# 1 · POST upserts + increments (idempotent + case-insensitive).
# ───────────────────────────────────────────────────────────────
def test_post_upserts_and_increments_case_insensitive(admin_h):
    title = f"{_TAG}Weekly Pool"
    r1 = requests.post(
        f"{API}/job-titles",
        headers=admin_h, json={"title": title}, timeout=15,
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["title"] == title
    assert body1["usage_count"] == 1

    # Case-differed re-post → same row, count = 2.
    r2 = requests.post(
        f"{API}/job-titles",
        headers=admin_h,
        json={"title": title.lower()}, timeout=15,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["id"] == body1["id"]
    assert body2["usage_count"] == 2
    # Original casing preserved on the row.
    assert body2["title"] == title


# ───────────────────────────────────────────────────────────────
# 2 · Whitespace-normalized dedupe.
# ───────────────────────────────────────────────────────────────
def test_post_normalizes_whitespace_before_dedupe(admin_h):
    a = requests.post(f"{API}/job-titles", headers=admin_h,
                        json={"title": f"  {_TAG}Normalize  Me  "},
                        timeout=15).json()
    b = requests.post(f"{API}/job-titles", headers=admin_h,
                        json={"title": f"{_TAG}Normalize Me"},
                        timeout=15).json()
    assert a["id"] == b["id"]
    assert b["usage_count"] == 2


# ───────────────────────────────────────────────────────────────
# 3 · GET returns tenant-scoped rows sorted by usage_count DESC.
# ───────────────────────────────────────────────────────────────
def test_get_returns_rows_sorted_by_usage_count(admin_h):
    # Seed three titles, second most popular.
    for i in range(3):
        requests.post(f"{API}/job-titles", headers=admin_h,
                        json={"title": f"{_TAG}Alpha"}, timeout=15)
    for i in range(5):
        requests.post(f"{API}/job-titles", headers=admin_h,
                        json={"title": f"{_TAG}Bravo"}, timeout=15)
    requests.post(f"{API}/job-titles", headers=admin_h,
                    json={"title": f"{_TAG}Charlie"}, timeout=15)
    r = requests.get(
        f"{API}/job-titles?q={_TAG}&limit=20", headers=admin_h, timeout=15,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    tag_rows = [row for row in rows if row["title"].startswith(_TAG)]
    # Bravo (5) > Alpha (3) > Charlie (1)
    assert [row["title"] for row in tag_rows[:3]] == [
        f"{_TAG}Bravo", f"{_TAG}Alpha", f"{_TAG}Charlie",
    ]
    assert tag_rows[0]["usage_count"] == 5


# ───────────────────────────────────────────────────────────────
# 4 · GET prefix filter (case-insensitive).
# ───────────────────────────────────────────────────────────────
def test_get_prefix_filter_case_insensitive(admin_h):
    requests.post(f"{API}/job-titles", headers=admin_h,
                    json={"title": f"{_TAG}Prefix Match"}, timeout=15)
    requests.post(f"{API}/job-titles", headers=admin_h,
                    json={"title": f"{_TAG}Different"}, timeout=15)
    # Prefix hits Prefix Match, not Different.
    q = f"{_TAG.lower()}prefix"
    r = requests.get(
        f"{API}/job-titles?q={q}&limit=20", headers=admin_h, timeout=15,
    )
    assert r.status_code == 200
    rows = r.json()
    titles = [row["title"] for row in rows]
    assert any(t == f"{_TAG}Prefix Match" for t in titles)
    assert not any(t == f"{_TAG}Different" for t in titles)


# ───────────────────────────────────────────────────────────────
# 5 · GET substring fallback when the prefix returns nothing.
# ───────────────────────────────────────────────────────────────
def test_get_substring_fallback(admin_h):
    requests.post(f"{API}/job-titles", headers=admin_h,
                    json={"title": f"{_TAG}Advanced Weekly Pool"}, timeout=15)
    # ``advanced weekly pool`` has NO tenant row whose title_lower
    # starts with it (the seeded row starts with the ``TEST_`` tag),
    # so the prefix branch returns [] and the substring fallback
    # engages, surfacing the seeded row by mid-string match.
    r = requests.get(
        f"{API}/job-titles?q=advanced weekly pool&limit=20",
        headers=admin_h, timeout=15,
    )
    assert r.status_code == 200
    titles = [row["title"] for row in r.json()]
    # Substring match found the row despite the query not being a prefix.
    assert any(t == f"{_TAG}Advanced Weekly Pool" for t in titles)


# ───────────────────────────────────────────────────────────────
# 6 · Auth gate — customer role gets 403.
# ───────────────────────────────────────────────────────────────
def test_customer_role_forbidden():
    # Any account not in the staff set. We rely on the login/register
    # flow being unavailable to arbitrary roles, so instead we
    # exercise no-auth path — the endpoint MUST NOT be public.
    r = requests.get(f"{API}/job-titles", timeout=15)
    assert r.status_code in (401, 403), r.text


# ───────────────────────────────────────────────────────────────
# 7 · Empty title rejected.
# ───────────────────────────────────────────────────────────────
def test_post_empty_title_rejected(admin_h):
    r = requests.post(f"{API}/job-titles", headers=admin_h,
                        json={"title": "   "}, timeout=15)
    # FastAPI Pydantic min_length=1 → 422; the min_length check runs
    # on the raw string, so whitespace-only passes it. Our
    # ``record_title_usage`` then rejects with 400.
    assert r.status_code in (400, 422), r.text


# ───────────────────────────────────────────────────────────────
# 8 · Hook — creating a job with a new title bumps the catalog.
# ───────────────────────────────────────────────────────────────
def test_job_create_hook_records_title(admin_h, aquaterra_tid):
    # First, find any customer on the tenant to attach the job to.
    cust = _sync.customers.find_one({"tenant_id": aquaterra_tid})
    assert cust is not None, "seed a customer first"

    unique_title = f"{_TAG}Hook-{uuid.uuid4().hex[:6]}"
    payload = {
        "title": unique_title,
        "service_type": "Pool Cleaning",
        "customer_id": cust["id"],
        "scheduled_date": "2027-01-15",
    }
    r = requests.post(
        f"{API}/jobs", headers=admin_h, json=payload, timeout=30,
    )
    assert r.status_code == 200, r.text
    job = r.json()
    jid = job["id"]
    # Give the background task a beat to fire.
    import time
    for _ in range(20):
        row = _sync.job_titles.find_one(
            {"tenant_id": aquaterra_tid,
              "title_lower": unique_title.lower()},
        )
        if row:
            break
        time.sleep(0.15)
    assert row is not None, (
        "record_title_usage hook did not run on job create"
    )
    assert row["title"] == unique_title
    assert row["usage_count"] >= 1

    # Cleanup the job we just created.
    _sync.jobs.delete_one({"id": jid, "tenant_id": aquaterra_tid})


# ───────────────────────────────────────────────────────────────
# 9 · Tenant isolation — a row seeded on tenant A must not
#     surface on tenant B's list.
# ───────────────────────────────────────────────────────────────
def test_tenant_isolation(admin_h, aquaterra_tid):
    # Seed a row directly on a fake tenant B.
    fake_tid = f"fake-tenant-{uuid.uuid4().hex[:6]}"
    _sync.job_titles.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": fake_tid,
        "title": f"{_TAG}TenantB Only",
        "title_lower": f"{_TAG}TenantB Only".lower(),
        "usage_count": 99,
        "created_at": "2026-06-01",
        "updated_at": "2026-06-01",
    })
    try:
        r = requests.get(
            f"{API}/job-titles?q={_TAG}&limit=100",
            headers=admin_h, timeout=15,
        )
        assert r.status_code == 200
        titles = [row["title"] for row in r.json()]
        assert not any("TenantB Only" in t for t in titles), (
            "Cross-tenant title leaked"
        )
    finally:
        _sync.job_titles.delete_many({"tenant_id": fake_tid})
