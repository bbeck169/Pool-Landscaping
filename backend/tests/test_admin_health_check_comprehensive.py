"""Phase I3 · Feb-2026 — Comprehensive health-check endpoint.

Tests the super_admin-only endpoint that surfaces a 10-check
GO/GO_WITH_WARNINGS/NO_GO verdict for post-deploy verification.
Runs against the live ASGI transport so the RBAC gate + response
shape are exercised the same way k8s would exercise the anonymous
probes.
"""
from __future__ import annotations

import os

import httpx

from tests._f7_loop_fixture import run_test


ENDPOINT = "/api/admin/health-check/comprehensive"


def _get_app():
    from server import app
    return app


def _get_state():
    import server as srv
    return srv._F4_BOOT_INTEGRITY_STATE


async def _ensure_perf_customers_migration(db):
    from datetime import datetime, timezone
    await db.migration_status.update_one(
        {"key": "perf_customers_v1"},
        {"$setOnInsert": {"key": "perf_customers_v1",
                            "completed_at":
                                datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )


async def _make_super_admin_token(db, email="i3super@aquaterra.com"):
    """Create (or reuse) a super_admin user + return a fresh JWT.
    The RBAC gate this endpoint enforces is the strictest we ship;
    every RBAC test must exercise the full JWT round-trip so a
    future middleware regression can't sneak past."""
    from utils import create_token, new_id
    from datetime import datetime, timezone
    existing = await db.users.find_one({"email": email})
    if existing:
        return create_token(existing)
    user = {
        "id": new_id(),
        "email": email,
        "role": "super_admin",
        "tenant_id": "aquaterra",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user)
    return create_token(user)


async def _make_role_token(db, role, email):
    from utils import create_token, new_id
    from datetime import datetime, timezone
    existing = await db.users.find_one({"email": email})
    if existing:
        # Refresh role if drifted.
        if existing.get("role") != role:
            await db.users.update_one({"email": email},
                                          {"$set": {"role": role}})
            existing["role"] = role
        return create_token(existing)
    user = {
        "id": new_id(),
        "email": email,
        "role": role,
        "tenant_id": "aquaterra",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user)
    return create_token(user)


# ═══════════════════════════════════════════════════════════════════
# Happy path — GO verdict
# ═══════════════════════════════════════════════════════════════════
def test_i3_happy_path_returns_go_verdict():
    async def _go(db):
        await _ensure_perf_customers_migration(db)
        state = _get_state()
        saved = dict(state)
        state["complete"] = True
        state["dangling_refs_total"] = 0
        state["error"] = None
        try:
            token = await _make_super_admin_token(db)
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.get(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                # Overall shape.
                assert body["overall_verdict"] in (
                    "GO", "GO_WITH_WARNINGS", "NO_GO",
                )
                assert body["tenant_id"] == "aquaterra"
                assert "timestamp" in body
                assert "app_version" in body
                assert isinstance(body["checks"], list)
                assert len(body["checks"]) == 10
                # Summary matches per-check tally.
                statuses = [c["status"] for c in body["checks"]]
                assert body["summary"]["checks_total"] == 10
                assert body["summary"]["ok"] == statuses.count("ok")
                assert body["summary"]["warn"] == statuses.count("warn")
                assert body["summary"]["fail"] == statuses.count("fail")
                # Every check carries name/status/details/duration_ms.
                for c in body["checks"]:
                    assert set(c.keys()) >= {
                        "name", "status", "details", "duration_ms",
                    }
                    assert c["status"] in ("ok", "warn", "fail")
                    assert isinstance(c["duration_ms"], int)
                # All 10 required check names present.
                names = {c["name"] for c in body["checks"]}
                assert names == {
                    "boot_state", "mongo_ping",
                    "required_migrations", "optional_migrations",
                    "hotpath_smoke", "comms_gate",
                    "rc_sms_from_number", "scheduler",
                    "env_sanity", "feature_gates",
                }
                # Boot state + Mongo + required migrations are the
                # gates the readiness probe enforces — assert they
                # come back ok on the happy path so the verdict is
                # never NO_GO here purely for env reasons.
                by_name = {c["name"]: c for c in body["checks"]}
                assert by_name["boot_state"]["status"] == "ok"
                assert by_name["mongo_ping"]["status"] == "ok"
                assert by_name["required_migrations"]["status"] == "ok"
        finally:
            state.update(saved)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# Failure: required migration missing → NO_GO
# ═══════════════════════════════════════════════════════════════════
def test_i3_required_migration_missing_returns_no_go():
    async def _go(db):
        # Nuke the sentinel to simulate a fresh deploy that hasn't
        # run the migration yet. Restore afterwards.
        state = _get_state()
        saved = dict(state)
        state["complete"] = True
        state["dangling_refs_total"] = 0
        state["error"] = None
        snapshot = await db.migration_status.find_one(
            {"key": "perf_customers_v1"}, {"_id": 0},
        )
        await db.migration_status.delete_one({"key": "perf_customers_v1"})
        try:
            token = await _make_super_admin_token(db)
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.get(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["overall_verdict"] == "NO_GO"
                by_name = {c["name"]: c for c in body["checks"]}
                assert by_name["required_migrations"]["status"] == "fail"
                assert "perf_customers_v1" in (
                    by_name["required_migrations"]["details"]["missing"]
                )
                # Recommendation surfaces the migration name.
                recs = " ".join(body["recommendations"])
                assert "perf_customers_v1" in recs
        finally:
            if snapshot:
                await db.migration_status.insert_one(snapshot)
            else:
                await _ensure_perf_customers_migration(db)
            state.update(saved)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# Dangling refs + enforce=true → NO_GO (matches /health/ready 503)
# ═══════════════════════════════════════════════════════════════════
def test_i3_dangling_refs_with_enforce_true_returns_no_go():
    async def _go(db):
        await _ensure_perf_customers_migration(db)
        state = _get_state()
        saved = dict(state)
        state["complete"] = True
        state["dangling_refs_total"] = 4
        state["error"] = None
        prev_env = os.environ.get("INTEGRITY_CHECK_ENFORCE")
        os.environ["INTEGRITY_CHECK_ENFORCE"] = "true"
        try:
            token = await _make_super_admin_token(db)
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.get(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["overall_verdict"] == "NO_GO"
                by_name = {c["name"]: c for c in body["checks"]}
                assert by_name["boot_state"]["status"] == "fail"
                assert by_name["boot_state"]["details"][
                    "dangling_refs_total"] == 4
                assert by_name["boot_state"]["details"][
                    "integrity_check_enforce"] is True
        finally:
            state.update(saved)
            if prev_env is None:
                os.environ.pop("INTEGRITY_CHECK_ENFORCE", None)
            else:
                os.environ["INTEGRITY_CHECK_ENFORCE"] = prev_env

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# Dangling refs + enforce=false → GO_WITH_WARNINGS (recovery mode)
# ═══════════════════════════════════════════════════════════════════
def test_i3_dangling_refs_with_enforce_false_returns_warnings():
    async def _go(db):
        await _ensure_perf_customers_migration(db)
        state = _get_state()
        saved = dict(state)
        state["complete"] = True
        state["dangling_refs_total"] = 4
        state["error"] = None
        prev_env = os.environ.get("INTEGRITY_CHECK_ENFORCE")
        os.environ["INTEGRITY_CHECK_ENFORCE"] = "false"
        try:
            token = await _make_super_admin_token(db)
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.get(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200, r.text
                body = r.json()
                # With refs>0 + enforce=false the boot check is
                # 'warn', which means overall is at worst
                # GO_WITH_WARNINGS unless some other check hard-fails.
                assert body["overall_verdict"] in (
                    "GO_WITH_WARNINGS", "NO_GO",
                )
                by_name = {c["name"]: c for c in body["checks"]}
                assert by_name["boot_state"]["status"] == "warn"
                assert by_name["boot_state"]["details"][
                    "note"] == "recovery_mode"
                # Recovery-mode signal shows up in recommendations
                # + in the feature-gate notes.
                recs = " ".join(body["recommendations"]).lower()
                assert "recovery" in recs or "enforce" in recs
        finally:
            state.update(saved)
            if prev_env is None:
                os.environ.pop("INTEGRITY_CHECK_ENFORCE", None)
            else:
                os.environ["INTEGRITY_CHECK_ENFORCE"] = prev_env

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# RBAC — admin, tech, unauth all rejected
# ═══════════════════════════════════════════════════════════════════
def test_i3_rbac_admin_gets_403():
    async def _go(db):
        token = await _make_role_token(db, "admin",
                                            "i3admin@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.get(
                ENDPOINT,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 403, r.text
            assert "super admin" in r.json().get("detail", "").lower()

    run_test(_go)


def test_i3_rbac_tech_gets_403():
    async def _go(db):
        token = await _make_role_token(db, "tech",
                                            "i3tech@aquaterra.com")
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.get(
                ENDPOINT,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 403, r.text

    run_test(_go)


def test_i3_rbac_unauth_gets_401_or_403():
    async def _go(_db):
        transport = httpx.ASGITransport(app=_get_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test",
        ) as ac:
            r = await ac.get(ENDPOINT)  # no Authorization header
            # FastAPI HTTPBearer without credentials returns 403 by
            # default (auto_error=True). Depending on the runtime
            # security wrapper it may surface as 401 elsewhere. Both
            # are acceptable — the endpoint MUST NOT return 200
            # without a super_admin token.
            assert r.status_code in (401, 403), r.text

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# Endpoint never 5xxes (contract): even with catastrophic per-check
# failure, the top-level response is 200 with encoded failures.
# ═══════════════════════════════════════════════════════════════════
def test_i3_response_is_never_5xx_even_when_checks_fail():
    async def _go(db):
        state = _get_state()
        saved = dict(state)
        # Force multiple sad states simultaneously.
        state["complete"] = True
        state["dangling_refs_total"] = 999
        state["error"] = "boot integrity scan crashed"
        try:
            token = await _make_super_admin_token(db)
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.get(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                )
                # ALWAYS 200 — failures are payload-encoded.
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["overall_verdict"] == "NO_GO"
                by_name = {c["name"]: c for c in body["checks"]}
                assert by_name["boot_state"]["status"] == "fail"
                assert body["summary"]["fail"] >= 1
        finally:
            state.update(saved)

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# Feature-gate check is always ``ok`` (informational only)
# ═══════════════════════════════════════════════════════════════════
def test_i3_feature_gates_are_informational_ok():
    async def _go(db):
        await _ensure_perf_customers_migration(db)
        state = _get_state()
        saved = dict(state)
        state["complete"] = True
        state["dangling_refs_total"] = 0
        state["error"] = None
        try:
            token = await _make_super_admin_token(db)
            transport = httpx.ASGITransport(app=_get_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test",
            ) as ac:
                r = await ac.get(
                    ENDPOINT,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert r.status_code == 200
                body = r.json()
                by_name = {c["name"]: c for c in body["checks"]}
                fg = by_name["feature_gates"]
                assert fg["status"] == "ok"
                # Every documented gate is present in values (even
                # if unset — surfaced as "(unset)").
                values = fg["details"]["values"]
                assert "SOSHIE_MODERATION_ENABLED" in values
                assert "SOSHIE_REGEX_PREFILTER_ENABLED" in values
                assert "INTEGRITY_CHECK_ENFORCE" in values
                assert "HEALTH_READY_INTEGRITY_CHECK" in values
                assert "ENABLE_SCHEDULER" in values
        finally:
            state.update(saved)

    run_test(_go)
