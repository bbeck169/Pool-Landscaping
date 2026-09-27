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
    # Feb-2026 · Portal-invite merge-tags fix — the send-path now
    # fetches the tenant record for the ``{{COMPANY_*}}`` catalog
    # resolvers; any synthetic tenant row seeded by a test must be
    # removed alongside the templates so re-runs stay hermetic.
    await db.tenants.delete_many({"id": tenant_id})


async def _seed_synthetic_tenant(
    db, tenant_id: str,
    *,
    company_name: str = "TE Synthetic Pool Co.",
    company_phone: str = "555-000-0001",
) -> None:
    """Feb-2026 · Portal-invite merge-tags fix — insert a synthetic
    tenant row so the ``_try_send_reset_email`` pre-send branding
    check (needs ``{{COMPANY_NAME}}`` + ``{{COMPANY_PHONE}}``
    non-empty) doesn't abort the send.  Mirrors the shape the live
    Business Card editor writes.
    """
    await db.tenants.insert_one({
        "id": tenant_id,
        "slug": f"te-synth-{tenant_id}",
        "name": company_name,
        "settings": {
            "business_card": {
                "company_name": company_name,
                "phone": company_phone,
            },
        },
    })


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
            # Feb-2026 · Portal-invite merge-tags fix — seed body
            # now uses double-brace ``{{TEMP_PASSWORD}}``.
            assert "<code>{{TEMP_PASSWORD}}</code>" in row["body"]
            # Legacy single-brace must NOT be present in the seed.
            assert "{temp_password}" not in row["body"]

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
    have been sent, so no network I/O occurs.

    Feb-2026 · Portal-invite merge-tags fix — the send-path now
    routes through ``merge_tags.render_template`` (double-brace
    only), so the marker body uses ``{{NAME}}`` / ``{{LOGIN_URL}}``.
    A synthetic tenant with a populated Business Card is seeded so
    the pre-send branding check passes.
    """
    from migrations.te_portal_job_templates_seed import seed_for_tenant
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        await _clean_tenant(db, tid)
        try:
            await _seed_synthetic_tenant(db, tid)
            await seed_for_tenant(tid)
            # Mutate the DB row so we can prove it's the source of
            # truth (a hardcoded copy is byte-identical, so a
            # marker string is the only way to tell the two apart).
            marker = "TE-DB-MARKER-" + uuid.uuid4().hex[:8]
            await db.marketing_templates.update_one(
                {"tenant_id": tid, "code": "portal_invite_email"},
                {"$set": {"body":
                          "<p>Hi {{NAME}}, marker=" + marker
                          + " login={{LOGIN_URL}}</p>"}},
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
    identical rendered surface to pre-TE output (subject unchanged,
    signature phrase present, name substituted).

    Feb-2026 · Portal-invite merge-tags fix — synthetic tenant is
    seeded so the pre-send branding check passes on the fallback
    path.
    """
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        # No template seed — collection is empty for this synthetic
        # tenant.  The tenant record IS seeded so the branding gate
        # doesn't abort the send.
        try:
            await _seed_synthetic_tenant(db, tid)
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
        finally:
            await _clean_tenant(db, tid)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# Feb-2026 · Portal-invite merge-tags fix — new coverage
