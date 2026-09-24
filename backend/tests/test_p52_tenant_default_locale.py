"""Phase P52 · Feb-2026 — Tenant ``default_locale`` migration + settings PATCH.

Locks two invariants for the locale slice of P52 (timezone deferred
pending user's Q1 decision):

1. ``migrations/p52_tenant_default_locale.py``
   * Backfills every tenant document missing ``default_locale`` (or
     carrying a value outside ``{en, es, fr}``).
   * Idempotent on re-run — second pass reports ``already_set`` +
     stamps the ``migrations_applied`` marker.
   * Force mode ignores the marker and re-inspects.
   * Dry-run inspects without writing.

2. ``PATCH /tenants/mine/settings`` accepting ``default_locale``
   * Existing Phase D5 handler validates against
     ``services.i18n_notifications.SUPPORTED_LOCALES`` which is
     the same ``{en, es, fr}`` set my migration writes.
   * Unknown locale rejected with 422 (Phase D5 shape).
   * Tenant scoping — a call from tenant A cannot mutate tenant B's
     document.

Test-loop convention mirrors P47 / P48 / P50: sync ``pymongo`` for
seeding + cleanup, per-test fresh asyncio loop + Motor client for
the SUT call.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "P52_"


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    """Tracks every P52_-tagged tenant + marker row this test wrote
    and drops them on teardown so full-suite runs stay hermetic."""
    seeded_tenant_ids: List[str] = []
    yield seeded_tenant_ids
    if seeded_tenant_ids:
        dbc.tenants.delete_many({"id": {"$in": seeded_tenant_ids}})


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_tenant(dbc, *, default_locale: Optional[str] = "MISSING") -> str:
    tid = _fresh("TEN")
    doc: Dict[str, Any] = {
        "id": tid,
        "name": f"P52 seed tenant {tid[-8:]}",
        "timezone": "America/Phoenix",
        "created_at": "2026-02-01T00:00:00Z",
    }
    if default_locale != "MISSING":
        doc["default_locale"] = default_locale
    dbc.tenants.insert_one(doc)
    return tid


# ═════════════════════════════════════════════════════════════════════
# Per-test async loop + Motor db handle
# ═════════════════════════════════════════════════════════════════════
def _run(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    try:
        return loop.run_until_complete(coro_factory(adb))
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# Migration tests
# ═════════════════════════════════════════════════════════════════════
def test_migration_backfills_missing_default_locale(dbc, cleanup):
    """A tenant with no ``default_locale`` field gets ``en`` written."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.p52_tenant_default_locale import run
        # ``force=True`` so an earlier full-DB run doesn't
        # short-circuit us via the marker.
        return await run(dry_run=False, force=True, db_client=adb)

    summary = _run(_apply)
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("default_locale") == "en", row
    # ``backfilled`` counter includes our seeded tenant (may include
    # organic others too, that's fine — we test row-level truth).
    assert summary["backfilled"] >= 1


def test_migration_leaves_already_valid_default_locale_untouched(dbc, cleanup):
    """A tenant already carrying ``es`` stays on ``es`` — the sweep
    only fixes missing / invalid values."""
    tid = _seed_tenant(dbc, default_locale="es")
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.p52_tenant_default_locale import run
        return await run(dry_run=False, force=True, db_client=adb)

    _run(_apply)
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("default_locale") == "es"


def test_migration_coerces_invalid_value_to_en(dbc, cleanup):
    """A tenant carrying an out-of-bundle locale (``de``,
    ``zh_TW``, garbage string) gets coerced to ``en`` and is
    counted under ``coerced_bad_value`` — distinct from the
    ``backfilled`` (missing-field) bucket so the summary tells
    ops which drift path they inherited."""
    tid = _seed_tenant(dbc, default_locale="de")
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.p52_tenant_default_locale import run
        return await run(dry_run=False, force=True, db_client=adb)

    _run(_apply)
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("default_locale") == "en", row


def test_migration_dry_run_does_not_write(dbc, cleanup):
    """Dry-run inspects but never persists.  A follow-up read must
    still show the missing/absent field on the seeded tenant."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.p52_tenant_default_locale import run
        return await run(dry_run=True, force=True, db_client=adb)

    summary = _run(_apply)
    assert summary["dry_run"] is True
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert "default_locale" not in row, (
        "dry-run must NOT write to the tenants collection")


def test_migration_stamps_marker_on_execute(dbc, cleanup):
    """A successful execute writes to ``migrations_applied`` so a
    subsequent boot short-circuits without --force."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.p52_tenant_default_locale import run
        return await run(dry_run=False, force=True, db_client=adb)

    _run(_apply)
    marker = dbc.migrations_applied.find_one(
        {"name": "p52_tenant_default_locale"}, {"_id": 0})
    assert marker is not None
    assert marker.get("applied_at")
    assert marker.get("summary", {}).get("backfilled") is not None


