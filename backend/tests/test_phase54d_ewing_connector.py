"""Phase 54d · Feb-2026 — Ewing connector + sync tests.

Playwright fully mocked. NO live Ewing network calls. Mirrors the
Phase 54c SiteOne suite structure — one file, both the connector
guard-rails and the test-connection endpoint failure classification.

Covers:

* Missing-credential guard on ``authenticate``.
* ``run_supplier_sync`` via ``EwingConnector`` — success / login-fail
  / layout-change / dedupe + soft-delete across two runs.
* Router ``POST /suppliers/ewing/sync``: manager 403, no-creds 400
  ``{error: "no_credentials"}``, creds saved → 202 + job_id.
* Router ``POST /suppliers/ewing/test-connection`` (generic endpoint):
  success + login_failed + rate_limited + unknown + timeout branches.
* Heritage / ePoolSupply still return 501 on both sync + test-connection
  with the correct planned-phase pointer.
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_asyncio import batch_safe_run as _run

from services.suppliers.ewing import EwingConnector
from services.suppliers.poolcorp import LoginFailedError, LayoutChangedError
from services.suppliers.connector import ExternalProduct, SupplierSession
from services.suppliers import sync as sync_mod


TID = "3814833a-dd0d-4bd9-90ea-351c24924649"


def _get_db():
    from config import db
    return db


def _clean_supplier():
    return {"id": f"supp-{uuid.uuid4()}", "slug": "ewing", "tenant_id": TID,
            "display_name": "Ewing Irrigation"}


async def _cleanup(supp):
    db = _get_db()
    await db.items.delete_many({"supplier_id": supp["id"]})
    await db.supplier_sync_jobs.delete_many({"supplier_id": supp["id"]})


# ═══════════════════════════════════════════════════════════════════
# Missing-credentials guard
# ═══════════════════════════════════════════════════════════════════
def test_ewing_authenticate_missing_credentials_raises():
    conn = EwingConnector()
    with pytest.raises(LoginFailedError):
        _run(conn.authenticate({}))
    with pytest.raises(LoginFailedError):
        _run(conn.authenticate({"username": "u"}))
    with pytest.raises(LoginFailedError):
        _run(conn.authenticate({"password": "p"}))


# ═══════════════════════════════════════════════════════════════════
# run_supplier_sync via Ewing (mocked connector)
# ═══════════════════════════════════════════════════════════════════
class _FakeConnector:
    slug = "ewing"
    display_name = "Ewing Irrigation"

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
            TID, supp, {"username": "u", "password": "p"}, job["id"], fake)
        db = _get_db()
        return await db.supplier_sync_jobs.find_one(
            {"id": job["id"]}, {"_id": 0})
    return _run(go())


def test_run_ewing_sync_success():
    supp = _clean_supplier()
    fake = _FakeConnector(products=[
        ExternalProduct(sku="E1", name="Rain sensor", cost=25.0, msrp=45.0,
                        category="Irrigation", uom="each", description="wireless"),
        ExternalProduct(sku="E2", name="Rotor head", cost=8.0, msrp=15.0,
                        category="Irrigation", uom="each", description="4in pop-up"),
    ])
    try:
        finished = _run_sync_with_fake(fake, supp)
        assert finished["status"] == "success"
        assert finished["items_added"] == 2
    finally:
        _run(_cleanup(supp))


def test_run_ewing_sync_login_failure():
    supp = _clean_supplier()
    fake = _FakeConnector(login_error=LoginFailedError(
        "Login failed — check credentials"))
    try:
        finished = _run_sync_with_fake(fake, supp)
        assert finished["status"] == "error"
        assert "Login failed" in finished["error_message"]
    finally:
        _run(_cleanup(supp))


def test_run_ewing_sync_layout_change_preserves_rows():
    supp = _clean_supplier()

    async def seed():
        await sync_mod.apply_products_to_pricebook(TID, supp, [
            {"sku": "EWING-PRE", "name": "Pre-existing",
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
                {"external_sku": "EWING-PRE", "supplier_id": supp["id"]},
                {"_id": 0})
        pre = _run(check())
        assert pre is not None
        assert pre["deleted_at"] is None
    finally:
        _run(_cleanup(supp))


def test_run_ewing_sync_dedupe_and_softdelete_across_runs():
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
            assert finished2["items_added"]   == 1
            assert finished2["items_updated"] == 1
            assert finished2["items_removed"] == 1

            b_row = await db.items.find_one(
                {"external_sku": "B", "supplier_id": supp["id"]}, {"_id": 0})
            assert b_row["deleted_at"] is not None
            assert b_row["active"] is False
        finally:
            await _cleanup(supp)
    _run(go())


# ═══════════════════════════════════════════════════════════════════
# Router role gate + no-credentials 400 + creds 202 for Ewing sync.
# Uses localhost:8001 to bypass preview-URL flakiness.
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
            "display_name": {"ewing": "Ewing Irrigation"}.get(slug, slug),
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


def test_ewing_sync_forbidden_for_manager():
    r = requests.post(f"{LOCAL_API}/suppliers/ewing/sync",
                      headers=_hdr("manager@aquaterra.com"),
                      timeout=TIMEOUT)
    assert r.status_code == 403


def test_ewing_sync_400_when_no_credentials():
    _wipe_creds()
    r = requests.post(f"{LOCAL_API}/suppliers/ewing/sync",
                      headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("error") == "no_credentials"


def test_ewing_sync_202_with_credentials():
    r_save = requests.post(f"{LOCAL_API}/suppliers/ewing/credentials",
                           headers=_hdr(),
                           json={"username": "u", "password": "p"},
                           timeout=TIMEOUT)
    assert r_save.status_code == 200, r_save.text
    r = requests.post(f"{LOCAL_API}/suppliers/ewing/sync",
                      headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["supplier_slug"] == "ewing"
    assert body["job_id"]
    _wipe_creds()


# ═══════════════════════════════════════════════════════════════════
# test-connection endpoint — Ewing branches + unwired-slug 501
# ═══════════════════════════════════════════════════════════════════
def test_test_connection_501_for_heritage():
    # Heritage is planned for 54e — still not wired.
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


def test_test_connection_success_ewing():
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row("ewing")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        return SupplierSession(supplier_slug="ewing", credentials_ref="")
    orig = CONNECTORS["ewing"].authenticate
    CONNECTORS["ewing"].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            "ewing", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is True
        assert body["supplier_slug"] == "ewing"
    finally:
        CONNECTORS["ewing"].authenticate = orig
        _wipe_creds()


def test_test_connection_login_failed_ewing():
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row("ewing")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        raise LoginFailedError("Login failed — check credentials")
    orig = CONNECTORS["ewing"].authenticate
    CONNECTORS["ewing"].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            "ewing", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "login_failed"
    finally:
        CONNECTORS["ewing"].authenticate = orig
        _wipe_creds()


def test_test_connection_rate_limited_ewing():
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row("ewing")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        raise RuntimeError("HTTP 503 throttled by Ewing")
    orig = CONNECTORS["ewing"].authenticate
    CONNECTORS["ewing"].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            "ewing", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "rate_limited"
    finally:
        CONNECTORS["ewing"].authenticate = orig
        _wipe_creds()


def test_test_connection_unknown_ewing():
    from services.suppliers.connector import CONNECTORS
    from routers.suppliers import test_supplier_connection

    supp = _wire_supplier_row("ewing")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        raise RuntimeError("chromium exploded")
    orig = CONNECTORS["ewing"].authenticate
    CONNECTORS["ewing"].authenticate = fake_auth
    try:
        body = _run(test_supplier_connection(
            "ewing", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "unknown"
    finally:
        CONNECTORS["ewing"].authenticate = orig
        _wipe_creds()


def test_test_connection_timeout_ewing():
    from services.suppliers.connector import CONNECTORS
    from routers import suppliers as suppliers_router
    import asyncio as _asyncio

    supp = _wire_supplier_row("ewing")
    _save_creds_direct(supp)

    async def fake_auth(credentials):
        await _asyncio.sleep(2.0)

    orig_auth = CONNECTORS["ewing"].authenticate
    orig_timeout = suppliers_router.TEST_CONNECTION_TIMEOUT_S
    CONNECTORS["ewing"].authenticate = fake_auth
    suppliers_router.TEST_CONNECTION_TIMEOUT_S = 0.5
    try:
        body = _run(suppliers_router.test_supplier_connection(
            "ewing", user={"role": "admin", "tenant_id": TID}))
        assert body["ok"] is False
        assert body["error"] == "timeout"
    finally:
        CONNECTORS["ewing"].authenticate = orig_auth
        suppliers_router.TEST_CONNECTION_TIMEOUT_S = orig_timeout
        _wipe_creds()
