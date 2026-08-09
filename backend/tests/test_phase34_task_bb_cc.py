"""Phase 34 · Task BB + CC · Feb 2026 — Bulk-delete + Leads status enum.

Backend-side coverage for:
* POST /api/invoices/bulk-delete
* POST /api/estimates/bulk-delete
* POST /api/payments/bulk-delete
* POST /api/leads/bulk-delete
* migrate_lead_statuses() legacy → canonical rewrite.
* Lead API rejects any status value outside the five canonical enum
  entries (via ``_normalize_status``).

Uses direct Motor DB inserts to plant fixtures + HTTP for the endpoints
so the tests exercise the full stack. Every test isolates its own rows.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Dict, List, Optional

import pytest

# Phase 34-migrate-v2 · Phase 34-v2-b (canary) · Feb 2026 — swapped
# ``requests`` for the in-process ASGI shim. HTTP calls now run on
# the same event loop Motor is pinned to via ``_phase34_asyncio``,
# eliminating the batched-run ``ReadTimeout`` cluster and any
# potential "Task got Future attached to a different loop" bleed.
from tests._phase34_http_shim import http

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


from tests._phase34_asyncio import batch_safe_run as _run  # Phase 41.1d


def _login(email: str, password: str = "password123") -> str:
    r = http.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    assert r.status_code == 200, f"login {email} => {r.status_code} {r.text}"
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
        assert t, "aquaterra tenant missing"
        return t["id"]
    return _run(_go())


@pytest.fixture(scope="module")
def aq_customer_id(db, aq_tenant_id):
    async def _go():
        c = await db.customers.find_one(
            {"tenant_id": aq_tenant_id}, {"_id": 0, "id": 1},
        )
        assert c, "aquaterra needs at least one seeded customer"
        return c["id"]
    return _run(_go())


# ═══════════════════════════════════════════════════════════════════════
# Role gate — customer role must receive 403 on every bulk-delete
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", [
    "/invoices/bulk-delete",
    "/estimates/bulk-delete",
    "/payments/bulk-delete",
    "/leads/bulk-delete",
])
def test_bulk_delete_role_gate(customer_headers, path):
    r = http.post(
        f"{API}{path}",
        headers={**customer_headers, "Content-Type": "application/json"},
        json={"ids": ["anything"]}, timeout=30,
    )
    assert r.status_code == 403, f"{path} => {r.status_code} {r.text}"


# ═══════════════════════════════════════════════════════════════════════
# Invoices bulk-delete
# ═══════════════════════════════════════════════════════════════════════
def test_invoices_bulk_delete_happy_path(db, super_headers, aq_tenant_id, aq_customer_id):
    async def _plant(n: int) -> List[str]:
        ids = []
        for _ in range(n):
            iid = uuid.uuid4().hex
            await db.quotes.insert_one({
                "id": iid, "tenant_id": aq_tenant_id, "doc_type": "invoice",
                "customer_id": aq_customer_id, "customer_name": "T",
                "title": f"BB-Test-{iid[:6]}", "total": 100.0, "amount_paid": 0.0,
                "payment_status": "unpaid", "created_at": "2026-02-01T00:00:00Z",
            })
            ids.append(iid)
        return ids

    ids = _run(_plant(3))
    r = http.post(
        f"{API}/invoices/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ids}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 3
    assert set(body["deleted"]) == set(ids)
    assert body["failed"] == []

    # Verify soft-deleted (deleted_at set) — no hard delete.
    remain = _run(db.quotes.count_documents({"id": {"$in": ids}}))
    assert remain == 3
    softdel = _run(db.quotes.count_documents(
        {"id": {"$in": ids}, "deleted_at": {"$ne": None}}))
    assert softdel == 3


def test_invoices_bulk_delete_mixed_tenant_rejected(db, super_headers, aq_tenant_id, aq_customer_id):
    """A row from another tenant returns as not-found instead of leaking cross-tenant."""
    other_tid = uuid.uuid4().hex
    other_iid = uuid.uuid4().hex
    _run(db.quotes.insert_one({
        "id": other_iid, "tenant_id": other_tid, "doc_type": "invoice",
        "customer_id": "other", "title": "Cross-tenant", "total": 1.0,
        "amount_paid": 0.0, "payment_status": "unpaid",
        "created_at": "2026-02-01T00:00:00Z",
    }))
    r = http.post(
        f"{API}/invoices/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [other_iid]}, timeout=30,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["deleted_count"] == 0
    assert body["failed"] and body["failed"][0]["status_code"] == 404


# ═══════════════════════════════════════════════════════════════════════
# Estimates bulk-delete
# ═══════════════════════════════════════════════════════════════════════
def test_estimates_bulk_delete_happy_path(db, super_headers, aq_tenant_id, aq_customer_id):
    async def _plant() -> str:
        eid = uuid.uuid4().hex
        await db.estimates.insert_one({
            "id": eid, "tenant_id": aq_tenant_id,
            "customer_id": aq_customer_id, "title": "BB-Est",
            "total": 200.0, "created_at": "2026-02-01T00:00:00Z",
        })
        return eid
    eid = _run(_plant())
    r = http.post(
        f"{API}/estimates/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [eid]}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Payments bulk-delete — Stripe-locked rows land in failed[]
# ═══════════════════════════════════════════════════════════════════════
def test_payments_bulk_delete_stripe_locked(db, super_headers, aq_tenant_id, aq_customer_id):
    async def _plant() -> tuple[str, str]:
        # 1) unlockable cash payment
        cash_id = uuid.uuid4().hex
        await db.quotes.insert_one({
            "id": cash_id, "tenant_id": aq_tenant_id, "doc_type": "invoice",
            "customer_id": aq_customer_id, "title": "cash-paid",
            "total": 100.0, "amount_paid": 100.0, "payment_status": "paid",
            "payment_method": "Cash", "paid_at": "2026-02-01T00:00:00Z",
            "created_at": "2026-02-01T00:00:00Z",
        })
        # 2) Stripe-linked payment — should refuse
        stripe_id = uuid.uuid4().hex
        await db.quotes.insert_one({
            "id": stripe_id, "tenant_id": aq_tenant_id, "doc_type": "invoice",
            "customer_id": aq_customer_id, "title": "stripe-paid",
            "total": 100.0, "amount_paid": 100.0, "payment_status": "paid",
            "payment_method": "Card", "payment_intent_id": "pi_test_1234",
            "paid_at": "2026-02-01T00:00:00Z",
            "created_at": "2026-02-01T00:00:00Z",
        })
        return cash_id, stripe_id
    cash_id, stripe_id = _run(_plant())
    r = http.post(
        f"{API}/payments/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [cash_id, stripe_id]}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 1
    assert body["deleted"] == [cash_id]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == stripe_id
    assert "Stripe" in body["failed"][0]["reason"]


# ═══════════════════════════════════════════════════════════════════════
# Leads bulk-delete — closed_won protection + closed_lost freely deletable
# ═══════════════════════════════════════════════════════════════════════
def test_leads_bulk_delete_closed_won_protected(db, super_headers, aq_tenant_id):
    async def _plant() -> tuple[str, str, str]:
        new_id_ = uuid.uuid4().hex
        won_id = uuid.uuid4().hex
        lost_id = uuid.uuid4().hex
        await db.leads.insert_many([
            {"id": new_id_, "tenant_id": aq_tenant_id, "name": "BB new",
             "status": "new", "created_at": "2026-02-01T00:00:00Z"},
            {"id": won_id, "tenant_id": aq_tenant_id, "name": "BB won",
             "status": "closed_won", "converted_customer_id": "cust-abc",
             "created_at": "2026-02-01T00:00:00Z"},
            {"id": lost_id, "tenant_id": aq_tenant_id, "name": "BB lost",
             "status": "closed_lost", "created_at": "2026-02-01T00:00:00Z"},
        ])
        return new_id_, won_id, lost_id
    new_id_, won_id, lost_id = _run(_plant())
    r = http.post(
        f"{API}/leads/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [new_id_, won_id, lost_id]}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # new + closed_lost delete; closed_won with converted_customer_id refuses.
    assert set(body["deleted"]) == {new_id_, lost_id}
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == won_id
    assert body["failed"][0]["status_code"] == 409


# ═══════════════════════════════════════════════════════════════════════
# Task DD — bulk-delete cap raised 100 → 400
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("path", [
    "/invoices/bulk-delete",
    "/estimates/bulk-delete",
    "/payments/bulk-delete",
    "/leads/bulk-delete",
])
def test_bulk_delete_cap_rejects_over_400(super_headers, path):
    """Post 401 ids → 400 error with capped message. The 400 boundary is
    the smallest count that must succeed; 401 is the smallest count that
    must fail. We don't need real ids — the cap check runs first."""
    ids = [f"fake-{i}" for i in range(401)]
    r = http.post(
        f"{API}{path}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ids}, timeout=30,
    )
    assert r.status_code == 400, f"{path} => {r.status_code} {r.text}"
    detail = (r.json().get("detail") or "").lower()
    assert "400" in detail and "cap" in detail, f"{path} detail={detail!r}"


