"""TD-offline-bundle-tenant-cache · Phase 2 Lane D · Feb-2026 — regression.

Covers the per-``(tenant_id, tech_id)`` TTL cache + the decorator-
based invalidation sweep on job / quote mutation endpoints.

Scope:
    * Cache hit skips re-materialisation (no Mongo touches on 2nd call).
    * Cache expiry after 120 s.
    * Mutation on a job invalidates the cache for that tenant.
    * Mutation on a quote invalidates the cache for that tenant.
    * Different tenants do NOT share cache entries.
    * Response shape remains byte-identical (locks Lane A invariant).
    * ``invalidate`` is fire-and-forget: no exception bubbles out.

Pattern matches ``test_td_offline_bundle_perf_gather.py`` — unit-level
with a stubbed ``db`` so no live Mongo is needed.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from routers import mobile_sync as ms
from services import offline_bundle_cache as obc

# Re-use the fake DB layer from the Lane A regression so byte-shape
# locks stay in sync.
from tests.test_td_offline_bundle_perf_gather import (    # type: ignore
    _FakeDB, _USER, _TENANT, _EXPECTED_KEYS_IN_ORDER,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    obc._clear()
    yield
    obc._clear()


# ─── Cache basics ───────────────────────────────────────────────────────


def test_second_call_hits_cache_and_skips_mongo() -> None:
    """First call materialises the bundle; second call within the
    120 s window returns the cached payload WITHOUT touching the
    stubbed db collections.  We prove the no-touch by replacing the
    db with a sentinel that raises on access.
    """
    fake = _FakeDB(delay=0.0)
    with patch.object(ms, "db", fake):
        first = asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))

    class _ExplodingDB:
        """Any attribute access raises — proves no Mongo was touched."""
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(
                f"Second call hit MongoDB (accessed db.{name!r}) — "
                f"cache miss when a hit was expected.")

    with patch.object(ms, "db", _ExplodingDB()):
        second = asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))

    # Byte-identical payloads.
    assert first == second
    # Lane A byte-shape invariant still intact.
    assert list(second.keys()) == _EXPECTED_KEYS_IN_ORDER


def test_cache_expires_after_ttl() -> None:
    """When ``time.monotonic()`` advances past the entry's
    ``expires_at``, ``get`` returns ``None`` and pops the stale entry.
    """
    fake = _FakeDB(delay=0.0)
    with patch.object(ms, "db", fake):
        asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))
    # Confirm the cache has one entry.
    assert len(obc._snapshot()) == 1

    # Advance time past the 120 s TTL by monkey-patching
    # ``time.monotonic`` inside the module.
    original_monotonic = obc.time.monotonic
    try:
        obc.time.monotonic = lambda: original_monotonic() + obc.TTL_SECONDS + 1  # type: ignore[assignment]
        hit = obc.get(_TENANT["id"], _USER["technician_id"])
        assert hit is None, "expired entry must not return a payload"
    finally:
        obc.time.monotonic = original_monotonic    # type: ignore[assignment]

    # Expired entry was popped on expiry read.
    assert len(obc._snapshot()) == 0


# ─── Invalidation sweep ─────────────────────────────────────────────────


def test_invalidate_drops_only_target_tenant() -> None:
    """A call to ``invalidate("tenant-1")`` MUST clear every entry
    whose first key component is ``tenant-1`` and leave every other
    tenant's entries untouched.
    """
    # Prime two tenants, two techs on tenant-1.
    obc.put("tenant-1", "tech-A", {"marker": "1A"})
    obc.put("tenant-1", "tech-B", {"marker": "1B"})
    obc.put("tenant-2", "tech-X", {"marker": "2X"})
    assert len(obc._snapshot()) == 3

    dropped = obc.invalidate("tenant-1")
    assert dropped == 2
    snapshot = obc._snapshot()
    assert len(snapshot) == 1
    # Only the tenant-2 entry survives.
    assert ("tenant-2", "tech-X") in snapshot


def test_invalidator_decorator_fires_on_job_mutation() -> None:
    """A route-handler stamped with ``@invalidates_offline_bundle``
    MUST drop the tenant's cache after a successful call.  Exercises
    the decorator directly without plumbing a live FastAPI route.
    """
    @obc.invalidates_offline_bundle
    async def _fake_job_mutator(*, user: dict, tenant: dict) -> dict:
        return {"ok": True, "id": "job-99"}

    obc.put("tenant-1", "tech-A", {"marker": "pre-mutation"})
    assert len(obc._snapshot()) == 1

    result = asyncio.run(_fake_job_mutator(user=_USER, tenant=_TENANT))
    assert result == {"ok": True, "id": "job-99"}
    assert len(obc._snapshot()) == 0


def test_invalidator_decorator_fires_on_quote_mutation() -> None:
    """Same as the job case — the decorator is schema-agnostic; what
    matters is the ``tenant`` kwarg being present.
    """
    @obc.invalidates_offline_bundle
    async def _fake_quote_mutator(*, user: dict, tenant: dict) -> dict:
        return {"ok": True, "id": "quote-99"}

    obc.put("tenant-1", "tech-A", {"marker": "pre-mutation"})
    obc.put("tenant-1", "tech-B", {"marker": "pre-mutation"})
    assert len(obc._snapshot()) == 2

    asyncio.run(_fake_quote_mutator(user=_USER, tenant=_TENANT))
    assert len(obc._snapshot()) == 0


def test_invalidator_decorator_tenant_fallback_from_user() -> None:
    """``routers.invoice_edit.patch_invoice`` has no ``tenant`` kwarg
    (it derives tenant internally).  The decorator falls back to
    ``user.tenant_id`` so this surface still invalidates correctly.
    """
    @obc.invalidates_offline_bundle
    async def _fake_invoice_edit(*, user: dict) -> dict:
        return {"ok": True}

    obc.put("tenant-fallback", "tech-X", {"marker": "pre"})
    assert len(obc._snapshot()) == 1

    asyncio.run(_fake_invoice_edit(user={"id": "u-1", "tenant_id": "tenant-fallback"}))
    assert len(obc._snapshot()) == 0


def test_invalidator_decorator_swallows_mis_op_errors() -> None:
    """Fire-and-forget: a cache mis-op MUST NOT propagate out of the
    handler.  Simulate by making ``invalidate`` raise; the handler's
    return value should still pass through.
    """
    @obc.invalidates_offline_bundle
    async def _fake_handler(*, user: dict, tenant: dict) -> dict:
        return {"ok": True}

    original_invalidate = obc.invalidate

    def _raise(*a, **kw):
        raise RuntimeError("simulated invalidate failure")

    try:
        obc.invalidate = _raise    # type: ignore[assignment]
        result = asyncio.run(_fake_handler(user=_USER, tenant=_TENANT))
    finally:
        obc.invalidate = original_invalidate    # type: ignore[assignment]
    assert result == {"ok": True}


# ─── Tenant isolation ────────────────────────────────────────────────────


def test_different_tenants_do_not_share_cache_entries() -> None:
    """Running the handler against two different tenants MUST yield
    two independent cache entries that don't leak to each other.
    """
    fake1 = _FakeDB(delay=0.0)
    fake2 = _FakeDB(delay=0.0)
    # Make the two fake jobs collections return clearly-different data.
    fake2.jobs._rows = [{"id": "job-99", "customer_id": "cust-99",    # type: ignore[attr-defined]
                          "scheduled_date": "2026-02-15"}]
    fake2.customers._rows = [{"id": "cust-99", "name": "Second Customer",    # type: ignore[attr-defined]
                               "phone": "999", "address_line_1": "99 Elsewhere",
                               "updated_at": "2026-02-15T00:00:00Z"}]

    tenant_a = {"id": "tenant-A"}
    tenant_b = {"id": "tenant-B"}

    with patch.object(ms, "db", fake1):
        bundle_a = asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=tenant_a))
    with patch.object(ms, "db", fake2):
        bundle_b = asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=tenant_b))

    assert bundle_a["jobs"][0]["id"] == "job-1"
    assert bundle_b["jobs"][0]["id"] == "job-99"

    snapshot = obc._snapshot()
    assert ("tenant-A", _USER["technician_id"]) in snapshot
    assert ("tenant-B", _USER["technician_id"]) in snapshot

    # Invalidate ONLY tenant-A; tenant-B must survive.
    obc.invalidate("tenant-A")
    snapshot = obc._snapshot()
    assert ("tenant-A", _USER["technician_id"]) not in snapshot
    assert ("tenant-B", _USER["technician_id"]) in snapshot


# ─── Lane A byte-identity preservation ──────────────────────────────────


def test_lane_a_byte_identity_still_holds_through_cache() -> None:
    """A cached-return payload MUST preserve the dict insertion order
    locked in ``test_response_keys_byte_identical`` from Lane A.
    """
    fake = _FakeDB(delay=0.0)
    with patch.object(ms, "db", fake):
        out = asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))
    assert list(out.keys()) == _EXPECTED_KEYS_IN_ORDER
    # Cache-hit path returns the same dict object (reference-identical
    # or deep-equal depending on the implementation).  Confirm deep-
    # equal + same key order on a second call.
    class _ExplodingDB:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError("second call must hit cache")
    with patch.object(ms, "db", _ExplodingDB()):
        out2 = asyncio.run(ms.mobile_offline_bundle(
            tech_id="me", user=_USER, tenant=_TENANT))
    assert out == out2
    assert list(out2.keys()) == _EXPECTED_KEYS_IN_ORDER


# ─── Hook-sweep source-level audit ──────────────────────────────────────


def test_hook_sweep_stamps_primary_mutation_endpoints() -> None:
    """Lock the invalidation hook sweep at the source level so a
    future refactor can't silently drop one of the primary mutation
    endpoints from the sweep.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]

    jobs_src = (root / "routers/jobs.py").read_text(encoding="utf-8")
    quotes_src = (root / "routers/quotes.py").read_text(encoding="utf-8")
    invoice_edit_src = (
        root / "routers/invoice_edit.py").read_text(encoding="utf-8")

    # jobs.py — POST, PUT, DELETE, PATCH on /jobs or /jobs/{jid}.
    assert "@invalidates_offline_bundle\nasync def create_job(" in jobs_src
    assert "@invalidates_offline_bundle\nasync def update_job(" in jobs_src
    assert "@invalidates_offline_bundle\nasync def delete_job(" in jobs_src
    assert ("@invalidates_offline_bundle\nasync def patch_job_edit_window("
            in jobs_src)

    # quotes.py — POST, PUT status, DELETE.
    assert "@invalidates_offline_bundle\nasync def create_quote(" in quotes_src
    assert ("@invalidates_offline_bundle\nasync def update_quote_status("
            in quotes_src)
    assert "@invalidates_offline_bundle\nasync def delete_quote(" in quotes_src

    # invoice_edit.py — PATCH /quotes/{invoice_id}.  The ``patch_invoice``
    # handler intentionally does NOT use the ``@invalidates_offline_bundle``
    # decorator — the decorator conflicts with FastAPI's resolution of the
    # ``body: InvoiceEditBody = Body(...)`` ForwardRef at openapi schema
    # build time (``PydanticUserError``).  See
    # ``TD-invalidates-offline-bundle-forwardref-safe`` for the root-cause
    # fix that would benefit the 7 other decorated handlers too.  Until
    # then, the handler calls the inline
    # ``_invalidate_offline_bundle_for_user`` helper (mirrors the
    # decorator's runtime semantics 1:1) at each success-return site.
    assert "_invalidate_offline_bundle_for_user(user)" in invoice_edit_src
    assert "def _invalidate_offline_bundle_for_user(" in invoice_edit_src

    # Every router that uses the decorator must import it.
    assert ("from services.offline_bundle_cache import "
            "invalidates_offline_bundle") in jobs_src
    assert ("from services.offline_bundle_cache import "
            "invalidates_offline_bundle") in quotes_src
    # invoice_edit.py imports the ``invalidate`` function directly (used
    # by the inline helper); it does NOT import the decorator.
    assert ("from services.offline_bundle_cache import invalidate "
            "as _invalidate_offline_bundle_cache") in invoice_edit_src
