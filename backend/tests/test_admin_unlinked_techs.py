"""Feb 2026 · Sprint 2 · Section A — Admin "Unlinked Technicians" tests.

Covers ``GET /api/admin/technicians/unlinked`` + ``POST /api/admin/
technicians/{tech_id}/create-user``:

* GET returns only techs with ``user_id: null`` for the caller's tenant.
* GET as tech role → 403.
* POST creates + links + audit; second POST → 409 ``already_linked``.
* POST with duplicate email in the tenant → 409 ``email_already_in_use``
  with existing user_id.
* POST for a tech doc missing an email → 400 ``email_required``.
* Response ``temporary_password`` is 12 chars.
* Tenant isolation — a tech in a DIFFERENT tenant is 404 from the
  caller's perspective (even though the id string is valid).

Test infra
----------
Follows the ``httpx.ASGITransport`` + async pattern used by
``test_work_class.py`` — an isolated tenant is seeded per module,
then torn down. No hits against the real seed tenants so parallel
runs stay clean.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest
from httpx import ASGITransport, AsyncClient

from server import app
from config import db


TEST_TENANT_ID = "test-tenant-unlinked-techs"
TEST_TENANT_ID_OTHER = "test-tenant-unlinked-techs-b"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _seed() -> Dict[str, Any]:
    from utils import create_token, hash_password

    # Idempotent clean of any residue from prior runs.
    for coll in ("users", "technicians", "tenants", "audit_log"):
        await db[coll].delete_many({"tenant_id": {"$in": [
            TEST_TENANT_ID, TEST_TENANT_ID_OTHER,
        ]}})

    for tid in (TEST_TENANT_ID, TEST_TENANT_ID_OTHER):
        await db.tenants.insert_one({
            "id": tid, "name": f"Unlinked Techs Test Co ({tid})",
            "slug": tid, "active": True, "settings": {},
        })

    admin = {
        "id":            "u-unl-admin",
        "tenant_id":     TEST_TENANT_ID,
        "email":         "unl-admin@test.co",
        "password_hash": hash_password("x"),
        "role":          "admin",
        "name":          "Unlinked Admin",
        "deleted_at":    None,
    }
    plain_tech = {
        "id":            "u-unl-tech",
        "tenant_id":     TEST_TENANT_ID,
        "email":         "unl-tech-user@test.co",
        "password_hash": hash_password("x"),
        "role":          "technician",
        "name":          "Unlinked Existing Tech",
        "deleted_at":    None,
    }
    # A DIFFERENT tenant's admin — proves tenant isolation on GET/POST.
    other_admin = {
        "id":            "u-unl-admin-b",
        "tenant_id":     TEST_TENANT_ID_OTHER,
        "email":         "unl-admin-b@test.co",
        "password_hash": hash_password("x"),
        "role":          "admin",
        "name":          "Unlinked Admin (Other)",
        "deleted_at":    None,
    }
    await db.users.insert_many([admin, plain_tech, other_admin])

    # Seed technicians:
    # * ``t-unl-linked``  — already linked (user_id set) — MUST NOT
    #   appear in the GET response.
    # * ``t-unl-solo``    — unlinked, has an email, unique.
    # * ``t-unl-dup``     — unlinked, email COLLIDES with the
    #   ``plain_tech`` user row above → POST should 409.
    # * ``t-unl-noemail`` — unlinked, no email → POST should 400.
    # * ``t-unl-other``   — belongs to the OTHER tenant → hidden.
    await db.technicians.insert_many([
        {"id": "t-unl-linked",  "tenant_id": TEST_TENANT_ID,
         "name": "Linked Alice",  "email": "alice@test.co",
         "user_id": "u-unl-tech", "created_at": "2026-02-01T00:00:00Z"},
        {"id": "t-unl-solo",    "tenant_id": TEST_TENANT_ID,
         "name": "Sara Nguyen",   "email": "sara@test.co",
         "phone": "+16025550137", "user_id": None,
         "created_at": "2026-02-05T00:00:00Z"},
        {"id": "t-unl-dup",     "tenant_id": TEST_TENANT_ID,
         "name": "Duplicate Dan", "email": "unl-tech-user@test.co",
         "user_id": None,        "created_at": "2026-02-06T00:00:00Z"},
        {"id": "t-unl-noemail", "tenant_id": TEST_TENANT_ID,
         "name": "No Mail Mel",   "email": "",
         "user_id": None,        "created_at": "2026-02-07T00:00:00Z"},
        {"id": "t-unl-other",   "tenant_id": TEST_TENANT_ID_OTHER,
         "name": "Cross-tenant Carl", "email": "carl@test.co",
         "user_id": None,        "created_at": "2026-02-08T00:00:00Z"},
    ])

    return {
        "tenant_id":         TEST_TENANT_ID,
        "tenant_id_other":   TEST_TENANT_ID_OTHER,
        "admin_token":       create_token(admin),
        "tech_token":        create_token(plain_tech),
        "other_admin_token": create_token(other_admin),
    }


async def _teardown() -> None:
    for coll in ("users", "technicians", "tenants", "audit_log"):
        await db[coll].delete_many({"tenant_id": {"$in": [
            TEST_TENANT_ID, TEST_TENANT_ID_OTHER,
        ]}})
    # Also purge the users this suite creates (email lives on a
    # different tenant filter for the create-user endpoint).
    await db.users.delete_many({"tenant_id": {"$in": [
        TEST_TENANT_ID, TEST_TENANT_ID_OTHER,
    ]}})


@pytest.fixture(scope="module")
def seeded():
    ctx = _run(_seed())
    yield ctx
    _run(_teardown())


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _hdr(seeded, key="admin_token"):
    return {"Authorization": f"Bearer {seeded[key]}"}


# ══════════════════════════════════════════════════════════════════
# GET /api/admin/technicians/unlinked
# ══════════════════════════════════════════════════════════════════
class TestListUnlinked:
    def test_returns_only_unlinked_for_caller_tenant(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.get("/api/admin/technicians/unlinked",
                                 headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                body = r.json()
                tech_ids = {t["tech_id"] for t in body["technicians"]}
                assert "t-unl-solo" in tech_ids
                assert "t-unl-dup" in tech_ids
                assert "t-unl-noemail" in tech_ids
                # Linked tech + cross-tenant tech MUST NOT appear.
                assert "t-unl-linked" not in tech_ids
                assert "t-unl-other" not in tech_ids
                assert body["count"] == len(body["technicians"])
        _run(go())

    def test_response_shape(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.get("/api/admin/technicians/unlinked",
                                 headers=_hdr(seeded))
                body = r.json()
                sara = next(t for t in body["technicians"]
                            if t["tech_id"] == "t-unl-solo")
                assert set(sara.keys()) == {
                    "tech_id", "name", "email", "phone",
                    "created_at", "tenant_id",
                }
                assert sara["name"] == "Sara Nguyen"
                assert sara["email"] == "sara@test.co"
                assert sara["tenant_id"] == seeded["tenant_id"]
        _run(go())

    def test_tech_role_403(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.get("/api/admin/technicians/unlinked",
                                 headers=_hdr(seeded, "tech_token"))
                assert r.status_code == 403
        _run(go())

    def test_unauthenticated_401(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.get("/api/admin/technicians/unlinked")
                assert r.status_code == 401
        _run(go())

    def test_tenant_isolation(self, seeded, client):
        """Other-tenant admin sees ONLY their own tenant's unlinked tech."""
        async def go():
            async with client as c:
                r = await c.get("/api/admin/technicians/unlinked",
                                 headers=_hdr(seeded, "other_admin_token"))
                assert r.status_code == 200
                body = r.json()
                ids = {t["tech_id"] for t in body["technicians"]}
                assert ids == {"t-unl-other"}
        _run(go())


