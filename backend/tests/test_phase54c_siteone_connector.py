"""Phase 54c · Feb-2026 — SiteOne connector + test-connection tests.

Playwright is fully mocked. NO live SiteOne network calls. Covers:

* `_next_backoff` — exponential doubling, clamped to MAX_BACKOFF_SECONDS.
* `RATE_LIMIT_HTTP_STATUSES` — 429 + 503 both in the tuple.
* Sync reconciliation via `run_supplier_sync` (mocked connector):
    - success path (insert + update + soft-delete)
    - login failure → job.status == "error"
    - layout-change → job.status == "error", pre-existing rows NOT deleted
* Router `POST /suppliers/siteone/sync`:
    - manager 403
    - no-credentials 400 `{error: "no_credentials"}`
    - creds saved → 202 + job_id + status=running

Router `POST /suppliers/{slug}/test-connection` (Phase 54c generic):
* super_admin + admin allowed; manager 403
* no-credentials 400
* poolcorp AND siteone are wired; ewing / heritage / epoolsupply → 501
* success (mocked ``authenticate``) → 200 {ok: true}
* login failure → 200 {ok: false, error: "login_failed"}
* rate-limit inference (message contains "429") → error: "rate_limited"
* generic RuntimeError → error: "unknown"
* async timeout → error: "timeout" (bounded to 15s via ``wait_for``)
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_asyncio import batch_safe_run as _run

from services.suppliers.siteone import (
    SiteOneConnector, _next_backoff,
    RATE_LIMIT_HTTP_STATUSES, MAX_BACKOFF_SECONDS,
)
from services.suppliers.poolcorp import LoginFailedError, LayoutChangedError
from services.suppliers.connector import ExternalProduct, SupplierSession
from services.suppliers import sync as sync_mod


TID = "3814833a-dd0d-4bd9-90ea-351c24924649"


def _get_db():
    from config import db
    return db


def _clean_supplier(slug="siteone"):
    return {"id": f"supp-{uuid.uuid4()}", "slug": slug, "tenant_id": TID,
            "display_name": {"siteone": "SiteOne",
                             "poolcorp": "Pool360 (PoolCorp)"}.get(slug, slug)}


async def _cleanup(supp):
    db = _get_db()
    await db.items.delete_many({"supplier_id": supp["id"]})
    await db.supplier_sync_jobs.delete_many({"supplier_id": supp["id"]})


# ═══════════════════════════════════════════════════════════════════
# Pure-function helpers — connector internals
# ═══════════════════════════════════════════════════════════════════
def test_next_backoff_doubles_and_clamps():
    assert _next_backoff(1.0) == 2.0
    assert _next_backoff(4.0) == 8.0
    # Starts from at-least 1.0 even if the caller passes < 1.
    assert _next_backoff(0.1) == 2.0
    # Clamps at MAX_BACKOFF_SECONDS.
    assert _next_backoff(64.0) == MAX_BACKOFF_SECONDS
    assert _next_backoff(9999.0) == MAX_BACKOFF_SECONDS


def test_rate_limit_http_statuses():
    assert 429 in RATE_LIMIT_HTTP_STATUSES
    assert 503 in RATE_LIMIT_HTTP_STATUSES


def test_siteone_authenticate_missing_credentials_raises():
    conn = SiteOneConnector()
    with pytest.raises(LoginFailedError):
        _run(conn.authenticate({}))
    with pytest.raises(LoginFailedError):
        _run(conn.authenticate({"username": "u"}))  # no password
    with pytest.raises(LoginFailedError):
        _run(conn.authenticate({"password": "p"}))  # no username


# ═══════════════════════════════════════════════════════════════════
# run_supplier_sync via SiteOne (mocked connector)
# ═══════════════════════════════════════════════════════════════════
class _FakeConnector:
    slug = "siteone"
    display_name = "SiteOne"

    def __init__(self, products=None, login_error=None, list_error=None):
        self._products = products or []
        self._login_error = login_error
        self._list_error = list_error

    async def authenticate(self, credentials):
        if self._login_error:
            raise self._login_error
        return SupplierSession(supplier_slug=self.slug, credentials_ref="")

    async def list_products(self, session, since=None):
        if self._list_error:
            raise self._list_error
        for p in self._products:
            yield p


def _run_sync_with_fake(fake, supp):
    async def go():
        job = await sync_mod.start_sync_job(TID, supp)
        await sync_mod.run_supplier_sync(
            TID, supp, {"username": "u", "password": "p"},
            job["id"], fake,
        )
        db = _get_db()
        return await db.supplier_sync_jobs.find_one(
            {"id": job["id"]}, {"_id": 0})
    return _run(go())


def test_run_siteone_sync_success():
    supp = _clean_supplier()
    fake = _FakeConnector(products=[
        ExternalProduct(sku="S1", name="Turf fertilizer", cost=22.0, msrp=40.0,
                        category="Fertilizer", uom="bag", description="50lb"),
        ExternalProduct(sku="S2", name="Sprinkler head", cost=6.5, msrp=12.0,
                        category="Irrigation", uom="each", description="180deg"),
    ])
    try:
        finished = _run_sync_with_fake(fake, supp)
        assert finished["status"] == "success"
        assert finished["items_added"] == 2
        assert finished["items_updated"] == 0
    finally:
        _run(_cleanup(supp))


def test_run_siteone_sync_login_failure():
    supp = _clean_supplier()
    fake = _FakeConnector(login_error=LoginFailedError(
        "Login failed — check credentials"))
    try:
        finished = _run_sync_with_fake(fake, supp)
        assert finished["status"] == "error"
        assert "Login failed" in finished["error_message"]
    finally:
        _run(_cleanup(supp))


def test_run_siteone_sync_layout_change_preserves_rows():
    supp = _clean_supplier()

    async def seed():
        await sync_mod.apply_products_to_pricebook(TID, supp, [
            {"sku": "SITEONE-PRE", "name": "Pre-existing",
              "cost": 1.0, "msrp": 2.0}])
    _run(seed())

    fake = _FakeConnector(list_error=LayoutChangedError(
        "Layout changed — selectors returned zero product cards"))
    try:
        finished = _run_sync_with_fake(fake, supp)
        assert finished["status"] == "error"
        assert "Layout changed" in finished["error_message"]

        async def check():
            db = _get_db()
            return await db.items.find_one(
                {"external_sku": "SITEONE-PRE", "supplier_id": supp["id"]},
                {"_id": 0})
        pre = _run(check())
        assert pre is not None
        assert pre["deleted_at"] is None
    finally:
        _run(_cleanup(supp))


def test_run_siteone_sync_dedupe_and_softdelete_across_runs():
    """Second sync updates existing items and soft-deletes items
    dropped from the incoming list. Same invariants Phase 54b locked
    for Pool360 — verified again for SiteOne through the generic
    ``run_supplier_sync`` path."""
    supp = _clean_supplier()

    async def go():
        try:
            fake1 = _FakeConnector(products=[
                ExternalProduct(sku="A", name="Alpha", cost=1.0, msrp=2.0),
                ExternalProduct(sku="B", name="Beta",  cost=2.0, msrp=4.0),
            ])
            j1 = await sync_mod.start_sync_job(TID, supp)
            await sync_mod.run_supplier_sync(
                TID, supp, {"username": "u", "password": "p"}, j1["id"], fake1)

            fake2 = _FakeConnector(products=[
                ExternalProduct(sku="A", name="Alpha v2", cost=1.5, msrp=2.5),
                ExternalProduct(sku="C", name="Gamma",    cost=3.0, msrp=6.0),
            ])
            j2 = await sync_mod.start_sync_job(TID, supp)
            await sync_mod.run_supplier_sync(
                TID, supp, {"username": "u", "password": "p"}, j2["id"], fake2)

            db = _get_db()
            finished2 = await db.supplier_sync_jobs.find_one(
                {"id": j2["id"]}, {"_id": 0})
            assert finished2["status"] == "success"
            assert finished2["items_added"]   == 1  # C
            assert finished2["items_updated"] == 1  # A
            assert finished2["items_removed"] == 1  # B soft-deleted

            b_row = await db.items.find_one(
                {"external_sku": "B", "supplier_id": supp["id"]}, {"_id": 0})
            assert b_row["deleted_at"] is not None
            assert b_row["active"] is False
        finally:
            await _cleanup(supp)
    _run(go())


# ═══════════════════════════════════════════════════════════════════
# Router role gate + no-credentials 400 + creds 202 for SiteOne sync.
# Uses localhost:8001 to bypass preview-URL flakiness — same pattern
# Phase 54b locked for Pool360.
# ═══════════════════════════════════════════════════════════════════
import requests  # noqa: E402
from tests.conftest import demo_pw  # noqa: E402

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
        db_sync = mc[be["DB_NAME"]]
        db_sync.supplier_credentials.delete_many({"tenant_id": TID})
    finally:
        mc.close()


def _wire_supplier_row(slug: str):
    """Ensure the ``suppliers`` row exists for ``TID + slug`` (the
    router's ``_get_supplier_or_404`` auto-seeds on read, but the
    router function tests call the handler directly — no auto-seed
    path fires from a router-function call). Returns the row."""
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
            "display_name": {"siteone": "SiteOne",
                              "poolcorp": "Pool360 (PoolCorp)",
                              "ewing": "Ewing Irrigation"}.get(slug, slug),
            "active": False, "sync_frequency": "daily",
            "last_sync_at": None, "last_sync_status": None,
            "last_sync_item_count": 0,
            "created_at": "2026-02-14T00:00:00+00:00",
        }
        db_sync.suppliers.insert_one(doc)
        doc.pop("_id", None)
        return doc
    finally:
        mc.close()


def _save_creds_direct(supp):
    """Write a Fernet-encrypted credentials row for the given supplier
    row directly via pymongo (bypasses the HTTP path so the router
    function tests don't need a running server)."""
    from services.suppliers.crypto import encrypt
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        db_sync = mc[be["DB_NAME"]]
        db_sync.supplier_credentials.update_one(
            {"tenant_id": TID, "supplier_id": supp["id"]},
            {"$set": {
                "id": str(uuid.uuid4()),
                "tenant_id": TID,
                "supplier_id": supp["id"],
                "encrypted_username": encrypt("u"),
                "encrypted_password": encrypt("p"),
                "encrypted_api_key": encrypt(""),
                "notes": "",
                "updated_at": "2026-02-14T00:00:00+00:00",
            }},
            upsert=True,
        )
    finally:
        mc.close()


def test_siteone_sync_forbidden_for_manager():
    r = requests.post(f"{LOCAL_API}/suppliers/siteone/sync",
                      headers=_hdr("manager@aquaterra.com"),
                      timeout=TIMEOUT)
    assert r.status_code == 403


def test_siteone_sync_400_when_no_credentials():
    _wipe_creds()
    r = requests.post(f"{LOCAL_API}/suppliers/siteone/sync",
                      headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("error") == "no_credentials"


def test_siteone_sync_202_with_credentials():
    r_save = requests.post(f"{LOCAL_API}/suppliers/siteone/credentials",
                           headers=_hdr(),
                           json={"username": "u", "password": "p"},
                           timeout=TIMEOUT)
    assert r_save.status_code == 200, r_save.text

    r = requests.post(f"{LOCAL_API}/suppliers/siteone/sync",
                      headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["supplier_slug"] == "siteone"
    assert body["job_id"]

    _wipe_creds()


# ═══════════════════════════════════════════════════════════════════
# test-connection endpoint — Phase 54c generic
# ═══════════════════════════════════════════════════════════════════
def test_test_connection_forbidden_for_manager():
    r = requests.post(f"{LOCAL_API}/suppliers/siteone/test-connection",
                      headers=_hdr("manager@aquaterra.com"),
                      timeout=TIMEOUT)
    assert r.status_code == 403


def test_test_connection_501_for_unwired_supplier():
    # Phase 54d wired Ewing — the next unwired slug is heritage
    # (planned for 54e).
    r_save = requests.post(f"{LOCAL_API}/suppliers/heritage/credentials",
                           headers=_hdr(),
                           json={"username": "u", "password": "p"},
                           timeout=TIMEOUT)
    assert r_save.status_code == 200, r_save.text
    try:
        r = requests.post(f"{LOCAL_API}/suppliers/heritage/test-connection",
                          headers=_hdr(), timeout=TIMEOUT)
        assert r.status_code == 501
        assert "54e" in r.json().get("detail", "")
    finally:
        _wipe_creds()


def test_test_connection_400_when_no_credentials():
    _wipe_creds()
    r = requests.post(f"{LOCAL_API}/suppliers/siteone/test-connection",
                      headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert detail.get("error") == "no_credentials"


def test_test_connection_success_when_authenticate_returns_session():
    """Call the router function directly (no HTTP) so monkeypatching
    the wired connector actually takes effect. Uses ``batch_safe_run``
    to drive Motor on the persistent loop."""
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection
    from services.suppliers.crypto import encrypt

    supp = _wire_supplier_row("siteone")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        return SupplierSession(supplier_slug="siteone", credentials_ref="")
    orig = CONNECTORS["siteone"].authenticate
    CONNECTORS["siteone"].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            "siteone",
            user={"role": "admin", "tenant_id": TID},
        ))
        assert body["ok"] is True
        assert body["supplier_slug"] == "siteone"
    finally:
        CONNECTORS["siteone"].authenticate = orig
        _wipe_creds()


def test_test_connection_login_failed_branch():
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row("siteone")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        raise LoginFailedError("Login failed — check credentials")
    orig = CONNECTORS["siteone"].authenticate
    CONNECTORS["siteone"].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            "siteone", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "login_failed"
    finally:
        CONNECTORS["siteone"].authenticate = orig
        _wipe_creds()


def test_test_connection_rate_limited_branch():
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row("siteone")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        raise RuntimeError("HTTP 429 rate-limited by SiteOne")
    orig = CONNECTORS["siteone"].authenticate
    CONNECTORS["siteone"].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            "siteone", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "rate_limited"
    finally:
        CONNECTORS["siteone"].authenticate = orig
        _wipe_creds()


def test_test_connection_unknown_error_branch():
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row("siteone")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        raise RuntimeError("chromium exploded")
    orig = CONNECTORS["siteone"].authenticate
    CONNECTORS["siteone"].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            "siteone", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "unknown"
    finally:
        CONNECTORS["siteone"].authenticate = orig
        _wipe_creds()


def test_test_connection_timeout_branch():
    """Cap-based timeout — the connector's ``authenticate`` never
    returns. The router applies a ``TEST_CONNECTION_TIMEOUT_S``
    ``asyncio.wait_for`` around it. Monkeypatch that to a small value
    so this test finishes fast."""
    from services.suppliers.connector import CONNECTORS
    from routers import suppliers as suppliers_router
    import asyncio as _asyncio

    supp = _wire_supplier_row("siteone")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        await _asyncio.sleep(2.0)

    orig_auth = CONNECTORS["siteone"].authenticate
    orig_timeout = suppliers_router.TEST_CONNECTION_TIMEOUT_S
    CONNECTORS["siteone"].authenticate = fake_auth
    suppliers_router.TEST_CONNECTION_TIMEOUT_S = 0.5
    try:
        body = _run(suppliers_router.test_supplier_connection(
            "siteone", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "timeout"
    finally:
        CONNECTORS["siteone"].authenticate = orig_auth
        suppliers_router.TEST_CONNECTION_TIMEOUT_S = orig_timeout
        _wipe_creds()
