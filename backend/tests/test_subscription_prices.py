"""Phase B4 · Feb-2026 — Subscription prices tests.

Verifies list_prices() returns flattened rows from the Stripe SDK
AND that a second call within the TTL is served from cache
(no extra Stripe API hit).
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
            {"id": "price_A", "unit_amount": 2999, "currency": "usd",
             "recurring": {"interval": "month"},
             "nickname": "Pro monthly",
             "product": {"id": "prod_A", "name": "Pool Pro"}},
            {"id": "price_B", "unit_amount": 29999, "currency": "usd",
             "recurring": {"interval": "year"},
             "nickname": "Pro yearly",
             "product": {"id": "prod_A", "name": "Pool Pro"}},
        ]}

    monkeypatch.setattr(sc._stripe.Price, "list", _fake_price_list)
    monkeypatch.setattr(sc, "_init_api_key", lambda: None)
    monkeypatch.setattr(sub_svc, "_init_api_key", lambda: None)
    return calls


def test_list_prices_flattens_stripe_response(price_stub):
    rows = asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    assert len(rows) == 2
    assert rows[0]["id"] == "price_A"
    assert rows[0]["product_id"] == "prod_A"
    assert rows[0]["product_name"] == "Pool Pro"
    assert rows[0]["unit_amount"] == 2999
    assert rows[0]["recurring"] == {"interval": "month"}


def test_list_prices_cache_hits_on_second_call(price_stub):
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    # Stripe was called exactly once even though we asked three times.
    assert len(price_stub["list"]) == 1


def test_list_prices_cache_invalidates_across_stripe_modes(price_stub, monkeypatch):
    """Prices cache is keyed on mode — switching modes forces a refetch."""
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    assert len(price_stub["list"]) == 1
    # Simulate mode flip by forcing the cache mode to a mismatch.
    sub_svc._prices_cache["mode"] = "other-mode"
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    assert len(price_stub["list"]) == 2


def test_list_prices_passes_active_and_expand_flags(price_stub):
    asyncio.get_event_loop().run_until_complete(sub_svc.list_prices())
    kw = price_stub["list"][0]
    assert kw["active"] is True
    assert kw["expand"] == ["data.product"]
    assert kw["limit"] == 100
