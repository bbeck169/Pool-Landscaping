"""P0 · Feb-2026 — Read-only recurring-jobs audit endpoint tests.

Pins two surfaces of
``routers/admin_recurring_jobs_audit.py``:

  1. ``_classify`` — the server-side classification helper that
     maps the 5 branches of the P0 ticket to one of
     ``preview_clean`` / ``convention_mismatch_suspected`` /
     ``cursor_stuck`` / ``silent_materializer_failure`` /
     ``unknown``.
  2. End-to-end endpoint shape — admin-gated, read-only, returns
     the full response contract keys without exploding when the
     DB has data (preview smoke test — the live preview DB
     has 18 Tuesday templates + 18 jobs on 2026-10-13, so the
     ``preview_clean`` branch should resolve).

No DB writes anywhere.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
# Guarantee the module-level MONGO_URL / DB_NAME exist so ``config``
# imports cleanly; the test uses the live preview Mongo (same as
# the other integration-style tests in this directory).
for _k in ("MONGO_URL", "DB_NAME"):
    if _k not in os.environ and _BE.get(_k):
        os.environ[_k] = _BE[_k]


# ─── §1 · _classify — 5-branch coverage ──────────────────────────

def test_classify_preview_clean():
    """``jobs == python_match > 0`` → ``preview_clean``."""
    from routers.admin_recurring_jobs_audit import _classify
    assert _classify(
        jobs_template_origin=18, python_match=18, js_match=21,
        cursors_python=[{"_id": "2026-10-27", "n": 18}],
        target_date="2026-10-13",
    ) == "preview_clean"


def test_classify_convention_mismatch_suspected():
    """``js_match >> python_match`` → convention mismatch."""
    from routers.admin_recurring_jobs_audit import _classify
    assert _classify(
        jobs_template_origin=2, python_match=2, js_match=15,
        cursors_python=[{"_id": "2026-10-13", "n": 2}],
        target_date="2026-10-13",
    ) == "convention_mismatch_suspected"


def test_classify_cursor_stuck():
    """Under-counted jobs + at least one cursor < target → stuck."""
    from routers.admin_recurring_jobs_audit import _classify
    assert _classify(
        jobs_template_origin=2, python_match=15, js_match=0,
        cursors_python=[
            {"_id": "2026-10-06", "n": 10},  # stuck
            {"_id": "2026-10-20", "n": 5},
        ],
        target_date="2026-10-13",
    ) == "cursor_stuck"


def test_classify_silent_materializer_failure():
    """Under-counted jobs + ALL cursors ≥ target → silent fail."""
    from routers.admin_recurring_jobs_audit import _classify
    assert _classify(
        jobs_template_origin=2, python_match=15, js_match=0,
        cursors_python=[
            {"_id": "2026-10-20", "n": 10},
            {"_id": "2026-10-27", "n": 5},
        ],
        target_date="2026-10-13",
    ) == "silent_materializer_failure"


def test_classify_unknown_falls_through():
    """No signal matches any branch → ``unknown``."""
    from routers.admin_recurring_jobs_audit import _classify
    assert _classify(
        jobs_template_origin=0, python_match=0, js_match=0,
        cursors_python=[],
        target_date="2026-10-13",
    ) == "unknown"


# ─── §2 · Host-redaction helper ──────────────────────────────────

def test_redact_mongo_host_strips_credentials():
    """``user:pass@host`` → ``host``."""
    from routers.admin_recurring_jobs_audit import _redact_mongo_host
    assert _redact_mongo_host(
        "mongodb+srv://user:pass@cluster0.abc.mongodb.net/db?opts=1",
    ) == "cluster0.abc.mongodb.net"
    assert _redact_mongo_host("mongodb://localhost:27017") == "localhost:27017"
    assert _redact_mongo_host(None) == ""
    assert _redact_mongo_host("") == ""


# ─── §3 · Endpoint shape + admin gate ────────────────────────────

def _make_app_with_fake_admin():
    """Build an isolated FastAPI with the audit router mounted and
    ``require_admin`` overridden to a stub that returns an admin
    user without hitting the real auth stack."""
    from routers import admin_recurring_jobs_audit as m
    from utils import require_admin
    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    def _fake_admin():
        return {"id": "test-admin", "role": "admin",
                "tenant_id": "test-tenant"}

    app.dependency_overrides[require_admin] = _fake_admin
    return app


def _run(coro):
    """Run coroutine on a dedicated loop and ensure the Motor
    client in ``config.db`` is bound to that same loop.  Motor's
    AsyncIOMotorClient captures the running loop at the moment
    it issues its first I/O call; by resetting ``_io_loop`` the
    client re-attaches to the test loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Re-point the shared Motor client at the current loop.
        # ``config.db`` is a Database handle whose underlying
        # client (``.client``) carries a ``_io_loop`` ref.
        import config as _cfg
        try:
            _cfg.db.client._io_loop = loop  # noqa: SLF001
        except Exception:
            pass
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_endpoint_returns_full_contract_shape_against_preview_db():
    """Smoke test — hit the endpoint with a known-good date and
    assert every top-level key in the response contract is
    present with the right type. Uses the live preview Mongo
    (same wiring every integration test in this directory relies on)."""
    app = _make_app_with_fake_admin()

    async def _go():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                "/api/admin/diagnostics/recurring-jobs-audit",
                params={"date": "2026-10-13"},
            )

    r = _run(_go())
    assert r.status_code == 200, r.text
    body = r.json()
    # Top-level contract keys.
    for k in ("env", "target", "jobs_on_date",
              "active_templates_by_convention",
              "dow_distribution_weekly_active",
              "cursor_distribution", "per_template_sample",
              "classification_hint"):
        assert k in body, f"missing contract key: {k}"
    # Target shape.
    assert body["target"]["date"] == "2026-10-13"
    assert body["target"]["weekday_name"] == "Tuesday"
    assert body["target"]["day_of_week_python"] == 1
    assert body["target"]["day_of_week_js"] == 2
    # jobs_on_date subkeys.
    assert set(body["jobs_on_date"].keys()) == {
        "template_origin_not_deleted",
        "template_origin_including_deleted",
        "all_origins",
    }
    # Convention counts both present.
    assert "python_weekday_match" in body["active_templates_by_convention"]
    assert "js_getday_match" in body["active_templates_by_convention"]
    # dow distribution has 7 enum rows + 1 null sentinel.
    assert len(body["dow_distribution_weekly_active"]) == 8
    assert body["dow_distribution_weekly_active"][-1]["day_of_week"] is None
    # Sample capped at 20.
    assert len(body["per_template_sample"]) <= 20
    # Mongo host redacted (no @ sign).
    assert "@" not in (body["env"]["mongo_host_redacted"] or "")
    # Classification is one of the 5 string values.
    assert body["classification_hint"] in {
        "preview_clean", "convention_mismatch_suspected",
        "cursor_stuck", "silent_materializer_failure", "unknown",
    }


