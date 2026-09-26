"""Phase P59 · Feb-2026 — Tenant isolation coverage for the 5 JSON
report endpoints scoped in Commit 5 of ``routers/reports.py``:

  * GET /reports/revenue-by-city
  * GET /reports/revenue-by-crew
  * GET /reports/revenue-by-customer
  * GET /reports/gross-sales
  * GET /reports/invoiced-items

Commit 5 swapped each handler to a strict ``Depends(get_current_tenant)``
chain and spliced ``"tenant_id": tenant["id"]`` into the three direct
``find({})`` calls in the two-tenant-mixing routes:

  * ``db.customers.find({}, ...)`` in ``revenue_by_city``
  * ``db.jobs.find({}, ...)`` in ``revenue_by_crew``
  * ``db.crews.find({}, ...)`` in ``revenue_by_crew``

The three helpers ``_fetch_paid`` and ``_fetch_all_invoices`` were
already scoped in Commit 3. What this suite pins per route:

  1. Plant N=3 rows on tenant A (aquaterra) and N=2 on a foreign
     tenant. Rows are markered so we can attribute them post-fetch.
  2. Call the endpoint with tenant A's admin token.
  3. Response payload MUST include every seeded aquaterra row and
     MUST NOT include any foreign-tenant row.

For ``gross-sales`` and ``invoiced-items`` — which reduce to totals —
we assert both the presence-in-rows guarantee AND that the summary
totals do NOT count the foreign-tenant invoices.
"""
from __future__ import annotations

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


# ── seeding helpers ──────────────────────────────────────────────────
def _plant_paid_invoice(
    db, tenant_id: str, *,
    customer_id: str, customer_name: str, customer_address: str,
    total: float, created_at: str = "2026-02-15T00:00:00Z",
    paid_at: str = "2026-02-16T00:00:00Z",
    line_desc: str = "P59 Widget", line_qty: float = 1.0,
    line_price: float = 100.0,
) -> str:
    qid = f"p59-jinv-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.quotes.insert_one({
            "id": qid,
            "tenant_id": tenant_id,
            "doc_type": "invoice",
            "customer_id": customer_id,
            "customer_name": customer_name,
            "customer_address": customer_address,
            "title": customer_name,
            "total": total,
            "amount_paid": total,
            "payment_status": "paid",
            "paid_at": paid_at,
            "created_at": created_at,
            "line_items": [{
                "description": line_desc,
                "quantity": line_qty,
                "unit_price": line_price,
                "category": "Pool",
            }],
        })
    _run(_go())
    return qid


