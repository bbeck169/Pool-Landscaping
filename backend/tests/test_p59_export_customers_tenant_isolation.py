"""Phase P59 · Feb-2026 — Tenant isolation coverage for
``GET /export/customers``.

Companion to the P59 Commit 1 fix in ``routers/impexp.py`` which
scoped ``export_customers`` to the caller's tenant via a
``Depends(get_current_tenant)`` chain and a
``"tenant_id": tenant["id"]`` splice into the ``db.customers.find``
filter.  Prior to this fix the handler ran ``db.customers.find({}, ...)``
with an empty filter, letting any admin token on any tenant enumerate
cross-tenant customer rows through a CSV download.

Contract this suite pins:

  1. Plant N=3 customer rows on tenant A (aquaterra) and N=2 on a
     distinct foreign tenant.
  2. Call ``GET /api/export/customers`` with tenant A's admin token.
  3. Response CSV MUST include every seeded aquaterra row and MUST
     NOT include any foreign-tenant row.  Row count reflects
     aquaterra scope only.

Precedent fixture shape: ``test_p58_import_items_tenant_isolation.py``.
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


def _plant_customer(db, tenant_id: str, name: str, email: str) -> str:
    cid = f"p59-cust-{uuid.uuid4().hex[:12]}"

    async def _go():
        await db.customers.insert_one({
            "id": cid,
            "tenant_id": tenant_id,
            "name": name,
            "email": email,
            "phone": "",
            "address": "",
            "created_at": "2026-02-15T00:00:00Z",
        })
    _run(_go())
    return cid


def _cleanup(db, ids: list[str]) -> None:
    if not ids:
        return

    async def _go():
        await db.customers.delete_many({"id": {"$in": ids}})
    _run(_go())


def test_export_customers_tenant_isolation(
    db, admin_headers, aq_tenant_id, foreign_tenant_id,
):
    """P59 · Commit 1 — cross-tenant customer rows must NOT leak into
    the aquaterra admin's CSV export."""
    if not foreign_tenant_id:
        pytest.skip(
            "no second tenant available in preview — cannot exercise "
            "cross-tenant isolation")

    # Distinctive markers so the assertions can match on-CSV literal
    # substrings without false positives from real seed data.
    marker = uuid.uuid4().hex[:8]
    a_seeded: list[str] = []
    b_seeded: list[str] = []
    try:
        for i in range(3):
            a_seeded.append(_plant_customer(
                db, aq_tenant_id,
                name=f"P59 Aquaterra {marker} {i}",
                email=f"p59-a-{marker}-{i}@test.example",
            ))
        for i in range(2):
            b_seeded.append(_plant_customer(
                db, foreign_tenant_id,
                name=f"P59 Foreign {marker} {i}",
                email=f"p59-b-{marker}-{i}@test.example",
            ))

        r = http.get(f"{API}/export/customers",
                     headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text
        payload = r.json()
        content = payload["content"]

        # Every seeded aquaterra row is in the CSV.
        for i in range(3):
            needle = f"p59-a-{marker}-{i}@test.example"
            assert needle in content, (
                f"expected aquaterra customer {needle!r} in the export"
                f" CSV; got sample of {len(content)}-byte body")

        # No foreign-tenant row leaks into the CSV — this is the
        # actual regression guard.
        for i in range(2):
            needle_email = f"p59-b-{marker}-{i}@test.example"
            needle_name = f"P59 Foreign {marker} {i}"
            assert needle_email not in content, (
                f"leaked foreign-tenant customer email {needle_email!r}"
                f" — P59 tenant scoping regression")
            assert needle_name not in content, (
                f"leaked foreign-tenant customer name {needle_name!r}"
                f" — P59 tenant scoping regression")

        # Row count matches: reader-parsed row count minus header
        # must include our 3 seeded aquaterra rows (plus other pre-
        # existing aquaterra rows).  Foreign rows are excluded.
        rows = list(csv.DictReader(io.StringIO(content)))
        our_row_count = sum(
            1 for row in rows
            if (row.get("email") or "").startswith(f"p59-a-{marker}-")
        )
        assert our_row_count == 3, (
            f"expected 3 seeded aquaterra rows in the CSV, "
            f"found {our_row_count}")
        foreign_row_count = sum(
            1 for row in rows
            if (row.get("email") or "").startswith(f"p59-b-{marker}-")
        )
        assert foreign_row_count == 0, (
            f"expected 0 foreign-tenant rows in the CSV, "
            f"found {foreign_row_count} — P59 tenant scoping regression")
    finally:
        _cleanup(db, a_seeded + b_seeded)