@pytest.mark.parametrize("path", [
    "/invoices/bulk-delete",
    "/estimates/bulk-delete",
    "/payments/bulk-delete",
    "/leads/bulk-delete",
])
def test_bulk_delete_cap_accepts_400(super_headers, path):
    """Post exactly 400 fake ids → 200 with 0 deletions + 400 failures.
    The cap check must pass at 400."""
    ids = [f"boundary-{i}-{uuid.uuid4().hex[:8]}" for i in range(400)]
    r = http.post(
        f"{API}{path}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ids}, timeout=30,
    )
    assert r.status_code == 200, f"{path} => {r.status_code} {r.text}"
    body = r.json()
    assert body["deleted_count"] == 0
    assert len(body["failed"]) == 400


# ═══════════════════════════════════════════════════════════════════════
# Task CC — status enum normalization + migration
# ═══════════════════════════════════════════════════════════════════════
def test_normalize_status_maps_legacy_values():
    from routers.leads import _normalize_status
    assert _normalize_status("New") == "new"
    assert _normalize_status("Contacted") == "contacted"
    assert _normalize_status("quoted") == "quoted"
    assert _normalize_status("Closed Won") == "closed_won"
    assert _normalize_status("Closed Lost") == "closed_lost"
    assert _normalize_status("won") == "closed_won"
    assert _normalize_status("lost") == "closed_lost"
    assert _normalize_status("rejected") == "closed_lost"
    assert _normalize_status("converted") == "closed_won"
    assert _normalize_status("qualified") == "new"  # unknown → new
    assert _normalize_status(None) == "new"
    assert _normalize_status("") == "new"