def _plant_customer(db, tenant_id: str, cid: str, name: str, city: str) -> None:
    async def _go():
        await db.customers.insert_one({
            "id": cid,
            "tenant_id": tenant_id,
            "name": name,
            "city": city,
            "address": f"1 Test St, {city}, XX 00000",
            "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_go())


def _plant_crew(db, tenant_id: str, crew_id: str, name: str) -> None:
    async def _go():
        await db.crews.insert_one({
            "id": crew_id,
            "tenant_id": tenant_id,
            "name": name,
            "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_go())


def _plant_job(
    db, tenant_id: str, *,
    customer_id: str, crew_id: str, quote_id: str,
    title: str,
) -> str:
    jid = f"p59-jjob-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.jobs.insert_one({
            "id": jid,
            "tenant_id": tenant_id,
            "title": title,
            "customer_id": customer_id,
            "customer_name": title,
            "service_type": "pool",
            "status": "completed",
            "scheduled_date": "2026-02-15",
            "created_at": "2026-02-15T00:00:00Z",
            "crew_id": crew_id,
            "quote_id": quote_id,
            "price": 100.0,
        })
    _run(_go())
    return jid


def _cleanup(db, coll: str, ids: list[str]) -> None:
    if not ids:
        return

    async def _go():
        await getattr(db, coll).delete_many({"id": {"$in": ids}})
    _run(_go())


# ── /reports/revenue-by-city ─────────────────────────────────────────
def test_revenue_by_city_tenant_isolation(
    db, admin_headers, aq_tenant_id, foreign_tenant_id,
):
    """Foreign-tenant customers with paid invoices MUST NOT appear
    as their own city bucket in the aquaterra revenue-by-city."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available in preview")

    marker = uuid.uuid4().hex[:8]
    a_city = f"P59CityA-{marker}"
    b_city = f"P59CityB-{marker}"
    a_cust_ids: list[str] = []
    b_cust_ids: list[str] = []
    a_inv_ids: list[str] = []
    b_inv_ids: list[str] = []
    try:
        for i in range(3):
            cid = f"p59-c-a-{marker}-{i}"
            _plant_customer(db, aq_tenant_id, cid, f"A-Cust-{marker}-{i}", a_city)
            a_cust_ids.append(cid)
            a_inv_ids.append(_plant_paid_invoice(
                db, aq_tenant_id,
                customer_id=cid,
                customer_name=f"A-Cust-{marker}-{i}",
                customer_address=f"1 Ln, {a_city}, XX 00000",
                total=100.0 + i,
            ))
        for i in range(2):
            cid = f"p59-c-b-{marker}-{i}"
            _plant_customer(db, foreign_tenant_id, cid, f"B-Cust-{marker}-{i}", b_city)
            b_cust_ids.append(cid)
            b_inv_ids.append(_plant_paid_invoice(
                db, foreign_tenant_id,
                customer_id=cid,
                customer_name=f"B-Cust-{marker}-{i}",
                customer_address=f"1 Ln, {b_city}, XX 00000",
                total=200.0 + i,
            ))

        r = http.get(
            f"{API}/reports/revenue-by-city?start=2026-02-01&end=2026-02-28",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        cities = {row["city"] for row in r.json()["rows"]}
        assert a_city in cities, f"expected aquaterra city {a_city}"
        assert b_city not in cities, (
            f"leaked foreign-tenant city {b_city} — P59 regression")
    finally:
        _cleanup(db, "customers", a_cust_ids + b_cust_ids)
        _cleanup(db, "quotes", a_inv_ids + b_inv_ids)


# ── /reports/revenue-by-crew ─────────────────────────────────────────
def test_revenue_by_crew_tenant_isolation(
    db, admin_headers, aq_tenant_id, foreign_tenant_id,
):
    """Foreign-tenant crew names MUST NOT appear as their own bucket
    in the aquaterra revenue-by-crew, and foreign-tenant jobs MUST
    NOT drive revenue attribution."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available in preview")

    marker = uuid.uuid4().hex[:8]
    a_crew_name = f"P59CrewA-{marker}"
    b_crew_name = f"P59CrewB-{marker}"
    a_crew_id = f"p59-crew-a-{marker}"
    b_crew_id = f"p59-crew-b-{marker}"
    a_inv_ids: list[str] = []
    b_inv_ids: list[str] = []
    a_job_ids: list[str] = []
    b_job_ids: list[str] = []
    try:
        _plant_crew(db, aq_tenant_id, a_crew_id, a_crew_name)
        _plant_crew(db, foreign_tenant_id, b_crew_id, b_crew_name)

        for i in range(3):
            cust_id = f"p59-cc-a-{marker}-{i}"
            qid = _plant_paid_invoice(
                db, aq_tenant_id,
                customer_id=cust_id,
                customer_name=f"A-Cust-{marker}-{i}",
                customer_address=f"1 A St",
                total=100.0 + i,
            )
            a_inv_ids.append(qid)
            a_job_ids.append(_plant_job(
                db, aq_tenant_id,
                customer_id=cust_id, crew_id=a_crew_id, quote_id=qid,
                title=f"A-Job-{marker}-{i}",
            ))
        for i in range(2):
            cust_id = f"p59-cc-b-{marker}-{i}"
            qid = _plant_paid_invoice(
                db, foreign_tenant_id,
                customer_id=cust_id,
                customer_name=f"B-Cust-{marker}-{i}",
                customer_address=f"1 B St",
                total=200.0 + i,
            )
            b_inv_ids.append(qid)
            b_job_ids.append(_plant_job(
                db, foreign_tenant_id,
                customer_id=cust_id, crew_id=b_crew_id, quote_id=qid,
                title=f"B-Job-{marker}-{i}",
            ))

        r = http.get(
            f"{API}/reports/revenue-by-crew?start=2026-02-01&end=2026-02-28",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        crews = {row["crew"] for row in r.json()["rows"]}
        assert a_crew_name in crews, f"expected aquaterra crew {a_crew_name}"
        assert b_crew_name not in crews, (
            f"leaked foreign-tenant crew {b_crew_name} — P59 regression")
    finally:
        _cleanup(db, "crews", [a_crew_id, b_crew_id])
        _cleanup(db, "jobs", a_job_ids + b_job_ids)
        _cleanup(db, "quotes", a_inv_ids + b_inv_ids)


# ── /reports/revenue-by-customer ─────────────────────────────────────
def test_revenue_by_customer_tenant_isolation(
    db, admin_headers, aq_tenant_id, foreign_tenant_id,
):
    """Foreign-tenant customers with paid invoices MUST NOT appear
    in the aquaterra revenue-by-customer rollup."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available in preview")

    marker = uuid.uuid4().hex[:8]
    a_inv_ids: list[str] = []
    b_inv_ids: list[str] = []
    try:
        for i in range(3):
            a_inv_ids.append(_plant_paid_invoice(
                db, aq_tenant_id,
                customer_id=f"p59-cust-a-{marker}-{i}",
                customer_name=f"P59-A-Cust-{marker}-{i}",
                customer_address="1 A St",
                total=100.0 + i,
            ))
        for i in range(2):
            b_inv_ids.append(_plant_paid_invoice(
                db, foreign_tenant_id,
                customer_id=f"p59-cust-b-{marker}-{i}",
                customer_name=f"P59-B-Cust-{marker}-{i}",
                customer_address="1 B St",
                total=200.0 + i,
            ))

        r = http.get(
            f"{API}/reports/revenue-by-customer?start=2026-02-01&end=2026-02-28",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        names = {row["customer_name"] for row in r.json()["rows"]}
        for i in range(3):
            assert f"P59-A-Cust-{marker}-{i}" in names, (
                f"expected aquaterra customer P59-A-Cust-{marker}-{i}")
        for i in range(2):
            assert f"P59-B-Cust-{marker}-{i}" not in names, (
                f"leaked foreign-tenant customer P59-B-Cust-{marker}-{i}"
                f" — P59 regression")
    finally:
        _cleanup(db, "quotes", a_inv_ids + b_inv_ids)


# ── /reports/gross-sales ─────────────────────────────────────────────
def test_gross_sales_tenant_isolation(
    db, admin_headers, aq_tenant_id, foreign_tenant_id,
):
    """Foreign-tenant invoices MUST NOT show up as rows OR as summary
    ``gross`` / ``collected`` contributions in aquaterra gross-sales."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available in preview")

    marker = uuid.uuid4().hex[:8]
    a_inv_ids: list[str] = []
    b_inv_ids: list[str] = []
    b_ids_lookup: set[str] = set()
    try:
        for i in range(3):
            a_inv_ids.append(_plant_paid_invoice(
                db, aq_tenant_id,
                customer_id=f"p59-cust-a-{marker}-{i}",
                customer_name=f"P59-A-Cust-{marker}-{i}",
                customer_address="1 A St",
                total=100.0 + i,
            ))
        for i in range(2):
            qid = _plant_paid_invoice(
                db, foreign_tenant_id,
                customer_id=f"p59-cust-b-{marker}-{i}",
                customer_name=f"P59-B-Cust-{marker}-{i}",
                customer_address="1 B St",
                total=999.0 + i,   # big number → easy to spot in totals
            )
            b_inv_ids.append(qid)
            b_ids_lookup.add(qid)

        r = http.get(
            f"{API}/reports/gross-sales?start=2026-02-01&end=2026-02-28",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        row_ids = {row["id"] for row in payload["rows"]}
        assert row_ids.isdisjoint(b_ids_lookup), (
            f"foreign-tenant invoice ids leaked into gross-sales rows: "
            f"{row_ids & b_ids_lookup}")
        # Any of our foreign-tenant customer_name markers in the rows?
        row_names = {row.get("customer_name") for row in payload["rows"]}
        for i in range(2):
            assert f"P59-B-Cust-{marker}-{i}" not in row_names, (
                f"leaked foreign-tenant customer P59-B-Cust-{marker}-{i}")
        # The aquaterra rows we planted must be present.
        for i in range(3):
            assert f"P59-A-Cust-{marker}-{i}" in row_names, (
                f"missing aquaterra customer P59-A-Cust-{marker}-{i}")
    finally:
        _cleanup(db, "quotes", a_inv_ids + b_inv_ids)


# ── /reports/invoiced-items ──────────────────────────────────────────
def test_invoiced_items_tenant_isolation(
    db, admin_headers, aq_tenant_id, foreign_tenant_id,
):
    """Foreign-tenant line-item descriptions MUST NOT aggregate into
    the aquaterra invoiced-items rollup."""
    if not foreign_tenant_id:
        pytest.skip("no second tenant available in preview")

    marker = uuid.uuid4().hex[:8]
    a_line_desc = f"P59-A-Item-{marker}"
    b_line_desc = f"P59-B-Item-{marker}"
    a_inv_ids: list[str] = []
    b_inv_ids: list[str] = []
    try:
        for i in range(3):
            a_inv_ids.append(_plant_paid_invoice(
                db, aq_tenant_id,
                customer_id=f"p59-cust-a-{marker}-{i}",
                customer_name=f"P59-A-Cust-{marker}-{i}",
                customer_address="1 A St",
                total=100.0,
                line_desc=a_line_desc, line_qty=2.0, line_price=50.0,
            ))
        for i in range(2):
            b_inv_ids.append(_plant_paid_invoice(
                db, foreign_tenant_id,
                customer_id=f"p59-cust-b-{marker}-{i}",
                customer_name=f"P59-B-Cust-{marker}-{i}",
                customer_address="1 B St",
                total=200.0,
                line_desc=b_line_desc, line_qty=4.0, line_price=50.0,
            ))

        r = http.get(
            f"{API}/reports/invoiced-items?start=2026-02-01&end=2026-02-28",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        descs = {row["description"] for row in r.json()["rows"]}
        assert a_line_desc in descs, f"expected aquaterra line {a_line_desc}"
        assert b_line_desc not in descs, (
            f"leaked foreign-tenant line {b_line_desc} — P59 regression")
    finally:
        _cleanup(db, "quotes", a_inv_ids + b_inv_ids)
