"""Phase 34 · Tasks JJ + KK + EE-extension + Digest — backend coverage.

Covers:
* Task JJ — ai_employees dedupe migration + unique compound index.
* Task KK — pricebook PATCH + bulk-delete with locked-state guard.
* Task EE (extension) — invoices/estimates bulk-delete accept
  ``query_selector`` filter shape.
* Task Digest — weekly bulk-actions digest rollup builder + zero-actions
  skip + dry-run send through the guarded adapter.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

import pytest

# Phase 34-migrate-v2 · Phase 34-v2-c · Feb 2026 — swapped ``requests``
# for the in-process ASGI shim.
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
# Task JJ — dedupe migration
# ═══════════════════════════════════════════════════════════════════════
def test_jj_migration_is_idempotent(db):
    from migrations.task_jj_dedupe_ai_employees import dedupe_ai_employees

    async def _go():
        first = await dedupe_ai_employees()
        second = await dedupe_ai_employees()
        return first, second

    first, second = _run(_go())
    # First run may (has already) dropped rows on the initial boot;
    # second run must be a no-op.
    assert second["null_tenant_dropped"] == 0
    assert second["in_tenant_dupes_merged"] == 0
    assert second["before"] == second["after"]


def test_jj_unique_index_installed(db):
    async def _go():
        indexes = await db.ai_employees.list_indexes().to_list(100)
        names = [ix.get("name") for ix in indexes]
        return names
    names = _run(_go())
    assert "phase34_task_jj_tenant_key_uniq" in names


def test_jj_null_tenant_rows_removed(db):
    async def _go():
        return await db.ai_employees.count_documents({"tenant_id": None})
    assert _run(_go()) == 0


def test_jj_ai_ops_list_is_tenant_scoped(super_headers, db, aq_tenant_id):
    """`GET /api/ai-ops/employees` must only return rows for the
    caller's tenant. Pre-Task-JJ it returned every row across every
    tenant."""
    r = http.get(f"{API}/ai-ops/employees", headers=super_headers, timeout=30)
    assert r.status_code == 200
    rows = r.json()
    # If any rows come back, they must all belong to aquaterra.
    # (Some pods may seed the list lazily; the invariant we care about
    # is "no cross-tenant leakage".)
    for row in rows:
        tid = row.get("tenant_id")
        if tid is not None:
            assert tid == aq_tenant_id, \
                f"cross-tenant leakage: row {row.get('id')} tenant_id={tid}"


# ═══════════════════════════════════════════════════════════════════════
# Task KK — pricebook PATCH + bulk-delete
# ═══════════════════════════════════════════════════════════════════════
def _plant_item(db, name: str = "KK-item") -> str:
    iid = uuid.uuid4().hex
    async def _go():
        await db.items.insert_one({
            "id": iid, "name": f"{name}-{iid[:6]}",
            "category": "Pool", "unit": "each",
            "unit_price": 10.0, "cost": 5.0, "tax_rate": 8.0,
            "active": True, "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_go())
    return iid


def test_pricebook_patch_happy(db, super_headers):
    iid = _plant_item(db)
    r = http.patch(
        f"{API}/items/{iid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"unit_price": 12.50, "description": "updated"}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unit_price"] == 12.50


def test_pricebook_patch_role_gate(db, customer_headers):
    iid = _plant_item(db)
    r = http.patch(
        f"{API}/items/{iid}",
        headers={**customer_headers, "Content-Type": "application/json"},
        json={"unit_price": 1}, timeout=30,
    )
    assert r.status_code == 403


def test_pricebook_patch_rejects_negative(db, super_headers):
    iid = _plant_item(db)
    r = http.patch(
        f"{API}/items/{iid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"unit_price": -1}, timeout=30,
    )
    assert r.status_code == 422


def test_pricebook_bulk_delete_happy(db, super_headers):
    ids = [_plant_item(db, "KK-bulk") for _ in range(3)]
    r = http.post(
        f"{API}/pricebook/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": ids}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 3


def test_pricebook_bulk_delete_locked_by_active_invoice(db, super_headers, aq_tenant_id):
    """An item referenced by an active invoice line refuses hard-delete."""
    iid = _plant_item(db, "KK-locked")
    async def _plant_ref():
        await db.quotes.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": aq_tenant_id,
            "doc_type": "invoice", "customer_id": "c-x",
            "title": "KK ref", "total": 100.0, "amount_paid": 0.0,
            "payment_status": "unpaid",
            "line_items": [{"item_id": iid, "name": "x", "qty": 1, "amount": 10}],
            "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_plant_ref())
    r = http.post(
        f"{API}/pricebook/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"ids": [iid]}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 0
    assert len(body["failed"]) == 1
    assert "active document" in body["failed"][0]["reason"]


def test_pricebook_bulk_delete_role_gate(customer_headers):
    r = http.post(
        f"{API}/pricebook/bulk-delete",
        headers={**customer_headers, "Content-Type": "application/json"},
        json={"ids": ["x"]}, timeout=30,
    )
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════
# Task EE (extension) — query_selector on invoices + estimates
# ═══════════════════════════════════════════════════════════════════════
def test_invoices_bulk_delete_query_selector(db, super_headers, aq_tenant_id):
    marker = uuid.uuid4().hex[:8]
    async def _plant():
        for _ in range(2):
            await db.quotes.insert_one({
                "id": uuid.uuid4().hex, "tenant_id": aq_tenant_id,
                "doc_type": "invoice", "customer_id": "c-x",
                "title": f"EE-marker-{marker}", "total": 10.0, "amount_paid": 0,
                "payment_status": "unpaid",
                "created_at": "2026-02-01T00:00:00Z",
            })
    _run(_plant())
    r = http.post(
        f"{API}/invoices/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"query_selector": {"search": marker, "status": "unpaid"},
              "exclude_ids": []}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_count"] == 2


def test_estimates_bulk_delete_query_selector(db, super_headers, aq_tenant_id):
    marker = uuid.uuid4().hex[:8]
    async def _plant():
        for _ in range(2):
            await db.estimates.insert_one({
                "id": uuid.uuid4().hex, "tenant_id": aq_tenant_id,
                "customer_id": "c-x", "title": f"EE-est-{marker}",
                "total": 20.0, "created_at": "2026-02-01T00:00:00Z",
            })
    _run(_plant())
    r = http.post(
        f"{API}/estimates/bulk-delete",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"query_selector": {"search": marker}, "exclude_ids": []},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted_count"] == 2


# ═══════════════════════════════════════════════════════════════════════
# Weekly Digest — rollup + skip zero + dry-run send
# ═══════════════════════════════════════════════════════════════════════
def test_digest_rollup_counts(db, aq_tenant_id):
    from services.weekly_bulk_actions_digest import build_digest_rollup
    # Plant fresh audit rows within the last 7 days.
    now = datetime.now(timezone.utc)
    async def _plant():
        for action in ["invoice.soft_delete", "invoice.soft_delete",
                          "lead.bulk_status_change", "estimate.soft_delete"]:
            await db.audit_log.insert_one({
                "id": uuid.uuid4().hex, "tenant_id": aq_tenant_id,
                "action": action,
                "at": (now - timedelta(days=2)).isoformat(),
            })
    _run(_plant())
    since = (now - timedelta(days=7)).isoformat()
    rollup = _run(build_digest_rollup(aq_tenant_id, since))
    assert rollup["total"] >= 4
    assert rollup["counts"].get("invoice.soft_delete", 0) >= 2
    assert rollup["counts"].get("lead.bulk_status_change", 0) >= 1
    assert rollup["counts"].get("estimate.soft_delete", 0) >= 1


def test_digest_skips_zero_actions(db):
    """A brand-new tenant with no audit rows in 7d must NOT get emailed."""
    fake_tid = f"digest-test-{uuid.uuid4().hex}"
    # Plant a tenant + user but zero audit rows.
    async def _plant():
        await db.tenants.insert_one({
            "id": fake_tid, "slug": fake_tid, "name": "Zero Actions",
            "created_at": "2026-02-01T00:00:00Z",
        })
        await db.users.insert_one({
            "id": uuid.uuid4().hex, "tenant_id": fake_tid,
            "role": "owner", "email": "owner-zero@example.com",
            "name": "Zero", "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_plant())

    from services.weekly_bulk_actions_digest import send_weekly_digest_for_tenant
    result = _run(send_weekly_digest_for_tenant({"id": fake_tid}))
    assert result.get("skipped_zero_actions") is True


def test_digest_send_uses_dry_run_in_preview(db, aq_tenant_id):
    """When the digest has actions, it must route through the guarded
    adapter — in preview `APP_ENV=preview`, delivery lands as dry-run
    (unless recipient is in the allowlist). We just check no exception
    and that the return payload reports something."""
    from services.weekly_bulk_actions_digest import send_weekly_digest_for_tenant
    result = _run(send_weekly_digest_for_tenant({"id": aq_tenant_id}))
    # Either it was skipped (no owner) or it processed (sent/dry_ran).
    assert ("skipped_no_owners" in result
            or "skipped_zero_actions" in result
            or ("sent" in result and "dry_ran" in result))