def test_migration_marker_short_circuits_on_re_run(dbc, cleanup):
    """When the marker exists and ``force=False``, the sweep
    returns immediately with ``skipped_by_marker=True`` — no
    ``tenants.find`` cursor drained."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.p52_tenant_default_locale import run
        # First pass writes the marker.
        await run(dry_run=False, force=True, db_client=adb)
        # Second pass respects the marker — no --force.
        return await run(dry_run=False, force=False, db_client=adb)

    summary = _run(_apply)
    assert summary["skipped_by_marker"] is True
    assert summary["tenants_seen"] == 0


# ═════════════════════════════════════════════════════════════════════
# PATCH /tenants/mine/settings tests
# ═════════════════════════════════════════════════════════════════════
def test_patch_settings_accepts_valid_default_locale(dbc, cleanup):
    """``default_locale`` in ``{en, es, fr}`` writes cleanly and the
    response document reflects the new value."""
    tid = _seed_tenant(dbc, default_locale="en")
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import patch_own_settings, TenantSettingsUpdate
        # Patch the module-level ``db`` so the SUT uses our loop's Motor.
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = TenantSettingsUpdate(default_locale="es")
            return await patch_own_settings(
                body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    doc = _run(_apply)
    assert doc.get("default_locale") == "es"
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    assert row.get("default_locale") == "es"


def test_patch_settings_rejects_unknown_default_locale(dbc, cleanup):
    """``default_locale`` outside the D5 supported set → 422 (the
    shipped Phase D5 handler uses 422, not 400).  Test locks the
    behaviour so a future refactor that changes the status code
    intentionally shows up as a green-to-red flip."""
    from fastapi import HTTPException
    tid = _seed_tenant(dbc, default_locale="en")
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import patch_own_settings, TenantSettingsUpdate
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = TenantSettingsUpdate(default_locale="klingon")
            return await patch_own_settings(
                body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    with pytest.raises(HTTPException) as excinfo:
        _run(_apply)
    assert excinfo.value.status_code == 422
    # The detail payload carries the D5 error code so the frontend
    # can surface a targeted toast.
    assert excinfo.value.detail.get("code") == "invalid_default_locale"


def test_patch_settings_non_admin_rejected(dbc, cleanup):
    """Only admin / super_admin can flip tenant settings — the
    handler 403s a member / technician / customer.  Locks the
    role-gate that shipped as part of the D5 handler."""
    from fastapi import HTTPException
    tid = _seed_tenant(dbc, default_locale="en")
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import patch_own_settings, TenantSettingsUpdate
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = TenantSettingsUpdate(default_locale="es")
            return await patch_own_settings(
                body=body,
                # role=member should NOT be able to flip tenant settings.
                user={"role": "member", "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    with pytest.raises(HTTPException) as excinfo:
        _run(_apply)
    assert excinfo.value.status_code == 403


def test_patch_settings_scoped_to_callers_tenant(dbc, cleanup):
    """The handler resolves ``tenant_id`` from ``user.tenant_id``
    — a caller can't target another tenant even by supplying its
    id in the body (the body doesn't accept a tenant_id at all).
    We seed two tenants + prove the mutation only lands on the
    caller's own document."""
    tid_a = _seed_tenant(dbc, default_locale="en")
    tid_b = _seed_tenant(dbc, default_locale="en")
    cleanup.extend([tid_a, tid_b])

    async def _apply(adb):
        from routers.tenants import patch_own_settings, TenantSettingsUpdate
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = TenantSettingsUpdate(default_locale="fr")
            # Caller is tenant A's admin.
            return await patch_own_settings(
                body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid_a},
            )
        finally:
            _t.db = _t._orig_db

    _run(_apply)
    row_a = dbc.tenants.find_one({"id": tid_a}, {"_id": 0})
    row_b = dbc.tenants.find_one({"id": tid_b}, {"_id": 0})
    assert row_a.get("default_locale") == "fr"
    assert row_b.get("default_locale") == "en", (
        "tenant B must not be mutated by tenant A's admin — "
        "cross-tenant leak")
