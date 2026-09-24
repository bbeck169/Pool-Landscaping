"""Task D · Feb-2026 — Employee Benefits pytest coverage.

Contract pinning for ``backend/routers/benefits.py``. Same
structural pattern as ``test_p58_patch_item_tenant_isolation.py``
(tenant isolation via a foreign-tenant seed) plus role-gate
assertions for POST/PATCH/DELETE against a technician account.

Cases covered:
  * GET seed-on-first-hit + idempotency (second GET does NOT
    re-seed).
  * GET tenant isolation (tenant A GET returns only tenant A rows).
  * POST admin creates → GET reflects.
  * POST as technician → 403.
  * PATCH admin updates → GET reflects; audit_log row stamped.
  * PATCH cross-tenant → 404.
  * PATCH as technician → 403.
  * DELETE admin → row disappears; audit_log stamped.
  * DELETE cross-tenant → 404.
  * DELETE as technician → 403.
  * Seed idempotency after delete (delete seed → GET returns [];
    ``count_documents({tenant_id})`` still returns >= 1).
  * Icon allowlist rejection on POST + PATCH.
  * external_url scheme rejection (javascript:, data:, file:).
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

import pytest

from tests._phase34_http_shim import http
from tests._phase34_asyncio import batch_safe_run as _run


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = http.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    from config import db as _db  # noqa: PLC0415
    return _db


@pytest.fixture(scope="module")
def aq_tenant_id(db) -> str:
    async def _go():
        t = await db.tenants.find_one(
            {"slug": "aquaterra"}, {"_id": 0, "id": 1},
        )
        return t["id"]
    return _run(_go())


@pytest.fixture(scope="module")
def super_headers() -> dict:
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}",
             "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def tech_headers() -> dict:
    return {"Authorization": f"Bearer {_login('mike@aquaterra.com')}",
             "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def foreign_tenant_id(db) -> Optional[str]:
    async def _go():
        aq = await db.tenants.find_one(
            {"slug": "aquaterra"}, {"_id": 0, "id": 1},
        )
        aq_id = aq["id"] if aq else None
        other = await db.tenants.find_one(
            {"id": {"$ne": aq_id}}, {"_id": 0, "id": 1},
        )
        return other["id"] if other else None
    return _run(_go())


@pytest.fixture
def _cleanup(db, aq_tenant_id):
    """Delete every non-Perks-at-Work row planted during a test to
    keep the preview seed tidy across runs. The seeded row itself
    is preserved so idempotency assertions stay honest."""
    yield
    async def _go():
        await db.benefits.delete_many({
            "tenant_id": aq_tenant_id,
            "title": {"$ne": "Perks at Work"},
        })
    _run(_go())


def test_get_seeds_perks_at_work_on_first_hit(db, super_headers, aq_tenant_id):
    r = http.get(f"{API}/benefits", headers=super_headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    titles = [b["title"] for b in body["items"]]
    assert "Perks at Work" in titles, titles

    seeded = next(b for b in body["items"] if b["title"] == "Perks at Work")
    assert seeded["icon"] == "gift"
    assert seeded["external_url"] == "https://www.perksatwork.com/login"
    assert seeded["tenant_id"] == aq_tenant_id
    assert seeded["deleted_at"] is None


def test_get_is_idempotent(super_headers, db, aq_tenant_id):
    """Second GET returns the same rows — no re-seed."""
    async def _count():
        return await db.benefits.count_documents({"tenant_id": aq_tenant_id})
    before = _run(_count())
    r = http.get(f"{API}/benefits", headers=super_headers, timeout=30)
    assert r.status_code == 200
    after = _run(_count())
    assert after == before, f"GET re-seeded: {before} -> {after}"


def test_get_tenant_isolation(db, super_headers, aq_tenant_id,
                                 foreign_tenant_id):
    """Tenant A's GET must NOT return tenant B's rows."""
    if not foreign_tenant_id:
        pytest.skip("preview seed has only one tenant")
    foreign_id = uuid.uuid4().hex

    async def _plant():
        await db.benefits.insert_one({
            "id": foreign_id,
            "tenant_id": foreign_tenant_id,
            "title": f"Foreign Perk {foreign_id[:6]}",
            "description": "",
            "external_url": "https://example.com/foreign",
            "icon": "shield",
            "is_active": True,
            "sort_order": 0,
            "deleted_at": None,
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        })
    _run(_plant())
    try:
        r = http.get(f"{API}/benefits", headers=super_headers, timeout=30)
        assert r.status_code == 200
        ids = {b["id"] for b in r.json()["items"]}
        assert foreign_id not in ids
    finally:
        async def _cleanup():
            await db.benefits.delete_one({"id": foreign_id})
        _run(_cleanup())


def test_post_admin_creates(super_headers, _cleanup):
    payload = {
        "title": "P58 Test Benefit",
        "description": "Sample created by pytest.",
        "external_url": "https://example.com/perk",
        "icon": "heart",
        "is_active": True,
        "sort_order": 5,
    }
    r = http.post(f"{API}/benefits", headers=super_headers,
                     json=payload, timeout=30)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "P58 Test Benefit"
    assert body["icon"] == "heart"
    assert body["tenant_id"], body

    # GET reflects the new row.
    r2 = http.get(f"{API}/benefits", headers=super_headers, timeout=30)
    assert body["id"] in {b["id"] for b in r2.json()["items"]}


def test_post_technician_is_forbidden(tech_headers):
    r = http.post(f"{API}/benefits", headers=tech_headers,
                     json={"title": "should-fail",
                             "description": "",
                             "external_url": "https://example.com/",
                             "icon": "gift"}, timeout=30)
    assert r.status_code == 403, r.text


def test_patch_admin_updates(db, super_headers, aq_tenant_id, _cleanup):
    r = http.post(f"{API}/benefits", headers=super_headers, json={
        "title": "Task D · patch", "description": "",
        "external_url": "https://example.com/x", "icon": "book",
    }, timeout=30)
    assert r.status_code == 201, r.text
    bid = r.json()["id"]

    r2 = http.patch(f"{API}/benefits/{bid}",
                       headers=super_headers,
                       json={"description": "updated"}, timeout=30)
    assert r2.status_code == 200
    assert r2.json()["description"] == "updated"

    async def _find_audit():
        return await db.audit_log.find_one({
            "action": "benefit.patch",
            "resource_id": bid,
            "tenant_id": aq_tenant_id,
        }, {"_id": 0, "tenant_id": 1, "resource_type": 1})
    audit = _run(_find_audit())
    assert audit is not None
    assert audit["tenant_id"] == aq_tenant_id
    assert audit["resource_type"] == "benefit"


def test_patch_cross_tenant_returns_404(db, super_headers,
                                             foreign_tenant_id):
    if not foreign_tenant_id:
        pytest.skip("preview seed has only one tenant")
    foreign_id = uuid.uuid4().hex

    async def _plant():
        await db.benefits.insert_one({
            "id": foreign_id, "tenant_id": foreign_tenant_id,
            "title": f"Cross {foreign_id[:6]}", "description": "",
            "external_url": "https://example.com/f",
            "icon": "shield", "is_active": True, "sort_order": 0,
            "deleted_at": None,
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        })
    _run(_plant())
    try:
        r = http.patch(f"{API}/benefits/{foreign_id}",
                          headers=super_headers,
                          json={"description": "PWNED"}, timeout=30)
        assert r.status_code == 404, r.text
        # Verify the foreign row was NOT mutated.
        async def _refetch():
            return await db.benefits.find_one({"id": foreign_id},
                                                 {"_id": 0, "description": 1})
        row = _run(_refetch())
        assert row["description"] == ""
    finally:
        async def _cleanup():
            await db.benefits.delete_one({"id": foreign_id})
        _run(_cleanup())


def test_patch_technician_is_forbidden(super_headers, tech_headers,
                                            _cleanup):
    r = http.post(f"{API}/benefits", headers=super_headers, json={
        "title": "Task D · patch-role", "description": "",
        "external_url": "https://example.com/y", "icon": "coffee",
    }, timeout=30)
    bid = r.json()["id"]
    r2 = http.patch(f"{API}/benefits/{bid}", headers=tech_headers,
                       json={"description": "x"}, timeout=30)
    assert r2.status_code == 403, r2.text


def test_delete_admin_removes_from_get(db, super_headers, aq_tenant_id,
                                            _cleanup):
    r = http.post(f"{API}/benefits", headers=super_headers, json={
        "title": "Task D · delete", "description": "",
        "external_url": "https://example.com/d", "icon": "briefcase",
    }, timeout=30)
    bid = r.json()["id"]

    d = http.delete(f"{API}/benefits/{bid}", headers=super_headers,
                       timeout=30)
    assert d.status_code == 200, d.text

    # Row disappears from GET (soft-delete respected).
    lst = http.get(f"{API}/benefits", headers=super_headers, timeout=30)
    assert bid not in {b["id"] for b in lst.json()["items"]}

    async def _find_audit():
        return await db.audit_log.find_one({
            "action": "benefit.delete", "resource_id": bid,
            "tenant_id": aq_tenant_id,
        }, {"_id": 0, "tenant_id": 1})
    audit = _run(_find_audit())
    assert audit is not None
    assert audit["tenant_id"] == aq_tenant_id


def test_delete_cross_tenant_returns_404(db, super_headers,
                                              foreign_tenant_id):
    if not foreign_tenant_id:
        pytest.skip("preview seed has only one tenant")
    foreign_id = uuid.uuid4().hex

    async def _plant():
        await db.benefits.insert_one({
            "id": foreign_id, "tenant_id": foreign_tenant_id,
            "title": f"Delete-cross {foreign_id[:6]}", "description": "",
            "external_url": "https://example.com/f",
            "icon": "shield", "is_active": True, "sort_order": 0,
            "deleted_at": None,
            "created_at": "2026-02-01T00:00:00Z",
            "updated_at": "2026-02-01T00:00:00Z",
        })
    _run(_plant())
    try:
        r = http.delete(f"{API}/benefits/{foreign_id}",
                           headers=super_headers, timeout=30)
        assert r.status_code == 404, r.text
        async def _still_there():
            return await db.benefits.find_one({"id": foreign_id},
                                                 {"_id": 0, "deleted_at": 1})
        row = _run(_still_there())
        assert row["deleted_at"] is None
    finally:
        async def _cleanup():
            await db.benefits.delete_one({"id": foreign_id})
        _run(_cleanup())


def test_delete_technician_is_forbidden(super_headers, tech_headers,
                                             _cleanup):
    r = http.post(f"{API}/benefits", headers=super_headers, json={
        "title": "Task D · delete-role", "description": "",
        "external_url": "https://example.com/z", "icon": "smile",
    }, timeout=30)
    bid = r.json()["id"]
    r2 = http.delete(f"{API}/benefits/{bid}", headers=tech_headers,
                        timeout=30)
    assert r2.status_code == 403, r2.text


def test_seed_idempotency_after_delete(db, super_headers, aq_tenant_id):
    """Delete the seeded Perks at Work row → GET must NOT
    re-create it, because the deleted row still counts toward the
    ``count_documents({tenant_id})`` gate. This is the primary
    contract that prevents 'delete-then-re-seed on next GET' bugs.
    """
    async def _seeded():
        return await db.benefits.find_one({
            "tenant_id": aq_tenant_id, "title": "Perks at Work",
        }, {"_id": 0, "id": 1, "deleted_at": 1})
    row = _run(_seeded())
    if not row:
        # Prime the seed if a prior test wiped it.
        http.get(f"{API}/benefits", headers=super_headers, timeout=30)
        row = _run(_seeded())
    assert row is not None
    bid = row["id"]

    # Soft-delete the seeded row (if it isn't already).
    if not row.get("deleted_at"):
        d = http.delete(f"{API}/benefits/{bid}",
                           headers=super_headers, timeout=30)
        assert d.status_code == 200

    # Follow-up GET must NOT re-seed.
    r = http.get(f"{API}/benefits", headers=super_headers, timeout=30)
    assert r.status_code == 200
    titles = [b["title"] for b in r.json()["items"]]
    assert "Perks at Work" not in titles

    # count_documents (with NO deleted_at filter) still >= 1 —
    # this is the gate that prevents the re-seed.
    async def _total():
        return await db.benefits.count_documents({"tenant_id": aq_tenant_id})
    total = _run(_total())
    assert total >= 1

    # Restore for downstream tests / preview cleanliness.
    async def _restore():
        await db.benefits.update_one(
            {"id": bid, "tenant_id": aq_tenant_id},
            {"$set": {"deleted_at": None}},
        )
    _run(_restore())


def test_icon_allowlist_rejects_unknown_on_post(super_headers):
    r = http.post(f"{API}/benefits", headers=super_headers, json={
        "title": "bad-icon", "description": "",
        "external_url": "https://example.com/",
        "icon": "not-in-allowlist",
    }, timeout=30)
    assert r.status_code == 422, r.text
    # pydantic surfaces the icon error in ``detail``.
    text = r.text.lower()
    assert "icon" in text and "must be one of" in text


def test_icon_allowlist_rejects_unknown_on_patch(super_headers, _cleanup):
    r = http.post(f"{API}/benefits", headers=super_headers, json={
        "title": "Task D · icon-patch", "description": "",
        "external_url": "https://example.com/", "icon": "gift",
    }, timeout=30)
    bid = r.json()["id"]
    r2 = http.patch(f"{API}/benefits/{bid}", headers=super_headers,
                       json={"icon": "made-up-icon"}, timeout=30)
    assert r2.status_code == 422, r2.text


@pytest.mark.parametrize("bad_url", [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://example.com/",
    "//example.com/relative",
    "example.com/no-scheme",
])
def test_external_url_scheme_rejection(super_headers, bad_url):
    r = http.post(f"{API}/benefits", headers=super_headers, json={
        "title": f"bad-{bad_url[:20]}", "description": "",
        "external_url": bad_url, "icon": "gift",
    }, timeout=30)
    assert r.status_code == 422, (bad_url, r.text)