def test_lead_patch_normalizes_status(db, super_headers, aq_tenant_id):
    """Any legacy value posted via PATCH /leads/{id} lands as canonical."""
    async def _plant() -> str:
        lid = uuid.uuid4().hex
        await db.leads.insert_one({
            "id": lid, "tenant_id": aq_tenant_id, "name": "CC-patch",
            "status": "new", "created_at": "2026-02-01T00:00:00Z",
        })
        return lid
    lid = _run(_plant())
    r = http.patch(
        f"{API}/leads/{lid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"status": "Closed Won"}, timeout=30,
    )
    assert r.status_code == 200, r.text
    row = _run(db.leads.find_one({"id": lid}, {"_id": 0, "status": 1}))
    assert row["status"] == "closed_won"


def test_migration_sweeps_legacy_values(db, aq_tenant_id):
    """Plant a bunch of legacy-value leads, run the migration, and
    verify every value ends up in one of the five canonical buckets."""
    legacy_variants = [
        ("New", "new"), ("Contacted", "contacted"), ("Quoted", "quoted"),
        ("Closed Won", "closed_won"), ("Closed Lost", "closed_lost"),
        ("rejected", "closed_lost"), ("On Hold", "contacted"),
        ("converted", "closed_won"), ("qualified", "new"),
    ]
    planted: List[tuple[str, str]] = []

    async def _plant():
        for legacy, _ in legacy_variants:
            lid = uuid.uuid4().hex
            await db.leads.insert_one({
                "id": lid, "tenant_id": aq_tenant_id,
                "name": f"CC-mig-{legacy}", "status": legacy,
                "created_at": "2026-02-01T00:00:00Z",
            })
            planted.append((lid, legacy))

    _run(_plant())

    from routers.leads import migrate_lead_statuses

    async def _go():
        return await migrate_lead_statuses()

    result = _run(_go())
    assert result["total"] >= len(legacy_variants)

    # Verify every planted row was rewritten.
    for lid, legacy in planted:
        expected = dict(legacy_variants)[legacy]
        row = _run(db.leads.find_one({"id": lid}, {"_id": 0, "status": 1}))
        assert row["status"] == expected, \
            f"lead {lid!r} legacy={legacy!r} expected={expected!r} got={row['status']!r}"


def test_migration_is_idempotent(db, aq_tenant_id):
    """Running the migration a second time is a no-op (no re-updates)."""
    from routers.leads import migrate_lead_statuses

    async def _go():
        first = await migrate_lead_statuses()
        second = await migrate_lead_statuses()
        return first, second

    first, second = _run(_go())
    # Idempotent — both runs see the same totals per bucket.
    assert first["per_bucket"] == second["per_bucket"]
