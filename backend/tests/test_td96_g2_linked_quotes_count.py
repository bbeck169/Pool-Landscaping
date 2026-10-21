"""TD-96-g2 · Feb-2026 — ``linked_quotes_count`` field on ``GET /leads/{lid}``.

Locks the invariants that drive the lead-detail Linked-Quotes panel's
post-conversion visibility fix:

  1. ``linked_quotes_count`` counts both pre-conversion lead-recipient
     docs AND post-conversion reparented docs (``$or`` semantics
     mirroring ``GET /leads/{lid}/quotes``).
  2. ``quotes_count`` continues to count ONLY pre-conversion
     lead-recipient docs — the new field is strictly additive.
  3. After close-won reparent (lead-recipient → customer-recipient with
     ``converted_from_lead_id`` provenance), ``quotes_count`` drops to
     0 BUT ``linked_quotes_count`` stays ≥ 1 so the FE panel stays
     visible.
  4. Cross-tenant quotes don't leak into either count.

Harness mirrors ``test_lead_linked_quotes_endpoint.py``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_ENV = {k: (v.strip().strip('"').strip("'") if isinstance(v, str) else v)
        for k, v in _ENV.items()}
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _patch_db_everywhere():
    import config
    config.db = _DB
    for mod in ("routers.leads",):
        __import__(mod)
        import sys as _sys
        _sys.modules[mod].db = _DB


PREFIX = f"td96g2-{uuid4().hex[:8]}"
TENANT_A = f"{PREFIX}-tenant-a"
TENANT_B = f"{PREFIX}-tenant-b"
ADMIN = {"id": f"{PREFIX}-u-admin", "role": "admin"}


async def _seed_tenant(tid):
    await _DB.tenants.insert_one({"id": tid, "name": f"Tenant {tid}",
        "timezone": "America/Phoenix", "settings": {}})


async def _seed_lead(lid, tid, name="Larry Lead"):
    await _DB.leads.insert_one({
        "id": lid, "tenant_id": tid, "name": name,
        "email": "larry@example.com", "phone": "480-555-0001",
        "status": "new", "source": "admin_manual",
    })


async def _seed_quote(qid, tid, *, lid=None, cid=None, title="Q",
                       status="sent", total=100.0,
                       created_at="2026-02-10T00:00:00+00:00",
                       converted_from_lead_id=None, doc_type="quote"):
    doc = {
        "id": qid, "tenant_id": tid, "doc_type": doc_type,
        "title": title, "status": status, "total": total,
        "line_items": [], "subtotal": total, "tax": 0.0,
        "amount_paid": 0.0, "payment_status": "unpaid",
        "created_at": created_at,
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


async def _cleanup():
    rx = {"$regex": f"^{PREFIX}"}
    for coll in ("quotes", "leads"):
        await _DB[coll].delete_many(
            {"$or": [{"id": rx}, {"tenant_id": rx}]},
        )
    await _DB.tenants.delete_many({"id": rx})


@pytest.fixture(autouse=True)
def _clean():
    _patch_db_everywhere()
    _run(_cleanup())
    yield
    _run(_cleanup())


def _call_get_lead(lid, tenant_id):
    from routers.leads import get_lead
    return _run(get_lead(lid, user=ADMIN, tenant={"id": tenant_id}))


def test_pre_conversion_counts_equal():
    """Pre-conversion: both counts == # of lead-recipient quotes."""
    lid = f"{PREFIX}-l-pre"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    _run(_seed_quote(f"{PREFIX}-q-pre-1", TENANT_A, lid=lid, title="A"))
    _run(_seed_quote(f"{PREFIX}-q-pre-2", TENANT_A, lid=lid, title="B"))

    out = _call_get_lead(lid, TENANT_A)
    assert out["quotes_count"] == 2
    assert out["linked_quotes_count"] == 2


def test_post_reparent_quotes_count_zero_linked_nonzero():
    """Post close-won reparent — ``quotes_count`` drops to 0,
    ``linked_quotes_count`` retains the reparented docs so the panel
    stays visible. This is the exact regression TD-96-g2 fixes."""
    lid = f"{PREFIX}-l-reparent"
    cid = f"{PREFIX}-cust-materialized"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    # Two reparented quotes — ``recipient_type="customer"`` + provenance.
    _run(_seed_quote(f"{PREFIX}-q-rep-1", TENANT_A, cid=cid,
                      title="Reparented-1", status="accepted",
                      converted_from_lead_id=lid))
    _run(_seed_quote(f"{PREFIX}-q-rep-2", TENANT_A, cid=cid,
                      title="Reparented-2", status="sent",
                      converted_from_lead_id=lid))

    out = _call_get_lead(lid, TENANT_A)
    assert out["quotes_count"] == 0, \
        "legacy quotes_count must stay scoped to lead-recipient docs"
    assert out["linked_quotes_count"] == 2, \
        "linked_quotes_count must include reparented docs"


def test_mixed_pre_and_post_conversion():
    """Mixed state: some docs still lead-recipient, some reparented.
    ``linked_quotes_count`` is the full sum; ``quotes_count`` only the
    unreparented half."""
    lid = f"{PREFIX}-l-mixed"
    cid = f"{PREFIX}-cust-mixed"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    # 1 reparented
    _run(_seed_quote(f"{PREFIX}-q-mix-rep", TENANT_A, cid=cid,
                      title="R", status="accepted",
                      converted_from_lead_id=lid))
    # 2 still lead-recipient (e.g., re-opened lead post-conversion)
    _run(_seed_quote(f"{PREFIX}-q-mix-lr-1", TENANT_A, lid=lid, title="L1"))
    _run(_seed_quote(f"{PREFIX}-q-mix-lr-2", TENANT_A, lid=lid, title="L2"))

    out = _call_get_lead(lid, TENANT_A)
    assert out["quotes_count"] == 2
    assert out["linked_quotes_count"] == 3


def test_cross_tenant_isolation():
    """Cross-tenant lead-recipient + reparented quotes don't leak
    into either count."""
    lid = f"{PREFIX}-l-xten"
    cid_b = f"{PREFIX}-cust-b"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_tenant(TENANT_B))
    _run(_seed_lead(lid, TENANT_A))
    # Noise: tenant B owns these — same ``lid`` string but different tenant.
    _run(_seed_quote(f"{PREFIX}-q-b-lr", TENANT_B, lid=lid, title="Bnoise"))
    _run(_seed_quote(f"{PREFIX}-q-b-rep", TENANT_B, cid=cid_b,
                      title="BnoiseR", status="accepted",
                      converted_from_lead_id=lid))
    # Tenant A legit quote
    _run(_seed_quote(f"{PREFIX}-q-a-lr", TENANT_A, lid=lid, title="Alegit"))

    out = _call_get_lead(lid, TENANT_A)
    assert out["quotes_count"] == 1
    assert out["linked_quotes_count"] == 1


def test_zero_zero_for_leads_with_no_quotes():
    """Brand-new lead with no quotes — both counts == 0 so the FE
    lazy-fetch gate correctly skips the ``/quotes`` call."""
    lid = f"{PREFIX}-l-empty"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))

    out = _call_get_lead(lid, TENANT_A)
    assert out["quotes_count"] == 0
    assert out["linked_quotes_count"] == 0
