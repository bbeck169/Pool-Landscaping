"""Phase B4 · Feb-2026 — Subscription prices tests.

Verifies list_prices() returns flattened rows from the Stripe SDK
AND that a second call within the TTL is served from cache
(no extra Stripe API hit).

Follow-up (Feb-2026): also verifies the response is filtered to
recurring / active-product prices and sorted by
product_name → interval → unit_amount.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from services.payments import stripe_charge as sc
from services.payments import stripe_subscription as sub_svc


@pytest.fixture(autouse=True)
def _reset_cache():
    sub_svc.invalidate_prices_cache()
    yield
    sub_svc.invalidate_prices_cache()


@pytest.fixture
def price_stub(monkeypatch):
    calls: Dict[str, List[Dict[str, Any]]] = {"list": []}

    def _fake_price_list(**kw):
        calls["list"].append(kw)
        return {"data": [
            {"id": "price_A", "type": "recurring",
             "unit_amount": 2999, "currency": "usd",
             "recurring": {"interval": "month"},
             "nickname": "Pro monthly",
             "product": {"id": "prod_A", "name": "Pool Pro", "active": True}},
            {"id": "price_B", "type": "recurring",
             "unit_amount": 29999, "currency": "usd",
             "recurring": {"interval": "year"},
             "nickname": "Pro yearly",
             "product": {"id": "prod_A", "name": "Pool Pro", "active": True}},
        ]}

    monkeypatch.setattr(sc._stripe.Price, "list", _fake_price_list)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)
    monkeypatch.setattr(sub_svc, "_init_api_key", lambda: None)
    return calls


def test_list_prices_flattens_stripe_response(price_stub):
    rows = asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    assert len(rows) == 2
    # Sort order: month < year (both Pool Pro).
    assert rows[0]["id"] == "price_A"
    assert rows[0]["product_id"] == "prod_A"
    assert rows[0]["product_name"] == "Pool Pro"
    assert rows[0]["unit_amount"] == 2999
    assert rows[0]["recurring"] == {"interval": "month"}


def test_list_prices_cache_hits_on_second_call(price_stub):
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    assert len(price_stub["list"]) == 1


def test_list_prices_cache_invalidates_across_stripe_modes(price_stub, monkeypatch):
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    assert len(price_stub["list"]) == 1
    sub_svc._prices_cache["mode"] = "other-mode"
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    assert len(price_stub["list"]) == 2


def test_list_prices_passes_active_and_expand_flags(price_stub):
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    kw = price_stub["list"][0]
    assert kw["active"] is True
    assert kw["expand"] == ["data.product"]
    assert kw["limit"] == 100


# ── Follow-up · filter + sort semantics ─────────────────────────
@pytest.fixture
def mixed_price_stub(monkeypatch):
    """Stripe response with one-time + archived-product + a mix
    of intervals and product names to exercise filter + sort."""
    def _fake_price_list(**_kw):
        return {"data": [
            {"id": "price_onetime", "type": "one_time",
             "unit_amount": 5000, "currency": "usd", "recurring": None,
             "product": {"id": "prod_X", "name": "Setup Fee", "active": True}},
            {"id": "price_archived", "type": "recurring",
             "unit_amount": 999, "currency": "usd",
             "recurring": {"interval": "month"},
             "product": {"id": "prod_Y", "name": "Retired Plan", "active": False}},
            {"id": "price_zed_wk", "type": "recurring",
             "unit_amount": 4900, "currency": "usd",
             "recurring": {"interval": "week"},
             "product": {"id": "prod_Z", "name": "Zed Weekly", "active": True}},
            {"id": "price_alpha_yr", "type": "recurring",
             "unit_amount": 9900, "currency": "usd",
             "recurring": {"interval": "year"},
             "product": {"id": "prod_A", "name": "Alpha", "active": True}},
            {"id": "price_alpha_mo", "type": "recurring",
             "unit_amount": 999, "currency": "usd",
             "recurring": {"interval": "month"},
             "product": {"id": "prod_A", "name": "Alpha", "active": True}},
            {"id": "price_alpha_mo_tier2", "type": "recurring",
             "unit_amount": 1999, "currency": "usd",
             "recurring": {"interval": "month"},
             "product": {"id": "prod_A", "name": "Alpha", "active": True}},
        ]}
    monkeypatch.setattr(sc._stripe.Price, "list", _fake_price_list)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)
    monkeypatch.setattr(sub_svc, "_init_api_key", lambda: None)


def test_list_prices_filters_out_one_time_prices(mixed_price_stub):
    rows = asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    ids = [r["id"] for r in rows]
    assert "price_onetime" not in ids


def test_list_prices_filters_out_archived_product_prices(mixed_price_stub):
    rows = asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    ids = [r["id"] for r in rows]
    assert "price_archived" not in ids


def test_list_prices_sorts_by_product_then_interval_then_amount(mixed_price_stub):
    rows = asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    ids = [r["id"] for r in rows]
    # 1. Alpha Monthly ($9.99) → 2. Alpha Monthly tier 2 ($19.99)
    # → 3. Alpha Yearly ($99) → 4. Zed Weekly ($49)
    assert ids == [
        "price_alpha_mo",
        "price_alpha_mo_tier2",
        "price_alpha_yr",
        "price_zed_wk",
    ]