# ═══════════════════════════════════════════════════════════════════
def test_try_send_reset_email_resolves_company_tokens_from_tenant(
    monkeypatch,
):
    """Happy path for the merge-tags fix — a DB template that
    references ``{{COMPANY_NAME}}`` and ``{{COMPANY_PHONE}}`` renders
    to the tenant's Business Card values (NOT literal placeholder
    text)."""
    from migrations.te_portal_job_templates_seed import seed_for_tenant
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        await _clean_tenant(db, tid)
        try:
            await _seed_synthetic_tenant(
                db, tid,
                company_name="TE Merge-Tag Co.",
                company_phone="555-424-2424",
            )
            await seed_for_tenant(tid)
            await db.marketing_templates.update_one(
                {"tenant_id": tid, "code": "portal_invite_email"},
                {"$set": {"body":
                          "<p>Hi {{NAME}} — from {{COMPANY_NAME}}"
                          " ({{COMPANY_PHONE}})</p>"}},
            )
            monkeypatch.setattr(_cfg, "RESEND_API_KEY", "test-key-x",
                                raising=False)
            monkeypatch.setattr(_cfg, "EMAIL_FROM",
                                "test@example.com", raising=False)

            captured: Dict[str, Any] = {}

            class _FakeEmails:
                @staticmethod
                def send(payload):
                    captured.update(payload)
                    return {"id": "resend-mt-1"}

            class _FakeResendModule:
                api_key: Optional[str] = None
                Emails = _FakeEmails

            monkeypatch.setitem(__import__("sys").modules, "resend",
                                _FakeResendModule)

            email_id = await _pa._try_send_reset_email(
                "sam@example.com", "Sam", "Tempp1234",
                "https://x/login", tenant_id=tid,
            )
            assert email_id == "resend-mt-1"
            html = captured.get("html", "")
            # Company tokens resolved — no literal placeholder syntax
            # survives in the rendered body.
            assert "TE Merge-Tag Co." in html
            assert "555-424-2424" in html
            assert "{{COMPANY_NAME}}" not in html
            assert "{{COMPANY_PHONE}}" not in html
        finally:
            await _clean_tenant(db, tid)

    run_test(_go)


def test_try_send_reset_email_aborts_when_tenant_branding_missing(
    monkeypatch,
):
    """Missing-branding safety rail — when the tenant record lacks
    a resolvable ``COMPANY_NAME`` / ``COMPANY_PHONE`` (business card
    absent AND legacy fallbacks empty AND no per-slug default), the
    send is aborted with ``None`` return.  Compatible with P34's
    ``Optional[str]`` contract."""
    import routers.portal_admin as _pa
    import config as _cfg

    async def _go(db):
        tid = _mk_tid()
        await _clean_tenant(db, tid)
        try:
            # Insert a tenant with EMPTY business card fields AND
            # NO legacy phone fields — nothing for the cascade to
            # resolve.  ``slug`` is set to a value NOT present in
            # ``_BUSINESS_CARD_DEFAULTS`` so the per-slug fallback
            # also yields empty.
            await db.tenants.insert_one({
                "id": tid,
                "slug": f"te-empty-{tid}",
                "name": "",  # legacy COMPANY_NAME fallback empty too
                "settings": {"business_card": {}},
            })
            monkeypatch.setattr(_cfg, "RESEND_API_KEY", "test-key-x",
                                raising=False)
            monkeypatch.setattr(_cfg, "EMAIL_FROM",
                                "test@example.com", raising=False)

            send_called = {"n": 0}

            class _FakeEmails:
                @staticmethod
                def send(payload):
                    send_called["n"] += 1
                    return {"id": "should-not-fire"}

            class _FakeResendModule:
                api_key: Optional[str] = None
                Emails = _FakeEmails

            monkeypatch.setitem(__import__("sys").modules, "resend",
                                _FakeResendModule)

            email_id = await _pa._try_send_reset_email(
                "abort@example.com", "Aborted", "Tempp1234",
                "https://x/login", tenant_id=tid,
            )
            # Abort branch — None return, no Resend call.
            assert email_id is None
            assert send_called["n"] == 0
        finally:
            await _clean_tenant(db, tid)

    run_test(_go)


