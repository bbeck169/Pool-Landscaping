"""Feb-2026 · Slice K1 + K2 backend tests.
* K1 · videos on jobs: cap enforcement + delete RBAC.
* K2 · line items: role-based projection, cross-tenant isolation,
  unlimited items, RBAC on edit/delete.
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


def _rebind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.job_media_line_items as _jmli
    _jmli.db = fresh_db
    return fresh_db


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    _rebind_db()
    yield
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        fresh = AsyncIOMotorClient(os.environ["MONGO_URL"])
        fresh_db = fresh[os.environ["DB_NAME"]]
        import config as _cfg
        _cfg.db = fresh_db
        import routers.job_media_line_items as _jmli
        _jmli.db = fresh_db
    except Exception:
        pass


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


async def _get_a_tech_job(tech_id_hint="mike"):
    """Find a job assigned to Mike so tech-scoped tests work."""
    db = _db()
    tech = await db.users.find_one({"email": "mike@aquaterra.com"},
                                     {"_id": 0, "id": 1, "tenant_id": 1,
                                      "technician_id": 1})
    aqua = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    tenant_id = aqua["id"]
    tech_id = tech.get("technician_id") or tech.get("id")
    j = await db.jobs.find_one({"tenant_id": tenant_id,
                                  "technician_id": tech_id},
                                {"_id": 0, "id": 1})
    return j["id"] if j else None


async def _get_a_pricebook_item():
    db = _db()
    aqua = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
    row = await db.items.find_one(
        {"$or": [{"tenant_id": aqua["id"]}, {"tenant_id": {"$exists": False}}],
         "active": {"$ne": False}},
        {"_id": 0, "id": 1, "unit_price": 1, "name": 1},
    )
    if row:
        return row
    # Seed one if the catalogue is empty.
    item = {
        "id": "TEST_K2_" + uuid.uuid4().hex,
        "tenant_id": aqua["id"],
        "name": f"TEST_K2_Item_{uuid.uuid4().hex[:5]}",
        "category": "Repair",
        "unit": "each",
        "unit_price": 75.00,
        "taxable": True,
        "active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    await db.items.insert_one(item)
    return item


# ═══════════════════════════════════════════════════════════════════════
# K1 — videos on jobs (multipart via routers/media_uploads.py).
# The video endpoints existed pre-Slice-K1 as part of Phase 5A;
# Slice K1 tightened the cap 10→3 and added tech-own-delete RBAC.
# ═══════════════════════════════════════════════════════════════════════
def _fake_mp4(size_bytes=1024):
    # Minimal MP4 signature bytes for content-sniffing checks.
    return b"\x00\x00\x00\x20ftypmp42" + b"\x00" * max(0, size_bytes - 12)


def _upload_video(headers, jid, uploader_hint="X"):
    files = {"file": (f"TEST_K1_{uploader_hint}.mp4", _fake_mp4(),
                       "video/mp4")}
    data = {"caption": f"TEST_K1_{uploader_hint}", "visibility": "internal"}
    return requests.post(
        f"{API}/jobs/{jid}/videos",
        headers=headers,
        files=files, data=data,
        timeout=30,
    )


def test_k1_video_cap_is_three(admin_headers, tech_headers):
    jid = _run(_get_a_tech_job())
    assert jid, "need a tech-assigned job"

    async def _wipe():
        db = _db()
        await db.jobs.update_one({"id": jid}, {"$set": {"videos": []}})
    _run(_wipe())

    successes = 0
    for i in range(3):
        r = _upload_video(tech_headers, jid, f"tech-{i}")
        if r.status_code in (200, 201):
            successes += 1
        else:
            break
    assert successes == 3, f"expected 3 successful uploads, got {successes}"

    # 4th → 400/409/413 with cap error (per media_uploads.py detail shape).
    r = _upload_video(tech_headers, jid, "tech-4")
    assert r.status_code in (400, 409, 413), r.text
    assert "video" in r.text.lower() and (
        "cap" in r.text.lower()
        or "limit" in r.text.lower()
        or "maximum" in r.text.lower()
    ), r.text


def test_k1_video_delete_rbac(admin_headers, tech_headers):
    """Slice K1 RBAC: tech deletes only their own; admin deletes any."""
    jid = _run(_get_a_tech_job())

    async def _wipe():
        db = _db()
        await db.jobs.update_one({"id": jid}, {"$set": {"videos": []}})
    _run(_wipe())

    r_admin = _upload_video(admin_headers, jid, "admin")
    assert r_admin.status_code in (200, 201), r_admin.text
    admin_vid = r_admin.json().get("id") or r_admin.json().get("video", {}).get("id")

    r_tech = _upload_video(tech_headers, jid, "tech")
    tech_vid = r_tech.json().get("id") or r_tech.json().get("video", {}).get("id")

    # Tech deleting admin's → 403.
    if admin_vid:
        r = requests.delete(f"{API}/jobs/{jid}/videos/{admin_vid}",
                             headers=tech_headers, timeout=15)
        assert r.status_code == 403, r.text

    # Tech deleting own → 200.
    if tech_vid:
        r = requests.delete(f"{API}/jobs/{jid}/videos/{tech_vid}",
                             headers=tech_headers, timeout=15)
        assert r.status_code == 200, r.text

    # Admin deleting anyone → 200.
    if admin_vid:
        r = requests.delete(f"{API}/jobs/{jid}/videos/{admin_vid}",
                             headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text


def test_k1_video_customer_forbidden(customer_headers):
    jid = _run(_get_a_tech_job())
    r = _upload_video(customer_headers, jid, "cust")
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════
# K2 — line items with tech-hidden pricing
# ═══════════════════════════════════════════════════════════════════════
def test_k2_pricebook_projection_tech_hides_pricing(admin_headers, tech_headers):
    _run(_get_a_pricebook_item())
    r_admin = requests.get(f"{API}/pricebook-items", headers=admin_headers, timeout=15)
    assert r_admin.status_code == 200
    admin_rows = r_admin.json()["items"]
    assert admin_rows, "pricebook must have items"
    assert any("unit_price" in r for r in admin_rows)

    r_tech = requests.get(f"{API}/pricebook-items", headers=tech_headers, timeout=15)
    assert r_tech.status_code == 200
    tech_rows = r_tech.json()["items"]
    for r in tech_rows:
        assert "unit_price" not in r, r
        assert "cost" not in r, r
        assert "tax_rate" not in r, r


def test_k2_line_item_add_and_projection(admin_headers, tech_headers):
    jid = _run(_get_a_tech_job())
    pb = _run(_get_a_pricebook_item())

    async def _wipe():
        db = _db()
        await db.jobs.update_one({"id": jid},
                                  {"$set": {"line_items": [], "job_totals": None}})
    _run(_wipe())

    # Tech adds a line — succeeds. Response is stripped of pricing.
    r = requests.post(f"{API}/jobs/{jid}/line-items", headers=tech_headers,
                       json={"pricebook_item_id": pb["id"], "quantity": 2},
                       timeout=15)
    assert r.status_code == 201, r.text
    li_tech = r.json()
    assert "unit_price" not in li_tech
    assert "subtotal" not in li_tech

    # Admin GET → full payload with pricing + totals.
    r = requests.get(f"{API}/jobs/{jid}/line-items",
                      headers=admin_headers, timeout=15)
    body = r.json()
    assert "job_totals" in body
    assert body["line_items"], body
    assert "unit_price" in body["line_items"][0]
    assert body["job_totals"]["subtotal"] > 0

    # Tech GET → stripped, no job_totals.
    r = requests.get(f"{API}/jobs/{jid}/line-items",
                      headers=tech_headers, timeout=15)
    body = r.json()
    assert "job_totals" not in body
    for li in body["line_items"]:
        assert "unit_price" not in li
        assert "subtotal" not in li


def test_k2_line_item_edit_rbac(admin_headers, tech_headers):
    jid = _run(_get_a_tech_job())
    pb = _run(_get_a_pricebook_item())

    async def _wipe():
        db = _db()
        await db.jobs.update_one({"id": jid}, {"$set": {"line_items": []}})
    _run(_wipe())

    # Admin adds a line.
    r = requests.post(f"{API}/jobs/{jid}/line-items", headers=admin_headers,
                       json={"pricebook_item_id": pb["id"], "quantity": 1},
                       timeout=15)
    admin_lid = r.json()["id"]

    # Tech tries to edit admin's line → 403.
    r = requests.patch(f"{API}/jobs/{jid}/line-items/{admin_lid}",
                        headers=tech_headers, json={"quantity": 99},
                        timeout=15)
    assert r.status_code == 403

    # Admin can edit their own.
    r = requests.patch(f"{API}/jobs/{jid}/line-items/{admin_lid}",
                        headers=admin_headers, json={"quantity": 3},
                        timeout=15)
    assert r.status_code == 200
    assert abs(float(r.json()["quantity"]) - 3.0) < 1e-6

    # Tech tries to delete admin's line → 403.
    r = requests.delete(f"{API}/jobs/{jid}/line-items/{admin_lid}",
                         headers=tech_headers, timeout=15)
    assert r.status_code == 403


def test_k2_unlimited_line_items(admin_headers):
    jid = _run(_get_a_tech_job())
    pb = _run(_get_a_pricebook_item())

    async def _wipe():
        db = _db()
        await db.jobs.update_one({"id": jid}, {"$set": {"line_items": []}})
    _run(_wipe())

    for _ in range(50):
        r = requests.post(f"{API}/jobs/{jid}/line-items", headers=admin_headers,
                           json={"pricebook_item_id": pb["id"], "quantity": 1},
                           timeout=15)
        assert r.status_code == 201, r.text

    r = requests.get(f"{API}/jobs/{jid}/line-items",
                      headers=admin_headers, timeout=15)
    assert len(r.json()["line_items"]) == 50


def test_k2_cross_tenant_pricebook_isolation(tech_headers):
    """Tech in aquaterra cannot add a pricebook item from a foreign
    tenant to their job. 404 is the correct response (no signal
    about existence)."""
    jid = _run(_get_a_tech_job())
    # Insert a foreign-tenant pricebook item.
    foreign_id = "TEST_K2_FOREIGN_" + uuid.uuid4().hex

    async def _seed_foreign():
        db = _db()
        await db.items.insert_one({
            "id": foreign_id, "tenant_id": "foreign_tenant_id",
            "name": "TEST_K2_ForeignItem", "unit_price": 500.00,
            "active": True, "created_at": "2026-01-01T00:00:00+00:00",
        })
    _run(_seed_foreign())

    r = requests.post(f"{API}/jobs/{jid}/line-items",
                       headers=tech_headers,
                       json={"pricebook_item_id": foreign_id, "quantity": 1},
                       timeout=15)
    assert r.status_code == 404, r.text


def test_k2_customer_forbidden(customer_headers):
    jid = _run(_get_a_tech_job())
    r = requests.get(f"{API}/jobs/{jid}/line-items",
                      headers=customer_headers, timeout=15)
    assert r.status_code in (401, 403)
    r = requests.get(f"{API}/pricebook-items",
                      headers=customer_headers, timeout=15)
    assert r.status_code in (401, 403)
