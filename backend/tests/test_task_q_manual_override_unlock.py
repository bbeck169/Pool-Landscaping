"""Task Q · Feb-2026 — Manual-override unlock ops verification.

Preview ops override for tenant feature entitlements is a
DIRECT-DB path (``backend/scripts/ops_unlock_tenant_features.py``)
that intentionally NEVER touches Stripe. These 4 tests lock the
contract:

  1. ``has_feature`` returns True for each of the 4 keys once a
     ``manual_override`` row exists (the ``billing_status``
     branch inside ``is_entitlement_active`` grants access
     identically to ``active``).
  2. The layered ``ai_analytics_effective_gate`` returns
     ``allowed=True`` once BOTH the entitlement row AND
     ``settings.ai.analytics_enabled`` are set. Regression
     guard on the AND-gate.
  3. Stripe-path isolation guard — monkeypatch the ``stripe``
     module in ``sys.modules`` so ANY attribute access raises,
     then run ``has_feature`` for each of the 4 keys. If the
     manual-override read path is truly Stripe-free, none of
     the calls should raise.
  4. Idempotency — running the ops-script seed function twice
     yields identical row counts AND identical ``enabled_at``
     timestamps on already-enabled rows (short-circuit
     contract, matches ``seed_seo_heatmap_entitlement.py``
     shape).

Tests use an ephemeral test tenant id (uuid-generated per
module) so they never touch the real preview tenant. The
target tenant validated in Task Q Step 3 live-verify is
``affdfbfa-88b9-4baa-ae45-2ef78531b6e4`` — those rows persist
between test runs and are validated by hand.
"""
from __future__ import annotations

import importlib
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


# ── Env bootstrap ──────────────────────────────────────────────
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

# Task Q unlocks these 4 features on a preview tenant.
TARGET_FEATURES = ("zillow_data", "seo_heatmap", "ai_analytics", "ai_copilot")


# ── Fixtures ───────────────────────────────────────────────────
@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def ephemeral_tenant_id(dbc) -> Iterator[str]:
    """One-shot ephemeral tenant so tests never touch the real
    preview tenant (``affdfbfa-88b9-4baa-ae45-2ef78531b6e4``).
    Teardown deletes every collection this suite could touch."""
    tid = f"TEST-task-q-{uuid.uuid4().hex[:12]}"
    dbc.tenants.insert_one({
        "id": tid,
        "name": f"Task-Q ephemeral tenant {tid}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "settings": {"ai": {"kb_uploads_enabled": True}},
    })
    yield tid
    dbc.tenants.delete_many({"id": tid})
    dbc.feature_entitlements.delete_many({"tenant_id": tid})


