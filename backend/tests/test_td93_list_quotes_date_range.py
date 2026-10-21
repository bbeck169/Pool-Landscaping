"""TD-93 · Feb-2026 — ``list_quotes`` date-range filter.

Locks the ``date_from`` / ``date_to`` / ``date_field`` branch of
``GET /quotes?doc_type=invoice``:

  * ``date_field`` whitelist: ``created_at`` (default) or ``due_date``.
    Any other value → HTTP 400 with ``error_code=invalid_date_field``.
  * Both bounds inclusive (matches the BE date-range convention
    established by ``routers/chemical_applications.py`` +
    ``routers/attendance.py``).
  * ``created_at`` branch — day-only bounds are expanded to the full
    day at ``+00:00`` so an inclusive ``date_to`` matches invoices
    created later in that day.
  * ``due_date`` branch — raw ``YYYY-MM-DD`` lex-compare (correct
    because ``due_date`` is a date-only field).
  * Open-ended range (only one bound set) is accepted.
  * Tenant scoping unchanged.

Mirrors the test harness pattern established by
``test_fin_parity_b_list_quotes_payment_status_filter.py`` — FastAPI
``ASGITransport`` + per-test tenant override, monkey-patched module
``db`` to the test Motor DB.
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

PFX = "TESTtd93dr_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _seed_invoice(
    *,
    tenant_id: str,
    created_at: str,
    due_date: Optional[str] = None,
) -> str:
    inv_id = f"{PFX}inv_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": inv_id,
        "tenant_id": tenant_id,
        "doc_type": "invoice",
        "payment_status": "unpaid",
        "status": "sent",
        "total": 100.0,
        "amount_paid": 0.0,
        "created_at": created_at,
        "customer_id": f"{PFX}cust_{uuid.uuid4().hex[:6]}",
        "customer_name": "Test Customer",
    }
    if due_date is not None:
        doc["due_date"] = due_date
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


def _build_app(*, tenant_id: str) -> FastAPI:
    from routers import quotes as quotes_mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    user = {"id": "user_test", "role": "admin", "tenant_id": tenant_id}
    tenant = {"id": tenant_id}

    app = FastAPI()
    app.include_router(quotes_mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    quotes_mod.db = _DB
    return app


async def _get_quotes(*, tenant_id: str, params: Dict[str, Any]):
    app = _build_app(tenant_id=tenant_id)
    params = {"doc_type": "invoice", **params}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/quotes", params=params)
    return r.status_code, r.json()


def _iso(y: int, m: int, d: int, h: int = 12) -> str:
    return datetime(y, m, d, h, 0, 0, tzinfo=timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════
# §1 · date_field=created_at — inclusive day-bound expansion
# ═══════════════════════════════════════════════════════════════════
def test_date_from_to_filters_by_created_at_inclusive():
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 10)))  # before
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 2, 15)))  # in-range
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 2, 28, 23)))  # last-day
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 3, 5)))  # after
    status, rows = _run(_get_quotes(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_to": "2026-02-28",
                "date_field": "created_at"},
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 2
    for r in rows:
        assert "2026-02" in r["created_at"]


def test_date_from_only_is_half_open_lower_bound():
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 10)))  # before
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 2, 15)))
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 3, 5)))
    status, rows = _run(_get_quotes(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_field": "created_at"},
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 2
    for r in rows:
        assert r["created_at"] >= "2026-02-01"


def test_date_to_only_is_half_open_upper_bound():
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 10)))
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 2, 15)))
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 3, 5)))  # after
    status, rows = _run(_get_quotes(
        tenant_id=TENANT,
        params={"date_to": "2026-02-28", "date_field": "created_at"},
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 2
    for r in rows:
        assert r["created_at"] <= "2026-02-28T23:59:59.999999+00:00"


# ═══════════════════════════════════════════════════════════════════
# §2 · date_field=due_date — raw YYYY-MM-DD lex-compare
# ═══════════════════════════════════════════════════════════════════
def test_date_from_to_filters_by_due_date_inclusive():
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 1),
                        due_date="2026-01-15"))  # before
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 1),
                        due_date="2026-02-15"))  # in
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 1),
                        due_date="2026-02-28"))  # last-day inclusive
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 1),
                        due_date="2026-03-05"))  # after
    status, rows = _run(_get_quotes(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_to": "2026-02-28",
                "date_field": "due_date"},
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 2
    for r in rows:
        assert r["due_date"].startswith("2026-02")


# ═══════════════════════════════════════════════════════════════════
# §3 · date_field whitelist — reject anything else with 400
# ═══════════════════════════════════════════════════════════════════
def test_bogus_date_field_returns_400_with_stable_error_code():
    status, body = _run(_get_quotes(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_field": "bogus"},
    ))
    assert status == 400
    detail = body.get("detail") or {}
    assert detail.get("error_code") == "invalid_date_field"
    assert "created_at" in detail.get("accepted_values", [])
    assert "due_date" in detail.get("accepted_values", [])


def test_paid_at_rejected_as_date_field_via_400():
    # Explicit guard: ``paid_at`` is a stored field on invoice docs
    # but intentionally excluded from the whitelist (would hide
    # every unpaid row).  Verify it fails cleanly.
    status, body = _run(_get_quotes(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_field": "paid_at"},
    ))
    assert status == 400
    assert (body.get("detail") or {}).get("error_code") == "invalid_date_field"


# ═══════════════════════════════════════════════════════════════════
# §4 · date_field default = created_at when omitted
# ═══════════════════════════════════════════════════════════════════
def test_date_field_defaults_to_created_at_when_omitted():
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 10)))
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 2, 15)))
    status, rows = _run(_get_quotes(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01"},  # no ``date_field``
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 1
    assert "2026-02" in rows[0]["created_at"]


# ═══════════════════════════════════════════════════════════════════
# §5 · Tenant isolation unchanged
# ═══════════════════════════════════════════════════════════════════
def test_date_range_filter_respects_tenant_scope():
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 2, 15)))
    _run(_seed_invoice(tenant_id=TENANT_B, created_at=_iso(2026, 2, 15)))
    status, rows = _run(_get_quotes(
        tenant_id=TENANT,
        params={"date_from": "2026-02-01", "date_to": "2026-02-28"},
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 1
    assert rows[0]["tenant_id"] == TENANT


# ═══════════════════════════════════════════════════════════════════
# §6 · No range params → zero behaviour change (regression guard)
# ═══════════════════════════════════════════════════════════════════
def test_no_date_params_returns_all_rows_unchanged():
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 1, 1)))
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 6, 1)))
    _run(_seed_invoice(tenant_id=TENANT, created_at=_iso(2026, 12, 1)))
    status, rows = _run(_get_quotes(tenant_id=TENANT, params={}))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 3
