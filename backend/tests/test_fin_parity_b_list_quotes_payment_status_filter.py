"""FIN-PARITY-B · Feb-2026 — ``list_quotes`` server-side
``payment_status`` filter.

Locks:

  * payment_status=unpaid returns only unpaid rows.
  * payment_status=partial returns only partial rows.
  * payment_status=paid returns only paid rows.
  * payment_status=all returns everything (sentinel = no filter).
  * payment_status=garbage returns HTTP 400 with a stable
    ``error_code=invalid_payment_status`` in the response body.
  * No param → no filter (current behavior preserved).
  * Soft-delete filter still applies (HD-A).
  * Tenant isolation — never returns another tenant's rows.

TD-21 (RESOLVED, Feb-2026 cluster) — Migrated from the direct-call
``list_quotes(**kwargs)`` pattern to FastAPI ``AsyncClient`` /
``ASGITransport`` so FastAPI's parameter coercion actually runs. The
previous pattern bypassed FastAPI's dependency resolution, which left
every ``Query(...)``-defaulted param (``view``, ``offset``, ``limit``,
``category``, ``card_on_file``, ``customer_id``, ``slim``, ...) as the
raw ``FieldInfo`` sentinel inside the handler and tripped
``AttributeError: 'Query' object has no attribute 'strip'`` /
``TypeError: skip must be an integer`` depending on which sentinel was
touched first. The handler is correct for its documented HTTP contract;
only the test harness pattern needed fixing. See TECH_DEBT.md · TD-21
for the full reclassification story.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

_TEST_DIR = Path(__file__).resolve().parent
_BE = dotenv_values(_TEST_DIR.parent / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(MONGO_URL, io_loop=_LOOP)
_DB = _MC[DB_NAME]

PFX = "TESTfpBq_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _seed_invoice(
    *,
    tenant_id: str,
    payment_status: str,
    doc_type: str = "invoice",
    deleted_at: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> str:
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": doc_type,
        "total": 100.0,
        "amount_paid": {
            "unpaid": 0.0, "partial": 25.0, "paid": 100.0,
        }.get(payment_status, 0.0),
        "payment_status": payment_status,
        "status": "sent" if payment_status != "paid" else "accepted",
        "customer_id": customer_id or f"{PFX}cust_{uuid.uuid4().hex[:6]}",
        "customer_name": "Test Customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if deleted_at:
        doc["deleted_at"] = deleted_at
    await _DB.quotes.insert_one(doc)
    return inv_id


async def _wipe():
    await _DB.quotes.delete_many({"id": {"$regex": f"^{PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


TENANT = f"{PFX}tenant_A"
TENANT_B = f"{PFX}tenant_B"


def _build_app(*, tenant_id: str, role: str = "admin") -> FastAPI:
    """Mount ``routers.quotes.router`` under ``/api`` with per-test
    auth + tenant dependency overrides. Monkey-patches
    ``routers.quotes.db`` to the test Motor DB so inserts/reads land
    in the same place the seed helpers write to.
    """
    from routers import quotes as quotes_mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    user = {"id": "user_test", "role": role, "tenant_id": tenant_id}
    tenant = {"id": tenant_id}

    app = FastAPI()
    app.include_router(quotes_mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    # Monkey-patch module-level ``db`` to the test DB. Shared across
    # tests in this file; each test's autouse ``_clean`` fixture wipes
    # the ``TESTfpBq_``-prefixed rows so there's no cross-test bleed.
    quotes_mod.db = _DB
    return app


async def _get_quotes(
    *,
    tenant_id: str,
    payment_status: Optional[str] = None,
    role: str = "admin",
    include_deleted: bool = False,
    customer_id: Optional[str] = None,
    doc_type: str = "invoice",
):
    """GET /api/quotes with the given filters. Returns the parsed
    ``(status_code, json_body)`` tuple. Keeps the surface minimal —
    tests that need the raw body (error_code assertions) read
    ``body``; tests that need rows cast ``body`` to a list.
    """
    app = _build_app(tenant_id=tenant_id, role=role)
    params: Dict[str, Any] = {"doc_type": doc_type}
    if payment_status is not None:
        params["payment_status"] = payment_status
    if include_deleted:
        params["include_deleted"] = "true"
    if customer_id is not None:
        params["customer_id"] = customer_id
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/quotes", params=params)
    return r.status_code, r.json()


# ═══════════════════════════════════════════════════════════════════
# §1 · Each enum value narrows correctly
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_unpaid_returns_only_unpaid():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="partial"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    status, rows = _run(_get_quotes(tenant_id=TENANT, payment_status="unpaid"))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 1
    assert rows[0]["payment_status"] == "unpaid"


def test_payment_status_partial_returns_only_partial():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="partial"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    status, rows = _run(_get_quotes(tenant_id=TENANT, payment_status="partial"))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 1
    assert rows[0]["payment_status"] == "partial"


def test_payment_status_paid_returns_only_paid():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="partial"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    status, rows = _run(_get_quotes(tenant_id=TENANT, payment_status="paid"))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 1
    assert rows[0]["payment_status"] == "paid"


def test_payment_status_all_returns_every_state():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="partial"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    status, rows = _run(_get_quotes(tenant_id=TENANT, payment_status="all"))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    statuses = sorted(r["payment_status"] for r in rows)
    assert statuses == ["paid", "partial", "unpaid"]


def test_no_payment_status_param_preserves_prior_behavior():
    """Regression guard: omitting the param must return every row
    (identical to ``all``) so pre-FIN-PARITY-B callers keep working."""
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT, payment_status="paid"))
    status, rows = _run(_get_quotes(tenant_id=TENANT, payment_status=None))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 2


# ═══════════════════════════════════════════════════════════════════
# §2 · Garbage input → 400 with stable error_code
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_garbage_raises_400_with_stable_error_code():
    status, body = _run(_get_quotes(tenant_id=TENANT, payment_status="garbage"))
    assert status == 400
    detail = body["detail"]
    assert isinstance(detail, dict)
    assert detail["error_code"] == "invalid_payment_status"
    # Response must expose the accepted enum values so the FE can
    # render a deterministic error toast.
    assert detail["accepted_values"] == ["all", "paid", "partial", "unpaid"]


def test_payment_status_empty_string_rejected():
    """The empty string is NOT one of the enum values — reject with
    the same 400 as any other invalid input (guard against a bug
    where empty query param silently no-ops)."""
    status, body = _run(_get_quotes(tenant_id=TENANT, payment_status=""))
    assert status == 400
    assert body["detail"]["error_code"] == "invalid_payment_status"


def test_payment_status_case_sensitivity_rejects_uppercase():
    """Enum is lowercase; ``UNPAID`` / ``Paid`` must not sneak
    through. Locks the enum surface."""
    for bad in ("UNPAID", "Paid", "PARTIAL"):
        status, body = _run(_get_quotes(tenant_id=TENANT, payment_status=bad))
        assert status == 400
        assert body["detail"]["error_code"] == "invalid_payment_status"


# ═══════════════════════════════════════════════════════════════════
# §3 · Soft-delete filter still applies (HD-A regression guard)
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_filter_still_hides_soft_deleted_rows():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(
        tenant_id=TENANT, payment_status="unpaid",
        deleted_at=datetime.now(timezone.utc).isoformat(),
    ))
    status, rows = _run(_get_quotes(tenant_id=TENANT, payment_status="unpaid"))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    # Only the non-deleted row lands.
    assert len(rows) == 1
    assert rows[0].get("deleted_at") is None


def test_super_admin_include_deleted_opt_in_still_works():
    """super_admin + include_deleted=1 must return soft-deleted rows
    alongside the filtered payment_status matches."""
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(
        tenant_id=TENANT, payment_status="unpaid",
        deleted_at=datetime.now(timezone.utc).isoformat(),
    ))
    status, rows = _run(_get_quotes(
        tenant_id=TENANT, payment_status="unpaid",
        role="super_admin", include_deleted=True,
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 2


# ═══════════════════════════════════════════════════════════════════
# §4 · Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_filter_respects_tenant_scope():
    _run(_seed_invoice(tenant_id=TENANT, payment_status="unpaid"))
    _run(_seed_invoice(tenant_id=TENANT_B, payment_status="unpaid"))
    status_a, rows_a = _run(_get_quotes(tenant_id=TENANT, payment_status="unpaid"))
    status_b, rows_b = _run(_get_quotes(tenant_id=TENANT_B, payment_status="unpaid"))
    assert status_a == 200 and status_b == 200
    rows_a = [r for r in rows_a if r.get("id", "").startswith(PFX)]
    rows_b = [r for r in rows_b if r.get("id", "").startswith(PFX)]
    assert all(r["tenant_id"] == TENANT for r in rows_a)
    assert all(r["tenant_id"] == TENANT_B for r in rows_b)
    assert len(rows_a) == 1
    assert len(rows_b) == 1


def test_technician_role_still_forbidden_regardless_of_filter():
    """FIN-PARITY-B does NOT relax the tech-forbidden guard on
    list_quotes. Techs get 403, filter or no filter."""
    status, _body = _run(_get_quotes(
        tenant_id=TENANT, payment_status="unpaid", role="technician",
    ))
    assert status == 403


# ═══════════════════════════════════════════════════════════════════
# §5 · Filter composes with other list_quotes params
# ═══════════════════════════════════════════════════════════════════
def test_payment_status_composes_with_customer_id_filter():
    """Adding payment_status must not clobber other filter branches."""
    cid_target = f"{PFX}cust_target"
    cid_other = f"{PFX}cust_other"
    _run(_seed_invoice(
        tenant_id=TENANT, payment_status="unpaid", customer_id=cid_target,
    ))
    _run(_seed_invoice(
        tenant_id=TENANT, payment_status="paid", customer_id=cid_target,
    ))
    _run(_seed_invoice(
        tenant_id=TENANT, payment_status="unpaid", customer_id=cid_other,
    ))

    status, rows = _run(_get_quotes(
        tenant_id=TENANT, payment_status="unpaid", customer_id=cid_target,
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]

    # Composite match: cid_target + unpaid → exactly ONE row.
    assert len(rows) == 1
    assert rows[0]["customer_id"] == cid_target
    assert rows[0]["payment_status"] == "unpaid"
