"""Phase I1.7.c.3 · Feb-2026 — Tenant Calendars BYO Providers (Google + Outlook).

Uses ``CALENDARS_TESTMODE_MOCK=true`` so adapters short-circuit the
real Google / Microsoft Graph calls. Endpoint-level cases hit the
live backend on ``localhost:8001``.

Coverage matrix (locked with user, 2026-02):

  ── Provider registry ──────────────────────────────────────────
    * providers_registered           google_calendar + outlook
  ── OAuth start role gating ────────────────────────────────────
    * start_super_admin_ok           super_admin can start for any tech
    * start_admin_ok                 admin can start for any tech
    * start_self_ok                  technician can start for themselves
    * start_other_tech_403           tech cannot start for a different tech
    * start_json_format              format=json returns the auth URL
  ── OAuth state security ───────────────────────────────────────
    * state_tampered_rejected        signature mismatch → 302 to error
    * state_expired_rejected         exp<now → 302 to error
    * state_replay_rejected          nonce single-use enforced
    * callback_missing_params        no code/state → 302 to error
  ── Callback happy path ────────────────────────────────────────
    * callback_persists_link         creates tech link + meta row
  ── Cap semantics (mirror AI/Maps) ─────────────────────────────
    * cap_unlimited                  None means no block
    * cap_zero_blocks                0 means block-all → 429
    * cap_hard_block_at_limit        used>=cap → 429
    * cap_soft_warn_at_80pct         used>=0.8*cap → status=warn
  ── PUT cap endpoint ──────────────────────────────────────────
    * put_cap_updates_meta           PUT /calendars_google saves cap
  ── Usage endpoint ────────────────────────────────────────────
    * usage_endpoint_shape           /calendars/usage returns both
                                     providers + technicians
  ── Disconnect ────────────────────────────────────────────────
    * disconnect_technician_ok       POST /disconnect removes link
    * delete_provider_wipes_all      DELETE tears down every tech link

Every case is idempotent — a repeat run against the same DB is a
no-op except for the cap-warn ``record_usage`` fixture, which is
scoped to the current-month period key.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
# Force mock mode BEFORE we import the calendars module.
os.environ["CALENDARS_TESTMODE_MOCK"] = "true"

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


_LOOP: asyncio.AbstractEventLoop | None = None
_MOTOR_DB = None


def _setup_loop():
    global _LOOP, _MOTOR_DB
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _MOTOR_DB = _client[os.environ["DB_NAME"]]
        import services.secrets.store as _store
        _store._default_db = lambda: _MOTOR_DB  # type: ignore
        import services.calendars.usage as _cusage
        _cusage._default_db = lambda: _MOTOR_DB  # type: ignore
        import services.calendars.technician_link as _clink
        _clink._default_db = lambda: _MOTOR_DB  # type: ignore
    return _LOOP, _MOTOR_DB


def _drive(coro_factory):
    loop, db = _setup_loop()
    return loop.run_until_complete(coro_factory(db))


def _login(email="super@aquaterra.com", password="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id_for(email: str) -> str:
    u = _sync.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1})
    assert u and u.get("tenant_id"), f"user {email} missing tenant_id"
    return u["tenant_id"]


def _pick_tech_for(tenant_id: str) -> dict:
    """Return a technician-role user in the tenant. Creates one if none exist."""
    u = _sync.users.find_one(
        {"tenant_id": tenant_id, "role": {"$in": ["tech", "technician", "admin"]}},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "name": 1, "tenant_id": 1},
    )
    if u:
        return u
    # Fall back — insert a synthetic tech row.
    tech = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "email": f"tech-{uuid.uuid4().hex[:8]}@aquaterra.test",
        "role": "tech",
        "name": "Test Tech",
    }
    _sync.users.insert_one({**tech})
    return tech


def _clean_calendars_state_for(tenant_id: str) -> None:
    _sync.tenant_calendars_provider.delete_many({"tenant_id": tenant_id})
    _sync.tenant_calendars_usage.delete_many({"tenant_id": tenant_id})
    _sync.technician_calendar_link.delete_many({"tenant_id": tenant_id})
    _sync.calendar_oauth_state_consumed.delete_many({"tenant_id": tenant_id})
    _sync.tenant_secrets.delete_many({
        "tenant_id": tenant_id,
        "provider_key": {"$regex": r"^calendars_"},
    })


# ── 1. Provider registry ────────────────────────────────────────
def test_i17c3_providers_registered():
    from services.calendars import list_registered_calendar_provider_keys, list_short_names
    keys = set(list_registered_calendar_provider_keys())
    assert keys == {"calendars_google", "calendars_outlook"}, keys
    shorts = set(list_short_names())
    assert shorts == {"google", "outlook"}, shorts


# ── 2. OAuth start role gating ─────────────────────────────────
def test_i17c3_start_super_admin_ok():
    tok = _login()
    tid = _tenant_id_for("super@aquaterra.com")
    tech = _pick_tech_for(tid)
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["provider_key"] == "calendars_google"
    assert j["provider"] == "google"
    assert j["auth_url"].startswith("https://accounts.google.com/")
    assert j["state"], "state token must be non-empty"


def test_i17c3_start_admin_ok():
    # ``super@aquaterra.com`` is super_admin. Use an admin fixture.
    admin = _sync.users.find_one({"role": "admin"}, {"_id": 0, "email": 1, "tenant_id": 1})
    if not admin:
        pytest.skip("no admin user seeded")
    # Try password123 (demo password across seeds).
    r = requests.post(
        f"{API}/auth/login",
        json={"email": admin["email"], "password": "password123"},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code}")
    tok = r.json()["access_token"]
    tech = _pick_tech_for(admin["tenant_id"])
    r2 = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    assert r2.status_code == 200, r2.text


def test_i17c3_start_self_ok(two_technicians):
    # A technician can start OAuth for their own user_id (self-service).
    tech = two_technicians["tech_a"]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": tech["email"], "password": two_technicians["password"]},
        timeout=30,
    )
    assert r.status_code == 200, f"tech login failed: {r.status_code} · {r.text}"
    tok = r.json()["access_token"]
    r2 = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["technician_user_id"] == tech["id"]


def test_i17c3_start_other_tech_403(two_technicians):
    # Tech A logs in and tries to initiate OAuth for Tech B — must 403.
    tech_a = two_technicians["tech_a"]
    tech_b = two_technicians["tech_b"]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": tech_a["email"], "password": two_technicians["password"]},
        timeout=30,
    )
    assert r.status_code == 200, f"tech login failed: {r.status_code} · {r.text}"
    tok = r.json()["access_token"]
    r2 = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/start",
        params={"technician_user_id": tech_b["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    assert r2.status_code == 403, r2.text


def test_i17c3_start_super_can_initiate_for_any_tech(two_technicians):
    """super_admin must be able to initiate OAuth for tech A, tech B,
    AND themselves (three consecutive calls, all 200)."""
    tok = _login()
    super_row = _sync.users.find_one(
        {"email": "super@aquaterra.com"}, {"_id": 0, "id": 1},
    )
    assert super_row and super_row.get("id"), "aquaterra super seed missing"
    targets = [
        two_technicians["tech_a"]["id"],
        two_technicians["tech_b"]["id"],
        super_row["id"],
    ]
    for target in targets:
        r = requests.get(
            f"{API}/tenants/me/integrations/calendars_google/oauth/start",
            params={"technician_user_id": target, "format": "json"},
            headers=_hdrs(tok), timeout=15,
        )
        assert r.status_code == 200, (
            f"super failed to start OAuth for {target}: "
            f"{r.status_code} · {r.text}"
        )
        assert r.json()["technician_user_id"] == target


def test_i17c3_start_json_format():
    tok = _login()
    tid = _tenant_id_for("super@aquaterra.com")
    tech = _pick_tech_for(tid)
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_outlook/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    assert r.status_code == 200
    j = r.json()
    assert "login.microsoftonline.com" in j["auth_url"]


# ── 3. OAuth state security (P0 per user lock) ─────────────────
def test_i17c3_callback_rejects_tampered_state():
    from services.calendars import build_state_token
    state = build_state_token(
        tenant_id="tenant-x", technician_user_id="tech-x",
        provider_short="google",
    )
    # Flip a byte in the base64 sig — signature verification MUST fail.
    body, sig = state.rsplit(".", 1)
    tampered = f"{body}.{sig[:-2]}XY"
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/callback",
        params={"code": "any", "state": tampered},
        timeout=15, allow_redirects=False,
    )
    assert r.status_code == 302
    assert "calendar_connect=error" in r.headers["location"]
    assert "state_invalid" in r.headers["location"]


def test_i17c3_callback_rejects_expired_state():
    from services.calendars import build_state_token
    # ttl=1s → sleep for 2s → expired.
    state = build_state_token(
        tenant_id="tenant-y", technician_user_id="tech-y",
        provider_short="google", ttl_seconds=1,
    )
    import time
    time.sleep(2)
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/callback",
        params={"code": "any", "state": state},
        timeout=15, allow_redirects=False,
    )
    assert r.status_code == 302
    assert "state_expired" in r.headers["location"]


def test_i17c3_callback_rejects_replayed_state():
    tok = _login()
    tid = _tenant_id_for("super@aquaterra.com")
    tech = _pick_tech_for(tid)
    _clean_calendars_state_for(tid)
    # Mint a fresh state.
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    assert r.status_code == 200
    state = r.json()["state"]
    # First callback — must succeed (mock exchange_code).
    r1 = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/callback",
        params={"code": "mockcode1", "state": state},
        timeout=15, allow_redirects=False,
    )
    assert r1.status_code == 302
    assert "calendar_connect=success" in r1.headers["location"]
    # Replay — same state — must be rejected with state_replayed.
    r2 = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/callback",
        params={"code": "mockcode1", "state": state},
        timeout=15, allow_redirects=False,
    )
    assert r2.status_code == 302
    assert "state_replayed" in r2.headers["location"]


def test_i17c3_callback_missing_params():
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/callback",
        params={},
        timeout=15, allow_redirects=False,
    )
    assert r.status_code == 302
    assert "missing_params" in r.headers["location"]


# ── 4. Callback happy path — link + meta persistence ────────────
def test_i17c3_callback_persists_link_and_meta():
    tok = _login()
    tid = _tenant_id_for("super@aquaterra.com")
    tech = _pick_tech_for(tid)
    _clean_calendars_state_for(tid)
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_outlook/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    assert r.status_code == 200
    state = r.json()["state"]
    r2 = requests.get(
        f"{API}/tenants/me/integrations/calendars_outlook/oauth/callback",
        params={"code": "mockcode_outlook", "state": state},
        timeout=15, allow_redirects=False,
    )
    assert r2.status_code == 302
    assert "calendar_connect=success" in r2.headers["location"]

    # DB assertions.
    link = _sync.technician_calendar_link.find_one({
        "tenant_id": tid, "technician_user_id": tech["id"],
        "provider_key": "calendars_outlook",
    })
    assert link is not None
    assert link["provider"] == "outlook"
    assert link["calendar_id"] == "primary"
    meta = _sync.tenant_calendars_provider.find_one({
        "tenant_id": tid, "provider": "outlook",
    })
    assert meta is not None


# ── 5. Cap semantics ────────────────────────────────────────────
def test_i17c3_cap_unlimited_is_ok():
    async def _run(db):
        from services.calendars.usage import (
            enforce_cap_or_raise, upsert_provider_meta,
        )
        tid = f"tid-cap-unlim-{uuid.uuid4().hex[:8]}"
        await upsert_provider_meta(
            tenant_id=tid, provider="google",
            monthly_sync_op_cap=None, db=db,
        )
        r = await enforce_cap_or_raise(
            tenant_id=tid, provider="google", db=db,
        )
        assert r["status"] == "ok"
        assert r["cap"] is None
    _drive(_run)


def test_i17c3_cap_zero_blocks_all():
    async def _run(db):
        from services.calendars.models import TenantCalendarsSyncOpCapExceeded
        from services.calendars.usage import (
            enforce_cap_or_raise, upsert_provider_meta,
        )
        tid = f"tid-cap-0-{uuid.uuid4().hex[:8]}"
        await upsert_provider_meta(
            tenant_id=tid, provider="google",
            monthly_sync_op_cap=0, db=db,
        )
        with pytest.raises(TenantCalendarsSyncOpCapExceeded):
            await enforce_cap_or_raise(
                tenant_id=tid, provider="google", db=db,
            )
    _drive(_run)


def test_i17c3_cap_hard_block_at_limit():
    async def _run(db):
        from services.calendars.models import TenantCalendarsSyncOpCapExceeded
        from services.calendars.usage import (
            enforce_cap_or_raise, record_usage, upsert_provider_meta,
        )
        tid = f"tid-cap-hb-{uuid.uuid4().hex[:8]}"
        await upsert_provider_meta(
            tenant_id=tid, provider="outlook",
            monthly_sync_op_cap=2, db=db,
        )
        await record_usage(tenant_id=tid, provider="outlook",
                            operation="push_event", db=db)
        await record_usage(tenant_id=tid, provider="outlook",
                            operation="pull_delta", db=db)
        with pytest.raises(TenantCalendarsSyncOpCapExceeded):
            await enforce_cap_or_raise(
                tenant_id=tid, provider="outlook", db=db,
            )
    _drive(_run)


def test_i17c3_cap_soft_warn_at_80pct():
    async def _run(db):
        from services.calendars.usage import (
            enforce_cap_or_raise, record_usage, upsert_provider_meta,
        )
        tid = f"tid-cap-warn-{uuid.uuid4().hex[:8]}"
        await upsert_provider_meta(
            tenant_id=tid, provider="google",
            monthly_sync_op_cap=10, db=db,
        )
        # 8 ops of 10 → 80% → warn (but not blocked).
        for _ in range(8):
            await record_usage(tenant_id=tid, provider="google",
                                operation="push_event", db=db)
        r = await enforce_cap_or_raise(
            tenant_id=tid, provider="google", db=db,
        )
        assert r["status"] == "warn"
        assert r["used"] == 8
        assert r["cap"] == 10
    _drive(_run)


# ── 6. PUT cap endpoint ────────────────────────────────────────
def test_i17c3_put_cap_updates_meta():
    tok = _login()
    tid = _tenant_id_for("super@aquaterra.com")
    _clean_calendars_state_for(tid)
    r = requests.put(
        f"{API}/tenants/me/integrations/calendars_google",
        json={"config": {"default_calendar_id": "primary"},
                "monthly_sync_op_cap": 500},
        headers=_hdrs(tok), timeout=15,
    )
    assert r.status_code == 200, r.text
    row = _sync.tenant_calendars_provider.find_one({
        "tenant_id": tid, "provider": "google",
    })
    assert row is not None
    assert row["monthly_sync_op_cap"] == 500
    assert row.get("default_calendar_id") == "primary"


# ── 7. Usage endpoint ──────────────────────────────────────────
def test_i17c3_usage_endpoint_shape():
    tok = _login()
    tid = _tenant_id_for("super@aquaterra.com")
    tech = _pick_tech_for(tid)
    _clean_calendars_state_for(tid)
    # Connect a tech via mock callback.
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    state = r.json()["state"]
    requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/callback",
        params={"code": "mockcode", "state": state},
        timeout=15, allow_redirects=False,
    )
    r2 = requests.get(
        f"{API}/tenants/me/integrations/calendars/usage",
        headers=_hdrs(tok), timeout=15,
    )
    assert r2.status_code == 200, r2.text
    j = r2.json()
    assert j["tenant_id"] == tid
    # At least one provider row (google_calendar) with connected_technicians >= 1.
    google = next((p for p in j["providers"] if p["provider"] == "google"), None)
    assert google is not None
    assert google["connected_technicians"] >= 1
    # Technicians summary — should include our tech.
    assert any(t["technician_user_id"] == tech["id"] for t in j["technicians"])


# ── 8. Disconnect ──────────────────────────────────────────────
def test_i17c3_disconnect_technician_ok():
    tok = _login()
    tid = _tenant_id_for("super@aquaterra.com")
    tech = _pick_tech_for(tid)
    _clean_calendars_state_for(tid)
    # Connect first.
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    state = r.json()["state"]
    requests.get(
        f"{API}/tenants/me/integrations/calendars_google/oauth/callback",
        params={"code": "mockcode", "state": state},
        timeout=15, allow_redirects=False,
    )
    # Disconnect that technician.
    r2 = requests.post(
        f"{API}/tenants/me/integrations/calendars_google/disconnect",
        json={"technician_user_id": tech["id"]},
        headers=_hdrs(tok), timeout=15,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["removed"] is True
    # Row is gone.
    assert _sync.technician_calendar_link.find_one({
        "tenant_id": tid, "technician_user_id": tech["id"],
        "provider_key": "calendars_google",
    }) is None


def test_i17c3_delete_provider_wipes_all_tech_links():
    tok = _login()
    tid = _tenant_id_for("super@aquaterra.com")
    tech = _pick_tech_for(tid)
    _clean_calendars_state_for(tid)
    # Connect via mock.
    r = requests.get(
        f"{API}/tenants/me/integrations/calendars_outlook/oauth/start",
        params={"technician_user_id": tech["id"], "format": "json"},
        headers=_hdrs(tok), timeout=15,
    )
    state = r.json()["state"]
    requests.get(
        f"{API}/tenants/me/integrations/calendars_outlook/oauth/callback",
        params={"code": "mockcode", "state": state},
        timeout=15, allow_redirects=False,
    )
    # DELETE the provider entirely.
    r2 = requests.delete(
        f"{API}/tenants/me/integrations/calendars_outlook",
        headers=_hdrs(tok), timeout=15,
    )
    assert r2.status_code == 200, r2.text
    # Every per-tech link + meta row gone.
    assert _sync.technician_calendar_link.count_documents({
        "tenant_id": tid, "provider_key": "calendars_outlook",
    }) == 0
    assert _sync.tenant_calendars_provider.find_one({
        "tenant_id": tid, "provider": "outlook",
    }) is None