@pytest.fixture(scope="module")
def _script():
    """Import the ops script module directly so tests can call
    its pure functions (``_upsert_entitlement`` /
    ``_set_analytics_enabled``) without re-implementing them."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    mod = importlib.import_module("ops_unlock_tenant_features")
    return mod


@pytest.fixture()
def _seeded_tenant(dbc, ephemeral_tenant_id, _script) -> str:
    """Run the ops-script upserts against the ephemeral tenant
    at test-time — a clean pre-image for the per-test asserts.
    Re-idempotent across tests (later tests re-invoke on
    already-enabled rows → no-op)."""
    for key in TARGET_FEATURES:
        _script._upsert_entitlement(
            dbc,
            tenant_id=ephemeral_tenant_id,
            feature_key=key,
            reason="Task Q pytest",
        )
    _script._set_analytics_enabled(dbc, tenant_id=ephemeral_tenant_id)
    return ephemeral_tenant_id


# ── Tests ──────────────────────────────────────────────────────
@pytest.mark.anyio
async def test_has_feature_true_for_all_four_manual_override_keys(_seeded_tenant):
    """Task Q · Case 1 — each of the 4 manual_override rows
    grants access via ``has_feature``. This is the read-side
    contract the router-level ``require_feature`` gates depend
    on. If this fails, the gates 402 the tenant even though
    the DB row is present."""
    from services.entitlements.check import has_feature

    adb = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    for key in TARGET_FEATURES:
        got = await has_feature(_seeded_tenant, key, db=adb)
        assert got is True, (
            f"has_feature({key!r}) returned {got!r} — expected True. "
            f"The manual_override branch inside is_entitlement_active "
            f"should grant access identically to 'active'."
        )


@pytest.mark.anyio
async def test_ai_analytics_effective_gate_allowed_after_upsert(_seeded_tenant):
    """Task Q · Case 2 — the layered ``ai_analytics_effective_gate``
    returns allowed=True only when BOTH:
      * ``settings.ai.analytics_enabled=True`` (org toggle)
      * ``has_feature('ai_analytics')=True`` (entitlement)
    The ops script sets both — regression guard on the AND-gate."""
    from services.entitlements.check import ai_analytics_effective_gate

    adb = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    gate = await ai_analytics_effective_gate(_seeded_tenant, db=adb)
    assert gate["allowed"] is True, (
        f"ai_analytics_effective_gate returned {gate!r} — expected "
        f"allowed=True after ops-script set both layers."
    )
    assert gate["org_toggle_state"] is True, (
        f"org_toggle_state expected True (settings.ai.analytics_enabled "
        f"was $set by _set_analytics_enabled)."
    )


@pytest.mark.anyio
async def test_manual_override_read_path_never_touches_stripe(_seeded_tenant, monkeypatch):
    """Task Q · Case 3 — Stripe-path isolation guard.

    Monkeypatch the ``stripe`` module in ``sys.modules`` so ANY
    attribute access raises. Then call ``has_feature`` for each
    of the 4 keys. If the manual_override read path is truly
    Stripe-free (which it MUST be — the entitlement check only
    reads ``feature_entitlements`` and ``tenants.settings``),
    none of the calls should raise.

    A regression that lazily imports the ``stripe`` SDK inside
    the entitlement resolution path — even for observability —
    would fail this test loudly."""
    from services.entitlements.check import has_feature

    class _StripePoison:
        """Raises on ANY attribute access — catches both
        ``import stripe`` + ``stripe.<anything>`` code paths."""
        def __getattr__(self, name: str):
            raise RuntimeError(
                f"Task-Q guard: entitlement read path touched "
                f"stripe.{name} — refusing (this must never happen "
                f"for manual_override reads)"
            )

    monkeypatch.setitem(sys.modules, "stripe", _StripePoison())

    adb = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    for key in TARGET_FEATURES:
        # If this raises, the guard trips → test fails with the
        # underlying RuntimeError, surfacing the exact path that
        # touched Stripe.
        got = await has_feature(_seeded_tenant, key, db=adb)
        assert got is True, (
            f"has_feature({key!r}) returned {got!r} under the "
            f"Stripe-poison — expected True (Stripe-free path)."
        )


def test_script_idempotent_across_two_runs(dbc, ephemeral_tenant_id, _script):
    """Task Q · Case 4 — running the ops-script seed function
    twice yields:
      * identical row counts (4 rows).
      * identical ``enabled_at`` timestamps on already-enabled
        rows (short-circuit contract — no re-stamping).

    Matches the ``seed_seo_heatmap_entitlement.py`` idempotency
    shape."""
    # First run — fresh state (delete any prior rows for
    # deterministic first-run inserts).
    dbc.feature_entitlements.delete_many({"tenant_id": ephemeral_tenant_id})
    for key in TARGET_FEATURES:
        _script._upsert_entitlement(
            dbc,
            tenant_id=ephemeral_tenant_id,
            feature_key=key,
            reason="Task Q idempotency test — run 1",
        )
    first = {
        r["feature_key"]: r
        for r in dbc.feature_entitlements.find({"tenant_id": ephemeral_tenant_id})
    }
    assert set(first.keys()) == set(TARGET_FEATURES), (
        f"Run 1 produced {sorted(first)} — expected {sorted(TARGET_FEATURES)}"
    )
    first_enabled_ats = {k: r["enabled_at"] for k, r in first.items()}

    # Second run — every key should short-circuit as
    # "already-enabled" and leave ``enabled_at`` frozen.
    for key in TARGET_FEATURES:
        action = _script._upsert_entitlement(
            dbc,
            tenant_id=ephemeral_tenant_id,
            feature_key=key,
            reason="Task Q idempotency test — run 2 (should no-op)",
        )
        assert action == "already-enabled", (
            f"Run 2 for {key!r} action={action!r} — expected "
            f"'already-enabled' (idempotency short-circuit)."
        )

    second = {
        r["feature_key"]: r
        for r in dbc.feature_entitlements.find({"tenant_id": ephemeral_tenant_id})
    }
    assert len(second) == 4, (
        f"Run 2 row count = {len(second)} — expected 4 "
        f"(no duplicate inserts)"
    )
    for key in TARGET_FEATURES:
        assert second[key]["enabled_at"] == first_enabled_ats[key], (
            f"enabled_at drifted for {key!r} between runs — "
            f"pre={first_enabled_ats[key]!r} post={second[key]['enabled_at']!r}. "
            f"The already-enabled short-circuit must preserve the "
            f"original timestamp."
        )


@pytest.fixture(scope="module")
def anyio_backend():
    """Force pytest-anyio to use asyncio (matches every other
    async fixture in this repo)."""
    return "asyncio"