def test_source_lint_send_reset_email_uses_merge_tags_not_format():
    """Feb-2026 · Portal-invite merge-tags fix — source lint asserts
    the engine swap actually landed:

    * The function's executable body must NOT call ``.format(``
      anywhere (the ``str.format`` engine is gone).  Docstrings
      that reference the historical engine are stripped before
      the scan.
    * ``render_template`` from ``services.marketing.merge_tags`` MUST
      appear (the new engine).
    """
    import ast
    import inspect
    import routers.portal_admin as _pa

    src = inspect.getsource(_pa._try_send_reset_email)
    # Strip the docstring before scanning — it legitimately
    # references ``str.format(**kw)`` as the historical engine and
    # we don't want to lock that documentation out of the file.
    tree = ast.parse(src)
    fn = tree.body[0]
    assert isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        # Drop the docstring node in-place, then unparse.
        fn.body = fn.body[1:]
    executable_src = ast.unparse(tree)

    assert ".format(" not in executable_src, (
        "_try_send_reset_email executable body must not use"
        " str.format — swap regressed to the pre-fix engine"
    )
    assert "render_template(" in executable_src, (
        "_try_send_reset_email must call render_template from"
        " services.marketing.merge_tags"
    )
    assert "services.marketing.merge_tags" in executable_src, (
        "_try_send_reset_email must import from"
        " services.marketing.merge_tags"
    )


def test_source_lint_hardcoded_fallback_uses_double_brace():
    """Feb-2026 · Portal-invite merge-tags fix — the module-level
    hardcoded fallback constants must use double-brace
    ``{{TOKEN}}`` syntax to match the new renderer.  A regression
    to single-brace would silently render as literal placeholder
    text when the DB row is missing / inactive."""
    import routers.portal_admin as _pa

    for const_name in ("_HARDCODED_INVITE_HTML_TPL",
                       "_HARDCODED_INVITE_TEXT_TPL"):
        body = getattr(_pa, const_name)
        assert "{{NAME}}" in body, (
            f"{const_name} must contain double-brace {{{{NAME}}}}"
        )
        assert "{{TO}}" in body, (
            f"{const_name} must contain double-brace {{{{TO}}}}"
        )
        assert "{{TEMP_PASSWORD}}" in body, (
            f"{const_name} must contain double-brace"
            f" {{{{TEMP_PASSWORD}}}}"
        )
        assert "{{LOGIN_URL}}" in body, (
            f"{const_name} must contain double-brace {{{{LOGIN_URL}}}}"
        )
        # Legacy single-brace placeholders must NOT survive the
        # rebrace edit.
        for legacy in ("{name}", "{to}", "{temp_password}",
                       "{login_url}"):
            assert legacy not in body, (
                f"{const_name} still contains legacy single-brace"
                f" placeholder {legacy!r}"
            )


def test_source_lint_seed_migration_uses_double_brace():
    """Feb-2026 · Portal-invite merge-tags fix — the seed migration's
    ``PORTAL_INVITE_EMAIL_BODY_HTML`` constant must use double-brace
    tokens so new-tenant seeding lands in the correct shape (the
    boot-time rebrace migration handles historical rows)."""
    from migrations import te_portal_job_templates_seed as _seed

    body = _seed.PORTAL_INVITE_EMAIL_BODY_HTML
    for canonical in ("{{NAME}}", "{{TO}}", "{{TEMP_PASSWORD}}",
                      "{{LOGIN_URL}}"):
        assert canonical in body, (
            f"seed body must contain {canonical}"
        )
    for legacy in ("{name}", "{to}", "{temp_password}", "{login_url}"):
        assert legacy not in body, (
            f"seed body still contains legacy single-brace"
            f" placeholder {legacy!r}"
        )
    # SMS constants are UNRELATED and must NOT have been touched by
    # this edit.  Locking the byte-shape of the SMS body prevents a
    # future maintainer from bleeding portal-invite work into the
    # SMS surface.
    assert "{first_name}" in _seed.JOB_COMPLETION_SMS_BODY
    assert "{portal_link}" in _seed.JOB_COMPLETION_SMS_BODY
    assert "{{" not in _seed.JOB_COMPLETION_SMS_BODY


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
