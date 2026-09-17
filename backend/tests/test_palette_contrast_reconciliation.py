"""Feb-2026 · Preset Palette Contrast Reconciliation.

Acceptance suite:
  * ``GET /api/tech-colors/palette`` drops the 5 contrast-failing
    presets (``#10B981``, ``#14B8A6``, ``#F59E0B``, ``#84CC16``,
    ``#06B6D4``) and keeps every entry that clears WCAG 3.0.
  * Migration ``--dry-run`` reports affected user count + mapping
    without any DB mutation.
  * Migration real-run flips each blocked hex to its mapped
    replacement AND appends one ``color_migration_audit`` row per
    write. Second run = 0 changes (idempotent).
  * Users whose ``display_color_hex`` already passes are untouched.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv
from fastapi import HTTPException
from pymongo import MongoClient

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")
TENANT_ID = "test-tenant-palette-reconcile"


def _get_app():
    from server import app
    return app


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _cleanup():
    db = _sync_db()
    db.users.delete_many({"tenant_id": TENANT_ID})
    db.color_migration_audit.delete_many({"tenant_id": TENANT_ID})


@pytest.fixture(autouse=True)
def _pre_test_cleanup():
    """Reset the tenant's user + audit rows BEFORE each test so that
    a randomised pytest ordering (pytest-randomly) can't bleed
    seeded state from one test into the next."""
    _cleanup()
    yield
    _cleanup()


def _seed_users_with_colors(color_by_uid: dict) -> None:
    """Seed one user per (uid, color) pair."""
    db = _sync_db()
    _cleanup()
    for uid, color in color_by_uid.items():
        db.users.insert_one({
            "id": uid, "tenant_id": TENANT_ID,
            "email": f"{uid}@x", "role": "technician",
            "display_color_hex": color,
        })


def _install_overrides(*, role="admin"):
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    app = _get_app()

    async def _u():
        return {"id": "u-admin", "role": role,
                "email": "a@x", "tenant_id": TENANT_ID}

    async def _t():
        return {"id": TENANT_ID, "name": "T"}

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_tenant, None)
    return _clear


def _run(coro, *, role="admin"):
    clear = _install_overrides(role=role)
    try:
        async def _go(db):
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(transport=transport,
                                                 base_url="http://test") as ac:
                await coro(ac, db)
        run_test(_go)
    finally:
        clear()


# ── Palette endpoint filter ──────────────────────────────────────
def test_palette_endpoint_drops_low_contrast_entries():
    async def _t(ac, db):
        r = await ac.get("/api/tech-colors/palette")
        assert r.status_code == 200, r.text
        hexes = [row["hex"].upper() for row in r.json()["palette"]]
        # The 5 blocked entries MUST be filtered out.
        blocked = {"#10B981", "#14B8A6", "#F59E0B", "#84CC16", "#06B6D4"}
        for b in blocked:
            assert b not in hexes, (
                f"low-contrast preset {b} leaked into the response"
            )
        # A representative dark preset MUST survive.
        assert "#3B82F6" in hexes, "core palette entry unexpectedly dropped"
    _run(_t)


def test_palette_endpoint_survives_when_constant_is_all_dark(monkeypatch):
    """When the raw constant contains only dark hexes, the filter
    is a no-op — every entry passes through."""
    # Import late to grab the current live constant then rebuild the
    # filter with a subset. The endpoint reads from
    # ``_FILTERED`` computed at import time, so we exercise the
    # underlying helper directly for this branch.
    from routers.tech_colors import _filtered_palette
    all_dark = [("blue", "#3B82F6"), ("red", "#EF4444"),
                 ("indigo", "#6366F1")]
    monkeypatch.setattr("routers.tech_colors.TECH_COLOR_PALETTE", all_dark)
    got = _filtered_palette()
    assert [h for _n, h in got] == ["#3B82F6", "#EF4444", "#6366F1"]


# ── Migration · dry-run reports without mutation ─────────────────
def test_migration_dry_run_reports_affected_without_writes():
    _seed_users_with_colors({
        "u-emerald":  "#10B981",
        "u-teal":     "#14B8A6",
        "u-passing":  "#3B82F6",
        "u-blue":     "#3B82F6",  # already fine, ignored
    })
    async def _t(ac, db):
        from services.migrations.legacy_low_contrast_color_migration \
            import backfill
        result = await backfill(db, dry_run=True)
        assert result["dry_run"] is True
        # Both blocked users show up in ``affected``, ``updated`` == 0.
        assert result["affected"] == 2
        assert result["updated"] == 0
        # No rows were mutated.
        emerald = await db.users.find_one({"id": "u-emerald"})
        teal = await db.users.find_one({"id": "u-teal"})
        assert emerald["display_color_hex"] == "#10B981"
        assert teal["display_color_hex"] == "#14B8A6"
        # No audit rows were written.
        audit_count = await db.color_migration_audit.count_documents(
            {"tenant_id": TENANT_ID})
        assert audit_count == 0
        # Mapping preview shape.
        by_uid = {row["user_id"]: row for row in result["mapping"]}
        assert by_uid["u-emerald"]["before"] == "#10B981"
        assert by_uid["u-emerald"]["after"] == "#059669"
        assert by_uid["u-teal"]["after"] == "#0F766E"
    _run(_t)
    _cleanup()


# ── Migration · real run flips + audits + idempotent ─────────────
def test_migration_real_run_flips_colors_audits_and_is_idempotent():
    _seed_users_with_colors({
        "u-emerald": "#10B981",
        "u-teal":    "#14B8A6",
        "u-amber":   "#F59E0B",
        "u-lime":    "#84CC16",
        "u-cyan":    "#06B6D4",
        "u-orange":  "#F97316",
        "u-blue":    "#3B82F6",  # untouched
    })
    async def _t(ac, db):
        from services.migrations.legacy_low_contrast_color_migration \
            import backfill

        first = await backfill(db, dry_run=False)
        assert first["updated"] == 6
        assert first["affected"] == 6
        assert first["dry_run"] is False

        # All 6 blocked users flipped to their mapped darker shade.
        expected = {
            "u-emerald": "#059669",
            "u-teal":    "#0F766E",
            "u-amber":   "#B45309",
            "u-lime":    "#4D7C0F",
            "u-cyan":    "#0E7490",
            "u-orange":  "#C2410C",
        }
        for uid, new_hex in expected.items():
            row = await db.users.find_one({"id": uid})
            assert row["display_color_hex"] == new_hex, (
                f"{uid}: expected {new_hex}, got {row['display_color_hex']!r}"
            )
        # Untouched user's color is unchanged.
        row = await db.users.find_one({"id": "u-blue"})
        assert row["display_color_hex"] == "#3B82F6"

        # Each write emitted one audit row with the exact event label.
        audit_rows = await db.color_migration_audit.find(
            {"tenant_id": TENANT_ID}).to_list(50)
        assert len(audit_rows) == 6
        for row in audit_rows:
            assert row["event"] == "legacy_color_migrated"
            assert row["before"] in {"#10B981", "#14B8A6", "#F59E0B",
                                        "#84CC16", "#06B6D4", "#F97316"}
            assert row["after"] in {"#059669", "#0F766E", "#B45309",
                                       "#4D7C0F", "#0E7490", "#C2410C"}

        # Second run is a zero-op — nothing to remap.
        second = await backfill(db, dry_run=False)
        assert second["affected"] == 0
        assert second["updated"] == 0
        # Audit table did NOT grow.
        audit_count_2 = await db.color_migration_audit.count_documents(
            {"tenant_id": TENANT_ID})
        assert audit_count_2 == 6
    _run(_t)
    _cleanup()


# ── Migration · already-passing users are ignored ─────────────────
def test_migration_ignores_users_already_passing():
    _seed_users_with_colors({
        "u-blue":   "#3B82F6",
        "u-red":    "#EF4444",
        "u-violet": "#8B5CF6",
    })
    async def _t(ac, db):
        from services.migrations.legacy_low_contrast_color_migration \
            import backfill
        result = await backfill(db, dry_run=False)
        assert result["affected"] == 0
        assert result["updated"] == 0
        # No audit rows.
        audit_count = await db.color_migration_audit.count_documents(
            {"tenant_id": TENANT_ID})
        assert audit_count == 0
    _run(_t)
    _cleanup()


# ── Migration · malformed hex on a legacy row is left alone ──────
def test_migration_skips_malformed_hex_rows():
    _seed_users_with_colors({
        "u-garbage": "xyz",
    })
    async def _t(ac, db):
        from services.migrations.legacy_low_contrast_color_migration \
            import backfill
        result = await backfill(db, dry_run=False)
        assert result["affected"] == 0
        row = await db.users.find_one({"id": "u-garbage"})
        # Untouched.
        assert row["display_color_hex"] == "xyz"
    _run(_t)
    _cleanup()
