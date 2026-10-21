"""TD-96-g1 · Feb-2026 — ``list_quotes`` server-side ``lead_id`` filter.

Lead "View all" link on ``LeadDetail`` lands on ``/quotes?lead=<lid>``;
the FE wires that into the ``lead_id`` query param so the list
page actually filters to that lead's quotes (both pre-conversion
lead-recipient docs AND post-conversion reparented docs).

Locks:

  * ``lead_id=<lid>`` returns BOTH ``recipient_type="lead"
    + recipient_id=<lid>`` AND ``converted_from_lead_id=<lid>`` docs
    (``$or`` semantics — matches ``GET /leads/{lid}/quotes`` +
    ``linked_quotes_count``).
  * Tenant isolation — never leaks another tenant's lead-linked docs.
  * Unknown ``lead_id`` returns an empty list (no 404 — list endpoints
    don't 404 on empty-filter result sets).
  * Composes with ``view=accepted`` (narrows the lead's docs further).
  * Composes with ``status=accepted`` (post-FE filter) BUT the BE
    doesn't filter on ``status`` directly — covered by vitest.
  * ``customer_id`` + ``lead_id`` combo is non-erroring (intersection,
    typically empty but valid).

Harness mirrors ``test_fin_parity_b_list_quotes_payment_status_filter.py``
(FastAPI ASGITransport pattern per TD-21).
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

PFX = "td96g1_"


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


async def _seed_quote(
    *,
    tenant_id: str,
    lid: Optional[str] = None,
    cid: Optional[str] = None,
    converted_from_lead_id: Optional[str] = None,
    doc_type: str = "quote",
    status: str = "sent",
    title: str = "Q",
    total: float = 100.0,
) -> str:
    qid = f"{PFX}q_{uuid.uuid4().hex[:10]}"
    doc: Dict[str, Any] = {
        "id": qid,
        "tenant_id": tenant_id,
        "doc_type": doc_type,
        "title": title,
        "status": status,
        "total": total,
        "line_items": [],
        "subtotal": total,
        "tax": 0.0,
        "amount_paid": 0.0,
        "payment_status": "unpaid",
        "customer_name": "Test Customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if lid is not None:
        doc["recipient_type"] = "lead"
        doc["recipient_id"] = lid
        doc["customer_id"] = None
    if cid is not None:
        doc["recipient_type"] = "customer"
        doc["recipient_id"] = cid
        doc["customer_id"] = cid
    if converted_from_lead_id:
        doc["converted_from_lead_id"] = converted_from_lead_id
    await _DB.quotes.insert_one(doc)
    return qid


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
    ``routers.quotes.db`` to the test Motor DB."""
    from routers import quotes as quotes_mod
    from routers.tenants import get_current_tenant
    from utils import get_current_user

    user = {"id": "user_test", "role": role, "tenant_id": tenant_id}
    tenant = {"id": tenant_id}

    app = FastAPI()
    app.include_router(quotes_mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_tenant] = lambda: tenant
    quotes_mod.db = _DB
    return app


async def _get_quotes(
    *,
    tenant_id: str,
    lead_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    view: Optional[str] = None,
    doc_type: str = "quote",
    role: str = "admin",
):
    app = _build_app(tenant_id=tenant_id, role=role)
    params: Dict[str, Any] = {"doc_type": doc_type}
    if lead_id is not None:
        params["lead_id"] = lead_id
    if customer_id is not None:
        params["customer_id"] = customer_id
    if view is not None:
        params["view"] = view
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/quotes", params=params)
    return r.status_code, r.json()


# ═══════════════════════════════════════════════════════════════════
# §1 · $or semantics — pre-conversion + reparented returned together
# ═══════════════════════════════════════════════════════════════════
def test_lead_id_filter_returns_both_pre_and_reparented():
    lid = f"{PFX}lead_main"
    cid = f"{PFX}cust_mat"
    # Pre-conversion lead-recipient quote.
    q_lr = _run(_seed_quote(
        tenant_id=TENANT, lid=lid, title="Pre-conversion-LR",
    ))
    # Post-conversion reparented quote (recipient flipped to customer,
    # retains converted_from_lead_id).
    q_rep = _run(_seed_quote(
        tenant_id=TENANT, cid=cid,
        converted_from_lead_id=lid,
        status="accepted",
        title="Reparented",
    ))
    # Noise: unrelated lead's quote, same tenant.
    _run(_seed_quote(
        tenant_id=TENANT, lid=f"{PFX}other_lead", title="Noise",
    ))

    status, rows = _run(_get_quotes(tenant_id=TENANT, lead_id=lid))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    ids = {r["id"] for r in rows}
    assert ids == {q_lr, q_rep}


