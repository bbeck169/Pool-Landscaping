"""TD-64 · Feb-2026 — GET /api/auth/me surfaces effective_department +
show_time_clock.

Validates that the Time Clock designation gate is exposed on the
current-user payload so the web + mobile clients can hide the
entire Time Clock surface for pool techs without duplicating
``_resolve_tech_department`` / ``_LANDSCAPE_DEPTS`` logic.

Contract:
  * ``effective_department`` → the BE-resolved department (dual
    source: ``db.users.department`` wins, falls back to
    ``db.technicians.department`` for the pre-denorm cohort).
  * ``show_time_clock`` → boolean; true iff normalized
    ``effective_department`` is in ``_LANDSCAPE_DEPTS``.
  * Case + whitespace tolerance via the shared helper
    (``_resolve_tech_department`` returns the whitespace-stripped
    value; the ``show_time_clock`` boolean then lower-cases it
    before the frozenset check).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from dotenv import load_dotenv


load_dotenv("/app/backend/.env")


# ─────────────────────────────────────────────────────────────────
# Harness — call the ``me`` handler directly with a fake user doc.
# ─────────────────────────────────────────────────────────────────
def _call_me(user_doc, tech_doc=None):
    """Invoke ``auth.me`` with a stubbed ``get_current_user`` payload
    + a stubbed ``db.technicians.find_one`` return value.  Returns
    the full ``/auth/me`` payload."""
    from routers import auth as _auth
    from routers import timeclock_landscaping as _tl

    class _FakeColl:
        async def find_one(self, *_a, **_kw):
            return tech_doc

    # Patch the two surfaces the handler reads: tenants + technicians.
    _patch_tenants = AsyncMock(return_value=None)
    _patch_user_tenants = AsyncMock(return_value=[])
    with patch.object(_auth.db, "tenants", _patch_tenants_wrap(_patch_tenants)):
        with patch.object(_tl, "db", _FakeDbForTl(tech_doc)):
            with patch(
                "services.user_tenants.get_user_tenants",
                _patch_user_tenants,
            ):
                return asyncio.run(_auth.me(user_doc))


class _FakeDbForTl:
    def __init__(self, tech_doc):
        self._tech_doc = tech_doc

    class _TechniciansColl:
        def __init__(self, doc):
            self._doc = doc

        async def find_one(self, *_a, **_kw):
            return self._doc

    @property
    def technicians(self):
        return _FakeDbForTl._TechniciansColl(self._tech_doc)


def _patch_tenants_wrap(mock_find_one):
    class _TenantsColl:
        async def find_one(self, *_a, **_kw):
            return None
    return _TenantsColl()


# ─────────────────────────────────────────────────────────────────
# 1 · Landscaping tech with users.department populated.
# ─────────────────────────────────────────────────────────────────
def test_landscaping_tech_users_dept_sets_show_time_clock_true():
    user = {
        "id": "u-ls-1", "tenant_id": "t-A", "role": "technician",
        "technician_id": "tech-ls-1",
        "department": "landscaping",
    }
    payload = _call_me(user, tech_doc=None)
    assert payload["effective_department"] == "landscaping"
    assert payload["show_time_clock"] is True


# ─────────────────────────────────────────────────────────────────
# 2 · Landscaping tech with ``users.department`` NULL but
#     ``technicians.department`` populated (denormalized cohort).
# ─────────────────────────────────────────────────────────────────
def test_landscaping_tech_falls_back_to_technicians_department():
    user = {
        "id": "u-ls-2", "tenant_id": "t-A", "role": "technician",
        "technician_id": "tech-ls-2",
        "department": None,
    }
    payload = _call_me(
        user,
        tech_doc={"id": "tech-ls-2", "department": "landscaper"},
    )
    assert payload["effective_department"] == "landscaper"
    assert payload["show_time_clock"] is True


# ─────────────────────────────────────────────────────────────────
# 3 · Pool tech with users.department == "pool".
# ─────────────────────────────────────────────────────────────────
def test_pool_tech_show_time_clock_false():
    user = {
        "id": "u-pool-1", "tenant_id": "t-A", "role": "technician",
        "technician_id": "tech-pool-1",
        "department": "pool",
    }
    payload = _call_me(user, tech_doc=None)
    assert payload["effective_department"] == "pool"
    assert payload["show_time_clock"] is False


# ─────────────────────────────────────────────────────────────────
# 4 · Pool tech with department=="pool_tech".
# ─────────────────────────────────────────────────────────────────
def test_pool_tech_pool_tech_dept_still_hidden():
    user = {
        "id": "u-pool-2", "tenant_id": "t-A", "role": "technician",
        "technician_id": "tech-pool-2",
        "department": "pool_tech",
    }
    payload = _call_me(user, tech_doc=None)
    assert payload["effective_department"] == "pool_tech"
    assert payload["show_time_clock"] is False


# ─────────────────────────────────────────────────────────────────
# 5 · Admin user — show_time_clock False (field is tech-focused).
# ─────────────────────────────────────────────────────────────────
def test_admin_show_time_clock_false():
    user = {
        "id": "u-admin-1", "tenant_id": "t-A", "role": "admin",
        "department": None,
    }
    payload = _call_me(user, tech_doc=None)
    # Admin users typically carry no department; the helper returns
    # None → normalized to "" → NOT in the landscape set.
    assert payload["show_time_clock"] is False


# ─────────────────────────────────────────────────────────────────
# 6 · Case + whitespace normalization.
# ─────────────────────────────────────────────────────────────────
def test_show_time_clock_tolerant_of_case_and_whitespace():
    user = {
        "id": "u-ls-3", "tenant_id": "t-A", "role": "technician",
        "technician_id": "tech-ls-3",
        "department": " Landscaping ",
    }
    payload = _call_me(user, tech_doc=None)
    # ``_resolve_tech_department`` strips whitespace but preserves
    # the admin-entered casing; ``show_time_clock`` lower-cases
    # before the frozenset check so " Landscaping " still gates in.
    assert payload["effective_department"] == "Landscaping"
    assert payload["show_time_clock"] is True


# ─────────────────────────────────────────────────────────────────
# 7 · Regression — every pre-TD-64 /auth/me field is still present.
# ─────────────────────────────────────────────────────────────────
def test_me_preserves_pre_td64_fields():
    user = {
        "id": "u-ls-4", "tenant_id": "t-A", "role": "technician",
        "technician_id": "tech-ls-4",
        "department": "landscaping",
    }
    payload = _call_me(user, tech_doc=None)
    # Pre-TD-64 fields:
    for key in (
        "must_accept_tos", "auto_clockin_enabled",
        "available_tenants", "active_tenant_id",
        "tenant_memberships", "tenant_default_locale",
    ):
        assert key in payload, f"regression — pre-TD-64 field {key!r} dropped from /auth/me"
    # TD-64 fields:
    assert "effective_department" in payload
    assert "show_time_clock" in payload
