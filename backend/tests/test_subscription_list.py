"""Phase B4 · Feb-2026 — Subscription list tests."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests

from services.payments import stripe_charge as sc
from services.payments import stripe_subscription as sub_svc


BASE = os.environ.get("STRIPE_TEST_BASE") or "http://localhost:8001"
TID = f"tenSUBL-{uuid.uuid4().hex[:8]}"
TID_OTHER = f"tenSUBL-OTHER-{uuid.uuid4().hex[:8]}"


def _demo_pw() -> str:
    md = Path("/app/memory/test_credentials.md").read_text()
    for line in md.splitlines():
        if "admin@aquaterra.com" in line:
            toks = [t for t in line.split("`") if t and " " not in t]
            if len(toks) >= 2:
                return toks[1]
    return "password123"


@pytest.fixture
def db():
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.stripe_subscriptions.delete_many(
            {"tenant_id": {"$in": [TID, TID_OTHER]}},
        )
    asyncio.get_event_loop().run_until_complete(_wipe())
    yield
    asyncio.get_event_loop().run_until_complete(_wipe())


async def _seed(sub_id: str, tenant_id: str, customer_id: str, status: str = "active"):
    await sc.db.stripe_subscriptions.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id, "customer_id": customer_id,
        "stripe_subscription_id": sub_id, "stripe_customer_id": "cus_x",
        "price_id": "price_x", "quantity": 1,
        "status": status, "cancel_at_period_end": False,
        "created_at": f"2026-02-{15 + hash(sub_id) % 10:02d}T00:00:00+00:00",
    })


def test_list_filters_by_tenant(db):
    asyncio.get_event_loop().run_until_complete(_seed("sub_a", TID, "cust1"))
    asyncio.get_event_loop().run_until_complete(_seed("sub_b", TID, "cust1"))
    asyncio.get_event_loop().run_until_complete(_seed("sub_c", TID_OTHER, "cust1"))
    res = asyncio.get_event_loop().run_until_complete(
        sub_svc.list_subscriptions(tenant_id=TID),
    )
    ids = {r["stripe_subscription_id"] for r in res["rows"]}
    assert res["total"] == 2
    assert ids == {"sub_a", "sub_b"}
    assert "sub_c" not in ids  # tenant leak guard


def test_list_filters_by_customer(db):
    asyncio.get_event_loop().run_until_complete(_seed("sub_a", TID, "custA"))
    asyncio.get_event_loop().run_until_complete(_seed("sub_b", TID, "custB"))
    res = asyncio.get_event_loop().run_until_complete(
        sub_svc.list_subscriptions(tenant_id=TID, customer_id="custA"),
    )
    assert res["total"] == 1
    assert res["rows"][0]["stripe_subscription_id"] == "sub_a"


def test_list_filters_by_status(db):
    asyncio.get_event_loop().run_until_complete(_seed("sub_a", TID, "cust1", status="active"))
    asyncio.get_event_loop().run_until_complete(_seed("sub_b", TID, "cust1", status="canceled"))
    res = asyncio.get_event_loop().run_until_complete(
        sub_svc.list_subscriptions(tenant_id=TID, status="canceled"),
    )
    ids = {r["stripe_subscription_id"] for r in res["rows"]}
    assert ids == {"sub_b"}
    # And "all" returns both.
    res_all = asyncio.get_event_loop().run_until_complete(
        sub_svc.list_subscriptions(tenant_id=TID, status="all"),
    )
    assert res_all["total"] == 2


def test_list_pagination(db):
    for i in range(5):
        asyncio.get_event_loop().run_until_complete(_seed(f"sub_p_{i}", TID, "cust1"))
    r1 = asyncio.get_event_loop().run_until_complete(
        sub_svc.list_subscriptions(tenant_id=TID, limit=2, skip=0),
    )
    r2 = asyncio.get_event_loop().run_until_complete(
        sub_svc.list_subscriptions(tenant_id=TID, limit=2, skip=2),
    )
    assert r1["total"] == 5
    assert len(r1["rows"]) == 2
    assert len(r2["rows"]) == 2
    # Distinct rows across pages.
    ids = {r["stripe_subscription_id"] for r in (r1["rows"] + r2["rows"])}
    assert len(ids) == 4


def test_list_http_endpoint_returns_tenant_scoped_rows(db):
    # Seed against the admin@aquaterra.com login's own tenant so the
    # HTTP endpoint has something visible. The seed row lands in the
    # tenant that the logged-in admin belongs to.
    tok_r = requests.post(f"{BASE}/api/auth/login",
                           json={"email": "admin@aquaterra.com",
                                 "password": _demo_pw()},
                           timeout=60)
    tok_r.raise_for_status()
    me = requests.get(f"{BASE}/api/auth/me",
                       headers={"Authorization": f"Bearer {tok_r.json()['access_token']}"},
                       timeout=15).json()
    tid = me["tenant_id"]
    unique_sub_id = f"sub_http_test_{uuid.uuid4().hex[:10]}"
    asyncio.get_event_loop().run_until_complete(_seed(unique_sub_id, tid, "cust-http"))
    try:
        r = requests.get(
            f"{BASE}/api/subscriptions?customer_id=cust-http",
            headers={"Authorization": f"Bearer {tok_r.json()['access_token']}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert any(row["stripe_subscription_id"] == unique_sub_id for row in body["rows"])
    finally:
        asyncio.get_event_loop().run_until_complete(
            sc.db.stripe_subscriptions.delete_many({"stripe_subscription_id": unique_sub_id}),
        )
