"""Feb-2026 Enhancement — `logo_updated_*` audit stamps on
``GET /api/tenants/current``.

The POST /tenants/branding/logo endpoint has stamped ``logo_updated_at``
+ ``logo_updated_by_user_id`` on the tenant row since the TD-08
ship. This test file locks in the corresponding READ contract:
``GET /tenants/current`` MUST surface those stamps plus a resolved
``logo_updated_by_name`` (best-effort join against the users
collection). Absence of a stamp → all three fields null (empty
state).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import pytest

from routers import tenants as tenants_router


class _FakeColl:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    async def find_one(self, q, projection=None):
        for r in self._rows:
            if all(r.get(k) == v for k, v in q.items()):
                return dict(r)
        return None


class _FakeDb:
    def __init__(self, tenants=None, users=None):
        self.tenants = _FakeColl(tenants or [])
        self.users = _FakeColl(users or [])


def _tenant_row(**overrides) -> Dict[str, Any]:
    base = {
        "id": "t-1", "slug": "acme", "name": "Acme Pools",
        "brand_primary": None, "brand_secondary": None,
        "custom_domain": None, "plan_tier": None,
        "logo_url": None, "timezone": "America/Phoenix",
    }
    base.update(overrides)
    return base


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeRequest:
    def __init__(self):
        self.headers = {}


def _call_current(monkeypatch, tenant_row, user_row=None,
                   extra_users=None):
    users_list = []
    if extra_users:
        users_list.extend(extra_users)
    fake_db = _FakeDb(tenants=[tenant_row], users=users_list)
    monkeypatch.setattr(tenants_router, "db", fake_db)
    user = user_row or {"id": "u-caller", "tenant_id": tenant_row["id"],
                          "role": "admin"}
    return _run(tenants_router.current_tenant(
        _FakeRequest(), tenant=tenant_row, user=user,
    ))


def test_current_returns_all_three_logo_stamps_when_populated(monkeypatch):
    tenant = _tenant_row(
        logo_url="/api/objects/foo/bar.png",
        logo_updated_at="2026-02-14T10:00:00+00:00",
        logo_updated_by_user_id="u-actor",
    )
    users = [{"id": "u-actor", "name": "Brian Beckman",
               "email": "brian@aquaterra.com"}]
    resp = _call_current(monkeypatch, tenant, extra_users=users)
    assert resp["logo_updated_at"] == "2026-02-14T10:00:00+00:00"
    assert resp["logo_updated_by"] == "u-actor"
    assert resp["logo_updated_by_name"] == "Brian Beckman"


def test_current_returns_null_stamps_when_never_uploaded(monkeypatch):
    tenant = _tenant_row(logo_url=None)
    resp = _call_current(monkeypatch, tenant)
    assert resp["logo_updated_at"] is None
    assert resp["logo_updated_by"] is None
    assert resp["logo_updated_by_name"] is None


def test_current_falls_back_to_email_when_actor_has_no_name(monkeypatch):
    tenant = _tenant_row(
        logo_url="/api/objects/foo/bar.png",
        logo_updated_at="2026-02-14T10:00:00+00:00",
        logo_updated_by_user_id="u-noname",
    )
    users = [{"id": "u-noname", "name": None,
               "email": "svc@aquaterra.com"}]
    resp = _call_current(monkeypatch, tenant, extra_users=users)
    assert resp["logo_updated_by_name"] == "svc@aquaterra.com"


def test_current_returns_none_when_actor_user_deleted(monkeypatch):
    tenant = _tenant_row(
        logo_url="/api/objects/foo/bar.png",
        logo_updated_at="2026-02-14T10:00:00+00:00",
        logo_updated_by_user_id="u-ghost",
    )
    # No matching user row in the users collection.
    resp = _call_current(monkeypatch, tenant, extra_users=[])
    assert resp["logo_updated_by"] == "u-ghost"
    assert resp["logo_updated_by_name"] is None
