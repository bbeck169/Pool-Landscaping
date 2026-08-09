"""Phase 54b · Feb-2026 — Pool360 connector + sync flow tests.

Playwright is fully mocked. NO live Pool360 network calls. Covers:

* ``_parse_price`` helper — currency parse
* Sync insert / update / soft-delete reconciliation
* Empty product list refuses to wipe existing rows
* ``run_poolcorp_sync`` success path (mocked connector)
* ``run_poolcorp_sync`` login failure → job.status == "error"
* ``run_poolcorp_sync`` layout-change → job.status == "error"
  AND pre-existing supplier rows NOT soft-deleted
* Router: manager role → 403 on ``POST /suppliers/poolcorp/sync``
* Router: no credentials saved → 400 with ``error=no_credentials``
* Router: creds saved → 202 Accepted + job_id + status=running

Uses ``batch_safe_run`` (session-persistent event loop + Motor
rebind) so every ``asyncio.run``-style entry point stays bound to
the same loop across tests. See ``tests/_phase34_asyncio.py``.
"""
from __future__ import annotations

import uuid

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient

from tests._phase34_asyncio import batch_safe_run as _run

from services.suppliers.poolcorp import (
    PoolCorpConnector, LoginFailedError, LayoutChangedError, _parse_price,
)
from services.suppliers.connector import ExternalProduct, SupplierSession
from services.suppliers import sync as sync_mod


TID = "3814833a-dd0d-4bd9-90ea-351c24924649"


def _get_db():
    from config import db
    return db


def _clean_supplier():
    return {"id": f"supp-{uuid.uuid4()}", "slug": "poolcorp",
            "tenant_id": TID}


async def _cleanup(supp):
    db = _get_db()
    await db.items.delete_many({"supplier_id": supp["id"]})
    await db.supplier_sync_jobs.delete_many({"supplier_id": supp["id"]})


# ═══════════════════════════════════════════════════════════════════
# _parse_price helper
# ═══════════════════════════════════════════════════════════════════
def test_parse_price_helper():
    assert _parse_price("$1,234.56") == 1234.56
    assert _parse_price("42") == 42.0
    assert _parse_price(None) is None
    assert _parse_price("") is None
    assert _parse_price("abc") is None


# ═══════════════════════════════════════════════════════════════════
# Sync reconciliation
# ═══════════════════════════════════════════════════════════════════
def test_apply_products_insert_update_softdelete():
    supp = _clean_supplier()

    async def go():
        try:
            counts1 = await sync_mod.apply_products_to_pricebook(TID, supp, [
                {"sku": "SKU-A", "name": "Filter A", "cost": 10.0, "msrp": 25.0,
                 "category": "Filters", "uom": "each", "description": "small"},
                {"sku": "SKU-B", "name": "Pump B", "cost": 100.0, "msrp": 250.0,
                 "category": "Pumps", "uom": "each", "description": "1HP"},
            ])
            assert counts1 == {"added": 2, "updated": 0, "removed": 0}

            counts2 = await sync_mod.apply_products_to_pricebook(TID, supp, [
                {"sku": "SKU-A", "name": "Filter A v2", "cost": 12.0, "msrp": 30.0,
                 "category": "Filters", "uom": "each"},
                {"sku": "SKU-C", "name": "Heater C", "cost": 200.0, "msrp": 400.0,
                 "category": "Heaters", "uom": "each"},
            ])
            assert counts2 == {"added": 1, "updated": 1, "removed": 1}

            db = _get_db()
            a = await db.items.find_one(
                {"external_sku": "SKU-A", "supplier_id": supp["id"]},
                {"_id": 0})
            b = await db.items.find_one(
                {"external_sku": "SKU-B", "supplier_id": supp["id"]},
                {"_id": 0})
            assert a["name"] == "Filter A v2" and a["wholesale_price"] == 12.0
            assert b["deleted_at"] is not None and b["active"] is False
        finally:
            await _cleanup(supp)

    _run(go())


def test_apply_products_empty_list_refuses_to_wipe():
    supp = _clean_supplier()

    async def go():
        try:
            await sync_mod.apply_products_to_pricebook(TID, supp, [
                {"sku": "SKU-X", "name": "X", "cost": 1.0, "msrp": 2.0}])
            counts = await sync_mod.apply_products_to_pricebook(TID, supp, [])
            assert counts == {"added": 0, "updated": 0, "removed": 0}
            db = _get_db()
            row = await db.items.find_one(
                {"external_sku": "SKU-X", "supplier_id": supp["id"]},
                {"_id": 0})
            assert row["deleted_at"] is None
        finally:
            await _cleanup(supp)

    _run(go())


