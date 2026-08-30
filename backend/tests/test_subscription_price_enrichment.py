"""Phase B4 follow-up · Feb-2026 — price enrichment tests.

Covers:
  1. ``_extract_price_meta`` pulls all 5 fields from an expanded
     Stripe.Subscription payload.
  2. ``_extract_price_meta`` returns a partial dict when product
     wasn't expanded (fallback path used by the webhook handler).
  3. ``format_plan_label`` renders the canonical formats + edge
     cases (yearly / weekly / every-3-months / missing name /
     zero-cents / non-USD currency).
  4. ``create_subscription`` populates the 5 enriched fields on
     the mirror row AND stamps ``formatted_plan_label``.
  5. ``update_subscription`` refreshes enriched fields when price
     changes.
  6. ``list_subscriptions`` stamps ``formatted_plan_label`` on
     every row it returns.
  7. Backfill script populates missing rows + sentinel prevents
     a second run.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List

import pytest

from services.payments import stripe_charge as sc
from services.payments import stripe_subscription as sub_svc
from services.migrations.stripe_subscriptions_price_enrichment import (
    run_stripe_subscriptions_price_enrichment,
)


TID = f"tenSUBE-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def db():
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.customers.delete_many({"tenant_id": TID})
        await db.stripe_subscriptions.delete_many({"tenant_id": TID})
        await db.migrations.delete_many(
            {"id": "stripe_subscriptions_price_enrichment_v1"},
        )
    asyncio.get_event_loop().run_until_complete(_wipe())
    yield
    asyncio.get_event_loop().run_until_complete(_wipe())


# ── Pure-function tests ──────────────────────────────────────────
def test_extract_price_meta_from_expanded_payload():
    sub = {
        "items": {"data": [{
            "price": {
                "id": "price_A", "unit_amount": 2999, "currency": "usd",
                "recurring": {"interval": "month", "interval_count": 1},
                "product": {"id": "prod_A", "name": "Pool Pro"},
            },
        }]},
    }
    meta = sub_svc._extract_price_meta(sub)
    assert meta == {
        "price_id": "price_A",
        "price_product_name": "Pool Pro",
        "price_amount_cents": 2999,
        "price_currency": "usd",
        "price_interval": "month",
        "price_interval_count": 1,
    }


def test_extract_price_meta_partial_when_product_not_expanded():
    sub = {
        "items": {"data": [{
            "price": {
                "id": "price_A", "unit_amount": 2999, "currency": "usd",
                "recurring": {"interval": "year", "interval_count": 1},
                "product": "prod_A",  # id only — webhook payload case
            },
        }]},
    }
    meta = sub_svc._extract_price_meta(sub)
    assert meta["price_id"] == "price_A"
    assert meta["price_product_name"] is None  # cannot resolve without retrieve
    assert meta["price_interval"] == "year"


def test_format_plan_label_monthly_usd():
    row = {"price_product_name": "Pool Pro", "price_amount_cents": 2999,
             "price_currency": "usd", "price_interval": "month",
             "price_interval_count": 1}
    assert sub_svc.format_plan_label(row) == "Pool Pro — $29.99/month"


def test_format_plan_label_yearly_dollar_only():
    row = {"price_product_name": "Landscape Yearly", "price_amount_cents": 29900,
             "price_currency": "usd", "price_interval": "year",
             "price_interval_count": 1}
    # $299.00 drops the trailing .00
    assert sub_svc.format_plan_label(row) == "Landscape Yearly — $299/year"


def test_format_plan_label_every_three_months():
    row = {"price_product_name": "Quarterly Service", "price_amount_cents": 7500,
             "price_currency": "usd", "price_interval": "month",
             "price_interval_count": 3}
    assert sub_svc.format_plan_label(row) == "Quarterly Service — $75 every 3 months"


def test_format_plan_label_missing_product_name_falls_back():
    row = {"price_amount_cents": 100, "price_currency": "usd",
             "price_interval": "month", "price_interval_count": 1}
    assert sub_svc.format_plan_label(row) == "Custom plan — $1/month"


def test_format_plan_label_non_usd_currency():
    row = {"price_product_name": "EU Basic", "price_amount_cents": 999,
             "price_currency": "eur", "price_interval": "month",
             "price_interval_count": 1}
    assert sub_svc.format_plan_label(row) == "EU Basic — $9.99 EUR/month"


def test_format_plan_label_missing_amount_returns_name_only():
    row = {"price_product_name": "Legacy Plan"}
    assert sub_svc.format_plan_label(row) == "Legacy Plan"


# ── Service-layer tests ──────────────────────────────────────────
@pytest.fixture
def stripe_stub(monkeypatch):
    calls: Dict[str, List[Dict[str, Any]]] = {
        "customer_create": [], "customer_modify": [],
        "sub_create": [], "sub_modify": [], "sub_retrieve": [],
        "price_retrieve": [],
    }

    def _fake_customer_create(**kw):
        calls["customer_create"].append(kw)
        return {"id": f"cus_stub_{uuid.uuid4().hex[:10]}"}

    def _fake_customer_modify(cid, **kw):
        calls["customer_modify"].append({"id": cid, **kw})
        return {"id": cid}

    def _fake_sub_create(**kw):
        calls["sub_create"].append(kw)
        # Return an EXPANDED subscription (product inline).
        return {
            "id": f"sub_stub_{uuid.uuid4().hex[:10]}",
            "status": "active",
            "current_period_start": 1700000000,
            "current_period_end": 1702592000,
            "cancel_at_period_end": bool(kw.get("cancel_at_period_end")),
            "canceled_at": None,
            "created": 1700000000,
            "items": {"data": [{
                "id": "si_stub",
                "price": {
                    "id": kw["items"][0]["price"],
                    "unit_amount": 2999, "currency": "usd",
                    "recurring": {"interval": "month", "interval_count": 1},
                    "product": {"id": "prod_stub", "name": "Pool Pro"},
                },
            }]},
        }

    def _fake_sub_retrieve(sid, **kw):
        calls["sub_retrieve"].append({"id": sid, **kw})
        return {
            "id": sid,
            "items": {"data": [{
                "id": "si_stub_item",
                "price": {"id": "price_old", "unit_amount": 999,
                          "currency": "usd",
                          "recurring": {"interval": "month", "interval_count": 1},
                          "product": {"id": "prod_stub", "name": "Old Plan"}},
            }]},
            "status": "active",
        }

    def _fake_sub_modify(sid, **kw):
        calls["sub_modify"].append({"id": sid, **kw})
        # Reflect whatever was patched.
        item = ((kw.get("items") or [{}])[0]) if kw.get("items") else {}
        new_price = item.get("price") or "price_new"
        return {
            "id": sid,
            "status": "active",
            "current_period_start": 1700000000,
            "current_period_end": 1702592000,
            "cancel_at_period_end": bool(kw.get("cancel_at_period_end")),
            "canceled_at": None,
            "created": 1700000000,
            "items": {"data": [{
                "id": "si_stub_item",
                "price": {
                    "id": new_price,
                    "unit_amount": 4999, "currency": "usd",
                    "recurring": {"interval": "month", "interval_count": 1},
                    "product": {"id": "prod_stub_new", "name": "Pool Pro Plus"},
                },
            }]},
        }

    def _fake_price_retrieve(pid, **kw):
        calls["price_retrieve"].append({"id": pid, **kw})
        return {
            "id": pid, "unit_amount": 12500, "currency": "usd",
            "recurring": {"interval": "week", "interval_count": 1},
            "product": {"id": "prod_weekly", "name": "Weekly Service"},
        }

    monkeypatch.setattr(sc._stripe.Customer, "create", _fake_customer_create)
    monkeypatch.setattr(sc._stripe.Customer, "modify", _fake_customer_modify)
    monkeypatch.setattr(sc._stripe.Subscription, "create", _fake_sub_create)
    monkeypatch.setattr(sc._stripe.Subscription, "retrieve", _fake_sub_retrieve)
    monkeypatch.setattr(sc._stripe.Subscription, "modify", _fake_sub_modify)
    monkeypatch.setattr(sc._stripe.Price, "retrieve", _fake_price_retrieve)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)
    monkeypatch.setattr(sub_svc, "_init_api_key", lambda: None)
    return calls


async def _seed_customer(cid: str) -> None:
    await sc.db.customers.insert_one({
        "id": cid, "tenant_id": TID, "name": "Enrich Test",
        "email": "enrich-test@example.com",
    })


def test_create_populates_enriched_fields_and_label(db, stripe_stub):
    cid = f"crm-cust-{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(_seed_customer(cid))
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.create_subscription(
            tenant_id=TID, customer_id=cid, price_id="price_pro", quantity=1,
        ),
    )
    assert row["price_product_name"] == "Pool Pro"
    assert row["price_amount_cents"] == 2999
    assert row["price_currency"] == "usd"
    assert row["price_interval"] == "month"
    assert row["price_interval_count"] == 1
    assert row["formatted_plan_label"] == "Pool Pro — $29.99/month"
    # Stripe.Subscription.create was called with the expand param.
    assert stripe_stub["sub_create"][0]["expand"] == ["items.data.price.product"]


def test_update_refreshes_enriched_fields_when_price_changes(db, stripe_stub):
    # Seed a mirror row with the OLD enrichment.
    sub_id = f"sub_stub_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(
        sc.db.stripe_subscriptions.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": TID, "customer_id": "cust-x",
            "stripe_subscription_id": sub_id, "stripe_customer_id": "cus_x",
            "price_id": "price_old", "quantity": 1, "status": "active",
            "price_product_name": "Pool Pro", "price_amount_cents": 2999,
            "price_currency": "usd", "price_interval": "month",
            "price_interval_count": 1,
        }),
    )
    row = asyncio.get_event_loop().run_until_complete(
        sub_svc.update_subscription(
            tenant_id=TID, sub_id=sub_id, price_id="price_new",
        ),
    )
    assert row["price_id"] == "price_new"
    assert row["price_product_name"] == "Pool Pro Plus"
    assert row["price_amount_cents"] == 4999
    assert row["formatted_plan_label"] == "Pool Pro Plus — $49.99/month"


def test_list_subscriptions_stamps_formatted_plan_label(db, stripe_stub):
    asyncio.get_event_loop().run_until_complete(
        sc.db.stripe_subscriptions.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": TID, "customer_id": "cust-x",
            "stripe_subscription_id": f"sub_ll_{uuid.uuid4().hex[:6]}",
            "stripe_customer_id": "cus_x",
            "price_id": "price_x", "quantity": 1, "status": "active",
            "price_product_name": "Pool Pro", "price_amount_cents": 2999,
            "price_currency": "usd", "price_interval": "month",
            "price_interval_count": 1,
        }),
    )
    res = asyncio.get_event_loop().run_until_complete(
        sub_svc.list_subscriptions(tenant_id=TID),
    )
    assert res["total"] == 1
    assert res["rows"][0]["formatted_plan_label"] == "Pool Pro — $29.99/month"


def test_list_subscriptions_fallback_label_when_fields_missing(db, stripe_stub):
    asyncio.get_event_loop().run_until_complete(
        sc.db.stripe_subscriptions.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": TID, "customer_id": "cust-x",
            "stripe_subscription_id": f"sub_ll2_{uuid.uuid4().hex[:6]}",
            "stripe_customer_id": "cus_x",
            "price_id": "price_missing", "quantity": 1, "status": "active",
            # No enriched fields.
        }),
    )
    res = asyncio.get_event_loop().run_until_complete(
        sub_svc.list_subscriptions(tenant_id=TID),
    )
    # Row still gets a label — "Custom plan" fallback.
    assert res["rows"][0]["formatted_plan_label"] == "Custom plan"


def test_backfill_migration_populates_missing_rows_and_writes_sentinel(db, stripe_stub):
    sub_id = f"sub_bf_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(
        sc.db.stripe_subscriptions.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": TID, "customer_id": "cust-x",
            "stripe_subscription_id": sub_id, "stripe_customer_id": "cus_x",
            "price_id": "price_wk", "quantity": 1, "status": "active",
            # NO enriched fields — the backfill should populate them.
        }),
    )
    res = asyncio.get_event_loop().run_until_complete(
        run_stripe_subscriptions_price_enrichment(force=True),
    )
    assert res["status"] == "ok"
    assert res["summary"]["enriched"] >= 1
    row = asyncio.get_event_loop().run_until_complete(
        sc.db.stripe_subscriptions.find_one({"stripe_subscription_id": sub_id}, {"_id": 0}),
    )
    assert row["price_product_name"] == "Weekly Service"
    assert row["price_interval"] == "week"
    # Sentinel was written.
    sentinel = asyncio.get_event_loop().run_until_complete(
        sc.db.migrations.find_one(
            {"id": "stripe_subscriptions_price_enrichment_v1"},
            {"_id": 0},
        ),
    )
    assert sentinel is not None
    assert sentinel["summary"]["enriched"] >= 1


def test_backfill_sentinel_prevents_second_run(db, stripe_stub):
    # First run writes sentinel.
    asyncio.get_event_loop().run_until_complete(
        run_stripe_subscriptions_price_enrichment(force=True),
    )
    # Add a fresh un-enriched row after the sentinel.
    sub_id = f"sub_bf2_{uuid.uuid4().hex[:8]}"
    asyncio.get_event_loop().run_until_complete(
        sc.db.stripe_subscriptions.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": TID, "customer_id": "cust-x",
            "stripe_subscription_id": sub_id, "stripe_customer_id": "cus_x",
            "price_id": "price_wk", "quantity": 1, "status": "active",
        }),
    )
    # Second run (non-force) skips.
    res = asyncio.get_event_loop().run_until_complete(
        run_stripe_subscriptions_price_enrichment(),
    )
    assert res["status"] == "skipped"
    assert res["reason"] == "sentinel_present"
    # Row remains un-enriched.
    row = asyncio.get_event_loop().run_until_complete(
        sc.db.stripe_subscriptions.find_one({"stripe_subscription_id": sub_id}, {"_id": 0}),
    )
    assert row.get("price_product_name") is None