# ═══════════════════════════════════════════════════════════════════
# §2 · Tenant isolation
# ═══════════════════════════════════════════════════════════════════
def test_lead_id_filter_tenant_isolation():
    lid = f"{PFX}lead_xten"
    # Tenant A has the real quote.
    q_a = _run(_seed_quote(tenant_id=TENANT, lid=lid, title="A-legit"))
    # Tenant B has noise — same lid string, different tenant.
    _run(_seed_quote(tenant_id=TENANT_B, lid=lid, title="B-noise"))
    _run(_seed_quote(
        tenant_id=TENANT_B, cid=f"{PFX}cust_b",
        converted_from_lead_id=lid, title="B-noise-rep",
    ))

    status, rows = _run(_get_quotes(tenant_id=TENANT, lead_id=lid))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    ids = {r["id"] for r in rows}
    assert ids == {q_a}


# ═══════════════════════════════════════════════════════════════════
# §3 · Unknown lead_id → empty list (no 404)
# ═══════════════════════════════════════════════════════════════════
def test_lead_id_unknown_returns_empty_list():
    _run(_seed_quote(
        tenant_id=TENANT, lid=f"{PFX}other", title="Noise",
    ))
    status, rows = _run(_get_quotes(
        tenant_id=TENANT, lead_id=f"{PFX}does_not_exist",
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert rows == []


# ═══════════════════════════════════════════════════════════════════
# §4 · Composes with view= (lifecycle filter) via $and
# ═══════════════════════════════════════════════════════════════════
def test_lead_id_composes_with_view_accepted():
    lid = f"{PFX}lead_compose"
    cid = f"{PFX}cust_compose"
    # Pre-conversion sent (will NOT match view=accepted).
    _run(_seed_quote(
        tenant_id=TENANT, lid=lid, status="sent", title="Pre-sent",
    ))
    # Post-conversion reparented, status=accepted (matches view=accepted).
    q_acc = _run(_seed_quote(
        tenant_id=TENANT, cid=cid,
        converted_from_lead_id=lid,
        status="accepted", title="Reparented-accepted",
    ))

    status, rows = _run(_get_quotes(
        tenant_id=TENANT, lead_id=lid, view="accepted",
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    ids = {r["id"] for r in rows}
    assert ids == {q_acc}


# ═══════════════════════════════════════════════════════════════════
# §5 · No lead_id → no filter applied (current behavior preserved)
# ═══════════════════════════════════════════════════════════════════
def test_no_lead_id_param_preserves_prior_behavior():
    lid_a = f"{PFX}lead_a"
    lid_b = f"{PFX}lead_b"
    _run(_seed_quote(tenant_id=TENANT, lid=lid_a, title="A"))
    _run(_seed_quote(tenant_id=TENANT, lid=lid_b, title="B"))

    status, rows = _run(_get_quotes(tenant_id=TENANT))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    assert len(rows) == 2


# ═══════════════════════════════════════════════════════════════════
# §6 · customer_id + lead_id combo is non-erroring (intersection OK)
# ═══════════════════════════════════════════════════════════════════
def test_lead_id_with_customer_id_intersects_non_erroring():
    lid = f"{PFX}lead_intersect"
    cid = f"{PFX}cust_intersect"
    # Reparented quote whose owning customer == cid.
    q_rep = _run(_seed_quote(
        tenant_id=TENANT, cid=cid,
        converted_from_lead_id=lid,
        status="accepted", title="Intersect-match",
    ))
    # Noise: lead-recipient-only (no customer_id → excluded by
    # customer_id filter).
    _run(_seed_quote(
        tenant_id=TENANT, lid=lid, title="Lead-only",
    ))

    status, rows = _run(_get_quotes(
        tenant_id=TENANT, lead_id=lid, customer_id=cid,
    ))
    assert status == 200
    rows = [r for r in rows if r.get("id", "").startswith(PFX)]
    ids = {r["id"] for r in rows}
    assert ids == {q_rep}