# ══════════════════════════════════════════════════════════════════
# POST /api/admin/technicians/{tech_id}/create-user
# ══════════════════════════════════════════════════════════════════
class TestCreateUserForUnlinked:
    def test_happy_path_creates_links_and_audits(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post(
                    "/api/admin/technicians/t-unl-solo/create-user",
                    headers=_hdr(seeded),
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["ok"] is True
                assert body["email"] == "sara@test.co"
                assert body["user_id"]
                assert isinstance(body["temporary_password"], str)
                assert len(body["temporary_password"]) == 12
                # New user doc exists + is linked.
                new_user = await db.users.find_one(
                    {"id": body["user_id"]}, {"_id": 0})
                assert new_user is not None
                assert new_user["role"] == "technician"
                assert new_user["email"] == "sara@test.co"
                assert new_user["tenant_id"] == seeded["tenant_id"]
                assert new_user["must_reset_password"] is True
                assert new_user["invited_at"]
                # Technician doc is now linked.
                tech = await db.technicians.find_one(
                    {"id": "t-unl-solo"}, {"_id": 0})
                assert tech["user_id"] == body["user_id"]
                assert tech["linked_at"]
                # Audit log written.
                audit = await db.audit_log.find_one({
                    "action": "technician_user_created_and_linked",
                    "target_tech_id": "t-unl-solo",
                }, {"_id": 0})
                assert audit is not None
                assert audit["target_user_id"] == body["user_id"]
        _run(go())

    def test_second_post_returns_already_linked(self, seeded, client):
        async def go():
            # First one links (from the previous test class or a re-run) —
            # ensure the tech has a user_id, then try again.
            await db.technicians.update_one(
                {"id": "t-unl-solo"},
                {"$set": {"user_id": "u-unl-solo-existing"}},
            )
            async with client as c:
                r = await c.post(
                    "/api/admin/technicians/t-unl-solo/create-user",
                    headers=_hdr(seeded),
                )
                assert r.status_code == 409
                body = r.json()
                # FastAPI wraps HTTPException(dict, ...) into {detail: dict}
                detail = body.get("detail") or body
                assert detail["code"] == "already_linked"
                assert detail["user_id"] == "u-unl-solo-existing"
        _run(go())

    def test_duplicate_email_returns_409_with_existing_user_id(
            self, seeded, client):
        async def go():
            # Ensure t-unl-dup is still unlinked at test start.
            await db.technicians.update_one(
                {"id": "t-unl-dup"},
                {"$set": {"user_id": None}},
            )
            async with client as c:
                r = await c.post(
                    "/api/admin/technicians/t-unl-dup/create-user",
                    headers=_hdr(seeded),
                )
                assert r.status_code == 409
                body = r.json()
                detail = body.get("detail") or body
                assert detail["code"] == "email_already_in_use"
                # Existing user id belongs to the plain_tech seed.
                assert detail["user_id"] == "u-unl-tech"
        _run(go())

    def test_missing_email_returns_400(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post(
                    "/api/admin/technicians/t-unl-noemail/create-user",
                    headers=_hdr(seeded),
                )
                assert r.status_code == 400
                body = r.json()
                detail = body.get("detail") or body
                assert detail["code"] == "email_required"
        _run(go())

    def test_unknown_tech_id_returns_404(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post(
                    "/api/admin/technicians/does-not-exist/create-user",
                    headers=_hdr(seeded),
                )
                assert r.status_code == 404
        _run(go())

    def test_cross_tenant_tech_is_404(self, seeded, client):
        """Caller's tenant scoping means an id in another tenant → 404."""
        async def go():
            async with client as c:
                r = await c.post(
                    "/api/admin/technicians/t-unl-other/create-user",
                    headers=_hdr(seeded),
                )
                assert r.status_code == 404
        _run(go())

    def test_tech_role_403_on_post(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post(
                    "/api/admin/technicians/t-unl-noemail/create-user",
                    headers=_hdr(seeded, "tech_token"),
                )
                assert r.status_code == 403
        _run(go())
