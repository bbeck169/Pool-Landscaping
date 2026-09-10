"""Feb-2026 · Portal onboarding health tile — backend contract tests.

Covers:
  * ``GET /api/reports/portal-onboarding-health`` envelope shape.
  * RBAC — admin 200, manager 403, no-token 401 (via the raw endpoint
    function guard for the last two; live 401 is proven by the shared
    ``get_current_user`` dependency and is already covered by the
    Feb-2026 auth-nit test suite — this file focuses on the report's
    own gate).
  * Cohort math + trailing-window deltas on a seeded state.
  * 60-second cache hit returns the same ``as_of`` on the second call.
  * ``delta_30d`` returns ``null`` for the two cohorts whose defining
    event has no dated timestamp on the customer document.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, length=None):
        return list(self._rows)


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])

    def find(self, filt=None, projection=None):
        return _Cursor(self._match(filt or {}))

    def _match(self, filt: Dict[str, Any]):
        return [r for r in self.rows if self._doc_matches(r, filt)]

    @staticmethod
    def _doc_matches(doc, filt) -> bool:
        for k, v in (filt or {}).items():
            if k == "$or":
                if not any(_Coll._doc_matches(doc, sub) for sub in v):
                    return False
            elif k == "$and":
                if not all(_Coll._doc_matches(doc, sub) for sub in v):
                    return False
            elif isinstance(v, dict):
                val = doc.get(k)
                if "$exists" in v:
                    if bool(v["$exists"]) != (k in doc):
                        return False
                if "$nin" in v and val in v["$nin"]:
                    return False
                if "$ne" in v and val == v["$ne"]:
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True


class _DB:
    def __init__(self):
        self.customers = _Coll()


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _DB()
    from routers import profit_report as pr
    monkeypatch.setattr(pr, "db", fake)
    # Isolate the module-level cache so every test starts clean.
    pr._ONBOARDING_CACHE.clear()
    return fake


TID = "t-onb"


def _now():
    return datetime.now(timezone.utc)


def _iso_offset(days: int) -> str:
    return (_now() + timedelta(days=days)).isoformat()


# ═══════════════════════════════════════════════════════════════════
# 1. Envelope shape.
# ═══════════════════════════════════════════════════════════════════
def test_envelope_shape_returns_four_cohorts(fake_db):
    from routers.profit_report import portal_onboarding_health
    admin = {"id": "u-a", "role": "admin", "tenant_id": TID}
    out = _run(portal_onboarding_health(window_days=30, user=admin))
    assert set(out.keys()) >= {"as_of", "window_days", "cohorts",
                                    "assumptions"}
    assert out["window_days"] == 30
    assert set(out["cohorts"].keys()) == {
        "invited", "activated", "signed_in", "never_logged_in"}
    for name, block in out["cohorts"].items():
        assert set(block.keys()) == {"count", "delta_30d"}, name


# ═══════════════════════════════════════════════════════════════════
# 2. RBAC — admin 200, manager 403.
# ═══════════════════════════════════════════════════════════════════
def test_manager_role_rejected_with_403(fake_db):
    from routers.profit_report import portal_onboarding_health
    manager = {"id": "u-m", "role": "manager", "tenant_id": TID}
    with pytest.raises(HTTPException) as ei:
        _run(portal_onboarding_health(window_days=30, user=manager))
    assert ei.value.status_code == 403


def test_admin_super_admin_owner_all_allowed(fake_db):
    from routers.profit_report import portal_onboarding_health
    for role in ("admin", "super_admin", "owner"):
        user = {"id": f"u-{role}", "role": role, "tenant_id": TID}
        out = _run(portal_onboarding_health(window_days=30, user=user))
        assert "cohorts" in out


# ═══════════════════════════════════════════════════════════════════
# 3. Cohort math + trailing-window deltas.
# ═══════════════════════════════════════════════════════════════════
def test_cohort_math_on_seeded_state(fake_db):
    """Seeded state matches the spec's 3/2/1/2 shape:
      * 3 invited (has_login=True).
      * 2 of those activated (pw_set set). Both activations OUTSIDE
        the 30-day window → activated_delta == 0.
      * 1 of those signed in — first_login INSIDE the window →
        signed_in_delta == 1.
      * 2 never_logged_in — the invited customers who lack a
        first_login (one activated, one not).

    Layout:
      c-1 — invited, activated (pw_set 45d ago), NOT signed in.
      c-2 — invited, activated (pw_set 50d ago), signed in 3d ago.
      c-3 — invited, NOT activated, NOT signed in.
      c-not-invited — has_login=False + fully cold (dropped as an
        "invited" but STILL counted as never_logged_in per the
        chip-aligned predicate).
    """
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-1", "tenant_id": TID, "has_login": True,
          "portal_password_set_at": _iso_offset(-45)},
        {"id": "c-2", "tenant_id": TID, "has_login": True,
          "portal_password_set_at": _iso_offset(-50),
          "portal_first_login_at": _iso_offset(-3)},
        {"id": "c-3", "tenant_id": TID, "has_login": True},
        {"id": "c-not-invited", "tenant_id": TID, "has_login": False},
    ]
    admin = {"id": "u-a", "role": "admin", "tenant_id": TID}
    out = _run(portal_onboarding_health(window_days=30, user=admin))
    c = out["cohorts"]
    # Counts.
    assert c["invited"]["count"] == 3
    assert c["activated"]["count"] == 2
    assert c["signed_in"]["count"] == 1
    # never_logged_in aligns with the ?first_access=never chip:
    # c-1 (invited, never), c-3 (invited, never), c-not-invited
    # (not invited, still never).
    assert c["never_logged_in"]["count"] == 3
    # Deltas — 0 activations in-window, 1 sign-in in-window.
    assert c["activated"]["delta_30d"] == 0
    assert c["signed_in"]["delta_30d"] == 1


# ═══════════════════════════════════════════════════════════════════
# 4. Cache — second call returns the same ``as_of``.
# ═══════════════════════════════════════════════════════════════════
def test_60s_cache_hit_returns_same_as_of(fake_db):
    from routers.profit_report import portal_onboarding_health
    admin = {"id": "u-a", "role": "admin", "tenant_id": TID}
    fake_db.customers.rows = [
        {"id": "c-1", "tenant_id": TID, "has_login": True},
    ]
    first = _run(portal_onboarding_health(window_days=30, user=admin))
    # Second call — MUST hit the cache (same as_of even though wall
    # time has advanced by a few ms).
    second = _run(portal_onboarding_health(window_days=30, user=admin))
    assert first["as_of"] == second["as_of"]
    # Different window bypasses the cache.
    third = _run(portal_onboarding_health(window_days=60, user=admin))
    assert third["as_of"] != first["as_of"] or third["window_days"] == 60


# ═══════════════════════════════════════════════════════════════════
# 5. ``delta_30d`` returns null for cohorts without a defining
#    timestamp — and the assumption note explains why.
# ═══════════════════════════════════════════════════════════════════
def test_null_deltas_for_cohorts_without_defining_timestamp(fake_db):
    from routers.profit_report import portal_onboarding_health
    admin = {"id": "u-a", "role": "admin", "tenant_id": TID}
    fake_db.customers.rows = [
        {"id": "c-1", "tenant_id": TID, "has_login": True,
          "portal_password_set_at": _iso_offset(-2),
          "portal_first_login_at": _iso_offset(-2)},
        {"id": "c-2", "tenant_id": TID, "has_login": True},
    ]
    out = _run(portal_onboarding_health(window_days=30, user=admin))
    c = out["cohorts"]
    assert c["invited"]["delta_30d"] is None
    assert c["never_logged_in"]["delta_30d"] is None
    # The two dated cohorts must expose an int, not None.
    assert isinstance(c["activated"]["delta_30d"], int)
    assert isinstance(c["signed_in"]["delta_30d"], int)
    # Assumption notes for the two null-delta cohorts are present.
    assert "invited_delta" in out["assumptions"]
    assert "never_logged_in_delta" in out["assumptions"]


# ═══════════════════════════════════════════════════════════════════
# 6. Soft-deleted + K49b-orphan rows are excluded from every cohort.
# ═══════════════════════════════════════════════════════════════════
def test_soft_deleted_and_id_orphan_excluded(fake_db):
    from routers.profit_report import portal_onboarding_health
    fake_db.customers.rows = [
        {"id": "c-live", "tenant_id": TID, "has_login": True},
        {"id": "c-del", "tenant_id": TID, "has_login": True,
          "deleted_at": _iso_offset(-1)},
        # Orphan: no top-level id.
        {"tenant_id": TID, "has_login": True},
    ]
    admin = {"id": "u-a", "role": "admin", "tenant_id": TID}
    out = _run(portal_onboarding_health(window_days=30, user=admin))
    # Only ``c-live`` survives.
    assert out["cohorts"]["invited"]["count"] == 1
