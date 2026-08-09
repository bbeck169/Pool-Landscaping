"""Phase 54e · Feb-2026 — Heritage + ePoolSupply + cron + PATCH tests.

Playwright fully mocked. NO live wholesaler network calls. Covers:

* Heritage + ePoolSupply connector class wiring (`display_name`, `slug`,
  `planned_phase`, inheritance from the shared scraper base).
* Missing-credential guard on both connectors' ``authenticate``.
* Router sync HTTP contract for both slugs (403/400/202).
* Test-connection endpoint success + login_failed branches for both.
* PATCH /suppliers/{slug}:
    - role gate (manager 403)
    - sync_frequency enum validation
    - active toggle
    - empty patch rejected
* Cron ``_run_tick`` behavior:
    - dry-run when SUPPLIER_SYNC_LIVE unset
    - live path launches sync per (tenant, supplier) with mocked runner
    - skips suppliers with no credentials
    - skips suppliers with recent successful sync (< 6 h)
    - respects sync_frequency (hourly/daily/weekly/manual)
    - Sunday-only weekly gating via _should_sync_now
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_asyncio import batch_safe_run as _run
from tests.conftest import demo_pw

from services.suppliers.heritage import HeritageConnector
from services.suppliers.epoolsupply import EPoolSupplyConnector
from services.suppliers.poolcorp import LoginFailedError
from services.suppliers.connector import SupplierSession
from services.suppliers import cron as cron_mod


TID = "3814833a-dd0d-4bd9-90ea-351c24924649"
LOCAL_API = "http://localhost:8001/api"
TIMEOUT = 30


def _login(email: str) -> str:
    r = requests.post(f"{LOCAL_API}/auth/login",
                      json={"email": email, "password": demo_pw(email)},
                      timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _hdr(email: str = "admin@aquaterra.com") -> dict:
    return {"Authorization": f"Bearer {_login(email)}"}


def _wipe_creds():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        mc[be["DB_NAME"]].supplier_credentials.delete_many({"tenant_id": TID})
    finally:
        mc.close()


# ═══════════════════════════════════════════════════════════════════
# Connector class wiring
# ═══════════════════════════════════════════════════════════════════
def test_heritage_connector_class_wiring():
    conn = HeritageConnector()
    assert conn.slug == "heritage"
    assert conn.display_name == "Heritage Pool Plus"
    assert conn.planned_phase == "54e"
    assert "login_url" in conn.SELECTORS
    assert "product_card" in conn.SELECTORS


def test_epoolsupply_connector_class_wiring():
    conn = EPoolSupplyConnector()
    assert conn.slug == "epoolsupply"
    assert conn.display_name == "ePoolSupply"
    assert conn.planned_phase == "54e"
    assert "login_url" in conn.SELECTORS
    assert "product_card" in conn.SELECTORS


def test_heritage_authenticate_missing_credentials_raises():
    conn = HeritageConnector()
    with pytest.raises(LoginFailedError):
        _run(conn.authenticate({}))


def test_epoolsupply_authenticate_missing_credentials_raises():
    conn = EPoolSupplyConnector()
    with pytest.raises(LoginFailedError):
        _run(conn.authenticate({"username": "u"}))


# ═══════════════════════════════════════════════════════════════════
# Router sync HTTP contract for both new slugs
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("slug", ["heritage", "epoolsupply"])
def test_new_supplier_sync_forbidden_for_manager(slug):
    r = requests.post(f"{LOCAL_API}/suppliers/{slug}/sync",
                      headers=_hdr("manager@aquaterra.com"), timeout=TIMEOUT)
    assert r.status_code == 403


@pytest.mark.parametrize("slug", ["heritage", "epoolsupply"])
def test_new_supplier_sync_400_when_no_credentials(slug):
    _wipe_creds()
    r = requests.post(f"{LOCAL_API}/suppliers/{slug}/sync",
                      headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 400
    detail = r.json().get("detail") or {}
    assert detail.get("error") == "no_credentials"


@pytest.mark.parametrize("slug", ["heritage", "epoolsupply"])
def test_new_supplier_sync_202_with_credentials(slug):
    r_save = requests.post(f"{LOCAL_API}/suppliers/{slug}/credentials",
                           headers=_hdr(),
                           json={"username": "u", "password": "p"},
                           timeout=TIMEOUT)
    assert r_save.status_code == 200
    r = requests.post(f"{LOCAL_API}/suppliers/{slug}/sync",
                      headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "running"
    assert body["supplier_slug"] == slug
    _wipe_creds()


# ═══════════════════════════════════════════════════════════════════
# Test-connection endpoint — happy + failure for both slugs
# ═══════════════════════════════════════════════════════════════════
def _wire_supplier_row(slug: str):
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        db_sync = mc[be["DB_NAME"]]
        row = db_sync.suppliers.find_one(
            {"tenant_id": TID, "slug": slug}, {"_id": 0})
        if row:
            return row
        doc = {
            "id": str(uuid.uuid4()), "tenant_id": TID, "slug": slug,
            "display_name": slug,
            "active": True, "sync_frequency": "daily",
            "created_at": "2026-02-14T00:00:00+00:00",
        }
        db_sync.suppliers.insert_one(doc)
        doc.pop("_id", None)
        return doc
    finally:
        mc.close()


def _save_creds_direct(supp):
    from services.suppliers.crypto import encrypt
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        db_sync = mc[be["DB_NAME"]]
        db_sync.supplier_credentials.update_one(
            {"tenant_id": TID, "supplier_id": supp["id"]},
            {"$set": {
                "id": str(uuid.uuid4()),
                "tenant_id": TID, "supplier_id": supp["id"],
                "encrypted_username": encrypt("u"),
                "encrypted_password": encrypt("p"),
                "encrypted_api_key": encrypt(""),
                "notes": "",
                "updated_at": "2026-02-14T00:00:00+00:00",
            }}, upsert=True,
        )
    finally:
        mc.close()


@pytest.mark.parametrize("slug", ["heritage", "epoolsupply"])
def test_test_connection_success_new_slugs(slug):
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row(slug)
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        return SupplierSession(supplier_slug=slug, credentials_ref="")
    orig = CONNECTORS[slug].authenticate
    CONNECTORS[slug].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            slug, user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is True
        assert body["supplier_slug"] == slug
    finally:
        CONNECTORS[slug].authenticate = orig
        _wipe_creds()


@pytest.mark.parametrize("slug", ["heritage", "epoolsupply"])
def test_test_connection_login_failed_new_slugs(slug):
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row(slug)
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        raise LoginFailedError("Login failed — check credentials")
    orig = CONNECTORS[slug].authenticate
    CONNECTORS[slug].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            slug, user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "login_failed"
    finally:
        CONNECTORS[slug].authenticate = orig
        _wipe_creds()


# ═══════════════════════════════════════════════════════════════════
# PATCH /suppliers/{slug} — sync_frequency + active
# ═══════════════════════════════════════════════════════════════════
def test_patch_supplier_forbidden_for_manager():
    r = requests.patch(f"{LOCAL_API}/suppliers/heritage",
                       headers=_hdr("manager@aquaterra.com"),
                       json={"sync_frequency": "weekly"},
                       timeout=TIMEOUT)
    assert r.status_code == 403


def test_patch_supplier_updates_sync_frequency():
    r = requests.patch(f"{LOCAL_API}/suppliers/heritage",
                       headers=_hdr(),
                       json={"sync_frequency": "weekly"},
                       timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["sync_frequency"] == "weekly"


def test_patch_supplier_updates_active_toggle():
    r = requests.patch(f"{LOCAL_API}/suppliers/heritage",
                       headers=_hdr(),
                       json={"active": False},
                       timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    # Restore
    requests.patch(f"{LOCAL_API}/suppliers/heritage",
                   headers=_hdr(),
                   json={"active": True, "sync_frequency": "daily"},
                   timeout=TIMEOUT)


def test_patch_supplier_rejects_invalid_frequency():
    r = requests.patch(f"{LOCAL_API}/suppliers/heritage",
                       headers=_hdr(),
                       json={"sync_frequency": "every-5-mins"},
                       timeout=TIMEOUT)
    assert r.status_code == 400
    detail = r.json().get("detail") or {}
    assert detail.get("error") == "invalid_sync_frequency"


def test_patch_supplier_rejects_empty_body():
    r = requests.patch(f"{LOCAL_API}/suppliers/heritage",
                       headers=_hdr(), json={}, timeout=TIMEOUT)
    assert r.status_code == 400
    detail = r.json().get("detail") or {}
    assert detail.get("error") == "empty_patch"


# ═══════════════════════════════════════════════════════════════════
# Cron — dry-run + live + skip paths
# ═══════════════════════════════════════════════════════════════════
def test_cron_should_sync_now_weekly_only_on_sunday():
    monday = datetime(2026, 2, 16, 3, 0, tzinfo=timezone.utc)  # Monday
    sunday = datetime(2026, 2, 15, 3, 0, tzinfo=timezone.utc)  # Sunday
    assert _run(cron_mod._should_sync_now("weekly", monday)) is False
    assert _run(cron_mod._should_sync_now("weekly", sunday)) is True


def test_cron_should_sync_now_manual_never_matches():
    now = datetime(2026, 2, 16, 3, 0, tzinfo=timezone.utc)
    assert _run(cron_mod._should_sync_now("manual", now)) is False


def test_cron_dry_run_when_flag_unset(monkeypatch):
    """No SUPPLIER_SYNC_LIVE env var → dry-run summary, no runner call."""
    monkeypatch.delenv(cron_mod.ENV_LIVE, raising=False)
    supp = _wire_supplier_row("heritage")
    _save_creds_direct(supp)

    # Ensure the supplier row is active + daily.
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        mc[be["DB_NAME"]].suppliers.update_one(
            {"tenant_id": TID, "slug": "heritage"},
            {"$set": {"active": True, "sync_frequency": "daily"}})
    finally:
        mc.close()

    called = {"count": 0}

    async def fake_runner(*a, **k):
        called["count"] += 1

    # Patch the resolver so no real Playwright runner is used.
    monkeypatch.setattr(cron_mod, "_runner_for",
                        AsyncMock(return_value=fake_runner))
    result = _run(cron_mod.run_daily_tick())
    assert result["live"] is False
    assert result["dry_run"] >= 1
    assert called["count"] == 0
    _wipe_creds()


def test_cron_live_path_launches_runner(monkeypatch):
    """SUPPLIER_SYNC_LIVE=1 → runner invoked exactly once per (tenant,
    supplier) with saved credentials + matching cadence."""
    monkeypatch.setenv(cron_mod.ENV_LIVE, "1")
    supp = _wire_supplier_row("heritage")
    _save_creds_direct(supp)

    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        mc[be["DB_NAME"]].suppliers.update_one(
            {"tenant_id": TID, "slug": "heritage"},
            {"$set": {"active": True, "sync_frequency": "daily"}})
        # Wipe any recent successful sync so we don't hit the 6-h skip.
        mc[be["DB_NAME"]].supplier_sync_jobs.delete_many(
            {"tenant_id": TID, "supplier_id": supp["id"]})
    finally:
        mc.close()

    called = {"count": 0, "args": None}

    async def fake_runner(tenant_id, supplier, credentials, job_id):
        called["count"] += 1
        called["args"] = (tenant_id, supplier["slug"], job_id)

    async def fake_resolver(slug):
        return fake_runner

    monkeypatch.setattr(cron_mod, "_runner_for", fake_resolver)

    result = _run(cron_mod.run_daily_tick())
    assert result["live"] is True
    assert result["running"] >= 1
    # Yield the loop so the fire-and-forget task runs.
    import asyncio as _asyncio
    _run(_asyncio.sleep(0.05))
    assert called["count"] >= 1
    _wipe_creds()


def test_cron_skips_supplier_without_credentials(monkeypatch):
    monkeypatch.setenv(cron_mod.ENV_LIVE, "1")
    _wipe_creds()
    supp = _wire_supplier_row("heritage")

    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        mc[be["DB_NAME"]].suppliers.update_one(
            {"tenant_id": TID, "slug": "heritage"},
            {"$set": {"active": True, "sync_frequency": "daily"}})
    finally:
        mc.close()

    async def _boom(*a, **k):
        raise AssertionError("runner must NOT be called without creds")

    async def fake_resolver(slug):
        return _boom
    monkeypatch.setattr(cron_mod, "_runner_for", fake_resolver)

    result = _run(cron_mod.run_daily_tick())
    assert result["no_credentials"] >= 1


def test_cron_skips_supplier_with_recent_success(monkeypatch):
    monkeypatch.setenv(cron_mod.ENV_LIVE, "1")
    supp = _wire_supplier_row("heritage")
    _save_creds_direct(supp)

    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat()

    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        mc[be["DB_NAME"]].suppliers.update_one(
            {"tenant_id": TID, "slug": "heritage"},
            {"$set": {"active": True, "sync_frequency": "daily"}})
        mc[be["DB_NAME"]].supplier_sync_jobs.insert_one({
            "id": str(uuid.uuid4()),
            "tenant_id": TID, "supplier_id": supp["id"],
            "status": "success",
            "started_at": recent, "finished_at": recent,
            "items_added": 5, "items_updated": 0, "items_removed": 0,
        })
    finally:
        mc.close()

    async def _boom(*a, **k):
        raise AssertionError("runner must NOT be called for recent sync")

    async def fake_resolver(slug):
        return _boom
    monkeypatch.setattr(cron_mod, "_runner_for", fake_resolver)

    result = _run(cron_mod.run_daily_tick())
    assert result["recent"] >= 1

    # Cleanup
    mc = MongoClient(be["MONGO_URL"])
    try:
        mc[be["DB_NAME"]].supplier_sync_jobs.delete_many(
            {"supplier_id": supp["id"]})
    finally:
        mc.close()
    _wipe_creds()


def test_cron_hourly_tick_skips_daily_cadence(monkeypatch):
    monkeypatch.setenv(cron_mod.ENV_LIVE, "1")
    supp = _wire_supplier_row("heritage")
    _save_creds_direct(supp)

    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        mc[be["DB_NAME"]].suppliers.update_one(
            {"tenant_id": TID, "slug": "heritage"},
            {"$set": {"active": True, "sync_frequency": "daily"}})
    finally:
        mc.close()

    async def _boom(*a, **k):
        raise AssertionError("hourly tick must NOT touch daily suppliers")

    async def fake_resolver(slug):
        return _boom
    monkeypatch.setattr(cron_mod, "_runner_for", fake_resolver)

    result = _run(cron_mod.run_hourly_tick())
    assert result["skipped_cadence"] >= 1
    assert result["running"] == 0
    _wipe_creds()


# ═══════════════════════════════════════════════════════════════════
# Phase 54f addendum · Feb-2026 — Playwright cache-path smoke test
# ═══════════════════════════════════════════════════════════════════
def test_playwright_cache_path_defaults_to_default(monkeypatch):
    """When ``PLAYWRIGHT_BROWSERS_PATH`` is unset, the reporter falls
    back to ``~/.cache/ms-playwright`` (Playwright's own default)."""
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    resolved = cron_mod._report_playwright_cache_path()
    assert resolved.endswith(".cache/ms-playwright")


def test_playwright_cache_path_honors_env_override(monkeypatch):
    """When operators mount a persistent volume at a custom path they
    can set ``PLAYWRIGHT_BROWSERS_PATH`` — the reporter (and Playwright
    itself, natively) honors it."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/mnt/pw_cache")
    resolved = cron_mod._report_playwright_cache_path()
    assert resolved == "/mnt/pw_cache"


def test_playwright_cache_path_logs_chromium_version(caplog, monkeypatch):
    """The startup log line reports whether chromium is present.
    We rely on the pod's installed chromium from Phase 54e."""
    import logging
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    with caplog.at_level(logging.INFO):
        cron_mod._report_playwright_cache_path()
    # Effective startup log format is
    # ``supplier.playwright: cache_path=... chromium=<ver|missing>``.
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "supplier.playwright" in text
    assert "cache_path=" in text
    assert "chromium=" in text
