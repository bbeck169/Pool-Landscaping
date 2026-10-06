"""Phase B4 · Feb-2026 — Subscription create tests.

Uses direct service calls (with a monkey-patched Stripe SDK) for
the happy path + tenant isolation + idempotency assertions, and a
requests-based HTTP call for the role gate (verifies techs + customers
are 403'd before Stripe is touched).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest
import requests
from dotenv import dotenv_values

from tests._phase34_asyncio import batch_safe_run
from services.payments import stripe_charge as sc
from services.payments import stripe_subscription as sub_svc


BASE = os.environ.get("STRIPE_TEST_BASE") or "http://localhost:8001"
TID = f"tenSUBC-{uuid.uuid4().hex[:8]}"


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
    # STRIPE-TEST-ISOLATION · Feb-2026 — trigger the Phase-41.1d
    # Motor-client rebuild on the session-persistent loop BEFORE
    # handing ``sc.db`` to the test. After the rebuild, ``sc.db``
    # points at the fresh client bound to the persistent loop
    # (see tests/_phase34_asyncio._rebuild_motor_client_on_loop).
    import asyncio as _asyncio
    batch_safe_run(_asyncio.sleep(0))
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.customers.delete_many({"tenant_id": TID})
        await db.stripe_subscriptions.delete_many({"tenant_id": TID})
    batch_safe_run(_wipe())
    yield
    batch_safe_run(_wipe())


@pytest.fixture
def stripe_stub(monkeypatch):
    """Monkey-patch the Stripe SDK boundary — no live API calls."""
    calls: Dict[str, List[Dict[str, Any]]] = {
        "customer_create": [], "customer_modify": [],
        "sub_create": [],
    }

    def _fake_customer_create(**kw):
        calls["customer_create"].append(kw)
        return {"id": f"cus_stub_{uuid.uuid4().hex[:10]}"}

    def _fake_customer_modify(cid, **kw):
        calls["customer_modify"].append({"id": cid, **kw})
        return {"id": cid}

    def _fake_sub_create(**kw):
        calls["sub_create"].append(kw)
        return {
            "id": f"sub_stub_{uuid.uuid4().hex[:10]}",
            "status": "active",
            "current_period_start": 1700000000,
            "current_period_end": 1702592000,
            "cancel_at_period_end": bool(kw.get("cancel_at_period_end")),
            "canceled_at": None,
            "created": 1700000000,
        }

    monkeypatch.setattr(sc._stripe.Customer, "create", _fake_customer_create)
    monkeypatch.setattr(sc._stripe.Customer, "modify", _fake_customer_modify)
    monkeypatch.setattr(sc._stripe.Subscription, "create", _fake_sub_create)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)
    monkeypatch.setattr(sub_svc, "_init_api_key", lambda: None)
    return calls


async def _seed_customer(cid: str, tenant_id: str = TID,
                          stripe_customer_id: str | None = None) -> None:
    doc = {"id": cid, "tenant_id": tenant_id, "name": "Sub Test",
            "email": "sub-test@example.com"}
    if stripe_customer_id:
        doc["stripe_customer_id"] = stripe_customer_id
    await sc.db.customers.insert_one(doc)


def test_create_happy_path_creates_stripe_customer_and_mirror(db, stripe_stub):
    cid = f"crm-cust-{uuid.uuid4().hex[:8]}"
    batch_safe_run(_seed_customer(cid))
    row = batch_safe_run(
        sub_svc.create_subscription(
            tenant_id=TID, customer_id=cid, price_id="price_stub_1",
            quantity=2,
        ),
    )
    assert row["tenant_id"] == TID
    assert row["customer_id"] == cid
    assert row["price_id"] == "price_stub_1"
    assert row["quantity"] == 2
    assert row["status"] == "active"
    assert row["stripe_customer_id"].startswith("cus_stub_")
    assert row["stripe_subscription_id"].startswith("sub_stub_")
    assert row["webhook_source"] == "app_create"
    # Verify Stripe was called with the right metadata.
    kw = stripe_stub["sub_create"][0]
    assert kw["metadata"]["crm_tenant_id"] == TID
    assert kw["metadata"]["crm_customer_id"] == cid
    assert kw["items"] == [{"price": "price_stub_1", "quantity": 2}]
    assert "idempotency_key" in kw
    assert TID in kw["idempotency_key"] and cid in kw["idempotency_key"]


def test_create_reuses_existing_stripe_customer(db, stripe_stub):
    """When the CRM row already has a stripe_customer_id, don't
    create a fresh Stripe Customer."""
    cid = f"crm-cust-{uuid.uuid4().hex[:8]}"
    batch_safe_run(
        _seed_customer(cid, stripe_customer_id="cus_existing_ABC"),
    )
    row = batch_safe_run(
        sub_svc.create_subscription(
            tenant_id=TID, customer_id=cid, price_id="price_stub_1",
        ),
    )
    assert row["stripe_customer_id"] == "cus_existing_ABC"
    assert len(stripe_stub["customer_create"]) == 0
    assert len(stripe_stub["sub_create"]) == 1


def test_create_with_payment_method_sets_default_pm(db, stripe_stub):
    cid = f"crm-cust-{uuid.uuid4().hex[:8]}"
    batch_safe_run(
        _seed_customer(cid, stripe_customer_id="cus_pm_test"),
    )
    batch_safe_run(
        sub_svc.create_subscription(
            tenant_id=TID, customer_id=cid, price_id="price_x",
            payment_method_id="pm_xyz",
        ),
    )
    assert len(stripe_stub["customer_modify"]) == 1
    assert stripe_stub["customer_modify"][0]["invoice_settings"] == \
        {"default_payment_method": "pm_xyz"}


def test_create_rejects_missing_customer(db, stripe_stub):
    with pytest.raises(ValueError, match="customer_not_found"):
        batch_safe_run(
            sub_svc.create_subscription(
                tenant_id=TID, customer_id="does-not-exist",
                price_id="price_x",
            ),
        )


def test_create_tenant_isolation(db, stripe_stub):
    """A customer id belonging to tenant A cannot be subscribed
    against tenant B's context — the customer lookup filters by
    ``tenant_id`` so the wrong-tenant call raises customer_not_found."""
    cid = f"crm-cust-{uuid.uuid4().hex[:8]}"
    other_tid = f"tenSUBC-OTHER-{uuid.uuid4().hex[:8]}"
    batch_safe_run(
        _seed_customer(cid, tenant_id=other_tid),  # seeded on OTHER tenant
    )
    with pytest.raises(ValueError, match="customer_not_found"):
        batch_safe_run(
            sub_svc.create_subscription(
                tenant_id=TID, customer_id=cid,  # attempted from TID
                price_id="price_x",
            ),
        )


def test_create_role_gate_rejects_technician_via_http(db):
    tok = _login("carlos@aquaterra.com")
    r = requests.post(
        f"{BASE}/api/subscriptions",
        headers={"Authorization": f"Bearer {tok}"},
        json={"customer_id": "any", "price_id": "price_x"},
        timeout=15,
    )
    assert r.status_code == 403, r.text
    assert r.json().get("detail") == "subscription_write_forbidden"


def test_create_reserved_metadata_keys_are_not_overrideable(db, stripe_stub):
    """Caller-supplied metadata should not be able to spoof the
    tenant/customer identity of the resulting Stripe object."""
    cid = f"crm-cust-{uuid.uuid4().hex[:8]}"
    batch_safe_run(_seed_customer(cid))
    batch_safe_run(
        sub_svc.create_subscription(
            tenant_id=TID, customer_id=cid, price_id="price_x",
            metadata={"crm_tenant_id": "SPOOFED", "note": "hi"},
        ),
    )
    kw = stripe_stub["sub_create"][0]
    assert kw["metadata"]["crm_tenant_id"] == TID  # not spoofed
    assert kw["metadata"]["note"] == "hi"
