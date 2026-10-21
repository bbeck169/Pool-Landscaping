"""TD-93 · Feb-2026 — ``/payments/summary`` date-range filter.

Locks the ``date_from`` / ``date_to`` / ``date_field`` branch of
``GET /api/payments/summary`` + the semantics locked by audit §6:

  * **Collected** uses ``paid_at`` regardless of ``date_field`` —
    Collected is semantically about money-arrived, not
    invoice-dated.
  * **Outstanding + Overdue** use ``date_field`` with the current
    status gate intact (NOT a point-in-time balance-as-of-to
    reconstruction).
  * ``date_field`` whitelist = ``created_at`` (default) +
    ``due_date``.  Bogus values return 400 with
    ``error_code=invalid_date_field``.
  * ``range_active`` + ``date_field`` are echoed on the response so
    the FE can pick dynamic labels without re-deriving.

Pattern parity: same ASGITransport + per-test tenant override as
``test_td93_list_quotes_date_range.py``.
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

PFX = "TESTtd93sm_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _seed(
    *,
    tenant_id: str,
    total: float = 100.0,
    amount_paid: float = 0.0,
    status: str = "sent",
    created_at: Optional[str] = None,
    due_date: Optional[str] = None,
    paid_at: Optional[str] = None,
) -> str:
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "total": total,
        "amount_paid": amount_paid,
        "status": status,
        "customer_id": f"{PFX}cust_{uuid.uuid4().hex[:6]}",
        "customer_name": "Test Customer",
    }
    if created_at is not None:
        doc["created_at"] = created_at
    if due_date is not None:
        doc["due_date"] = due_date
    if paid_at is not None:
        doc["paid_at"] = paid_at
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


def _build_app(*, tenant_id: str, role: str = "admin") -> FastAPI:
    from routers import payments_summary as mod
    from utils import get_current_user

    user = {"id": "user_test", "role": role, "tenant_id": tenant_id}
    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    mod.db = _DB
    return app


async def _call(*, tenant_id: str, params: Dict[str, Any],
                 role: str = "admin"):
    app = _build_app(tenant_id=tenant_id, role=role)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/payments/summary", params=params)
    return r.status_code, r.json()


def _iso(y: int, m: int, d: int, h: int = 12) -> str:
    return datetime(y, m, d, h, 0, 0, tzinfo=timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# §1 · No range → zero behaviour change (regression guard)
# ═══════════════════════════════════════════════════════════════════
def test_no_range_params_preserves_legacy_shape_and_math():
    # Seed one in-month paid + one outstanding past_due.
    now = datetime.now(timezone.utc)
    _run(_seed(tenant_id=TENANT, total=100, amount_paid=100,
                status="accepted", paid_at=now.isoformat()))
    _run(_seed(tenant_id=TENANT, total=200, amount_paid=50,
                status="past_due", due_date="2025-01-10"))
    status, body = _run(_call(tenant_id=TENANT, params={}))
    assert status == 200
    assert body["collected_this_month"] == 100.0
    assert body["outstanding_total"] == 150.0
    assert body["outstanding_count"] == 1
    assert len(body["overdue"]) == 1
    assert body["range_active"] is False
    assert body["date_field"] is None


# ═══════════════════════════════════════════════════════════════════
# §2 · Collected uses paid_at regardless of date_field
# ═══════════════════════════════════════════════════════════════════
def test_collected_uses_paid_at_regardless_of_date_field():
    # Paid in Feb-2026, created in Jan-2026, due in Mar-2026.
    _run(_seed(tenant_id=TENANT, total=100, amount_paid=100,
                status="accepted",
                created_at=_iso(2026, 1, 15),
                due_date="2026-03-01",
                paid_at=_iso(2026, 2, 20)))
    # Even with date_field=due_date, Collected keys on paid_at.
    for df in ("created_at", "due_date"):
        status, body = _run(_call(
            tenant_id=TENANT,
            params={"date_from": "2026-02-01", "date_to": "2026-02-28",
                     "date_field": df},
        ))
        assert status == 200
        assert body["collected_this_month"] == 100.0, (
            f"Collected should see paid_at hit in Feb for date_field={df}"
        )
        assert body["range_active"] is True
        assert body["date_field"] == df


def test_collected_excludes_payments_outside_range():
    # Paid in Jan-2026 — must be excluded by Feb-2026 range.
    _run(_seed(tenant_id=TENANT, total=100, amount_paid=100,
                status="accepted",
                created_at=_iso(2026, 1, 15),
                paid_at=_iso(2026, 1, 20)))
    status, body = _run(_call(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_to": "2026-02-28"},
    ))
    assert status == 200
    assert body["collected_this_month"] == 0.0


# ═══════════════════════════════════════════════════════════════════
# §3 · Outstanding + Overdue · created_at range
# ═══════════════════════════════════════════════════════════════════
def test_outstanding_filtered_by_created_at_range():
    # Three outstanding invoices, created in different months.
    _run(_seed(tenant_id=TENANT, total=100, amount_paid=0,
                status="sent", created_at=_iso(2026, 1, 15),
                due_date="2026-04-01"))  # before
    _run(_seed(tenant_id=TENANT, total=200, amount_paid=0,
                status="sent", created_at=_iso(2026, 2, 15),
                due_date="2026-04-01"))  # in-range
    _run(_seed(tenant_id=TENANT, total=400, amount_paid=0,
                status="sent", created_at=_iso(2026, 3, 15),
                due_date="2026-04-01"))  # after
    status, body = _run(_call(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_to": "2026-02-28",
                 "date_field": "created_at"},
    ))
    assert status == 200
    assert body["outstanding_total"] == 200.0
    assert body["outstanding_count"] == 1


def test_overdue_filtered_by_due_date_range():
    # past_due invoices with different due_dates.
    _run(_seed(tenant_id=TENANT, total=100, amount_paid=0,
                status="past_due", created_at=_iso(2025, 12, 1),
                due_date="2026-01-10"))  # out
    _run(_seed(tenant_id=TENANT, total=200, amount_paid=0,
                status="past_due", created_at=_iso(2026, 1, 1),
                due_date="2026-02-10"))  # in
    _run(_seed(tenant_id=TENANT, total=300, amount_paid=0,
                status="past_due", created_at=_iso(2026, 1, 1),
                due_date="2026-02-28"))  # in (inclusive)
    _run(_seed(tenant_id=TENANT, total=400, amount_paid=0,
                status="past_due", created_at=_iso(2026, 1, 1),
                due_date="2026-03-05"))  # out
    status, body = _run(_call(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_to": "2026-02-28",
                 "date_field": "due_date"},
    ))
    assert status == 200
    assert body["outstanding_total"] == 500.0  # 200 + 300
    assert len(body["overdue"]) == 2
    for row in body["overdue"]:
        assert row["due_date"].startswith("2026-02")


# ═══════════════════════════════════════════════════════════════════
# §4 · Status gate preserved under range
# ═══════════════════════════════════════════════════════════════════
def test_outstanding_status_gate_intact_under_range():
    # paid status in range → NOT included (status gate).
    _run(_seed(tenant_id=TENANT, total=100, amount_paid=100,
                status="paid", created_at=_iso(2026, 2, 15),
                due_date="2026-02-28"))
    # live-status in range → included.
    _run(_seed(tenant_id=TENANT, total=200, amount_paid=0,
                status="sent", created_at=_iso(2026, 2, 15),
                due_date="2026-02-28"))
    status, body = _run(_call(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_to": "2026-02-28",
                 "date_field": "created_at"},
    ))
    assert status == 200
    assert body["outstanding_total"] == 200.0
    assert body["outstanding_count"] == 1


# ═══════════════════════════════════════════════════════════════════
# §5 · Whitelist · bogus date_field → 400
# ═══════════════════════════════════════════════════════════════════
def test_bogus_date_field_returns_400():
    status, body = _run(_call(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_field": "bogus"},
    ))
    assert status == 400
    detail = body.get("detail") or {}
    assert detail.get("error_code") == "invalid_date_field"


# ═══════════════════════════════════════════════════════════════════
# §6 · Role gate preserved (customer/tech → 403)
# ═══════════════════════════════════════════════════════════════════
def test_role_gate_preserved_under_range():
    status, body = _run(_call(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01"},
        role="technician",
    ))
    assert status == 403


# ═══════════════════════════════════════════════════════════════════
# §7 · Due-date branch skips invoices with no due_date
# ═══════════════════════════════════════════════════════════════════
def test_due_date_branch_skips_rows_with_null_due_date():
    _run(_seed(tenant_id=TENANT, total=100, amount_paid=0,
                status="sent", created_at=_iso(2026, 2, 15)))  # no due_date
    _run(_seed(tenant_id=TENANT, total=200, amount_paid=0,
                status="sent", created_at=_iso(2026, 2, 15),
                due_date="2026-02-15"))
    status, body = _run(_call(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_to": "2026-02-28",
                 "date_field": "due_date"},
    ))
    assert status == 200
    assert body["outstanding_total"] == 200.0
    assert body["outstanding_count"] == 1
