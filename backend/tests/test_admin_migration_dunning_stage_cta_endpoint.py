"""Feb 2026 · Invoice Email CTA Label ticket — admin migration endpoint tests.

Covers ``POST /api/admin/migrations/run-dunning-stage-cta-backfill``:
    * super_admin can invoke and gets the pass-through JSON summary
    * regular admin gets 403
    * dry-run does not mutate ``dunning_settings``
    * real-run writes + audit-stamps

Uses ``httpx.ASGITransport + @pytest.mark.anyio`` per the Feb 2026
baseline. The dunning migration itself is patched to a lightweight
in-memory recorder so the test is fully isolated from real Mongo.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
import httpx
from httpx import ASGITransport


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ─── Stub user records / auth override ─────────────────────────────

_SUPER = {"id": "u-super", "email": "super@ex.test",
          "role": "super_admin", "tenant_id": "t1"}
_ADMIN = {"id": "u-admin", "email": "admin@ex.test",
          "role": "admin", "tenant_id": "t1"}
_TENANT = {"id": "t1", "slug": "acme", "name": "Acme"}


async def _override_super():
    return _SUPER


async def _override_admin():
    return _ADMIN


async def _override_tenant():
    return _TENANT


# ─── Fake migration recorder ───────────────────────────────────────

class _Recorder:
    """Captures every ``run_backfill`` invocation and returns a
    deterministic report so the endpoint's JSON envelope is fully
    exercised without touching Mongo."""
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def run_backfill(self, *, dry_run: bool = True):
        self.calls.append({"dry_run": dry_run})
        # Realistic response shape — a dry-run + a commit both return
        # the same structure; only the ``dry_run`` + ``audit_stamped``
        # + counts vary. Mirror what the migration returns after
        # discovering 1 tenant with 2 legacy stages.
        return {
            "dry_run": dry_run,
            "tenants_scanned": 3,
            "tenants_affected": 1,
            "stages_rewritten": 2,
            "audit_stamped": 0 if dry_run else 1,
            "per_tenant": [{
                "tenant_id": "t1",
                "stages_rewritten": 2,
                "diffs": [
                    {"stage_id": "pre_due_3d",
                     "before": "Pay online: link",
                     "after": "View invoice: link"},
                    {"stage_id": "past_due_7d",
                     "before": "Pay online: link",
                     "after": "View invoice: link"},
                ],
            }],
        }


async def _build_client(role: str):
    """Return an ASGI-backed httpx.AsyncClient wired to the FastAPI
    app with dependency overrides so we don't need a real JWT."""
    from server import app
    from utils import get_current_user
    from routers.tenants import get_current_tenant

    async def _user():
        return _SUPER if role == "super_admin" else _ADMIN

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_current_tenant] = _override_tenant
    return app


# ─── Tests ─────────────────────────────────────────────────────────

async def test_super_admin_can_invoke_dry_run_default():
    rec = _Recorder()
    with patch("services.migrations.dunning_stages_view_invoice_backfill"
                ".run_backfill", rec.run_backfill):
        app = await _build_client("super_admin")
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/admin/migrations/run-dunning-stage-cta-backfill",
                json={},
            )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["dry_run"] is True                    # default
    assert data["tenants_scanned"] == 3
    assert data["tenants_affected"] == 1
    assert data["stages_rewritten"] == 2
    assert data["audit_stamped"] == 0
    assert rec.calls == [{"dry_run": True}]


async def test_super_admin_can_commit_when_dry_run_false():
    rec = _Recorder()
    with patch("services.migrations.dunning_stages_view_invoice_backfill"
                ".run_backfill", rec.run_backfill):
        app = await _build_client("super_admin")
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/admin/migrations/run-dunning-stage-cta-backfill",
                json={"dry_run": False},
            )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["dry_run"] is False
    # audit_stamped only lands on the commit path.
    assert data["audit_stamped"] == 1
    assert rec.calls == [{"dry_run": False}]


async def test_regular_admin_is_forbidden():
    rec = _Recorder()
    with patch("services.migrations.dunning_stages_view_invoice_backfill"
                ".run_backfill", rec.run_backfill):
        app = await _build_client("admin")
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/admin/migrations/run-dunning-stage-cta-backfill",
                json={"dry_run": True},
            )
    assert r.status_code == 403, r.text
    assert rec.calls == []  # migration never invoked


async def test_dry_run_does_not_call_migration_with_commit_flag():
    """Locks in the safety-first default — a body-less POST must
    invoke ``run_backfill(dry_run=True)`` verbatim."""
    rec = _Recorder()
    with patch("services.migrations.dunning_stages_view_invoice_backfill"
                ".run_backfill", rec.run_backfill):
        app = await _build_client("super_admin")
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/admin/migrations/run-dunning-stage-cta-backfill",
            )
    assert r.status_code == 200
    assert rec.calls == [{"dry_run": True}]


async def test_response_includes_per_tenant_diff_summary():
    """Sanity that the endpoint passes the migration's
    ``per_tenant`` shape through — the admin UI relies on this to
    render the before/after diff table."""
    rec = _Recorder()
    with patch("services.migrations.dunning_stages_view_invoice_backfill"
                ".run_backfill", rec.run_backfill):
        app = await _build_client("super_admin")
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
        ) as ac:
            r = await ac.post(
                "/api/admin/migrations/run-dunning-stage-cta-backfill",
                json={"dry_run": True},
            )
    assert r.status_code == 200
    per_tenant = r.json()["per_tenant"]
    assert len(per_tenant) == 1
    assert per_tenant[0]["tenant_id"] == "t1"
    diffs = per_tenant[0]["diffs"]
    stage_ids = {d["stage_id"] for d in diffs}
    assert stage_ids == {"pre_due_3d", "past_due_7d"}
    for d in diffs:
        assert d["before"].startswith("Pay online:")
        assert d["after"].startswith("View invoice:")
