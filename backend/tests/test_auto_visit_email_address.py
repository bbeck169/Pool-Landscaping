"""Feb-2026 · Part 1 · Auto-visit-email address resolution.

Regression coverage for the visit-summary email address bug.
Before this fix ``render_email`` read ``job.address`` directly —
a text string copied at job-generation time.  After a customer
moves (or after the property is corrected post-hoc) the email
body kept showing the stale address.

The fix looks up the property in ``db.properties`` via the FK
ladder ``job.property_id`` → ``customer.primary_property_id`` →
text-fallback, and stamps the CURRENT composed address into the
email body.  This suite locks:

* ``property_id`` on the job → composed address wins over stale
  ``job.address``.
* Property edited AFTER the job was generated → email uses the
  edited (current) address.
* Missing ``property_id`` AND missing
  ``customer.primary_property_id`` → falls back to
  ``job.address`` + emits the structured warning.
* Soft-deleted property → falls back + warning.
* Cross-tenant lookup → returns None → falls back + warning
  (never leaks tenant B's property text into a tenant A email).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from services import auto_visit_email as ave


TENANT_A = "tenant-A-avE"
TENANT_B = "tenant-B-avE"


# ═══════════════════════════════════════════════════════════════════
# In-memory Mongo stub (motor-compatible enough for this suite).
# ═══════════════════════════════════════════════════════════════════
class _Coll:
    def __init__(self, rows: List[Dict[str, Any]] | None = None):
        self.rows: List[Dict[str, Any]] = list(rows or [])

    async def find_one(self, query: Dict[str, Any], projection=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in query.items()):
                return dict(r)
        return None

    async def update_one(self, filt, update):
        for r in self.rows:
            if all(r.get(k) == v for k, v in filt.items()):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        # Support dot-notation for nested fields —
                        # the real Motor driver does; our tests need
                        # to mirror that so they can edit
                        # ``address.line1`` in-place.
                        if "." in k:
                            head, *rest = k.split(".")
                            cur = r.setdefault(head, {})
                            for part in rest[:-1]:
                                cur = cur.setdefault(part, {})
                            cur[rest[-1]] = v
                        else:
                            r[k] = v
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()


class _DB:
    def __init__(self, properties=None, customers=None):
        self.properties = _Coll(properties)
        self.customers = _Coll(customers)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════
def _property(pid: str, tenant_id: str, line1: str, city: str,
              state: str, postal: str, **extra) -> Dict[str, Any]:
    doc = {
        "id": pid, "tenant_id": tenant_id,
        "address": {"line1": line1, "line2": None, "city": city,
                    "state": state, "postal_code": postal,
                    "country": "US"},
    }
    doc.update(extra)
    return doc


def _seed(monkeypatch, properties=None, customers=None) -> _DB:
    fake = _DB(properties=properties, customers=customers)
    monkeypatch.setattr(ave, "db", fake)
    return fake


def _tenant(tid: str = TENANT_A) -> Dict[str, Any]:
    return {"id": tid, "name": tid}


# ═══════════════════════════════════════════════════════════════════
# 1 · Happy path — property_id on job wins over stale job.address.
# ═══════════════════════════════════════════════════════════════════
def test_property_address_wins_over_stale_job_address(monkeypatch):
    _seed(monkeypatch, properties=[
        _property("p-1", TENANT_A, "3112 W Adobe Dam Rd",
                    "Phoenix", "AZ", "85027"),
    ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": "p-1",
        "address": "STALE 5207 West Bajada Road, Phoenix, AZ, 85083",
    }
    resolved = _run(ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "3112 W Adobe Dam Rd, Phoenix, AZ 85027"
    assert "Bajada" not in resolved  # stale text never wins
    assert "STALE" not in resolved


# ═══════════════════════════════════════════════════════════════════
# 2 · Property edited after job generation → email uses the CURRENT
# address, not whatever was denormalized onto the job.
# ═══════════════════════════════════════════════════════════════════
def test_property_edited_post_job_generation_uses_current(monkeypatch):
    fake = _seed(monkeypatch, properties=[
        _property("p-1", TENANT_A, "OLD line1",
                    "Phoenix", "AZ", "85027"),
    ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": "p-1",
        "address": "OLD line1, Phoenix, AZ, 85027",
    }
    # Simulate an admin editing the property AFTER the job doc was
    # written (recurring generator or ad-hoc PATCH).
    _run(fake.properties.update_one(
        {"id": "p-1"},
        {"$set": {"address.line1": "3112 W Adobe Dam Rd"}},
    ))
    resolved = _run(ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "3112 W Adobe Dam Rd, Phoenix, AZ 85027"


# ═══════════════════════════════════════════════════════════════════
# 3 · Missing property_id → warning + text fallback.
# ═══════════════════════════════════════════════════════════════════
def test_missing_property_id_warns_and_falls_back(monkeypatch, caplog):
    _seed(monkeypatch, properties=[], customers=[
        {"id": "c-1", "tenant_id": TENANT_A,
         "primary_property_id": None},
    ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": None,
        "address": "123 Fallback St, Phoenix, AZ, 85001",
    }
    with caplog.at_level(logging.WARNING, logger="server_api"):
        resolved = _run(
            ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "123 Fallback St, Phoenix, AZ, 85001"
    assert any(
        "auto_visit_email.property_unresolved" in rec.getMessage()
        and "reason=no_property_id" in rec.getMessage()
        for rec in caplog.records
    )


# ═══════════════════════════════════════════════════════════════════
# 4 · Soft-deleted property → warning + text fallback.
# ═══════════════════════════════════════════════════════════════════
def test_soft_deleted_property_warns_and_falls_back(monkeypatch, caplog):
    _seed(monkeypatch, properties=[
        _property("p-1", TENANT_A, "3112 W Adobe Dam Rd",
                    "Phoenix", "AZ", "85027",
                    deleted_at="2026-02-01T00:00:00Z"),
    ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": "p-1",
        "address": "FALLBACK 999 Old Road, Phoenix, AZ, 85099",
    }
    with caplog.at_level(logging.WARNING, logger="server_api"):
        resolved = _run(
            ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "FALLBACK 999 Old Road, Phoenix, AZ, 85099"
    assert any(
        "reason=property_soft_deleted" in rec.getMessage()
        for rec in caplog.records
    )


# ═══════════════════════════════════════════════════════════════════
# 5 · Cross-tenant lookup — tenant A's request must NOT leak
# tenant B's property.
# ═══════════════════════════════════════════════════════════════════
def test_cross_tenant_lookup_never_leaks(monkeypatch, caplog):
    # Property lives in tenant B.
    _seed(monkeypatch, properties=[
        _property("p-Bshared", TENANT_B, "SECRET B ADDRESS",
                    "Phoenix", "AZ", "85099"),
    ])
    # Tenant A's job carries the SAME property_id as tenant B's
    # (id collision / referrer forgery).
    job = {
        "id": "j-A", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": "p-Bshared",
        "address": "TENANT A fallback address",
    }
    with caplog.at_level(logging.WARNING, logger="server_api"):
        resolved = _run(
            ave._resolve_visit_email_address(_tenant(TENANT_A), job))
    # Tenant B's line1 MUST NOT appear.
    assert "SECRET" not in resolved
    assert resolved == "TENANT A fallback address"
    assert any(
        "reason=property_not_found" in rec.getMessage()
        for rec in caplog.records
    )


# ═══════════════════════════════════════════════════════════════════
# 6 · Rung 2 — customer.primary_property_id fallback when the job
# doesn't carry a property_id.
# ═══════════════════════════════════════════════════════════════════
def test_primary_property_id_rung_is_honored(monkeypatch):
    _seed(monkeypatch,
          properties=[
              _property("p-primary", TENANT_A, "3112 W Adobe Dam Rd",
                          "Phoenix", "AZ", "85027"),
          ],
          customers=[
              {"id": "c-1", "tenant_id": TENANT_A,
               "primary_property_id": "p-primary"},
          ])
    job = {
        "id": "j-1", "tenant_id": TENANT_A, "customer_id": "c-1",
        "property_id": None,
        "address": "STALE fallback",
    }
    resolved = _run(ave._resolve_visit_email_address(_tenant(), job))
    assert resolved == "3112 W Adobe Dam Rd, Phoenix, AZ 85027"
