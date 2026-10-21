"""TD-96-mobile-reap-be · Feb-2026 — regression test for the retirement
of ``POST /leads/{lid}/convert-to-job`` + ``POST /leads/{lid}/convert-to-quote``.

Both routes were last called by the mobile Leads screen's convert
sheet, which was reaped as unreachable in ``a141e1366``
(TD-96-mobile-reap-fe).  Web + mobile production both use the
unified ``POST /leads/{lid}/convert`` instead.  The handlers now
return 410 Gone with a migration pointer.

The companion pytest ``test_iteration28_lead_convert.py`` (which
exercised the pre-retirement happy paths) was removed in this
ship — it would otherwise fail on every assertion because the
routes no longer accept a request body or create a job/quote.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _build_app():
    from routers import leads as leads_mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user, require_admin

    user = {"id": "u1", "role": "admin", "tenant_id": "t1"}
    tenant = {"id": "t1"}

    app = FastAPI()
    app.include_router(leads_mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    app.dependency_overrides[require_admin] = lambda: user
    return app


async def _call(route, body=None):
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post(route, json=body or {})


def test_convert_to_job_returns_410_gone():
    r = _run(_call("/api/leads/any-lid/convert-to-job"))
    assert r.status_code == 410
    assert "retired" in r.json().get("detail", "").lower()
    assert "/leads/{lid}/convert" in r.json().get("detail", "")


def test_convert_to_quote_returns_410_gone():
    r = _run(_call("/api/leads/any-lid/convert-to-quote"))
    assert r.status_code == 410
    assert "retired" in r.json().get("detail", "").lower()
    assert "/leads/{lid}/convert" in r.json().get("detail", "")


def test_convert_live_route_not_affected():
    """Smoke: the still-live ``POST /leads/{lid}/convert`` route
    (web LeadsDashboardPage + mobile d2d both call this) is NOT
    retired. We check route presence on the router (no DB hit) to
    confirm the retirement scope didn't accidentally delete the
    sibling handler."""
    from routers import leads as leads_mod
    paths = {r.path for r in leads_mod.router.routes}
    assert "/leads/{lid}/convert" in paths, (
        "POST /leads/{lid}/convert must stay registered — do NOT "
        "retire it as part of TD-96-mobile-reap-be"
    )
    # And the retired paths DO stay registered (so FastAPI returns
    # 410 from the handler, not 404 from the router).
    assert "/leads/{lid}/convert-to-job" in paths
    assert "/leads/{lid}/convert-to-quote" in paths
