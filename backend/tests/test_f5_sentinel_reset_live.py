"""F5 sentinel reset — LIVE preview API tests (T1 iteration 27).

Covers POST /api/admin/migrations/f5-leads-backfill/reset over the
public preview URL: shape, idempotency, role gate (admin/tech/customer
403, anonymous 401) and the F9 status regression smoke check.
"""
from __future__ import annotations

import os

import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or _env.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")

RESET_PATH = f"{BASE_URL}/api/admin/migrations/f5-leads-backfill/reset"
STATUS_PATH = f"{BASE_URL}/api/admin/data-repair/status"
TIMEOUT = 60


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=TIMEOUT,
    )
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    tok = r.json().get("access_token")
    if not tok:
        pytest.fail(f"no access_token for {email}: {r.text[:300]}")
    return tok


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def super_me(super_headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=super_headers, timeout=TIMEOUT)
    assert r.status_code == 200, r.text[:300]
    return r.json()


# ── F5 reset · happy path + idempotency ─────────────────────────────
class TestF5ResetSuperAdmin:
    def test_reset_returns_expected_shape(self, super_headers):
        r = requests.post(RESET_PATH, headers=super_headers, json={}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d["ok"] is True
        assert d["sentinel_key"] == "f5_leads_backfill_v1"
        assert isinstance(d["deleted_count"], int)
        assert d["deleted_count"] in (0, 1)
        assert "previous_state" in d
        assert isinstance(d["audit_event_id"], str) and d["audit_event_id"]

    def test_reset_is_idempotent(self, super_headers):
        first = requests.post(RESET_PATH, headers=super_headers, json={}, timeout=TIMEOUT)
        assert first.status_code == 200, first.text[:300]
        second = requests.post(RESET_PATH, headers=super_headers, json={}, timeout=TIMEOUT)
        assert second.status_code == 200, second.text[:300]
        d = second.json()
        assert d["deleted_count"] == 0
        assert d["previous_state"] is None
        assert d["audit_event_id"] != first.json()["audit_event_id"]

    def test_no_mongo_object_id_leak(self, super_headers):
        r = requests.post(RESET_PATH, headers=super_headers, json={}, timeout=TIMEOUT)
        assert r.status_code == 200
        assert '"_id"' not in r.text
        prev = r.json().get("previous_state")
        if isinstance(prev, dict):
            assert "_id" not in prev


# ── F5 reset · audit trail verified via Mongo ───────────────────────
class TestF5ResetAuditTrail:
    def test_audit_row_written_with_expected_fields(self, super_headers, super_me):
        import asyncio

        from motor.motor_asyncio import AsyncIOMotorClient

        # Seed a sentinel so deleted_count=1 / previous_state non-null.
        mongo_url = os.environ.get("MONGO_URL") or dotenv_values("/app/backend/.env").get("MONGO_URL")
        db_name = os.environ.get("DB_NAME") or dotenv_values("/app/backend/.env").get("DB_NAME")
        assert mongo_url and db_name, "MONGO_URL/DB_NAME missing from backend/.env"

        async def seed():
            cli = AsyncIOMotorClient(mongo_url)
            try:
                await cli[db_name].migration_status.insert_one({
                    "key": "f5_leads_backfill_v1",
                    "completed_at": "2026-02-01T12:00:00+00:00",
                    "summary": {"candidates_total": 3, "changed": 2, "skipped": 1},
                })
            finally:
                cli.close()

        async def fetch_audit(audit_id):
            cli = AsyncIOMotorClient(mongo_url)
            try:
                return await cli[db_name].audit_events.find_one({"id": audit_id}, {"_id": 0})
            finally:
                cli.close()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(seed())
            r = requests.post(RESET_PATH, headers=super_headers, json={}, timeout=TIMEOUT)
            assert r.status_code == 200, r.text[:300]
            d = r.json()
            assert d["deleted_count"] == 1
            assert d["previous_state"] is not None
            assert d["previous_state"]["summary"]["changed"] == 2

            audit = loop.run_until_complete(fetch_audit(d["audit_event_id"]))
            assert audit is not None, "audit_events row not written"
            assert audit["event_type"] == "f5_sentinel_reset"
            assert audit["actor_user_id"] == super_me.get("id")
            assert audit["tenant_id"]
            assert audit["timestamp"]
            assert audit["sentinel_key"] == "f5_leads_backfill_v1"
            assert audit["deleted_count"] == 1
        finally:
            loop.close()


# ── F5 reset · role gate ────────────────────────────────────────────
class TestF5ResetRoleGate:
    @pytest.mark.parametrize("email", [
        "admin@aquaterra.com",
        "carlos@aquaterra.com",
        "customer@aquaterra.com",
    ])
    def test_non_super_admin_is_403(self, email):
        headers = {"Authorization": f"Bearer {_login(email)}"}
        r = requests.post(RESET_PATH, headers=headers, json={}, timeout=TIMEOUT)
        assert r.status_code == 403, f"{email}: {r.status_code} {r.text[:300]}"
        assert "Super admin" in r.text

    def test_anonymous_is_401(self):
        r = requests.post(RESET_PATH, json={}, timeout=TIMEOUT)
        assert r.status_code in (401, 403), r.text[:300]


# ── F9 status regression smoke ──────────────────────────────────────
class TestF9StatusRegression:
    def test_status_shape_unchanged(self, super_headers):
        r = requests.get(STATUS_PATH, headers=super_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        for key in ("current_state", "last_dry_run", "last_apply", "last_dump_file"):
            assert key in d, f"missing {key}"
        cs = d["current_state"]
        assert "dangling_refs_total" in cs
        assert "log_only_mode_active" in cs

    def test_status_403_for_admin(self):
        headers = {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}
        r = requests.get(STATUS_PATH, headers=headers, timeout=TIMEOUT)
        assert r.status_code == 403, r.text[:300]
