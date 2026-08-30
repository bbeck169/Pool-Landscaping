"""Phase B4 · Feb-2026 — Subscription update tests."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests

from services.payments import stripe_charge as sc
from services.payments import stripe_subscription as sub_svc


BASE = os.environ.get("STRIPE_TEST_BASE") or "http://localhost:8001"
TID = f"tenSUBU-{uuid.uuid4().hex[:8]}"


def _demo_pw() -> str:
    md = Path("/app/memory/test_credentials.md").read_text()
    for line in md.splitlines():
        if "carlos@aquaterra.com" in line and "technician" in line:
            toks = [t for t in line.split("`") if t and " " not in t]
            if len(toks) >= 2:
                return toks[1]
    return "password123"


def _login(email: str) -> str:
    r = requests.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": _demo_pw()},
                       timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def db():
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.stripe_subscriptions.delete_many({"tenant_id": TID})
    asyncio.get_event_loop().run_until_complete(_wipe())
    yield
    asyncio.get_event_loop().run_until_complete(_wipe())


@pytest.fixture
def stripe_stub(monkeypatch):
    calls: Dict[str, List[Dict[str, Any]]] = {
        "retrieve": [], "modify": [],
    }

    def _fake_retrieve(sid):
        calls["retrieve"].append(sid)
        return {
            "id": sid,
            "items": {"data": [{"id": "si_stub_item"}]},
            "status": "active",
        }

    def _fake_modify(sid, **kw):
        calls["modify"].append({"id": sid, **kw})
        return {
            "id": sid,
            "status": kw.get("status", "active"),
            "current_period_start": 1700000000,
            "current_period_end": 1702592000,
            "cancel_at_period_end": bool(kw.get("cancel_at_period_end")),
            "canceled_at": None,
            "created": 1700000000,
        }

    monkeypatch.setattr(sc._stripe.Subscription, "retrieve", _fake_retrieve)
    monkeypatch.setattr(sc._stripe.Subscription, "modify", _fake_modify)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)
    monkeypatch.setattr(sub_svc, "_init_api_key", lambda: None)
    return calls


async def _seed_mirror(sub_id: str, tenant_id: str = TID) -> None:
    await sc.db.stripe_subscriptions.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": "cust-x",
        "stripe_subscription_id": sub_id,
        "stripe_customer_id": "cus_x",
        "price_id": "price_old",
        "quantity": 1,
        "status": "active",
        "cancel_at_period_end": False,
    })


def test_update_quantity_only_updates_mirror(db, stripe_stub):
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_mirror(sub_id))
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.update_subscription(tenant_id=TID, sub_id=sub_id, quantity=5),
    )
    assert row is not None
    assert row["quantity"] == 5
    assert row["webhook_source"] == "app_update"
    # Stripe was called with correct item patch.
    assert stripe_stub["modify"][0]["items"] == [
        {"id": "si_stub_item", "quantity": 5},
    ]


def test_update_price_and_quantity_patches_item(db, stripe_stub):
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_mirror(sub_id))
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.update_subscription(
            tenant_id=TID, sub_id=sub_id,
            price_id="price_new", quantity=3,
        ),
    )
    assert row["price_id"] == "price_new"
    assert row["quantity"] == 3
    assert stripe_stub["modify"][0]["items"] == [
        {"id": "si_stub_item", "price": "price_new", "quantity": 3},
    ]


def test_update_cancel_at_period_end_toggle(db, stripe_stub):
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_mirror(sub_id))
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.update_subscription(
            tenant_id=TID, sub_id=sub_id, cancel_at_period_end=True,
        ),
    )
    assert row["cancel_at_period_end"] is True
    assert stripe_stub["modify"][0]["cancel_at_period_end"] is True
    # Retrieve should NOT be called when no price/qty change is requested.
    assert stripe_stub["retrieve"] == []


def test_update_cross_tenant_returns_none(db, stripe_stub):
    """Attempting to modify a sub owned by another tenant returns
    None — the router turns this into a 404 (no info leak)."""
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    other_tid = f"tenSUBU-OTHER-{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_mirror(sub_id, tenant_id=other_tid))
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.update_subscription(
            tenant_id=TID,  # WRONG tenant
            sub_id=sub_id, quantity=2,
        ),
    )
    assert row is None
    # Stripe must NOT have been called on cross-tenant access.
    assert stripe_stub["modify"] == []
    assert stripe_stub["retrieve"] == []


def test_update_metadata_preserves_reserved_keys(db, stripe_stub):
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_mirror(sub_id))
    asyncio.get_event_loop().run_until_complete(
        sub_svc.update_subscription(
            tenant_id=TID, sub_id=sub_id,
            metadata={"crm_tenant_id": "SPOOFED", "note": "priority"},
        ),
    )
    mod = stripe_stub["modify"][0]
    assert mod["metadata"]["crm_tenant_id"] == TID
    assert mod["metadata"]["note"] == "priority"


def test_update_http_role_gate_rejects_technician(db):
    tok = _login("carlos@aquaterra.com")
    r = requests.patch(
        f"{BASE}/api/subscriptions/sub_stub_x",
        headers={"Authorization": f"Bearer {tok}"},
        json={"quantity": 3}, timeout=15,
    )
    assert r.status_code == 403, r.text


def test_update_http_returns_404_on_unknown_sub_for_admin(db):
    tok = _login("admin@aquaterra.com")
    r = requests.patch(
        f"{BASE}/api/subscriptions/sub_does_not_exist",
        headers={"Authorization": f"Bearer {tok}"},
        json={"quantity": 2}, timeout=15,
    )
    assert r.status_code == 404
