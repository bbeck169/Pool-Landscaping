"""Phase P58 · Feb-2026 — Tenant isolation coverage for
``PATCH /items/{iid}``.

Companion to the P58 fix commit ``4632ac030`` which locked
``patch_item`` down to require a per-row ``tenant_id`` match
alongside the item id. Prior to P58 an admin from tenant A could
PATCH tenant B's pricebook item just by knowing the item id — a
cross-tenant mutation breach.

This suite pins the fix by exercising two contracts:

  1. **Cross-tenant PATCH is rejected** — an admin in tenant A
     PATCHing a tenant B item gets a 404 (``Item not found``).
     The row's ``unit_price`` on tenant B is UNCHANGED post-call.

  2. **Same-tenant PATCH still works** (regression) — the
     admin's own-tenant row is updated to the new price.

Also covers the P58 audit-trail integrity fix — the
``pricebook.patch`` ``audit_log`` row now carries ``tenant_id`` so
tenant-scoped audit queries include it.

Precedent test files: ``test_p57_pricebook_bulk_delete_tenant_isolation.py``
(same structural pattern for the bulk-delete path).
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
    """Locate any tenant that is NOT aquaterra so we can plant a
    cross-tenant target row. If the preview seed only carries a
    single tenant, the test skips the cross-tenant assertion
    (documented in the test body itself)."""
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


def _plant_item(db, tenant_id: str, name: str = "P58-item",
                  unit_price: float = 25.0) -> str:
    """Seed a pricebook row in the given tenant. Returns the item
    id. Every field mirrors the phase34 ``_plant_item`` shape so
    the ``pricebook.patch`` validation path treats it as a
    well-formed product row."""
    iid = uuid.uuid4().hex

    async def _go():
        doc = {
            "id": iid,
            "tenant_id": tenant_id,
            "name": f"{name}-{iid[:6]}",
            "category": "Pool",
            "unit": "each",
            "unit_price": unit_price,
            "cost": 5.0,
            "tax_rate": 8.0,
            "active": True,
            "created_at": "2026-02-01T00:00:00Z",
        }
        await db.items.insert_one(doc)
    _run(_go())
    return iid


def test_patch_item_same_tenant_regression(db, super_headers,
                                              aq_tenant_id):
    """P58 regression — a super-admin from aquaterra PATCHing an
    aquaterra item MUST still succeed with 200. Same-tenant flow
    is the primary contract this fix must not break."""
    iid = _plant_item(db, tenant_id=aq_tenant_id)
    r = http.patch(
        f"{API}/items/{iid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"unit_price": 33.33}, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unit_price"] == 33.33
    assert body["tenant_id"] == aq_tenant_id


def test_patch_item_cross_tenant_returns_404(db, super_headers,
                                                aq_tenant_id,
                                                foreign_tenant_id):
    """P58 primary security assertion — a super-admin from
    aquaterra PATCHing an item planted in a DIFFERENT tenant
    must be rejected with 404 (``Item not found``). The target
    row's ``unit_price`` must be UNCHANGED post-call, proving no
    silent cross-tenant write happened."""
    if not foreign_tenant_id:
        pytest.skip(
            "preview seed has only one tenant; cross-tenant "
            "assertion cannot be exercised in this environment"
        )
    # Seed a distinctive price on the foreign tenant so we can
    # detect any silent write.
    iid = _plant_item(db, tenant_id=foreign_tenant_id,
                        name="P58-cross", unit_price=77.77)

    r = http.patch(
        f"{API}/items/{iid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"unit_price": 999.99}, timeout=30,
    )
    assert r.status_code == 404, r.text

    # Verify the foreign-tenant row was NOT rewritten.
    async def _refetch():
        return await db.items.find_one(
            {"id": iid}, {"_id": 0, "unit_price": 1, "tenant_id": 1},
        )
    row = _run(_refetch())
    assert row is not None
    assert row["tenant_id"] == foreign_tenant_id
    assert row["unit_price"] == 77.77, (
        f"cross-tenant write leaked; expected 77.77, got {row['unit_price']}"
    )


def test_patch_item_audit_log_carries_tenant_id(db, super_headers,
                                                    aq_tenant_id):
    """P58 audit-trail integrity fix — the ``pricebook.patch``
    audit row now stamps ``tenant_id``. Prior to P58 it did not,
    so tenant-scoped audit queries missed the action."""
    iid = _plant_item(db, tenant_id=aq_tenant_id, name="P58-audit")
    r = http.patch(
        f"{API}/items/{iid}",
        headers={**super_headers, "Content-Type": "application/json"},
        json={"unit_price": 44.44}, timeout=30,
    )
    assert r.status_code == 200, r.text

    async def _find_audit():
        return await db.audit_log.find_one(
            {
                "action": "pricebook.patch",
                "target_id": iid,
                "tenant_id": aq_tenant_id,
            },
            {"_id": 0, "tenant_id": 1, "action": 1, "target_id": 1,
              "changed_fields": 1},
        )
    audit = _run(_find_audit())
    assert audit is not None, (
        "expected a pricebook.patch audit row scoped to the "
        "aquaterra tenant; found none"
    )
    assert audit["tenant_id"] == aq_tenant_id
    assert "unit_price" in audit["changed_fields"]