def test_endpoint_rejects_malformed_date():
    """Non-ISO ``date`` param → 400."""
    app = _make_app_with_fake_admin()

    async def _go():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                "/api/admin/diagnostics/recurring-jobs-audit",
                params={"date": "not-a-date"},
            )

    r = _run(_go())
    assert r.status_code == 400
    assert "YYYY-MM-DD" in r.text


def test_endpoint_defaults_date_to_today_when_param_omitted():
    """``date`` param omitted → defaults to today (server TZ)."""
    from datetime import date as _d
    app = _make_app_with_fake_admin()

    async def _go():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                "/api/admin/diagnostics/recurring-jobs-audit",
            )

    r = _run(_go())
    assert r.status_code == 200
    body = r.json()
    assert body["target"]["date"] == _d.today().isoformat()


def test_endpoint_requires_admin():
    """Without the ``require_admin`` override, the endpoint should
    reject unauthenticated callers.  We hit the un-overridden
    FastAPI with the real auth dep; ``get_current_user`` raises
    401 when no bearer is present, so FastAPI returns 401."""
    from routers import admin_recurring_jobs_audit as m
    app = FastAPI()
    app.include_router(m.router, prefix="/api")

    async def _go():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get(
                "/api/admin/diagnostics/recurring-jobs-audit",
                params={"date": "2026-10-13"},
            )

    r = _run(_go())
    # 401 (no token) OR 403 (token present but non-admin) — both
    # count as "admin gate is wired".
    assert r.status_code in (401, 403), r.text
