"""Phase F4 · Feb-2026 — /health/live + /health/ready probe split.

Uses httpx.ASGITransport for real ASGI round-trips against ``app`` so
we exercise the full FastAPI response envelope (JSONResponse status
codes) rather than direct-function calls that bypass status_code
plumbing. Runs inside the same ``run_test`` loop harness as F3-F6c.
"""
from __future__ import annotations

import httpx

from tests._f7_loop_fixture import run_test


def _get_app():
    from server import app
    return app


def _get_state():
    import server as srv
    return srv._F4_BOOT_INTEGRITY_STATE


async def _ensure_perf_customers_migration(db):
    """Migrations gate requires ``perf_customers_v1`` — ensure the
    sentinel exists in the test DB even if the boot path was skipped."""
    from datetime import datetime, timezone
    await db.migration_status.update_one(
        {"key": "perf_customers_v1"},
        {"$setOnInsert": {"key": "perf_customers_v1",
                            "completed_at":
                                datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


# ─── /health/live ─────────────────────────────────────────────────────
def test_f4_health_live_is_200_no_deps():
    async def _go(_db):
        app = _get_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as ac:
            r = await ac.get("/health/live")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "alive"
            assert isinstance(body.get("uptime_seconds"), int)
            assert body["uptime_seconds"] >= 0
            assert "version" in body

    run_test(_go)


# ─── Legacy /health backward compat ──────────────────────────────────
def test_f4_legacy_health_still_200():
    async def _go(_db):
        app = _get_app()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                        base_url="http://test") as ac:
            r = await ac.get("/health")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert body["alias_of"] == "/health/live"

    run_test(_go)


# ─── /health/ready — boot pending ─────────────────────────────────────
def test_f4_health_ready_boot_pending_returns_503():
    async def _go(_db):
        state = _get_state()
        saved = dict(state)
        state["complete"] = False
        state["dangling_refs_total"] = None
        state["error"] = None
        try:
            app = _get_app()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                            base_url="http://test") as ac:
                r = await ac.get("/health/ready")
                assert r.status_code == 503
                body = r.json()
                assert body["status"] == "not_ready"
                reasons = [f.get("reason")
                           for f in body.get("failures") or []]
                assert "boot_integrity_pending" in reasons
        finally:
            state.update(saved)

    run_test(_go)


# ─── /health/ready — happy path (200) ─────────────────────────────────
def test_f4_health_ready_happy_path():
    async def _go(db):
        await _ensure_perf_customers_migration(db)
        state = _get_state()
        saved = dict(state)
        state["complete"] = True
        state["dangling_refs_total"] = 0
        state["error"] = None
        try:
            app = _get_app()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                            base_url="http://test") as ac:
                r = await ac.get("/health/ready")
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["status"] == "ready"
                assert body["checks"]["mongo"] == "ok"
                assert body["checks"]["integrity"] == "ok"
                assert body["checks"]["migrations"] == "ok"
        finally:
            state.update(saved)

    run_test(_go)


# ─── /health/ready — 503 with refs>0 AND enforce=true ────────────────
def test_f4_health_ready_503_when_dangling_refs_and_enforce_true():
    async def _go(_db):
        import os
        state = _get_state()
        saved = dict(state)
        prev_enf = os.environ.get("INTEGRITY_CHECK_ENFORCE")
        prev_ready = os.environ.get("HEALTH_READY_INTEGRITY_CHECK")
        os.environ["INTEGRITY_CHECK_ENFORCE"] = "true"
        os.environ["HEALTH_READY_INTEGRITY_CHECK"] = "true"
        state["complete"] = True
        state["dangling_refs_total"] = 5215
        state["error"] = None
        try:
            app = _get_app()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                            base_url="http://test") as ac:
                r = await ac.get("/health/ready")
                assert r.status_code == 503, r.text
                body = r.json()
                integ = [f for f in body.get("failures") or []
                         if f.get("check") == "integrity"]
                assert integ
                assert integ[0]["dangling_refs_total"] == 5215
        finally:
            state.update(saved)
            if prev_enf is None:
                os.environ.pop("INTEGRITY_CHECK_ENFORCE", None)
            else:
                os.environ["INTEGRITY_CHECK_ENFORCE"] = prev_enf
            if prev_ready is None:
                os.environ.pop("HEALTH_READY_INTEGRITY_CHECK", None)
            else:
                os.environ["HEALTH_READY_INTEGRITY_CHECK"] = prev_ready

    run_test(_go)


# ─── /health/ready — 200 with refs>0 AND enforce=false (preview) ─────
def test_f4_health_ready_ok_when_enforce_false():
    async def _go(db):
        import os
        await _ensure_perf_customers_migration(db)
        state = _get_state()
        saved = dict(state)
        prev = os.environ.get("INTEGRITY_CHECK_ENFORCE")
        os.environ["INTEGRITY_CHECK_ENFORCE"] = "false"
        state["complete"] = True
        state["dangling_refs_total"] = 42
        state["error"] = None
        try:
            app = _get_app()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                            base_url="http://test") as ac:
                r = await ac.get("/health/ready")
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["status"] == "ready"
                assert body["dangling_refs_total"] == 42
        finally:
            state.update(saved)
            if prev is None:
                os.environ.pop("INTEGRITY_CHECK_ENFORCE", None)
            else:
                os.environ["INTEGRITY_CHECK_ENFORCE"] = prev

    run_test(_go)


# ─── /health/ready — kill switch bypasses integrity gate ─────────────
def test_f4_health_ready_kill_switch_bypasses_integrity():
    async def _go(db):
        import os
        await _ensure_perf_customers_migration(db)
        state = _get_state()
        saved = dict(state)
        prev_enf = os.environ.get("INTEGRITY_CHECK_ENFORCE")
        prev_ready = os.environ.get("HEALTH_READY_INTEGRITY_CHECK")
        os.environ["INTEGRITY_CHECK_ENFORCE"] = "true"
        os.environ["HEALTH_READY_INTEGRITY_CHECK"] = "false"
        state["complete"] = True
        state["dangling_refs_total"] = 5215
        state["error"] = None
        try:
            app = _get_app()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport,
                                            base_url="http://test") as ac:
                r = await ac.get("/health/ready")
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["checks"]["integrity"] == "ok"
        finally:
            state.update(saved)
            if prev_enf is None:
                os.environ.pop("INTEGRITY_CHECK_ENFORCE", None)
            else:
                os.environ["INTEGRITY_CHECK_ENFORCE"] = prev_enf
            if prev_ready is None:
                os.environ.pop("HEALTH_READY_INTEGRITY_CHECK", None)
            else:
                os.environ["HEALTH_READY_INTEGRITY_CHECK"] = prev_ready

    run_test(_go)
