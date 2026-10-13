"""P2 #4 · Feb-2026 — GET /leads/{lid}/quotes pytest.

Locks four invariants:
  1. Returns lead-recipient quotes AND post-conversion reparented
     quotes (via converted_from_lead_id) ordered by created_at desc.
  2. Status values are lowercased before leaving the endpoint so the
     UI can render consistent status pills.
  3. Honors ``limit`` (capped at 50) and reports ``total`` separately.
  4. 404 on unknown or cross-tenant lead ids.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
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


PREFIX = f"p24d-{uuid4().hex[:8]}"
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
                       status="sent", total=100.0, created_at="2026-02-10T00:00:00+00:00",
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


def test_returns_lead_recipient_and_reparented_quotes_desc():
    lid = f"{PREFIX}-l-main"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    # Oldest lead-recipient quote
    _run(_seed_quote(f"{PREFIX}-q-a", TENANT_A, lid=lid, title="Alpha",
                        status="Sent", created_at="2026-02-01T00:00:00+00:00"))
    # Middle one: a reparented quote (lead was closed won, now customer-recipient
    # but retains converted_from_lead_id provenance)
    _run(_seed_quote(f"{PREFIX}-q-b", TENANT_A,
                        cid=f"{PREFIX}-cust-materialized", title="Bravo",
                        status="accepted",
                        created_at="2026-02-05T00:00:00+00:00",
                        converted_from_lead_id=lid))
    # Newest lead-recipient quote
    _run(_seed_quote(f"{PREFIX}-q-c", TENANT_A, lid=lid, title="Charlie",
                        status="draft", created_at="2026-02-10T00:00:00+00:00"))
    from routers.leads import list_linked_quotes
    out = _run(list_linked_quotes(lid, limit=10, user=ADMIN,
                                     tenant={"id": TENANT_A}))
    assert out["total"] == 3
    titles = [item["title"] for item in out["items"]]
    assert titles == ["Charlie", "Bravo", "Alpha"]
    # Status lowercased.
    assert out["items"][0]["status"] == "draft"
    # The reparented row flagged.
    bravo = next(i for i in out["items"] if i["title"] == "Bravo")
    assert bravo["reparented"] is True
    assert bravo["status"] == "accepted"
    alpha = next(i for i in out["items"] if i["title"] == "Alpha")
    assert alpha["reparented"] is False
    assert alpha["status"] == "sent"


def test_limit_cap_and_total_separation():
    lid = f"{PREFIX}-l-many"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_lead(lid, TENANT_A))
    for i in range(15):
        _run(_seed_quote(
            f"{PREFIX}-q-many-{i:02d}", TENANT_A, lid=lid,
            title=f"Q{i:02d}",
            created_at=f"2026-02-{1 + (i % 28):02d}T00:00:00+00:00",
        ))
    from routers.leads import list_linked_quotes
    out = _run(list_linked_quotes(lid, limit=5, user=ADMIN,
                                     tenant={"id": TENANT_A}))
    assert out["total"] == 15
    assert out["limit"] == 5
    assert len(out["items"]) == 5
    # Over-limit request is capped at 50 (the module constant).
    out2 = _run(list_linked_quotes(lid, limit=9999, user=ADMIN,
                                      tenant={"id": TENANT_A}))
    assert out2["limit"] == 50
    assert len(out2["items"]) == 15  # total < 50


def test_404_on_unknown_lead_id():
    _run(_seed_tenant(TENANT_A))
    from routers.leads import list_linked_quotes
    with pytest.raises(HTTPException) as exc:
        _run(list_linked_quotes(f"{PREFIX}-nope", limit=10,
                                   user=ADMIN, tenant={"id": TENANT_A}))
    assert exc.value.status_code == 404


def test_404_on_cross_tenant_lead_id():
    lid = f"{PREFIX}-l-xten"
    _run(_seed_tenant(TENANT_A))
    _run(_seed_tenant(TENANT_B))
    _run(_seed_lead(lid, TENANT_B))
    from routers.leads import list_linked_quotes
    with pytest.raises(HTTPException) as exc:
        _run(list_linked_quotes(lid, limit=10, user=ADMIN,
                                   tenant={"id": TENANT_A}))
    assert exc.value.status_code == 404
