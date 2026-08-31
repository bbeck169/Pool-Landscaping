"""F4 · Feb-2026 — regression: two auto-enqueued rows for the SAME
tenant must not collide on the ``tenant_source_unique`` index.

Discovered during backend testing_agent iteration_24: the original
enqueue helper set ``source_checkin_id=None`` while the unique index
on ``(tenant_id, source_checkin_id)`` was NOT sparse — so the SECOND
auto row per tenant hit E11000 and was silently dropped. Fix:
derive a unique-per-job token ``auto:{job_id}``.

This test would have caught the bug because it seeds the fake
collection with a prior null-slot row (mimicking a legacy demo row)
and then asserts two subsequent auto-enqueues both succeed.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from services import public_checkin_enqueue as svc


class _FakeColl:
    """A minimal duplicate-key aware Mongo double.

    We simulate the effect of ``createIndex(..., unique=True)`` on
    ``(tenant_id, source_checkin_id)`` by refusing inserts that
    would collide on that tuple.
    """
    def __init__(self, rows=None):
        self._rows: List[Dict[str, Any]] = list(rows or [])

    async def find_one(self, q, projection=None):
        for r in self._rows:
            if all(r.get(k) == v for k, v in q.items()):
                return dict(r)
        return None

    async def insert_one(self, doc):
        # Enforce the unique index.
        for r in self._rows:
            if (r.get("tenant_id") == doc.get("tenant_id")
                    and r.get("source_checkin_id") == doc.get("source_checkin_id")):
                # Mimic pymongo's DuplicateKeyError string surface.
                raise RuntimeError(
                    "E11000 duplicate key error: tenant_source_unique"
                )
        self._rows.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()


class _FakeDb:
    def __init__(self, tenants, customers, public_checkins, audit_logs=None):
        self.tenants = _FakeColl(tenants)
        self.customers = _FakeColl(customers)
        self.public_checkins = public_checkins
        self.audit_logs = _FakeColl(audit_logs or [])


def _job(job_id: str, tenant_id="t-1", customer_id="c-1") -> Dict[str, Any]:
    return {
        "id": job_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "service_type": "Weekly Cleaning",
        "service_category": "pool_service",
        "completed_at": "2026-02-15T12:00:00+00:00",
    }


def test_two_auto_enqueues_for_same_tenant_do_not_collide(monkeypatch):
    tenant_id = "t-1"
    # Pre-populate a legacy null-slot row to simulate the bug
    # environment the fix must survive.
    checkins = _FakeColl([
        {
            "id": "legacy-null-slot",
            "tenant_id": tenant_id,
            "source_checkin_id": None,   # legacy row from the buggy build
            "source_job_id": "legacy-job",
            "source": "auto",
            "state": "pending_review",
        },
    ])
    fake = _FakeDb(
        tenants=[{"id": tenant_id, "settings": {}}],
        customers=[
            {"id": "c-1", "tenant_id": tenant_id,
             "latitude": 33.7, "longitude": -112.3,
             "address_city": "Peoria", "address_state": "AZ"},
        ],
        public_checkins=checkins,
    )
    monkeypatch.setattr(svc, "db", fake)

    result_a = asyncio.get_event_loop().run_until_complete(
        svc.enqueue_public_checkin_for_completed_job(_job("job-A"))
    )
    result_b = asyncio.get_event_loop().run_until_complete(
        svc.enqueue_public_checkin_for_completed_job(_job("job-B"))
    )

    assert result_a["enqueued"] is True, result_a
    assert result_b["enqueued"] is True, result_b

    # source_checkin_id must be prefixed and unique per job.
    inserted = [r for r in checkins._rows if r.get("source") == "auto"
                 and r.get("id") != "legacy-null-slot"]
    assert len(inserted) == 2
    ids = {r["source_checkin_id"] for r in inserted}
    assert ids == {"auto:job-A", "auto:job-B"}


def test_source_checkin_id_uses_auto_job_id_prefix(monkeypatch):
    """The derived token must be a stable ``auto:<job_id>`` string so
    external observers can distinguish auto from tech rows at the
    index level."""
    tenant_id = "t-2"
    checkins = _FakeColl([])
    fake = _FakeDb(
        tenants=[{"id": tenant_id, "settings": {}}],
        customers=[
            {"id": "c-1", "tenant_id": tenant_id,
             "latitude": 33.7, "longitude": -112.3},
        ],
        public_checkins=checkins,
    )
    monkeypatch.setattr(svc, "db", fake)

    asyncio.get_event_loop().run_until_complete(
        svc.enqueue_public_checkin_for_completed_job(_job("job-X", tenant_id=tenant_id))
    )
    inserted = checkins._rows[-1]
    assert inserted["source_checkin_id"] == "auto:job-X"
    assert inserted["source_job_id"] == "job-X"
    assert inserted["source"] == "auto"


def test_replayed_completion_returns_idempotency_short_circuit(monkeypatch):
    """When the SAME job completes twice, the pre-flight
    ``source_job_id`` check must still return ``already_enqueued`` —
    the fix must not accidentally bypass idempotency for real
    duplicates."""
    tenant_id = "t-3"
    checkins = _FakeColl([
        {
            "id": "existing",
            "tenant_id": tenant_id,
            "source_checkin_id": "auto:job-Z",
            "source_job_id": "job-Z",
            "source": "auto",
            "state": "pending_review",
        },
    ])
    fake = _FakeDb(
        tenants=[{"id": tenant_id, "settings": {}}],
        customers=[
            {"id": "c-1", "tenant_id": tenant_id,
             "latitude": 33.7, "longitude": -112.3},
        ],
        public_checkins=checkins,
    )
    monkeypatch.setattr(svc, "db", fake)

    result = asyncio.get_event_loop().run_until_complete(
        svc.enqueue_public_checkin_for_completed_job(_job("job-Z", tenant_id=tenant_id))
    )
    assert result["enqueued"] is False
    assert result["reason"] == "already_enqueued"
    assert result["public_checkin_id"] == "existing"
    # Still only 1 row.
    assert len([r for r in checkins._rows if r["tenant_id"] == tenant_id]) == 1
