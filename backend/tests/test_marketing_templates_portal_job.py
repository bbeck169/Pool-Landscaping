"""TE-portal-job · Feb-2026 — Portal invite + job completion
transactional templates.

Coverage
────────
1. ``get_template_by_code`` returns the tenant row when present.
2. ``get_template_by_code`` returns None when the row is missing.
3. ``get_template_by_code`` returns None when the row is inactive
   (either ``is_active=False`` OR ``active=False``).
4. ``get_template_by_code`` enforces tenant isolation — tenant A's
   override never leaks into tenant B's read.
5. ``_try_send_reset_email`` uses the DB template body/subject when
   present.
6. ``_try_send_reset_email`` falls back to the hardcoded constants
   when the DB lookup returns None.
7. ``build_completion_sms_body`` uses the ``body_template=`` param
   when passed (DB-first path).
8. ``build_completion_sms_body`` falls back to i18n/inline flow when
   ``body_template=None`` (byte-identical to the pre-TE output).
9. The marketing-templates categories surface (list endpoint filter
   + variables endpoint) accepts ``portal_invite`` +
   ``job_completion``.
10. The migration ``seed_for_tenant`` is idempotent — a second call
    is a no-op.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, Optional

import pytest
import requests

from tests._f7_loop_fixture import run_test


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


# ═══════════════════════════════════════════════════════════════════
# Helpers — synthetic tenant seeds so tests are hermetic wrt the
# per-boot backfill migration's side-effects.
# ═══════════════════════════════════════════════════════════════════
def _mk_tid() -> str:
    return "TE_test_tenant_" + uuid.uuid4().hex[:10]


async def _clean_tenant(db, tenant_id: str) -> None:
    await db.marketing_templates.delete_many({"tenant_id": tenant_id})


# ═══════════════════════════════════════════════════════════════════
# 1-4 — get_template_by_code contract
# ═══════════════════════════════════════════════════════════════════
def test_get_template_by_code_returns_row_when_present():
    from services.marketing_template_lookup import get_template_by_code
    from migrations.te_portal_job_templates_seed import seed_for_tenant

    async def _go(db):
        tid = _mk_tid()
        await _clean_tenant(db, tid)
        try:
            res = await seed_for_tenant(tid)
            assert res == {
                "portal_invite_email": True,
                "job_completion_sms": True,
            }
            row = await get_template_by_code("portal_invite_email", tid)
            assert row is not None
            assert row["code"] == "portal_invite_email"
            assert row["tenant_id"] == tid
            assert row["subject"] == "Your customer portal login"
            assert "<code>{temp_password}</code>" in row["body"]

            row2 = await get_template_by_code("job_completion_sms", tid)
            assert row2 is not None
            assert row2["channel"] == "sms"
            assert row2["subject"] is None
            assert "{first_name}" in row2["body"]
            assert "{portal_link}" in row2["body"]
        finally:
            await _clean_tenant(db, tid)

    run_test(_go)


def test_get_template_by_code_returns_none_when_missing():
    from services.marketing_template_lookup import get_template_by_code

    async def _go(db):
        tid = _mk_tid()
        # No seed — collection is empty for this synthetic tenant.
        row = await get_template_by_code("portal_invite_email", tid)
        assert row is None
        row = await get_template_by_code("job_completion_sms", tid)
        assert row is None

    run_test(_go)


def test_get_template_by_code_returns_none_when_inactive():
    from services.marketing_template_lookup import get_template_by_code
    from migrations.te_portal_job_templates_seed import seed_for_tenant

    async def _go(db):
        tid = _mk_tid()
        await _clean_tenant(db, tid)
        try:
            await seed_for_tenant(tid)
            # Disable both variants of the "active" flag.
            await db.marketing_templates.update_one(
                {"tenant_id": tid, "code": "portal_invite_email"},
                {"$set": {"is_active": False}},
            )
            row = await get_template_by_code("portal_invite_email", tid)
            assert row is None
            # Sanity — sibling still readable.
            row2 = await get_template_by_code("job_completion_sms", tid)
            assert row2 is not None
            # Disable the sibling via the legacy ``active`` field.
            await db.marketing_templates.update_one(
                {"tenant_id": tid, "code": "job_completion_sms"},
                {"$set": {"active": False}},
            )
            row3 = await get_template_by_code("job_completion_sms", tid)
            assert row3 is None
        finally:
            await _clean_tenant(db, tid)

    run_test(_go)


def test_get_template_by_code_enforces_tenant_isolation():
    from services.marketing_template_lookup import get_template_by_code
    from migrations.te_portal_job_templates_seed import seed_for_tenant

    async def _go(db):
        tid_a = _mk_tid()
        tid_b = _mk_tid()
        await _clean_tenant(db, tid_a)
        await _clean_tenant(db, tid_b)
        try:
            await seed_for_tenant(tid_a)
            # Tenant B has NO row.
            row = await get_template_by_code("portal_invite_email", tid_b)
            assert row is None
            # Tenant A still resolves.
            row_a = await get_template_by_code("portal_invite_email", tid_a)
            assert row_a is not None
            assert row_a["tenant_id"] == tid_a
        finally:
            await _clean_tenant(db, tid_a)
            await _clean_tenant(db, tid_b)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5-6 — _try_send_reset_email DB path
# ═══════════════════════════════════════════════════════════════════
def test_try_send_reset_email_uses_db_template_when_present(monkeypatch):
    """When a DB row is present, its ``body``/``subject`` reaches the
    Resend send. We monkeypatch the Resend SDK to capture what would
    have been sent, so no network I/O occurs."""
    from migrations.te_portal_job_templates_seed import seed_for_tenant
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        await _clean_tenant(db, tid)
        try:
            await seed_for_tenant(tid)
            # Mutate the DB row so we can prove it's the source of
            # truth (a hardcoded copy is byte-identical, so a
            # marker string is the only way to tell the two apart).
            marker = "TE-DB-MARKER-" + uuid.uuid4().hex[:8]
            await db.marketing_templates.update_one(
                {"tenant_id": tid, "code": "portal_invite_email"},
                {"$set": {"body":
                          "<p>Hi {name}, marker=" + marker
                          + " login={login_url}</p>"}},
            )
            # Force RESEND_API_KEY truthy so the function reaches
            # the send branch.
            monkeypatch.setattr(_cfg, "RESEND_API_KEY", "test-key-x",
                                raising=False)
            monkeypatch.setattr(_cfg, "EMAIL_FROM",
                                "test@example.com", raising=False)

            captured: Dict[str, Any] = {}

            class _FakeEmails:
                @staticmethod
                def send(payload):
                    captured.update(payload)
                    return {"id": "resend-fake-id-42"}

            class _FakeResendModule:
                api_key: Optional[str] = None
                Emails = _FakeEmails

            monkeypatch.setitem(__import__("sys").modules, "resend",
                                _FakeResendModule)

            email_id = await _pa._try_send_reset_email(
                "sam@example.com", "Sam", "Tempp1234",
                "https://x/login", tenant_id=tid,
            )
            assert email_id == "resend-fake-id-42"
            assert marker in captured.get("html", "")
            assert "Sam" in captured.get("html", "")
            assert "https://x/login" in captured.get("html", "")
        finally:
            await _clean_tenant(db, tid)

    run_test(_go)


def test_try_send_reset_email_falls_back_to_hardcoded_when_no_db_row(
    monkeypatch,
):
    """No DB row for the tenant → the hardcoded constants win. Byte-
    identical to pre-TE output."""
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        # No seed — collection is empty for this synthetic tenant.
        monkeypatch.setattr(_cfg, "RESEND_API_KEY", "test-key-x",
                            raising=False)
        monkeypatch.setattr(_cfg, "EMAIL_FROM",
                            "test@example.com", raising=False)

        captured: Dict[str, Any] = {}

        class _FakeEmails:
            @staticmethod
            def send(payload):
                captured.update(payload)
                return {"id": "resend-fake-id-99"}

        class _FakeResendModule:
            api_key: Optional[str] = None
            Emails = _FakeEmails

        monkeypatch.setitem(__import__("sys").modules, "resend",
                            _FakeResendModule)

        email_id = await _pa._try_send_reset_email(
            "no-db@example.com", "Nobody", "Tempp1234",
            "https://x/login", tenant_id=tid,
        )
        assert email_id == "resend-fake-id-99"
        # Hardcoded subject wins.
        assert captured.get("subject") == "Your customer portal login"
        # Hardcoded HTML body — signature phrase.
        assert "Your portal login is ready" in captured.get("html", "")
        assert "Nobody" in captured.get("html", "")

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 7-8 — build_completion_sms_body body_template param
# ═══════════════════════════════════════════════════════════════════
def test_build_completion_sms_body_uses_body_template_when_passed():
    from services.completion_sms_template import build_completion_sms_body

    tpl = ("Hi {first_name}, TE-PATCH your {job_title} with "
           "{business_name}! link={portal_link}")
    out = build_completion_sms_body(
        tenant={"name": "AquaTerra", "id": "t1"},
        job={"title": "Weekly pool maintenance"},
        customer={"first_name": "Diego"},
        portal_link="https://x/portal",
        body_template=tpl,
    )
    assert out == (
        "Hi Diego, TE-PATCH your Weekly pool maintenance with "
        "AquaTerra! link=https://x/portal"
    )


def test_build_completion_sms_body_ignores_none_body_template():
    """When ``body_template=None`` the function reaches the pre-TE
    i18n loader → hardcoded fallback flow — byte-identical to the
    canonical spec."""
    from services.completion_sms_template import build_completion_sms_body

    PORTAL = "https://app.plofv.com/portal/service-reports?token=abc"
    out = build_completion_sms_body(
        tenant={"name": "Pool & Landscaping of Vistancia"},
        job={"title": "Weekly pool maintenance"},
        customer={"first_name": "Diego"},
        portal_link=PORTAL,
        body_template=None,
    )
    assert out == (
        "Hi Diego, your Weekly pool maintenance with "
        "Pool & Landscaping of Vistancia is complete! "
        "View your full report and photos here: " + PORTAL
    )


# ═══════════════════════════════════════════════════════════════════
# 9 — Categories endpoint (HTTP) accepts portal_invite + job_completion
# ═══════════════════════════════════════════════════════════════════
def test_router_allowed_categories_accepts_new_slugs(admin_headers):
    """The router's ``ALLOWED_CATEGORIES`` set is a filter-side
    contract — the list endpoint should accept ``category=portal_invite``
    and ``category=job_completion`` without a 422.

    (The seed rows land via the boot-time migration; whether they're
    in the DB at test time depends on migration order, so we only
    assert the filter is not rejected.)
    """
    for cat in ("portal_invite", "job_completion"):
        r = requests.get(
            f"{API}/marketing/templates?category={cat}",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, (cat, r.status_code, r.text[:200])
        body = r.json()
        assert "templates" in body
        # Every row returned MUST match the requested category.
        for row in body["templates"]:
            assert row.get("category") == cat


# ═══════════════════════════════════════════════════════════════════
# 10 — Migration idempotency
# ═══════════════════════════════════════════════════════════════════
def test_seed_for_tenant_is_idempotent():
    from migrations.te_portal_job_templates_seed import seed_for_tenant

    async def _go(db):
        tid = _mk_tid()
        await _clean_tenant(db, tid)
        try:
            first = await seed_for_tenant(tid)
            assert first == {
                "portal_invite_email": True,
                "job_completion_sms": True,
            }
            second = await seed_for_tenant(tid)
            assert second == {
                "portal_invite_email": False,
                "job_completion_sms": False,
            }
            # Row count is exactly 2 (no duplicates).
            n = await db.marketing_templates.count_documents(
                {"tenant_id": tid},
            )
            assert n == 2
        finally:
            await _clean_tenant(db, tid)

    run_test(_go)
