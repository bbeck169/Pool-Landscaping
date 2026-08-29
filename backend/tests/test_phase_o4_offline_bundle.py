"""Phase O4 · Feb-2026 — GET /mobile/offline-bundle expansion (G4).

The bundle now MUST include five new collection buckets plus a
per-collection ``versions`` freshness dict and a ``caps`` metadata
block.  Contract:

    * ``invoices``, ``quotes``, ``pricebook_items`` are capped
      (500 / 200 / 500) and ordered ``updated_at`` DESC.
    * ``income_categories`` and ``service_categories`` are small
      (uncapped, one row per tenant taxonomy entry).
    * ``versions`` is a dict of per-collection latest ISO
      timestamps (``None`` when the bucket is empty).
    * ``caps`` mirrors the module-level constants.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os as _os_local
_ENV_BASE = _os_local.environ.get("PHASE_O4_TEST_BASE")
BASE = (_ENV_BASE or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db  # noqa: E402
from utils import new_id, now_iso  # noqa: E402
from routers.mobile_sync import (  # noqa: E402
    BUNDLE_MAX_INVOICES, BUNDLE_MAX_QUOTES, BUNDLE_MAX_PRICEBOOK_ITEMS,
    BUNDLE_MAX_JOBS, OFFLINE_BUNDLE_WINDOW_DAYS,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_h() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def test_offline_bundle_includes_all_new_collections(admin_h):
    r = requests.get(f"{API}/mobile/offline-bundle",
                      headers=admin_h, timeout=15).json()
    for key in ("invoices", "quotes", "income_categories",
                 "service_categories", "pricebook_items",
                 "versions", "caps"):
        assert key in r, f"missing bundle key: {key}"
    assert isinstance(r["invoices"], list)
    assert isinstance(r["quotes"], list)
    assert isinstance(r["income_categories"], list)
    assert isinstance(r["service_categories"], list)
    assert isinstance(r["pricebook_items"], list)
    assert isinstance(r["versions"], dict)
    assert isinstance(r["caps"], dict)


def test_offline_bundle_versions_dict_covers_every_collection(admin_h):
    r = requests.get(f"{API}/mobile/offline-bundle",
                      headers=admin_h, timeout=15).json()
    versions = r["versions"]
    for key in ("jobs", "customers", "service_reports_in_progress",
                 "invoices", "quotes",
                 "income_categories", "service_categories",
                 "pricebook_items"):
        assert key in versions, f"versions missing collection: {key}"
        v = versions[key]
        # Every entry MUST be either None (empty) or an ISO string.
        assert v is None or (isinstance(v, str) and "T" in v)


def test_offline_bundle_caps_mirror_module_constants(admin_h):
    r = requests.get(f"{API}/mobile/offline-bundle",
                      headers=admin_h, timeout=15).json()
    caps = r["caps"]
    assert caps["jobs"] == BUNDLE_MAX_JOBS
    assert caps["invoices"] == BUNDLE_MAX_INVOICES
    assert caps["quotes"] == BUNDLE_MAX_QUOTES
    assert caps["pricebook_items"] == BUNDLE_MAX_PRICEBOOK_ITEMS
    assert caps["window_days"] == OFFLINE_BUNDLE_WINDOW_DAYS


def test_offline_bundle_invoices_ordered_updated_at_desc(admin_h):
    """Seed 3 invoices with staggered ``updated_at`` and prove the
    bundle returns them in DESC order.  Invoices live in
    ``db.quotes`` with ``doc_type == "invoice"`` (CRM quirk)."""
    async def _seed():
        u = await db.users.find_one(
            {"email": "admin@aquaterra.com"}, {"_id": 0})
        tid = u["tenant_id"]
        ids = []
        for i in range(3):
            iid = new_id()
            ids.append(iid)
            await db.quotes.insert_one({
                "id": iid, "tenant_id": tid,
                "doc_type": "invoice",
                # insert_invoice-shaped fingerprint (invoice_number
                # is required by the uniqueness index).
                "invoice_number": f"INV-2026-PHASE-O4-{i:04d}",
                "title": f"phase-o4-bundle-order-{i}",
                "created_at": now_iso(),
                # Staggered so ID index #0 is OLDEST, #2 is NEWEST.
                "updated_at": f"2026-01-0{i + 1}T00:00:00+00:00",
                "total": 10.0, "status": "draft",
            })
        return tid, ids
    tid, seeded_ids = _run(_seed())
    try:
        r = requests.get(f"{API}/mobile/offline-bundle",
                          headers=admin_h, timeout=15).json()
        our_invoices = [i for i in r["invoices"] if i["id"] in seeded_ids]
        assert len(our_invoices) == 3
        # ORDER: newest first — id #2 before id #1 before id #0.
        order = [i["id"] for i in our_invoices]
        assert order == [seeded_ids[2], seeded_ids[1], seeded_ids[0]], \
            f"expected DESC by updated_at, got {order}"
    finally:
        async def _c():
            await db.quotes.delete_many({"id": {"$in": seeded_ids}})
        _run(_c())
