"""Pricebook × Profit-Reporting Phase 1 · Feb-2026 —
`/api/{axis}-categories/{cid}/references` reference-count endpoints.

Covers both axes (income + service) and asserts:
  * 200 for admin, 403 for non-admin roles,
  * counts include pricebook items AND historical line items nested
    inside `db.quotes.line_items[]`,
  * `is_archived` flag is echoed from the category doc,
  * 404 for a bogus category id.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = _shared_client()
_db = _shared_db()
_CACHE: dict = {}


def _login(email: str) -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
        timeout=30,
    )
    r.raise_for_status()
    _CACHE[key] = r.json()["access_token"]
    return _CACHE[key]


def _admin_ctx() -> dict:
    if _CACHE.get("ctx"):
        return _CACHE["ctx"]
    tok = _login("admin@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=15
    ).json()
    _CACHE["ctx"] = {"token": tok, "tenant_id": me["tenant_id"]}
    return _CACHE["ctx"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── Fixture: one income + one service category, plus one pricebook
# ─── item and one quote line item referencing each. ────────────────
@pytest.fixture(scope="module")
def seeded_refs():
    ctx = _admin_ctx()
    tid = ctx["tenant_id"]

    inc_id = f"pb1-inc-{uuid.uuid4()}"
    svc_id = f"pb1-svc-{uuid.uuid4()}"
    _db.income_categories.insert_one(
        {"id": inc_id, "tenant_id": tid, "name": f"PB1-INC-{inc_id[-6:]}",
         "is_archived": False}
    )
    _db.service_categories.insert_one(
        {"id": svc_id, "tenant_id": tid, "name": f"PB1-SVC-{svc_id[-6:]}",
         "is_archived": False}
    )

    item_id = f"pb1-item-{uuid.uuid4()}"
    _db.items.insert_one({
        "id": item_id, "tenant_id": tid, "name": "PB1 sample",
        "active": True,
        "income_category_id": inc_id, "service_category_id": svc_id,
    })

    quote_id = f"pb1-quote-{uuid.uuid4()}"
    _db.quotes.insert_one({
        "id": quote_id, "tenant_id": tid, "doc_type": "quote",
        "customer_id": "test-customer",
        "line_items": [{
            "description": "X",
            "quantity": 1, "unit_price": 10,
            "income_category_id": inc_id,
            "service_category_id": svc_id,
        }],
    })

    yield {"income_id": inc_id, "service_id": svc_id,
           "quote_id": quote_id, "item_id": item_id}

    # Best-effort teardown.
    _db.income_categories.delete_one({"id": inc_id})
    _db.service_categories.delete_one({"id": svc_id})
    _db.items.delete_one({"id": item_id})
    _db.quotes.delete_one({"id": quote_id})


def test_income_references_counts(seeded_refs):
    ctx = _admin_ctx()
    r = requests.get(
        f"{API}/income-categories/{seeded_refs['income_id']}/references",
        headers=_headers(ctx["token"]), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category_id"] == seeded_refs["income_id"]
    assert body["kind"] == "income"
    assert body["is_archived"] is False
    assert body["pricebook_item_count"] >= 1
    assert body["line_item_count"] >= 1


def test_service_references_counts(seeded_refs):
    ctx = _admin_ctx()
    r = requests.get(
        f"{API}/service-categories/{seeded_refs['service_id']}/references",
        headers=_headers(ctx["token"]), timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "service"
    assert body["is_archived"] is False
    assert body["pricebook_item_count"] >= 1
    assert body["line_item_count"] >= 1


def test_references_404_for_bogus_id():
    ctx = _admin_ctx()
    r = requests.get(
        f"{API}/income-categories/does-not-exist/references",
        headers=_headers(ctx["token"]), timeout=15,
    )
    assert r.status_code == 404


def test_references_admin_only():
    # Technician role should be forbidden.
    tok = _login("mike@aquaterra.com")
    # Grab any income category for the tenant to guarantee route hits
    # the auth check, not the 404 branch.
    doc = _db.income_categories.find_one({"is_archived": {"$ne": True}})
    if not doc:
        pytest.skip("no income category to probe")
    r = requests.get(
        f"{API}/income-categories/{doc['id']}/references",
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 403


def test_references_respects_archive_flag(seeded_refs):
    ctx = _admin_ctx()
    _db.income_categories.update_one(
        {"id": seeded_refs["income_id"]},
        {"$set": {"is_archived": True}},
    )
    try:
        r = requests.get(
            f"{API}/income-categories/{seeded_refs['income_id']}/references",
            headers=_headers(ctx["token"]), timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["is_archived"] is True
    finally:
        _db.income_categories.update_one(
            {"id": seeded_refs["income_id"]},
            {"$set": {"is_archived": False}},
        )
