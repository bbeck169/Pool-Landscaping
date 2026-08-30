"""Phase B4 · Feb-2026 — Subscription cancel tests."""
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
TID = f"tenSUBX-{uuid.uuid4().hex[:8]}"


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
        "delete": [], "modify": [],
    }

    def _fake_delete(sid):
        calls["delete"].append(sid)
        return {"id": sid, "status": "canceled",
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
                "cancel_at_period_end": False,
                "canceled_at": 1701000000,
                "created": 1700000000}

    def _fake_modify(sid, **kw):
        calls["modify"].append({"id": sid, **kw})
        return {"id": sid, "status": "active",
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
                "cancel_at_period_end": bool(kw.get("cancel_at_period_end")),
                "canceled_at": None,
                "created": 1700000000}

    monkeypatch.setattr(sc._stripe.Subscription, "delete", _fake_delete)
    monkeypatch.setattr(sc._stripe.Subscription, "modify", _fake_modify)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)
    monkeypatch.setattr(sub_svc, "_init_api_key", lambda: None)
    return calls


async def _seed_mirror(sub_id: str, tenant_id: str = TID) -> None:
    await sc.db.stripe_subscriptions.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id, "customer_id": "cust-x",
        "stripe_subscription_id": sub_id, "stripe_customer_id": "cus_x",
        "price_id": "price_x", "quantity": 1,
        "status": "active", "cancel_at_period_end": False,
    })


def test_cancel_at_period_end_sets_flag(db, stripe_stub):
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_mirror(sub_id))
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.cancel_subscription(tenant_id=TID, sub_id=sub_id, immediate=False),
    )
    assert row is not None
    assert row["cancel_at_period_end"] is True
    assert row["status"] == "active"  # still active until period end
    assert row["webhook_source"] == "app_cancel_period_end"
    assert stripe_stub["modify"][0]["cancel_at_period_end"] is True
    assert stripe_stub["delete"] == []


def test_cancel_immediate_deletes_subscription(db, stripe_stub):
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_mirror(sub_id))
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.cancel_subscription(tenant_id=TID, sub_id=sub_id, immediate=True),
    )
    assert row is not None
    assert row["status"] == "canceled"
    assert row.get("canceled_at")
    assert row["webhook_source"] == "app_cancel_immediate"
    assert stripe_stub["delete"] == [sub_id]
    assert stripe_stub["modify"] == []


def test_cancel_cross_tenant_returns_none(db, stripe_stub):
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    other_tid = f"tenSUBX-OTHER-{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_mirror(sub_id, tenant_id=other_tid))
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.cancel_subscription(tenant_id=TID, sub_id=sub_id, immediate=False),
    )
    assert row is None
    assert stripe_stub["modify"] == []
    assert stripe_stub["delete"] == []


def test_cancel_http_role_gate_rejects_technician(db):
    tok = _login("carlos@aquaterra.com")
    r = requests.delete(
        f"{BASE}/api/subscriptions/sub_stub_x",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 403


def test_cancel_http_rejects_invalid_mode(db):
    tok = _login("admin@aquaterra.com")
    r = requests.delete(
        f"{BASE}/api/subscriptions/sub_x?mode=whenever",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 400


def test_cancel_http_returns_404_on_unknown_sub_for_admin(db):
    tok = _login("admin@aquaterra.com")
    r = requests.delete(
        f"{BASE}/api/subscriptions/sub_does_not_exist_XYZ",
        headers={"Authorization": f"Bearer {tok}"},
        timeout=15,
    )
    assert r.status_code == 404
