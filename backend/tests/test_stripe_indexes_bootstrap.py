"""Phase B3 · Feb-2026 — Stripe webhook hardening index bootstrap tests.

Verifies the migration writes every expected index to the four
target collections. Uses the shipped migration helper — a fresh
call with ``force=True`` re-runs the create passes even though the
sentinel is present, so re-runnable in CI.
"""
from __future__ import annotations

import asyncio
from typing import Set

import pytest

from services.migrations.stripe_webhook_hardening import (
    run_stripe_webhook_hardening_migration,
)
from services.payments import stripe_charge as sc


@pytest.fixture
def db():
    return sc.db


def _index_names(coll) -> Set[str]:
    async def _fetch():
        return {idx.get("name") or "" async for idx in coll.list_indexes()}
    return asyncio.get_event_loop().run_until_complete(_fetch())


def test_migration_runs_to_completion(db):
    res = asyncio.get_event_loop().run_until_complete(
        run_stripe_webhook_hardening_migration(force=True),
    )
    assert res["status"] == "ok"
    assert res["summary"]["errors"] == []


EXPECTED = {
    "stripe_webhook_events": {
        "stripe_webhook_events_event_id_unique",
        "stripe_webhook_events_status_idx",
    },
    "stripe_webhook_dead_letter": {
        "stripe_webhook_dead_letter_event_id_unique",
        "stripe_webhook_dead_letter_resolved_idx",
    },
    "payment_methods": {
        "payment_methods_tenant_customer_default_idx",
        "payment_methods_tenant_pm_unique",
    },
    "stripe_charges": {
        "stripe_charges_tenant_customer_created_idx",
        "stripe_charges_tenant_invoice_status_idx",
        "stripe_charges_pi_unique",
    },
}


def test_stripe_webhook_events_indexes_present(db):
    asyncio.get_event_loop().run_until_complete(
        run_stripe_webhook_hardening_migration(force=True),
    )
    names = _index_names(db.stripe_webhook_events)
    assert EXPECTED["stripe_webhook_events"].issubset(names)


def test_stripe_webhook_dead_letter_indexes_present(db):
    asyncio.get_event_loop().run_until_complete(
        run_stripe_webhook_hardening_migration(force=True),
    )
    names = _index_names(db.stripe_webhook_dead_letter)
    assert EXPECTED["stripe_webhook_dead_letter"].issubset(names)


def test_payment_methods_indexes_present(db):
    asyncio.get_event_loop().run_until_complete(
        run_stripe_webhook_hardening_migration(force=True),
    )
    names = _index_names(db.payment_methods)
    assert EXPECTED["payment_methods"].issubset(names)


def test_stripe_charges_indexes_present(db):
    asyncio.get_event_loop().run_until_complete(
        run_stripe_webhook_hardening_migration(force=True),
    )
    names = _index_names(db.stripe_charges)
    assert EXPECTED["stripe_charges"].issubset(names)


def test_sentinel_row_is_written_after_run(db):
    asyncio.get_event_loop().run_until_complete(
        run_stripe_webhook_hardening_migration(force=True),
    )
    row = asyncio.get_event_loop().run_until_complete(
        db.migrations.find_one({"id": "stripe_webhook_hardening_v1"}, {"_id": 0}),
    )
    assert row is not None
    assert row.get("completed_at")
    assert "summary" in row
