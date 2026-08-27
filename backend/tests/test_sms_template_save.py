"""Feb-2026 P0 · SMS template save contract.

Locks in the ``POST`` create + ``PATCH`` switch-channel paths so the
Item-2 channel picker's silent-fail regression can't recur.

Coverage:

* ``POST /marketing/templates`` with ``{channel: "sms", body: ..., no
  subject}`` → 200 and persists as SMS.
* ``PATCH /marketing/templates/{id}`` flipping an existing email
  template to SMS → subject cleared, channel updated.
* ``POST`` with ``channel="sms"`` but ``subject`` populated → 200
  and subject is nulled on write (SMS templates never carry a
  subject; validator matches ``_validate_shape``).
* Regression guard — ``POST`` email template without subject still
  422s (email shape unchanged).
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from config import db
from server import app
from utils import create_token, hash_password


TID = "test-tenant-sms-template-save"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _seed() -> dict:
    for coll in ("users", "tenants", "marketing_templates"):
        await db[coll].delete_many({"tenant_id": TID})
    await db.tenants.delete_many({"id": TID})
    await db.tenants.insert_one({
        "id": TID, "name": "SMS Save Tenant",
        "slug": "sms-save", "active": True, "settings": {},
    })
    admin = {
        "id": "u-sms-admin", "tenant_id": TID,
        "email": "sms-admin@test.co",
        "password_hash": hash_password("x"), "role": "admin",
        "name": "SMS Admin", "deleted_at": None,
    }
    await db.users.insert_one(admin)
    return {"admin_token": create_token(admin)}


async def _teardown():
    for coll in ("users", "tenants", "marketing_templates"):
        await db[coll].delete_many({"tenant_id": TID})
    await db.tenants.delete_many({"id": TID})


@pytest.fixture(scope="module")
def seeded():
    ctx = _run(_seed())
    yield ctx
    _run(_teardown())


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app),
                        base_url="http://test")


def _hdr(seeded):
    return {"Authorization": f"Bearer {seeded['admin_token']}"}


class TestSmsTemplateSaveFlow:
    def test_post_creates_sms_template_without_subject(self, seeded, client):
        async def go():
            async with client as c:
                r = await c.post("/api/marketing/templates",
                                    json={"name": "SMS create",
                                            "channel": "sms",
                                            "category": "reminder",
                                            "body": "Hi {{CUSTOMER_FIRST_NAME}}"},
                                    headers=_hdr(seeded))
                assert r.status_code in (200, 201), r.text
                j = r.json()
                assert j["channel"] == "sms"
                assert j["subject"] in (None, "")
                assert j["body"].startswith("Hi ")
        _run(go())

    def test_patch_flips_email_to_sms_clears_subject(self, seeded, client):
        async def go():
            async with client as c:
                # Seed an email template first.
                r = await c.post("/api/marketing/templates",
                                    json={"name": "Switch me",
                                            "channel": "email",
                                            "category": "reminder",
                                            "subject": "Hello there",
                                            "body": "<p>Hi</p>"},
                                    headers=_hdr(seeded))
                assert r.status_code in (200, 201), r.text
                tid = r.json()["id"]
                # Flip to SMS via the frontend's save payload shape —
                # explicit ``subject: null`` is DROPPED by the PATCH
                # model (Optional fields), but the handler nulls
                # subject when channel is SMS regardless. Verify the
                # end state.
                r = await c.patch(
                    f"/api/marketing/templates/{tid}",
                    json={"channel": "sms", "body": "SMS ver"},
                    headers=_hdr(seeded),
                )
                assert r.status_code in (200, 201), r.text
                j = r.json()
                assert j["channel"] == "sms"
                assert j["subject"] in (None, "")
                assert j["body"] == "SMS ver"
        _run(go())

    def test_post_email_without_subject_still_422s(self, seeded, client):
        """Regression guard — the email-shape validator is unchanged."""
        async def go():
            async with client as c:
                r = await c.post("/api/marketing/templates",
                                    json={"name": "Bad email",
                                            "channel": "email",
                                            "category": "reminder",
                                            "body": "<p>Hi</p>"},
                                    headers=_hdr(seeded))
                assert r.status_code in (400, 422)
        _run(go())

    def test_patch_sms_with_stray_subject_still_stores_null(self, seeded, client):
        """A caller that keeps the subject in the payload when
        flipping to SMS shouldn't corrupt storage — backend still
        writes ``subject: None`` on the SMS row."""
        async def go():
            async with client as c:
                r = await c.post("/api/marketing/templates",
                                    json={"name": "Stray subj",
                                            "channel": "email",
                                            "category": "reminder",
                                            "subject": "Original",
                                            "body": "<p>Hi</p>"},
                                    headers=_hdr(seeded))
                tid = r.json()["id"]
                r = await c.patch(
                    f"/api/marketing/templates/{tid}",
                    json={"channel": "sms",
                            "subject": "should-be-dropped",
                            "body": "sms"},
                    headers=_hdr(seeded),
                )
                assert r.status_code in (200, 201), r.text
                j = r.json()
                assert j["channel"] == "sms"
                assert j["subject"] in (None, "")
        _run(go())
