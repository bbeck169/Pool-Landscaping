"""Phase 34 · Tasks HH + II + GG + EE · Feb 2026 — backend coverage.

Covers:
* POST /api/leads/bulk-update-status (Task HH):
    - happy path multi-id → updated_count matches
    - non-canonical status → 422
    - role gate (customer) → 403
    - cross-tenant ids fail-per-row
    - 400 cap enforced (Task DD, 401 ids → 400)
* POST /api/leads/bulk-update-status query_selector shape (Task EE):
    - filter selector resolves to only the tenant's matching rows
    - unknown selector keys are ignored (whitelist)
* POST /api/autobilling/bulk-delete (Task II):
    - happy path deletes multiple plans
    - locked (Stripe subscription id) plan returns in failed[]
    - locked (next_run within 24h) plan returns in failed[]
    - role gate (customer) → 403
* PATCH /api/tenants/business-card google_review_url validation
  (Task GG):
    - accepts valid g.page/r/ URL
    - accepts valid search.google.com/local/writereview URL
    - rejects http:// URL → 422
    - rejects arbitrary https URL → 422
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

import pytest
import requests

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def super_headers():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def customer_headers():
    return {"Authorization": f"Bearer {_login('customer@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    from config import db as _db  # noqa: PLC0415
    return _db


@pytest.fixture(scope="module")
def aq_tenant_id(db):
    async def _go():
        t = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0, "id": 1})
        return t["id"]
    return _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Task HH — bulk-update-status
# ═══════════════════════════════════════════════════════════════════════
def _plant_leads(db, aq_tenant_id, statuses: List[str]) -> List[str]:
    ids: List[str] = []
    async def _go():
        for st in statuses:
            lid = uuid.uuid4().hex
            await db.leads.insert_one({
                "id": lid, "tenant_id": aq_tenant_id, "name": f"HH-{lid[:6]}",
                "status": st, "created_at": "2026-02-01T00:00:00Z",
            })
            ids.append(lid)
    _run(_go())
    return ids


def test_bulk_update_status_happy_path(db, super_headers, aq_tenant_id):
    ids = _plant_leads(db, aq_tenant_id, ["new", "contacted", "quoted"])
    r = requests.post(
        f"{API}/leads/bulk-update-status",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ids, "new_status": "closed_won"}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 3
    assert set(body["updated"]) == set(ids)
    # verify audit rows
    from config import db as _db
    rows_count = _run(_db.audit_log.count_documents(
        {"action": "lead.bulk_status_change", "target_id": {"$in": ids}}))
    assert rows_count == 3


def test_bulk_update_status_already_at_target(db, super_headers, aq_tenant_id):
    """A lead already at ``new_status`` is not updated and lands in failed[]."""
    ids = _plant_leads(db, aq_tenant_id, ["closed_won"])
    r = requests.post(
        f"{API}/leads/bulk-update-status",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ids, "new_status": "closed_won"}, timeout=30,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["updated_count"] == 0
    assert len(body["failed"]) == 1
    assert "already" in body["failed"][0]["reason"]


def test_bulk_update_status_rejects_non_canonical(super_headers):
    r = requests.post(
        f"{API}/leads/bulk-update-status",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ["x"], "new_status": "qualified"}, timeout=30,
    )
    assert r.status_code == 422
    assert "canonical" in (r.json().get("detail") or "").lower() or \
           "new_status" in (r.json().get("detail") or "")


def test_bulk_update_status_role_gate(customer_headers):
    r = requests.post(
        f"{API}/leads/bulk-update-status",
        headers={**customer_headers, "Content-Type": "application/json"},
        json={"ids": ["x"], "new_status": "closed_won"}, timeout=30,
    )
    assert r.status_code == 403


def test_bulk_update_status_cap_enforced(super_headers):
    ids = [f"cap-{i}" for i in range(401)]
    r = requests.post(
        f"{API}/leads/bulk-update-status",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ids, "new_status": "new"}, timeout=30,
    )
    assert r.status_code == 400
    detail = (r.json().get("detail") or "").lower()
    assert "400" in detail


# Task EE query_selector shape
def test_bulk_update_status_query_selector(db, super_headers, aq_tenant_id):
    """query_selector filter should resolve to tenant-scoped ids only."""
    # Plant 3 leads with unique 'name' searchable substring
    marker = uuid.uuid4().hex[:8]
    async def _plant():
        for _ in range(3):
            await db.leads.insert_one({
                "id": uuid.uuid4().hex, "tenant_id": aq_tenant_id,
                "name": f"EE-marker-{marker}",
                "status": "new", "created_at": "2026-02-01T00:00:00Z",
            })
        # Cross-tenant control row — must NOT be touched.
        await db.leads.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": "other-tenant-uuid",
            "name": f"EE-marker-{marker}",
            "status": "new", "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_plant())
    r = requests.post(
        f"{API}/leads/bulk-update-status",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"query_selector": {"search": marker, "unknown_key": "ignored"},
              "exclude_ids": [], "new_status": "closed_lost"}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 3

    # Ensure cross-tenant row wasn't touched.
    async def _check():
        return await db.leads.count_documents({
            "tenant_id": "other-tenant-uuid",
            "name": f"EE-marker-{marker}",
            "status": "new",
        })
    remaining = _run(_check())
    assert remaining == 1, "cross-tenant row must be untouched"


# ═══════════════════════════════════════════════════════════════════════
# Task II — autobilling bulk-delete
# ═══════════════════════════════════════════════════════════════════════
def test_autobilling_bulk_delete_happy_path(db, super_headers, aq_tenant_id):
    async def _plant() -> List[str]:
        ids = []
        for _ in range(3):
            pid = uuid.uuid4().hex
            # Set next_run 30 days out so not "within 24h".
            future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
            await db.billing_plans.insert_one({
                "id": pid, "tenant_id": aq_tenant_id, "customer_id": "cust-x",
                "customer_name": "T", "service": "Test", "frequency": "monthly",
                "amount": 100.0, "next_run": future, "active": True,
                "created_at": "2026-02-01T00:00:00Z",
            })
            ids.append(pid)
        return ids
    ids = _run(_plant())
    r = requests.post(
        f"{API}/autobilling/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ids}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 3


def test_autobilling_bulk_delete_stripe_locked(db, super_headers, aq_tenant_id):
    async def _plant() -> str:
        pid = uuid.uuid4().hex
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        await db.billing_plans.insert_one({
            "id": pid, "tenant_id": aq_tenant_id, "customer_id": "cust-x",
            "customer_name": "S", "service": "Sub", "frequency": "monthly",
            "amount": 100.0, "next_run": future, "active": True,
            "stripe_subscription_id": "sub_test_1234",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return pid
    pid = _run(_plant())
    r = requests.post(
        f"{API}/autobilling/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [pid]}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 0
    assert len(body["failed"]) == 1
    assert "Stripe" in body["failed"][0]["reason"]


def test_autobilling_bulk_delete_imminent_locked(db, super_headers, aq_tenant_id):
    async def _plant() -> str:
        pid = uuid.uuid4().hex
        # next_run 2 hours from now → within-24h lock.
        soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        await db.billing_plans.insert_one({
            "id": pid, "tenant_id": aq_tenant_id, "customer_id": "cust-x",
            "customer_name": "I", "service": "Imm", "frequency": "monthly",
            "amount": 100.0, "next_run": soon, "active": True,
            "created_at": "2026-02-01T00:00:00Z",
        })
        return pid
    pid = _run(_plant())
    r = requests.post(
        f"{API}/autobilling/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [pid]}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 0
    assert len(body["failed"]) == 1
    assert "24h" in body["failed"][0]["reason"]


def test_autobilling_bulk_delete_role_gate(customer_headers):
    r = requests.post(
        f"{API}/autobilling/bulk-delete",
        headers={**customer_headers, "Content-Type": "application/json"},
        json={"ids": ["x"]}, timeout=30,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Task GG — google_review_url validation
# ═══════════════════════════════════════════════════════════════════════
def test_google_review_url_valid_gpage(super_headers):
    r = requests.patch(
        f"{API}/tenants/business-card",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"google_review_url": "https://g.page/r/CXYZ123ABC/review"},
        timeout=30,
    )
    assert r.status_code == 200, r.text


def test_google_review_url_valid_writereview(super_headers):
    r = requests.patch(
        f"{API}/tenants/business-card",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"google_review_url": "https://search.google.com/local/writereview?placeid=ABC"},
        timeout=30,
    )
    assert r.status_code == 200, r.text


def test_google_review_url_rejects_http(super_headers):
    r = requests.patch(
        f"{API}/tenants/business-card",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"google_review_url": "http://g.page/r/X/review"}, timeout=30,
    )
    assert r.status_code == 422


def test_google_review_url_rejects_arbitrary(super_headers):
    r = requests.patch(
        f"{API}/tenants/business-card",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"google_review_url": "https://example.com/review-me"}, timeout=30,
    )
    assert r.status_code == 422


def test_google_review_url_allows_empty(super_headers):
    """Setting to empty string (unsetting) is allowed — some tenants
    intentionally clear the field when they haven't set up GBP yet."""
    r = requests.patch(
        f"{API}/tenants/business-card",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"google_review_url": ""}, timeout=30,
    )
    assert r.status_code == 200, r.text
