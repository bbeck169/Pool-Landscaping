"""Feb-2026 · Customer merge · rewire ``properties.customer_id``.

Regression coverage for the "duplicate-property under duplicate-
customer" gap.  Before this commit ``_rewire_related`` walked
``jobs``, ``payments``, ``service_reports``, ``leads``, and
``quotes`` (invoices + estimates) — but silently skipped the
``properties`` collection.  A merge of customer B into customer A
left B's properties orphaned, still pointing at the merged-away B.

This suite locks the new ``properties`` bucket at:
  1. dry-run counts include the ``properties`` bucket.
  2. real run rewires ``customer_id`` on every property owned by
     any secondary.
  3. cross-tenant properties (same secondary id, different
     tenant) never get rewritten.
  4. no-op when the secondary has zero properties.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from services.customer_merge import executor as cm


TENANT_A = "tenant-A-cm"
TENANT_B = "tenant-B-cm"


# ═══════════════════════════════════════════════════════════════════
# Minimal Motor-shaped in-memory stub.
# ═══════════════════════════════════════════════════════════════════
def _matches(row: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if isinstance(v, dict) and "$in" in v:
            if row.get(k) not in v["$in"]:
                return False
            continue
        if row.get(k) != v:
            return False
    return True


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _matches(r, query))

    async def update_many(self, query, update):
        n = 0
        setter = update.get("$set") or {}
        for r in self.rows:
            if _matches(r, query):
                r.update(setter)
                n += 1
        return type("R", (), {"modified_count": n})()


class _DB:
    _SUPPORTED = (
        "jobs", "payments", "service_reports", "leads",
        "properties", "quotes", "estimates",
    )

    def __init__(self, **kw):
        for name in self._SUPPORTED:
            setattr(self, name, _Coll(kw.get(name)))

    def __getitem__(self, name):
        return getattr(self, name)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════
def _prop(pid: str, tenant_id: str, customer_id: str) -> Dict[str, Any]:
    return {
        "id": pid, "tenant_id": tenant_id, "customer_id": customer_id,
        "label": "Main",
        "address": {"line1": f"{pid} Test St", "city": "Phoenix",
                    "state": "AZ", "postal_code": "85001"},
    }


def _seed(monkeypatch, **kw) -> _DB:
    fake = _DB(**kw)
    monkeypatch.setattr(cm, "db", fake)
    return fake


# ═══════════════════════════════════════════════════════════════════
# 1 · Rewire runs — property.customer_id gets flipped to primary.
# ═══════════════════════════════════════════════════════════════════
def test_rewire_related_rewires_properties(monkeypatch):
    fake = _seed(monkeypatch, properties=[
        _prop("p-1", TENANT_A, "cust-secondary"),
        _prop("p-2", TENANT_A, "cust-secondary"),
        # Untouched — belongs to an unrelated customer.
        _prop("p-3", TENANT_A, "cust-unrelated"),
    ])
    counts = _run(cm._rewire_related(
        tenant_id=TENANT_A,
        primary_id="cust-primary",
        secondary_ids=["cust-secondary"],
        dry_run=False,
    ))
    assert counts["properties"] == 2
    owners = {r["id"]: r["customer_id"] for r in fake.properties.rows}
    assert owners["p-1"] == "cust-primary"
    assert owners["p-2"] == "cust-primary"
    # Bystander untouched.
    assert owners["p-3"] == "cust-unrelated"


# ═══════════════════════════════════════════════════════════════════
# 2 · Dry-run reports the count WITHOUT rewriting anything.
# ═══════════════════════════════════════════════════════════════════
def test_rewire_related_dry_run_counts_only(monkeypatch):
    fake = _seed(monkeypatch, properties=[
        _prop("p-1", TENANT_A, "cust-secondary"),
        _prop("p-2", TENANT_A, "cust-secondary"),
    ])
    counts = _run(cm._rewire_related(
        tenant_id=TENANT_A,
        primary_id="cust-primary",
        secondary_ids=["cust-secondary"],
        dry_run=True,
    ))
    assert counts["properties"] == 2
    for r in fake.properties.rows:
        # Nothing written.
        assert r["customer_id"] == "cust-secondary"


# ═══════════════════════════════════════════════════════════════════
# 3 · Cross-tenant property with the same secondary id is untouched.
# ═══════════════════════════════════════════════════════════════════
def test_rewire_related_cross_tenant_property_is_safe(monkeypatch):
    """Tenant B happens to have a property owned by a customer id
    that COLLIDES with tenant A's secondary id.  The rewire must
    never cross tenants — B's property row stays intact."""
    fake = _seed(monkeypatch, properties=[
        _prop("p-A", TENANT_A, "cust-secondary"),
        _prop("p-B", TENANT_B, "cust-secondary"),
    ])
    _run(cm._rewire_related(
        tenant_id=TENANT_A,
        primary_id="cust-primary",
        secondary_ids=["cust-secondary"],
        dry_run=False,
    ))
    owners = {r["id"]: (r["tenant_id"], r["customer_id"])
              for r in fake.properties.rows}
    assert owners["p-A"] == (TENANT_A, "cust-primary")
    # Tenant B row: NEVER touched, still points at secondary.
    assert owners["p-B"] == (TENANT_B, "cust-secondary")


# ═══════════════════════════════════════════════════════════════════
# 4 · No-op when the secondary has zero properties.
# ═══════════════════════════════════════════════════════════════════
def test_rewire_related_no_properties_is_noop(monkeypatch):
    _seed(monkeypatch, properties=[
        _prop("p-x", TENANT_A, "cust-unrelated"),
    ])
    counts = _run(cm._rewire_related(
        tenant_id=TENANT_A,
        primary_id="cust-primary",
        secondary_ids=["cust-secondary"],
        dry_run=False,
    ))
    assert counts["properties"] == 0


# ═══════════════════════════════════════════════════════════════════
# 5 · Empty secondary list → all buckets zero, ``properties`` too.
# ═══════════════════════════════════════════════════════════════════
def test_rewire_related_empty_secondary_ids_is_noop(monkeypatch):
    _seed(monkeypatch, properties=[
        _prop("p-A", TENANT_A, "cust-secondary"),
    ])
    counts = _run(cm._rewire_related(
        tenant_id=TENANT_A,
        primary_id="cust-primary",
        secondary_ids=[],
        dry_run=False,
    ))
    assert counts["properties"] == 0
    # And the pre-existing buckets are also zero — sanity check
    # the empty-secondary short-circuit still works.
    for k in ("jobs", "payments", "service_reports", "leads"):
        assert counts[k] == 0
