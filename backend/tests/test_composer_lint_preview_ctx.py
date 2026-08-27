"""Feb-2026 · Composer-linter false-positive fix.

Before the fix ``POST /api/marketing/templates/lint`` used
``build_ctx``, which only populates subscriber/tenant/unsub scopes.
Registered tags that read from ``ctx['customer']`` / ``ctx['referral']``
/ ``ctx['job']`` / ``ctx['invoice']`` — e.g. ``CUSTOMER_CREDIT_BALANCE``,
``REFERRAL_FRIEND_NAME``, ``REFERRAL_CREDIT_AMOUNT`` — resolved to
empty strings and got flagged as ``unresolved_tokens`` in the composer.

The fix wires a new ``build_preview_ctx`` helper into the lint endpoint
(and the campaign preview endpoint) that layers realistic-looking mock
scopes on top of the subscriber context. Send-time paths remain on
``build_ctx``.

Coverage:
* ``build_preview_ctx`` resolves the previously-broken tags to
  non-empty, obviously-fake values.
* The mock is scoped to the linter path only — ``build_ctx``'s output
  shape is UNCHANGED (grep-style: same keys, same values).
* The lint endpoint returns ``clean=True`` / no ``unresolved_tokens``
  for a body containing the previously-broken tags.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from config import db
from server import app
from services.marketing_campaigns import (
    build_ctx, build_preview_ctx, render_body,
)
from utils import create_token, hash_password


TID = "test-tenant-composer-lint"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _seed() -> dict:
    for coll in ("users", "tenants"):
        await db[coll].delete_many({"tenant_id": TID})
    await db.tenants.delete_many({"id": TID})
    await db.tenants.insert_one({
        "id": TID, "name": "Composer Lint Tenant",
        "slug": "cl-test", "active": True, "settings": {},
    })
    admin = {
        "id": "u-cl-admin", "tenant_id": TID, "email": "cl-admin@test.co",
        "password_hash": hash_password("x"), "role": "admin",
        "name": "CL Admin", "deleted_at": None,
    }
    await db.users.insert_one(admin)
    return {"admin_token": create_token(admin)}


async def _teardown():
    await db.users.delete_many({"tenant_id": TID})
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


# ═══════════════════════════ Unit-level ══════════════════════════════
class TestBuildPreviewCtxUnit:
    def test_extends_ctx_with_mock_customer_referral_and_more(self):
        ctx = build_preview_ctx(
            {"id": "s1", "email": "a@b.co", "first_name": "S",
              "last_name": "P", "phone": "+15005550006",
              "status": "subscribed"},
            {"id": "t1", "name": "T"},
            {"id": "c1"},
            send_id="sid-1",
        )
        # Subscriber scope survives.
        assert ctx["first_name"] == "S"
        # Mock scopes populated.
        assert ctx["customer"]["first_name"] == "Alex"
        assert ctx["customer"]["credits_balance_cents"] == 0
        assert ctx["referral"]["friend_first_name"] == "Sam Referral"
        assert ctx["referral"]["credit_amount_cents"] == 2500
        assert ctx["invoice"]["total_cents"] == 12500
        assert ctx["job"]["scheduled_date"] == "2026-06-15"
        assert ctx["tech"]["name"] == "Sample Tech"
        # Top-level magic-link overrides so no real JWT mint happens.
        assert ctx["customer_portal_login_link"].startswith("https://sample.")
        assert ctx["service_record_link"].startswith("https://sample.")
        assert ctx["invoice_pay_link"].startswith("https://sample.")

    def test_previously_broken_tags_now_resolve_non_empty(self):
        ctx = build_preview_ctx(
            {"id": "s1", "email": "a@b.co", "first_name": "S",
              "last_name": "P", "status": "subscribed"},
            {"id": "t1", "name": "T"},
            {"id": "c1"},
            send_id="sid-2",
        )
        tpl = (
            "{{CUSTOMER_FIRST_NAME}} | {{CUSTOMER_CREDIT_BALANCE}} | "
            "{{REFERRAL_FRIEND_NAME}} | {{REFERRAL_CREDIT_AMOUNT}} | "
            "{{REFERRAL_ELIGIBLE_DATE}} | {{INVOICE_AMOUNT}} | "
            "{{JOB_DATE}} | {{TECH_NAME}} | "
            "{{CUSTOMER_PORTAL_LOGIN_LINK}}"
        )
        rendered, missing = render_body(tpl, ctx)
        assert missing == [], f"unexpected unresolved: {missing}"
        # Every segment is non-empty.
        for chunk in rendered.split(" | "):
            assert chunk.strip(), f"empty chunk in: {rendered!r}"

    def test_build_ctx_is_unchanged_by_preview_helper(self):
        """Send-time path (``build_ctx``) must not gain mock scopes.

        The mock scopes belong only to ``build_preview_ctx``. If the
        linter helper accidentally leaked mocks into ``build_ctx`` the
        production send would embed fake data in real emails.
        """
        real = build_ctx(
            {"id": "s1", "email": "a@b.co", "first_name": "S",
              "last_name": "P", "status": "subscribed"},
            {"id": "t1", "name": "T"},
            {"id": "c1"},
        )
        for scope in ("customer", "referral", "invoice", "estimate",
                       "job", "tech", "technician", "equipment_tracker",
                       "payment", "event", "service_report",
                       "customer_portal_login_link",
                       "service_record_link", "invoice_pay_link"):
            assert scope not in real, (
                f"send-time ctx must not carry preview mock '{scope}' "
                "— was the mock accidentally hoisted into build_ctx?"
            )


# ═══════════════════════════ Endpoint-level ══════════════════════════
class TestLintEndpoint:
    def test_previously_broken_tags_no_longer_flagged(self, seeded, client):
        async def go():
            async with client as c:
                body = {
                    "subject": (
                        "Welcome {{CUSTOMER_FIRST_NAME}} — your credit "
                        "balance is {{CUSTOMER_CREDIT_BALANCE}}"
                    ),
                    "email_html": (
                        "<p>Hi {{CUSTOMER_FIRST_NAME}}, "
                        "{{REFERRAL_FRIEND_NAME}} earned you "
                        "{{REFERRAL_CREDIT_AMOUNT}} — eligible "
                        "{{REFERRAL_ELIGIBLE_DATE}}.</p>"
                        "<p>Job on {{JOB_DATE}} at {{JOB_TIME}} with "
                        "{{TECH_NAME}}.</p>"
                        "<p><a href='{{CUSTOMER_PORTAL_LOGIN_LINK}}'>"
                        "Portal</a></p>"
                    ),
                    "sms_body": (
                        "Hi {{CUSTOMER_FIRST_NAME}}, credit "
                        "{{CUSTOMER_CREDIT_BALANCE}} — see "
                        "{{SERVICE_RECORD_LINK}}."
                    ),
                }
                r = await c.post("/api/marketing/templates/lint",
                                    json=body, headers=_hdr(seeded))
                assert r.status_code == 200, r.text
                j = r.json()
                # No unresolved tokens for the previously-broken set.
                unresolved = {u["token"] for u in j["unresolved_tokens"]}
                previously_broken = {
                    "CUSTOMER_CREDIT_BALANCE", "REFERRAL_FRIEND_NAME",
                    "REFERRAL_CREDIT_AMOUNT", "REFERRAL_ELIGIBLE_DATE",
                    "JOB_DATE", "JOB_TIME", "TECH_NAME",
                    "CUSTOMER_PORTAL_LOGIN_LINK", "SERVICE_RECORD_LINK",
                }
                still_broken = unresolved & previously_broken
                assert not still_broken, (
                    f"lint still flags: {still_broken}"
                )
                assert j["clean"] is True, j
        _run(go())

    def test_unknown_tag_is_still_flagged(self, seeded, client):
        """The mock scopes must NOT hide real typos / unknown tags."""
        async def go():
            async with client as c:
                r = await c.post(
                    "/api/marketing/templates/lint",
                    json={"email_html": "<p>{{DEFINITELY_NOT_A_TAG}}</p>"},
                    headers=_hdr(seeded),
                )
                assert r.status_code == 200
                j = r.json()
                tokens = {u["token"] for u in j["unresolved_tokens"]}
                assert "DEFINITELY_NOT_A_TAG" in tokens
                assert j["clean"] is False
        _run(go())