# ═══════════════════════════════════════════════════════════════════
# run_poolcorp_sync — fully mocked connector (no Playwright)
# ═══════════════════════════════════════════════════════════════════
class _FakeConnector:
    slug = "poolcorp"
    display_name = "Pool360 (PoolCorp)"

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


def _run_sync_with_fake(fake, supp, credentials=None):
    async def go():
        import services.suppliers.poolcorp as pc_mod
        orig = pc_mod.PoolCorpConnector
        pc_mod.PoolCorpConnector = lambda: fake
        try:
            job = await sync_mod.start_sync_job(TID, supp)
            await sync_mod.run_poolcorp_sync(
                TID, supp, credentials or {"username": "u", "password": "p"},
                job["id"],
            )
            db = _get_db()
            return await db.supplier_sync_jobs.find_one(
                {"id": job["id"]}, {"_id": 0})
        finally:
            pc_mod.PoolCorpConnector = orig

    return _run(go())


def test_run_poolcorp_sync_success():
    supp = _clean_supplier()
    fake = _FakeConnector(products=[
        ExternalProduct(sku="P1", name="Chlorine tabs", cost=15.0, msrp=25.0,
                        category="Chemicals", uom="case", description="10lb"),
    ])
    try:
        finished = _run_sync_with_fake(fake, supp)
        assert finished["status"] == "success"
        assert finished["items_added"] == 1
    finally:
        _run(_cleanup(supp))


def test_run_poolcorp_sync_login_failure():
    supp = _clean_supplier()
    fake = _FakeConnector(login_error=LoginFailedError(
        "Login failed — check credentials"))
    try:
        finished = _run_sync_with_fake(fake, supp)
        assert finished["status"] == "error"
        assert "Login failed" in finished["error_message"]
    finally:
        _run(_cleanup(supp))


def test_run_poolcorp_sync_layout_change():
    supp = _clean_supplier()

    async def seed():
        await sync_mod.apply_products_to_pricebook(TID, supp, [
            {"sku": "PRE", "name": "Pre-existing", "cost": 1.0, "msrp": 2.0}])
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
                {"external_sku": "PRE", "supplier_id": supp["id"]},
                {"_id": 0})
        pre = _run(check())
        assert pre["deleted_at"] is None
    finally:
        _run(_cleanup(supp))


# ═══════════════════════════════════════════════════════════════════
# Router: role gate + no-credentials 400 + creds 202
# ═══════════════════════════════════════════════════════════════════
# Hits the SUPERVISOR-managed backend on localhost — bypasses the
# preview-URL alias conftest installs, because those DNS-fronted
# hosts can throw sporadic ReadTimeouts under batch runs (see the
# Phase-34 timeout cluster we haven't shipped a fix for yet).
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


def _wipe_admin_creds():
    be = dotenv_values("/app/backend/.env")
    mc = MongoClient(be["MONGO_URL"])
    try:
        db_sync = mc[be["DB_NAME"]]
        db_sync.supplier_credentials.delete_many({"tenant_id": TID})
    finally:
        mc.close()


def test_poolcorp_sync_forbidden_for_manager():
    r = requests.post(f"{LOCAL_API}/suppliers/poolcorp/sync",
                      headers=_hdr("manager@aquaterra.com"),
                      timeout=TIMEOUT)
    assert r.status_code == 403, r.text


def test_poolcorp_sync_400_when_no_credentials():
    _wipe_admin_creds()
    r = requests.post(f"{LOCAL_API}/suppliers/poolcorp/sync",
                      headers=_hdr(), timeout=TIMEOUT)
    assert r.status_code == 400, r.text
    detail = r.json().get("detail") or {}
    assert isinstance(detail, dict)
    assert detail.get("error") == "no_credentials"


def test_poolcorp_sync_202_with_credentials():
    r_save = requests.post(f"{LOCAL_API}/suppliers/poolcorp/credentials",
                           headers=_hdr(),
                           json={"username": "u", "password": "p"},
                           timeout=TIMEOUT)
    assert r_save.status_code == 200, r_save.text

    r = requests.post(f"{LOCAL_API}/suppliers/poolcorp/sync",
                      headers=_hdr(), timeout=TIMEOUT)
    # The HTTP contract we're locking is 202 + job_id + status=running.
    # The background task will attempt a Pool360 request and fail
    # quickly (test env has no external network) — that failure is
    # captured in the job row and NOT in the HTTP response.
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["supplier_slug"] == "poolcorp"
    assert body["job_id"]

    _wipe_admin_creds()
