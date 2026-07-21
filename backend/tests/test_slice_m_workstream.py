"""Feb-2026 · Slice M backend tests.

Coverage:
* M1 · ``GET /api/workstream/jobs`` — auth (customer forbidden), tech
  auto-scoping, admin filters, sort options.
* M3 · media summary shape (thumbnails + counts).
* M5 · ``GET /api/jobs/{jid}/detail`` — 7 sections, tech pricing
  invariance, admin pricing surfaced, cross-tenant + tech isolation.

Style + rebind pattern mirrors ``test_slice_k_jobs.py`` so both files
share the same fresh-event-loop / rebound-db plumbing (safe under
pytest-asyncio-less runs).
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture(scope="module")
def tech_headers():
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


async def _get_tenant_id(slug="aquaterra"):
    row = await _db().tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    return row["id"] if row else None


async def _get_mike_tech_id():
    tech = await _db().users.find_one(
        {"email": "mike@aquaterra.com"},
        {"_id": 0, "technician_id": 1, "id": 1},
    )
    return tech.get("technician_id") or tech.get("id")


async def _get_mike_job_id():
    tid = await _get_mike_tech_id()
    tenant_id = await _get_tenant_id()
    j = await _db().jobs.find_one(
        {"tenant_id": tenant_id, "technician_id": tid},
        {"_id": 0, "id": 1},
    )
    return j["id"] if j else None


async def _get_a_pricebook_item(tenant_slug="aquaterra"):
    db = _db()
    aqua = await db.tenants.find_one({"slug": tenant_slug}, {"_id": 0, "id": 1})
    row = await db.items.find_one(
        {"$or": [{"tenant_id": aqua["id"]}, {"tenant_id": {"$exists": False}}],
         "active": {"$ne": False}},
        {"_id": 0, "id": 1, "unit_price": 1, "name": 1},
    )
    if row:
        return row
    item = {
        "id": "TEST_M_" + uuid.uuid4().hex,
        "tenant_id": aqua["id"],
        "name": f"TEST_M_Item_{uuid.uuid4().hex[:5]}",
        "category": "Repair",
        "unit": "each",
        "unit_price": 42.0,
        "taxable": False,
        "active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    await db.items.insert_one(item)
    return item


# ═══════════════════════════════════════════════════════════════════════
# M1 · GET /api/workstream/jobs — auth + scoping
# ═══════════════════════════════════════════════════════════════════════
def test_m1_customer_forbidden(customer_headers):
    r = requests.get(f"{API}/workstream/jobs", headers=customer_headers, timeout=15)
    assert r.status_code == 403, r.text


def test_m1_admin_lists_jobs(admin_headers):
    r = requests.get(f"{API}/workstream/jobs?limit=5", headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "jobs" in body and isinstance(body["jobs"], list)
    assert body["sort"] == "newest"
    assert body["limit"] == 5
    # Every row exposes the M3 media summary shape.
    for j in body["jobs"]:
        assert "media" in j
        for k in ("photos_count", "videos_count", "photo_thumbs",
                    "video_thumbs", "extra_count"):
            assert k in j["media"], k


def test_m1_tech_auto_scoped(tech_headers):
    """Tech only sees their own jobs; a foreign tech_id filter is silently
    ignored (does NOT leak other techs' work)."""
    tid = _run(_get_mike_tech_id())
    r = requests.get(
        f"{API}/workstream/jobs?limit=200&tech_id=SOME_OTHER_TECH",
        headers=tech_headers, timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    tids = {j.get("technician_id") for j in body["jobs"]}
    assert tids == {tid} or tids == set(), tids
    # filters payload for a tech never echoes back a tech_id override.
    assert body["filters"]["tech_id"] is None


def test_m1_tech_never_sees_pricing(tech_headers):
    r = requests.get(f"{API}/workstream/jobs?limit=50", headers=tech_headers, timeout=15)
    assert r.status_code == 200
    payload = r.text
    for banned in (
        "\"job_totals\"", "\"unit_price\"", "\"subtotal\"",
        "\"tax_rate\"", "\"cost\"", "\"labor_cost\"",
        "\"materials_cost\"", "\"gross_margin\"",
        "\"invoice_total\"", "\"quote_total\"", "\"revenue\"",
    ):
        assert banned not in payload, f"pricing leak for tech: {banned}"


def test_m1_admin_filter_by_tech(admin_headers):
    tid = _run(_get_mike_tech_id())
    r = requests.get(
        f"{API}/workstream/jobs?limit=200&tech_id={tid}",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filters"]["tech_id"] == tid
    for j in body["jobs"]:
        assert j.get("technician_id") == tid


def test_m1_sort_options(admin_headers):
    """All six sort options + default parse and return without error."""
    for opt in ("newest", "oldest", "tech_asc", "tech_desc",
                "customer_asc", "customer_desc"):
        r = requests.get(f"{API}/workstream/jobs?limit=5&sort={opt}",
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"{opt}: {r.text}"
        body = r.json()
        assert body["sort"] == opt
    r = requests.get(f"{API}/workstream/jobs?limit=5&sort=nonsense",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 400, r.text


def test_m1_sort_customer_asc_orders_correctly(admin_headers):
    r = requests.get(f"{API}/workstream/jobs?limit=20&sort=customer_asc",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200
    names = [(j.get("customer_name") or "").lower() for j in r.json()["jobs"]]
    assert names == sorted(names), names


def test_m1_since_until_filters(admin_headers):
    """The since filter clips to a small window; response echoes filters."""
    r = requests.get(
        f"{API}/workstream/jobs?limit=50&since=2099-01-01",
        headers=admin_headers, timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["filters"]["since"] == "2099-01-01"
    # No jobs scheduled in year 2099+.
    assert body["jobs"] == []


# ═══════════════════════════════════════════════════════════════════════
# M5 · GET /api/jobs/{jid}/detail — 7 sections + RBAC
# ═══════════════════════════════════════════════════════════════════════
_REQUIRED_SECTIONS = (
    "header", "media", "line_items", "notes",
    "checklist", "forms", "timeline",
)


def test_m5_admin_returns_all_seven_sections(admin_headers):
    jid = _run(_get_mike_job_id())
    assert jid, "need a tech-assigned job for the fixture"
    r = requests.get(f"{API}/jobs/{jid}/detail",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    for section in _REQUIRED_SECTIONS:
        assert section in body, section
    # Header carries the joined customer/technician/property.
    assert body["header"]["id"] == jid
    for k in ("photos_count", "videos_count", "photos_remaining",
                "videos_remaining", "photo_limit", "video_limit"):
        assert k in body["media"], k
    assert body["media"]["photo_limit"] == 10
    assert body["media"]["video_limit"] == 3
    # Admin-only fields.
    assert "job_totals" in body["line_items"]
    assert "internal_notes" in body["notes"]


def test_m5_tech_never_sees_pricing_or_internal_notes(tech_headers):
    jid = _run(_get_mike_job_id())
    r = requests.get(f"{API}/jobs/{jid}/detail",
                      headers=tech_headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    # No pricing anywhere in the payload.
    payload = r.text
    for banned in (
        "\"job_totals\"", "\"unit_price\"", "\"subtotal\"",
        "\"tax_rate\"", "\"cost\"", "\"labor_cost\"",
        "\"materials_cost\"", "\"gross_margin\"",
        "\"invoice_total\"", "\"quote_total\"", "\"revenue\"",
    ):
        assert banned not in payload, f"tech pricing leak: {banned}"
    # internal_notes is admin-only.
    assert "internal_notes" not in body["notes"]
    # But the operational notes (customer_note/account_notes/service_note)
    # are still surfaced to tech so they can service the job.
    for k in ("customer_note", "account_notes", "service_note"):
        assert k in body["notes"], k


def test_m5_tech_line_item_projection_after_add(admin_headers, tech_headers):
    """When a line item exists on the job, tech's detail response still
    strips every pricing field on every embedded item."""
    jid = _run(_get_mike_job_id())
    pb = _run(_get_a_pricebook_item())
    # Ensure clean state then add one line as admin so pricing is present in DB.
    async def _reset():
        await _db().jobs.update_one(
            {"id": jid}, {"$set": {"line_items": [], "job_totals": None}},
        )
    _run(_reset())
    r = requests.post(f"{API}/jobs/{jid}/line-items", headers=admin_headers,
                       json={"pricebook_item_id": pb["id"], "quantity": 3},
                       timeout=15)
    assert r.status_code == 201, r.text

    r = requests.get(f"{API}/jobs/{jid}/detail",
                      headers=tech_headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    items = body["line_items"]["items"]
    assert items, "tech should still see the line item row itself"
    for li in items:
        for k in ("unit_price", "subtotal", "tax_rate", "cost"):
            assert k not in li, f"tech leak: {k}"

    r = requests.get(f"{API}/jobs/{jid}/detail",
                      headers=admin_headers, timeout=15)
    body = r.json()
    admin_items = body["line_items"]["items"]
    assert any("unit_price" in li for li in admin_items)
    assert body["line_items"]["job_totals"] is not None
    assert body["line_items"]["job_totals"]["subtotal"] > 0


def test_m5_customer_forbidden(customer_headers):
    """Job detail is a staff-only surface."""
    # Pick any job id — auth check runs before load.
    jid = _run(_get_mike_job_id())
    r = requests.get(f"{API}/jobs/{jid}/detail",
                      headers=customer_headers, timeout=15)
    assert r.status_code == 403, r.text


def test_m5_tech_isolation_returns_403_for_other_techs_job(tech_headers):
    """Tech cannot view a job assigned to a different tech."""
    # Find a job in the same tenant NOT assigned to Mike.
    async def _find_other():
        tid = await _get_mike_tech_id()
        tenant_id = await _get_tenant_id()
        return await _db().jobs.find_one(
            {"tenant_id": tenant_id,
             "technician_id": {"$exists": True, "$nin": [None, tid]}},
            {"_id": 0, "id": 1},
        )
    other = _run(_find_other())
    if not other:
        pytest.skip("no non-Mike tech job in fixture tenant")
    r = requests.get(f"{API}/jobs/{other['id']}/detail",
                      headers=tech_headers, timeout=15)
    assert r.status_code == 403, r.text


def test_m5_missing_job_404(admin_headers):
    r = requests.get(f"{API}/jobs/does-not-exist-xyz/detail",
                      headers=admin_headers, timeout=15)
    assert r.status_code == 404, r.text
