"""M-TAG-FIX FOLLOWUP Fix 1 · Feb-2026 · Admin-migration endpoint tests.

Validates the super_admin-gated migration endpoint
``POST /api/admin/migrations/portal-invite-split-paragraph`` added
in the admin-migrations router.  Three scenarios:

  1. Non-super_admin callers → 403 ``super_admin_only``.
  2. Super_admin + ``fix=false`` (default) → dry-run report with
     match counts; DB is byte-identical afterwards; sentinel NOT
     stamped.
  3. Super_admin + ``fix=true`` → fix report with migration counts;
     DB row rewritten to the canonical two-paragraph shape;
     sentinel stamped.  Second fix invocation short-circuits via
     ``skipped=True reason=already_ran``.

Each test seeds under a unique ``TEST-admin-mig-split-`` tenant
prefix and cleans up both the ``marketing_templates`` rows AND the
sentinel on teardown so order doesn't matter.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


MIGRATION_KEY = (
    "portal_invite_split_email_temppassword_paragraph_v1"
)
_TENANT_PREFIX = "TEST-admin-mig-split-"

_LEGACY_SINGLE_P_BODY = (
    "<p>Hi {{NAME}},</p>"
    "<p>Your portal login is ready.</p>"
    "<p><strong>Email:</strong> {{TO}}<br>"
    "<strong>Temporary password:</strong> "
    "<code>{{TEMP_PASSWORD}}</code></p>"
    "<p><a href='{{LOGIN_URL}}'>Sign in here</a> and change "
    "your password from Profile.</p>"
)


def _mk_tid() -> str:
    return _TENANT_PREFIX + uuid.uuid4().hex[:12]


async def _seed_row(db, tenant_id: str) -> str:
    row_id = f"{_TENANT_PREFIX}row-{uuid.uuid4().hex[:8]}"
    await db.marketing_templates.insert_one({
        "id": row_id,
        "tenant_id": tenant_id,
        "code": "portal_invite_email",
        "name": "Portal Invite — Email",
        "channel": "email",
        "subject": "Your customer portal login",
        "body": _LEGACY_SINGLE_P_BODY,
        "is_system": True,
        "is_active": True,
    })
    return row_id


async def _cleanup(db, tenant_id: str) -> None:
    await db.marketing_templates.delete_many({"tenant_id": tenant_id})


async def _reset_sentinel(db) -> None:
    await db.migration_status.delete_one({"key": MIGRATION_KEY})


def _rebind_db(db) -> None:
    """Rebind ``routers.admin_migrations.db`` to the loop-scoped
    handle so the endpoint handler's global ``db`` reference points
    at the same Motor client the fixture spun up for this test.
    Mirrors the pattern ``_f7_loop_fixture`` applies to the
    pre-known hot-path routers; this test imports an admin-migration
    router that isn't in that fixture's whitelist, so we do the
    rebinding locally.
    """
    import routers.admin_migrations as _am
    _am.db = db


# ═══════════════════════════════════════════════════════════════════
# Auth gate — non-super_admin callers get 403.
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("role", ["admin", "manager", "customer",
                                    "technician", "owner"])
def test_portal_invite_split_endpoint_rejects_non_super_admin(role):
    async def _go(db):
        from routers.admin_migrations import run_portal_invite_split_paragraph
        user = {"id": "u-x", "email": "x@example.com", "role": role}
        tenant = {"id": "tenant-x", "slug": "tenant-x", "name": "T"}
        with pytest.raises(HTTPException) as excinfo:
            await run_portal_invite_split_paragraph(
                fix=False, user=user, tenant=tenant,
            )
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "super_admin_only"

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# Dry-run default (fix=False) — scans without writing.
# ═══════════════════════════════════════════════════════════════════
def test_portal_invite_split_endpoint_dry_run_reports_without_writing():
    async def _go(db):
        _rebind_db(db)
        from routers.admin_migrations import run_portal_invite_split_paragraph
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid)
            user = {"id": "sa-x", "email": "sa@example.com",
                    "role": "super_admin"}
            tenant = {"id": tid, "slug": "sa-tenant", "name": "SA"}

            res = await run_portal_invite_split_paragraph(
                fix=False, user=user, tenant=tenant,
            )
            assert res["ok"] is True
            assert res["dry_run"] is True
            assert res["templates_matched"] >= 1
            # Dry-run NEVER writes.
            assert res["templates_migrated"] == 0

            # Body unchanged.
            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            assert row["body"] == _LEGACY_SINGLE_P_BODY

            # Sentinel NOT stamped on a dry-run (allows operators to
            # iterate the audit pass safely).
            sen = await db.migration_status.find_one(
                {"key": MIGRATION_KEY}, {"_id": 0},
            )
            assert sen is None
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# Fix run (fix=True) — writes and stamps sentinel.  Second invocation
# short-circuits.
# ═══════════════════════════════════════════════════════════════════
def test_portal_invite_split_endpoint_fix_writes_and_is_idempotent():
    async def _go(db):
        _rebind_db(db)
        from routers.admin_migrations import run_portal_invite_split_paragraph
        tid = _mk_tid()
        await _cleanup(db, tid)
        await _reset_sentinel(db)
        try:
            row_id = await _seed_row(db, tid)
            user = {"id": "sa-y", "email": "sa2@example.com",
                    "role": "super_admin"}
            tenant = {"id": tid, "slug": "sa-tenant", "name": "SA"}

            # First fix run migrates.
            res1 = await run_portal_invite_split_paragraph(
                fix=True, user=user, tenant=tenant,
            )
            assert res1["ok"] is True
            assert res1["dry_run"] is False
            assert res1["templates_matched"] >= 1
            assert res1["templates_migrated"] >= 1

            row = await db.marketing_templates.find_one(
                {"id": row_id}, {"_id": 0, "body": 1},
            )
            assert (
                "<p><strong>Email:</strong> {{TO}}</p>" in row["body"]
            )
            assert "{{TO}}<br>" not in row["body"]

            sen = await db.migration_status.find_one(
                {"key": MIGRATION_KEY}, {"_id": 0},
            )
            assert sen is not None
            assert sen.get("completed_at")

            # Second fix run short-circuits.
            res2 = await run_portal_invite_split_paragraph(
                fix=True, user=user, tenant=tenant,
            )
            assert res2.get("skipped") is True
            assert res2.get("reason") == "already_ran"
        finally:
            await _cleanup(db, tid)
            await _reset_sentinel(db)

    run_test(_go)
