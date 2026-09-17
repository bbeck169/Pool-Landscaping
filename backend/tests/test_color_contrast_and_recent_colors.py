"""Feb-2026 · Global Custom Color Picker — backend acceptance suite.

Locks the contract for:
  * ``services/color/contrast.py::contrast_ratio_vs_white``
    (5 boundary cases: pure white, near-white, mid-gray, primary
    blue, black)
  * ``services/color/contrast.py::validate_color_hex_for_pin``
    raises HTTPException(400) with ``color_contrast_too_low`` for
    contrast < 3.0 (and ``color_hex_invalid`` for malformed inputs)
  * ``GET  /api/users/me/recent-colors`` returns ``[]`` when unset
  * ``POST /api/users/me/recent-colors`` — prepend, dedupe, cap 8
  * ``PATCH /api/team/users/{uid}`` with a low-contrast hex returns
    400 ``color_contrast_too_low`` (endpoint-level enforcement)

All async tests use the ``run_test + httpx.ASGITransport`` pattern.
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
TENANT_ID = "test-tenant-color-picker"
USER_ID = "user-recent-colors"
ADMIN_ID = "user-admin-color"


def _get_app():
    from server import app
    return app


def _sync_db():
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not (url and name):
        pytest.skip("MONGO_URL / DB_NAME not configured")
    return MongoClient(url)[name]


def _seed():
    db = _sync_db()
    db.tenants.delete_many({"id": TENANT_ID})
    db.tenants.insert_one({"id": TENANT_ID, "name": "T"})
    db.users.delete_many({"id": {"$in": [USER_ID, ADMIN_ID]}})
    db.users.insert_one({
        "id": USER_ID, "tenant_id": TENANT_ID,
        "email": "u@x", "role": "technician",
        "display_color_hex": "#3B82F6",
    })
    db.users.insert_one({
        "id": ADMIN_ID, "tenant_id": TENANT_ID,
        "email": "a@x", "role": "admin",
    })


def _install_overrides(*, as_user_id=USER_ID, role="technician"):
    from utils import get_current_user, require_admin
    from routers.tenants import get_current_tenant

    app = _get_app()

    async def _u():
        return {"id": as_user_id, "role": role,
                "email": "x@y", "tenant_id": TENANT_ID}

    async def _t():
        d = _sync_db().tenants.find_one({"id": TENANT_ID}) or {}
        d.pop("_id", None)
        return d

    async def _require_admin_dep():
        if role in ("admin", "super_admin"):
            return await _u()
        raise HTTPException(403, "admin only")

    app.dependency_overrides[get_current_user] = _u
    app.dependency_overrides[get_current_tenant] = _t
    app.dependency_overrides[require_admin] = _require_admin_dep

    def _clear():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_tenant, None)
        app.dependency_overrides.pop(require_admin, None)
    return _clear


def _run(coro, *, as_user_id=USER_ID, role="technician"):
    clear = _install_overrides(as_user_id=as_user_id, role=role)
    try:
        async def _go(db):
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(transport=transport,
                                                 base_url="http://test") as ac:
                await coro(ac, db)
        run_test(_go)
    finally:
        clear()


# ── Contrast validator utility (5 boundary cases) ────────────────
def test_contrast_pure_white_is_ratio_1():
    from services.color import contrast_ratio_vs_white
    assert contrast_ratio_vs_white("#FFFFFF") == pytest.approx(1.0, rel=1e-3)


def test_contrast_near_white_below_threshold():
    """``#F5F5F5`` (Tailwind gray-100) is too light — contrast ≈ 1.11."""
    from services.color import contrast_ratio_vs_white
    ratio = contrast_ratio_vs_white("#F5F5F5")
    assert ratio < 3.0


def test_contrast_mid_gray_boundary_around_3_0():
    """``#767676`` (WCAG's canonical 4.54:1) clears comfortably; a
    lighter gray fails. Locks the >= 3.0 boundary."""
    from services.color import contrast_ratio_vs_white
    assert contrast_ratio_vs_white("#767676") >= 3.0
    assert contrast_ratio_vs_white("#AAAAAA") < 3.0


def test_contrast_primary_blue_passes():
    """Palette blue ``#3B82F6`` — dominant tenant tech color, must
    always pass the guard."""
    from services.color import contrast_ratio_vs_white
    assert contrast_ratio_vs_white("#3B82F6") >= 3.0


def test_contrast_pure_black_is_maximum():
    from services.color import contrast_ratio_vs_white
    assert contrast_ratio_vs_white("#000000") == pytest.approx(21.0, rel=1e-2)


def test_validate_rejects_malformed_and_low_contrast():
    from services.color import validate_color_hex_for_pin
    # Malformed → color_hex_invalid.
    with pytest.raises(HTTPException) as ei_bad:
        validate_color_hex_for_pin("not-a-color")
    assert ei_bad.value.status_code == 400
    assert ei_bad.value.detail["code"] == "color_hex_invalid"
    # Low contrast → color_contrast_too_low.
    with pytest.raises(HTTPException) as ei_light:
        validate_color_hex_for_pin("#FEFEFE")
    assert ei_light.value.status_code == 400
    assert ei_light.value.detail["code"] == "color_contrast_too_low"
    assert ei_light.value.detail["min"] == 3.0
    # Happy path canonicalises to upper-case with leading ``#``.
    assert validate_color_hex_for_pin("3b82f6") == "#3B82F6"


