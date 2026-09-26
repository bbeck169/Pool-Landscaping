"""Phase P59 · Feb-2026 — Tenant isolation coverage for
``GET /export/jobs`` and ``GET /export/invoices``.

Companion to the P59 Commit 4 fix in ``routers/reports.py`` which
scoped both handlers to the caller's tenant via a
``Depends(get_current_tenant)`` chain and a
``"tenant_id": tenant["id"]`` splice into the direct
``db.jobs.find({}, ...)`` and ``db.quotes.find({"doc_type":"invoice",...})``
calls (L610, L632 pre-fix).

Contract this suite pins per route:

  1. Plant N=3 jobs/invoices on tenant A (aquaterra) and N=2 on
     a distinct foreign tenant.
  2. Call the endpoint with tenant A's admin token.
  3. Response CSV MUST include every seeded aquaterra row and MUST
     NOT include any foreign-tenant row.
"""
from __future__ import annotations

import csv
import io
import os
import uuid
from typing import Optional

import pytest

from tests._phase34_http_shim import http
from tests._phase34_asyncio import batch_safe_run as _run


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str, password: str = "password123") -> str:
    r = http.post(
        f"{API}/auth/login",
        json={"email": email, "password": password}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def db():
    from config import db as _db  # noqa: PLC0415
    return _db


@pytest.fixture(scope="module")
def aq_tenant_id(db) -> str:
    async def _go():
        t = await db.tenants.find_one(
            {"slug": "aquaterra"}, {"_id": 0, "id": 1},
        )
        return t["id"]
    return _run(_go())


@pytest.fixture(scope="module")
def foreign_tenant_id(db, aq_tenant_id) -> Optional[str]:
    async def _go():
        other = await db.tenants.find_one(
            {"id": {"$ne": aq_tenant_id}}, {"_id": 0, "id": 1},
        )
        return other["id"] if other else None
    return _run(_go())


@pytest.fixture(scope="module")
def admin_headers() -> dict:
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


def _plant_job(db, tenant_id: str, title: str,
                customer_name: str, price: float) -> str:
    jid = f"p59-job-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.jobs.insert_one({
            "id": jid,
            "tenant_id": tenant_id,
            "title": title,
            "customer_name": customer_name,
            "service_type": "pool",
            "status": "scheduled",
            "technician_name": "P59 Test Tech",
            "scheduled_date": "2026-02-20",
            "price": price,
            "created_at": "2026-02-15T00:00:00Z",
        })
    _run(_go())
    return jid


def _plant_invoice(db, tenant_id: str, title: str,
                    customer_name: str, total: float) -> str:
    qid = f"p59-inv-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.quotes.insert_one({
            "id": qid,
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "title": title,
            "customer_name": customer_name,
            "total": total,
            "amount_paid": 0.0,
            "payment_status": "unpaid",
            "created_at": "2026-02-15T00:00:00Z",
        })
    _run(_go())
    return qid


def _cleanup_jobs(db, ids: list[str]) -> None:
    if not ids:
        return

    async def _go():
        await db.jobs.delete_many({"id": {"$in": ids}})
    _run(_go())


def _cleanup_invoices(db, ids: list[str]) -> None:
    if not ids:
        return

    async def _go():
        await db.quotes.delete_many({"id": {"$in": ids}})
    _run(_go())


def test_export_jobs_tenant_isolation(
    db, admin_headers, aq_tenant_id, foreign_tenant_id,
):
    """P59 · Commit 4 — cross-tenant job rows must NOT leak into
    the aquaterra admin's CSV export."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available in preview")

    marker = uuid.uuid4().hex[:8]
    a_seeded: list[str] = []
    b_seeded: list[str] = []
    try:
        for i in range(3):
            a_seeded.append(_plant_job(
                db, aq_tenant_id,
                title=f"P59-A-Job-{marker}-{i}",
                customer_name=f"P59-A-Cust-{marker}",
                price=100.0 + i,
            ))
        for i in range(2):
            b_seeded.append(_plant_job(
                db, foreign_tenant_id,
                title=f"P59-B-Job-{marker}-{i}",
                customer_name=f"P59-B-Cust-{marker}",
                price=200.0 + i,
            ))

        r = http.get(f"{API}/export/jobs",
                     headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        content = r.json()["content"]

        for i in range(3):
            assert f"P59-A-Job-{marker}-{i}" in content, (
                f"expected aquaterra job P59-A-Job-{marker}-{i}")
        for i in range(2):
            assert f"P59-B-Job-{marker}-{i}" not in content, (
                f"leaked foreign-tenant job P59-B-Job-{marker}-{i}"
                f" — P59 tenant scoping regression")

        rows = list(csv.DictReader(io.StringIO(content)))
        our_ct = sum(
            1 for r in rows
            if (r.get("title") or "").startswith(f"P59-A-Job-{marker}-"))
        foreign_ct = sum(
            1 for r in rows
            if (r.get("title") or "").startswith(f"P59-B-Job-{marker}-"))
        assert our_ct == 3, f"expected 3 aquaterra rows, found {our_ct}"
        assert foreign_ct == 0, (
            f"expected 0 foreign rows, found {foreign_ct}")
    finally:
        _cleanup_jobs(db, a_seeded + b_seeded)


def test_export_invoices_tenant_isolation(
    db, admin_headers, aq_tenant_id, foreign_tenant_id,
):
    """P59 · Commit 4 — cross-tenant invoice rows must NOT leak
    into the aquaterra admin's CSV export."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available in preview")

    marker = uuid.uuid4().hex[:8]
    a_seeded: list[str] = []
    b_seeded: list[str] = []
    try:
        for i in range(3):
            a_seeded.append(_plant_invoice(
                db, aq_tenant_id,
                title=f"P59-A-Inv-{marker}-{i}",
                customer_name=f"P59-A-Cust-{marker}",
                total=500.0 + i,
            ))
        for i in range(2):
            b_seeded.append(_plant_invoice(
                db, foreign_tenant_id,
                title=f"P59-B-Inv-{marker}-{i}",
                customer_name=f"P59-B-Cust-{marker}",
                total=900.0 + i,
            ))

        r = http.get(f"{API}/export/invoices",
                     headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        content = r.json()["content"]

        for i in range(3):
            assert f"P59-A-Inv-{marker}-{i}" in content, (
                f"expected aquaterra invoice P59-A-Inv-{marker}-{i}")
        for i in range(2):
            assert f"P59-B-Inv-{marker}-{i}" not in content, (
                f"leaked foreign-tenant invoice P59-B-Inv-{marker}-{i}"
                f" — P59 tenant scoping regression")

        rows = list(csv.DictReader(io.StringIO(content)))
        our_ct = sum(
            1 for r in rows
            if (r.get("title") or "").startswith(f"P59-A-Inv-{marker}-"))
        foreign_ct = sum(
            1 for r in rows
            if (r.get("title") or "").startswith(f"P59-B-Inv-{marker}-"))
        assert our_ct == 3, f"expected 3 aquaterra rows, found {our_ct}"
        assert foreign_ct == 0, (
            f"expected 0 foreign rows, found {foreign_ct}")
    finally:
        _cleanup_invoices(db, a_seeded + b_seeded)
