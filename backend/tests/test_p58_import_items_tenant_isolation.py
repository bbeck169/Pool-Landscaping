"""Phase P58 · Feb-2026 — Tenant isolation coverage for
``POST /import/items``.

Companion to the P58 fix commit ``49b857902`` which locked
``import_items`` down to tenant-scope every ``db.items`` mutation
and stamp ``tenant_id`` on inserted docs. Prior to P58 the handler
matched candidate rows by case-insensitive name alone — an admin
uploading a CSV with an item name that collided with a foreign
tenant's item name would silently REWRITE that foreign row, and
new inserts had no ``tenant_id`` field (orphaned / globally-
visible rows).

This suite pins the fix by exercising two contracts:

  1. **Name collision does NOT overwrite a foreign-tenant row**
     — planting a distinctive-price row in tenant B, then having
     tenant A's admin upload a CSV that includes an item with
     the same name, must (a) leave tenant B's row untouched and
     (b) create a NEW row in tenant A carrying tenant A's
     ``tenant_id``.

  2. **Inserted rows always carry ``tenant_id``** — every row
     created by ``import_items`` must have the actor's
     ``tenant_id`` on it. Zero orphaned inserts.

Precedent test files: ``test_p57_pricebook_bulk_delete_tenant_isolation.py``.
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
def super_headers() -> dict:
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def foreign_tenant_id(db) -> Optional[str]:
    async def _go():
        aq = await db.tenants.find_one(
            {"slug": "aquaterra"}, {"_id": 0, "id": 1},
        )
        aq_id = aq["id"] if aq else None
        other = await db.tenants.find_one(
            {"id": {"$ne": aq_id}}, {"_id": 0, "id": 1},
        )
        return other["id"] if other else None
    return _run(_go())


def _plant_item(db, tenant_id: str, name: str, unit_price: float) -> str:
    iid = uuid.uuid4().hex

    async def _go():
        await db.items.insert_one({
            "id": iid,
            "tenant_id": tenant_id,
            "name": name,
            "category": "Pool",
            "unit": "each",
            "unit_price": unit_price,
            "cost": 5.0,
            "tax_rate": 8.0,
            "active": True,
            "created_at": "2026-02-01T00:00:00Z",
        })
    _run(_go())
    return iid


def _unique_name(prefix: str = "P58-import") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_import_items_name_collision_does_not_overwrite_foreign_tenant(
    db, super_headers, aq_tenant_id, foreign_tenant_id,
):
    """P58 primary security assertion — tenant A's admin uploads
    a CSV that includes an item name colliding with a
    distinctive-price row in tenant B. The foreign row's
    ``unit_price`` must be UNCHANGED post-import, and tenant A
    must have gained a NEW row carrying tenant A's ``tenant_id``.
    """
    if not foreign_tenant_id:
        pytest.skip(
            "preview seed has only one tenant; cross-tenant "
            "assertion cannot be exercised in this environment"
        )
    collision_name = _unique_name("P58-collide")
    # Plant a distinctive-price row on the foreign tenant.
    foreign_iid = _plant_item(
        db, tenant_id=foreign_tenant_id,
        name=collision_name, unit_price=88.88,
    )

    # Aquaterra admin uploads a CSV with the SAME item name at a
    # very different price. Pre-P58 this would have rewritten the
    # foreign row's unit_price via the unscoped $regex match.
    csv_body = (
        "name,category,unit,unit_price,taxable\n"
        f"{collision_name},Pool,each,11.11,true\n"
    )
    r = http.post(
        f"{API}/import/items",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"csv": csv_body}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # A NEW row was created in tenant A (not an update against
    # the foreign tenant's row).
    assert body["created"] == 1, body
    assert body["updated"] == 0, body

    # Assertion 1 — the foreign-tenant row's price is UNCHANGED.
    async def _refetch_foreign():
        return await db.items.find_one(
            {"id": foreign_iid},
            {"_id": 0, "unit_price": 1, "tenant_id": 1},
        )
    foreign_row = _run(_refetch_foreign())
    assert foreign_row is not None
    assert foreign_row["tenant_id"] == foreign_tenant_id
    assert foreign_row["unit_price"] == 88.88, (
        "cross-tenant write leaked; foreign row got rewritten: "
        f"expected 88.88, got {foreign_row['unit_price']}"
    )

    # Assertion 2 — tenant A now has its OWN row with the same
    # name at the CSV-provided price.
    async def _find_aq_row():
        return await db.items.find_one(
            {"tenant_id": aq_tenant_id, "name": collision_name},
            {"_id": 0, "unit_price": 1, "tenant_id": 1},
        )
    aq_row = _run(_find_aq_row())
    assert aq_row is not None, (
        "expected a new aquaterra-scoped row to be created"
    )
    assert aq_row["tenant_id"] == aq_tenant_id
    assert aq_row["unit_price"] == 11.11


def test_import_items_inserted_rows_always_carry_tenant_id(
    db, super_headers, aq_tenant_id,
):
    """P58 hygiene assertion — every row created by
    ``import_items`` must carry the actor's ``tenant_id``. Pre-P58
    the insert path stamped no ``tenant_id`` at all, producing
    orphaned / globally-visible rows.
    """
    n1 = _unique_name("P58-stamp-a")
    n2 = _unique_name("P58-stamp-b")
    csv_body = (
        "name,category,unit,unit_price,taxable\n"
        f"{n1},Service,each,9.99,true\n"
        f"{n2},Pool,each,19.99,false\n"
    )
    r = http.post(
        f"{API}/import/items",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"csv": csv_body}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2, body

    async def _find_rows():
        rows = []
        async for doc in db.items.find(
            {"name": {"$in": [n1, n2]}},
            {"_id": 0, "name": 1, "tenant_id": 1},
        ):
            rows.append(doc)
        return rows
    rows = _run(_find_rows())
    assert len(rows) == 2, rows
    # Every row carries the caller's tenant_id — zero orphans.
    for row in rows:
        assert row.get("tenant_id") == aq_tenant_id, (
            f"row missing/wrong tenant_id: {row}"
        )
