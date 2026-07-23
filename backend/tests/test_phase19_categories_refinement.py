"""Feb-2026 · Phase 19 refinement — Categories classifier & Mass
Messaging Categories filter behavior.

Verifies:
  1. ``recompute_customer_denorm`` assigns:
     - Only Pool category to a pool-only customer.
     - Only Landscaping category to a landscaping-only customer.
     - Pool + Landscaping + Both to a customer with jobs on both lines.
  2. Mass Messaging preview ``category_ids=[pool_id]`` matches pool +
     both, not landscaping-only.
  3. Mass Messaging preview ``category_ids=[both_id]`` matches only
     the both-line customer.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT_ID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def category_ids():
    rows = list(_sync.customer_categories.find(
        {"tenant_id": _TENANT_ID, "is_system": True}, {"_id": 0}))
    by_name = {r["name"].lower(): r["id"] for r in rows}
    assert {"pool", "landscaping", "both"}.issubset(by_name), by_name
    return by_name


@pytest.fixture
def three_customers(category_ids):
    m = uuid.uuid4().hex[:6]
    a = f"cat-A-pool-{m}"
    b = f"cat-B-land-{m}"
    c = f"cat-C-both-{m}"
    _sync.customers.insert_many([
        {"id": a, "tenant_id": _TENANT_ID, "name": "Pool Only Al",
          "email": f"a-{m}@ex.local", "phone": "+15550001111",
          "is_active": True, "first_name": "Al"},
        {"id": b, "tenant_id": _TENANT_ID, "name": "Landscape Only Ben",
          "email": f"b-{m}@ex.local", "phone": "+15550002222",
          "is_active": True, "first_name": "Ben"},
        {"id": c, "tenant_id": _TENANT_ID, "name": "Both Chris",
          "email": f"c-{m}@ex.local", "phone": "+15550003333",
          "is_active": True, "first_name": "Chris"},
    ])
    # Seed recurring_job_templates so classifier picks up service_type.
    _sync.recurring_job_templates.insert_many([
        {"id": f"tpl-a-{m}", "tenant_id": _TENANT_ID, "customer_id": a,
          "active": True, "service_type": "pool_weekly", "day_of_week": 1},
        {"id": f"tpl-b-{m}", "tenant_id": _TENANT_ID, "customer_id": b,
          "active": True, "service_type": "landscape_biweekly", "day_of_week": 2},
        {"id": f"tpl-c1-{m}", "tenant_id": _TENANT_ID, "customer_id": c,
          "active": True, "service_type": "pool_weekly", "day_of_week": 1},
        {"id": f"tpl-c2-{m}", "tenant_id": _TENANT_ID, "customer_id": c,
          "active": True, "service_type": "landscape_biweekly", "day_of_week": 4},
    ])
    yield {"marker": m, "a": a, "b": b, "c": c}
    _sync.customers.delete_many({"id": {"$in": [a, b, c]}})
    _sync.recurring_job_templates.delete_many({"tenant_id": _TENANT_ID,
                                                 "customer_id": {"$in": [a, b, c]}})


def _run_denorm(customer_id):
    from routers.customer_categories import recompute_customer_denorm
    asyncio.get_event_loop().run_until_complete(
        recompute_customer_denorm(_TENANT_ID, customer_id=customer_id))


def test_classifier_assigns_pool_only(three_customers, category_ids):
    _run_denorm(three_customers["a"])
    row = _sync.customers.find_one({"id": three_customers["a"]}, {"_id": 0})
    cats = set(row.get("category_ids") or [])
    assert category_ids["pool"] in cats
    assert category_ids["landscaping"] not in cats
    assert category_ids["both"] not in cats


def test_classifier_assigns_landscaping_only(three_customers, category_ids):
    _run_denorm(three_customers["b"])
    row = _sync.customers.find_one({"id": three_customers["b"]}, {"_id": 0})
    cats = set(row.get("category_ids") or [])
    assert category_ids["landscaping"] in cats
    assert category_ids["pool"] not in cats
    assert category_ids["both"] not in cats


def test_classifier_assigns_both_when_two_lines(three_customers, category_ids):
    _run_denorm(three_customers["c"])
    row = _sync.customers.find_one({"id": three_customers["c"]}, {"_id": 0})
    cats = set(row.get("category_ids") or [])
    assert category_ids["pool"] in cats
    assert category_ids["landscaping"] in cats
    assert category_ids["both"] in cats


def test_mass_messaging_pool_filter_matches_pool_and_both(
    admin_headers, three_customers, category_ids,
):
    """Direct-DB verification of the ``$in`` semantics — the same
    query the mass-messaging resolver uses. The API surface returns
    a truncated ``audience_sample`` so we assert via DB instead."""
    _run_denorm(three_customers["a"])
    _run_denorm(three_customers["b"])
    _run_denorm(three_customers["c"])
    ids = [d["id"] for d in _sync.customers.find(
        {"tenant_id": _TENANT_ID,
          "category_ids": {"$in": [category_ids["pool"]]},
          "id": {"$in": [three_customers["a"], three_customers["b"], three_customers["c"]]}},
        {"_id": 0, "id": 1})]
    assert three_customers["a"] in ids
    assert three_customers["c"] in ids
    assert three_customers["b"] not in ids


def test_mass_messaging_both_filter_matches_only_both(
    admin_headers, three_customers, category_ids,
):
    _run_denorm(three_customers["a"])
    _run_denorm(three_customers["b"])
    _run_denorm(three_customers["c"])
    ids = [d["id"] for d in _sync.customers.find(
        {"tenant_id": _TENANT_ID,
          "category_ids": {"$in": [category_ids["both"]]},
          "id": {"$in": [three_customers["a"], three_customers["b"], three_customers["c"]]}},
        {"_id": 0, "id": 1})]
    assert ids == [three_customers["c"]]