# ── Recent-colors GET default + POST prepend/dedupe/cap ──────────
def test_recent_colors_get_returns_empty_when_unset():
    _seed()
    async def _t(ac, db):
        r = await ac.get("/api/users/me/recent-colors")
        assert r.status_code == 200, r.text
        assert r.json() == {"recent_colors": []}
    _run(_t)


def test_recent_colors_post_prepends_and_dedupes():
    _seed()
    async def _t(ac, db):
        # Push three unique colors (all clear WCAG 3.0 vs white).
        for hx in ("#3B82F6", "#059669", "#EC4899"):
            r = await ac.post("/api/users/me/recent-colors",
                                json={"color": hx})
            assert r.status_code == 200, r.text
        r = await ac.get("/api/users/me/recent-colors")
        assert r.json()["recent_colors"] == [
            "#EC4899", "#059669", "#3B82F6",
        ]
        # Push an existing color → moves it to the head, list stays
        # size 3 (dedupe by value).
        r2 = await ac.post("/api/users/me/recent-colors",
                             json={"color": "#3B82F6"})
        assert r2.json()["recent_colors"] == [
            "#3B82F6", "#EC4899", "#059669",
        ]
    _run(_t)


def test_recent_colors_capped_at_eight():
    _seed()
    async def _t(ac, db):
        _hexes = [
            "#3B82F6", "#059669", "#EC4899", "#EF4444",
            "#B45309", "#8B5CF6", "#0369A1", "#A21CAF",
            "#B91C1C",  # 9th push → oldest should fall off.
            "#0F766E",  # 10th
        ]
        for h in _hexes:
            r = await ac.post("/api/users/me/recent-colors",
                                json={"color": h})
            assert r.status_code == 200
        r = await ac.get("/api/users/me/recent-colors")
        got = r.json()["recent_colors"]
        assert len(got) == 8
        # Most-recent-first — head = last hex pushed.
        assert got[0] == "#0F766E"
        assert got[1] == "#B91C1C"
        # The first two pushed (``#3B82F6`` + ``#059669``) fell off.
        assert "#3B82F6" not in got
        assert "#059669" not in got
    _run(_t)


def test_recent_colors_post_rejects_low_contrast():
    _seed()
    async def _t(ac, db):
        r = await ac.post("/api/users/me/recent-colors",
                            json={"color": "#FFFFFF"})
        assert r.status_code == 400
        detail = r.json().get("detail") or r.json()
        assert detail.get("code") == "color_contrast_too_low"
    _run(_t)


# ── Endpoint-level guard on the existing team.py PATCH ────────────
def test_team_patch_color_hex_rejects_low_contrast():
    _seed()
    async def _t(ac, db):
        # Admin caller (dependency override) — target = the tech user.
        r = await ac.patch(
            f"/api/users/{USER_ID}",
            json={"display_color_hex": "#FEFEFE"},
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail") or r.json()
        assert detail.get("code") == "color_contrast_too_low"
    _run(_t, as_user_id=ADMIN_ID, role="admin")


def test_team_patch_color_hex_accepts_freeform_when_contrast_ok():
    """Post-Ticket, the endpoint no longer palette-locks — any
    ``#RRGGBB`` with contrast ≥ 3.0 lands successfully. Uses a
    non-palette hex to prove the lock was removed."""
    _seed()
    async def _t(ac, db):
        r = await ac.patch(
            f"/api/users/{USER_ID}",
            json={"display_color_hex": "#4B0082"},  # Indigo, off-palette
        )
        assert r.status_code == 200, r.text
        row = await db.users.find_one({"id": USER_ID}, {"_id": 0})
        assert row["display_color_hex"] == "#4B0082"
    _run(_t, as_user_id=ADMIN_ID, role="admin")


# ── Idempotent migration ─────────────────────────────────────────
def test_recent_colors_migration_is_idempotent():
    from services.migrations.users_recent_colors_defaults import backfill

    async def _t(ac, db):
        # First: seed a user without ``recent_colors`` so we have a
        # target.  Then run the migration twice and assert the
        # second run writes zero rows.
        await db.users.delete_many({"id": "mig-probe"})
        await db.users.insert_one({"id": "mig-probe",
                                    "tenant_id": TENANT_ID,
                                    "email": "m@x", "role": "technician"})
        r1 = await backfill(db)
        r2 = await backfill(db)
        assert r1["users_updated"] >= 1
        assert r2["users_updated"] == 0
        row = await db.users.find_one({"id": "mig-probe"}, {"_id": 0})
        assert row["recent_colors"] == []
        await db.users.delete_many({"id": "mig-probe"})
    _run(_t)
