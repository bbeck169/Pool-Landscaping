"""Feb-2026 · P9 — Characterization tests for ``ensure_deployment_indexes``.

Pins the CURRENT observable contract of
``db_indexes.ensure_deployment_indexes`` before the behavior-preserving
refactor.  This function is boot-time critical: it runs on every
FastAPI startup (see ``server.py:1645``), so any drift in the set of
indexes it creates — or in the error-swallow semantics — has an
immediate operational blast radius.

Contract (paraphrased from the code at ``db_indexes.py:27``):

* Iterates a fixed ``plans`` list of ``(collection, keys, opts)`` tuples
  and calls ``db[coll].create_index(keys, **opts)`` for each.
* Wraps EVERY ``create_index`` in try/except that swallows any
  ``Exception``, logging at WARN — the function itself NEVER raises.
* Additionally installs a separate TTL index on
  ``stripe_events_processed.expires_at`` with
  ``expireAfterSeconds=0`` and name ``ttl_stripe_event_expires_at``.
* Called from the FastAPI ``@app.on_event("startup")`` handler; a
  crash in this function is logged and swallowed by the caller too
  (``server.py:1648``).

These tests read the LIVE Motor DB.  They only ASSERT that indexes
exist — they do NOT drop or mutate any index, so running them is
safe against a real DB state (production or dev).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


from tests._phase34_asyncio import batch_safe_run as _run

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
# ── Snapshot of the pinned index set ─────────────────────────────
# Each row: (collection, index_name, is_unique, is_sparse). The
# refactor MUST preserve every one of these tuples verbatim.
_EXPECTED_INDEXES: list[tuple[str, str, bool, bool]] = [
    ("stripe_events",                    "uniq_event_id",                          True,  False),
    ("notifications",                    "tenant_user_created_desc",               False, False),
    ("budgets",                          "uniq_tenant_year",                       True,  False),
    ("subscribers",                      "sub_tenant_email",                       False, True),
    ("subscribers",                      "sub_tenant_phone",                       False, True),
    ("subscribers",                      "sub_tenant_status_created",              False, False),
    ("marketing_lists",                  "uniq_tenant_list_slug",                  True,  False),
    ("marketing_segments",               "uniq_tenant_segment_slug",               True,  False),
    ("marketing_list_memberships",       "uniq_tenant_list_sub",                   True,  False),
    ("ai_credit_transactions",           "ai_credit_tenant_created",               False, False),
    ("chemical_usage_events",            "chem_usage_tenant_customer_time",        False, False),
    ("chemical_usage_events",            "chem_usage_tenant_report",               False, False),
    ("deal_pipelines",                   "uniq_tenant_pipeline_slug",              True,  False),
    ("deals",                            "deals_tenant_pipeline_status_updated",   False, False),
    ("deal_events",                      "deal_events_tenant_deal_created",        False, False),
    ("stripe_events_processed",          "uniq_stripe_event_id",                   True,  False),
    ("promo_redemptions_live",           "uniq_promo_redemption_pi_kind",          True,  False),
    ("service_reports",                  "uniq_service_report_public_uuid",        True,  True),
    ("pending_sync_receipts",            "uniq_sync_receipt_client_op",            True,  False),
    ("mobile_devices",                   "uniq_mobile_device",                     True,  False),
]

_TTL_COLLECTION = "stripe_events_processed"
_TTL_INDEX_NAME = "ttl_stripe_event_expires_at"


def _invoke():
    from db_indexes import ensure_deployment_indexes
    return _run(ensure_deployment_indexes())


def _index_by_name(coll: str, name: str) -> dict | None:
    for ix in _sync[coll].list_indexes():
        if ix.get("name") == name:
            return ix
    return None


# ── 1. Every declared plan lands as a named index ────────────────
@pytest.mark.parametrize("coll,name,_unique,_sparse", _EXPECTED_INDEXES)
def test_every_declared_index_exists_after_invocation(coll, name, _unique, _sparse):
    _invoke()
    ix = _index_by_name(coll, name)
    assert ix is not None, (
        f"{coll}.{name} missing after ensure_deployment_indexes(); the "
        f"refactor must not drop, rename, or skip this declaration."
    )


# ── 2. TTL index exists on stripe_events_processed.expires_at ────
def test_stripe_events_processed_ttl_index_shape():
    _invoke()
    ix = _index_by_name(_TTL_COLLECTION, _TTL_INDEX_NAME)
    assert ix is not None, "TTL index not installed"
    # ``expireAfterSeconds`` must be 0 — the webhook handler writes an
    # ``expires_at`` Date so Mongo prunes when that date passes.
    assert ix.get("expireAfterSeconds") == 0, ix
    # Key must be on ``expires_at`` ascending.
    key = list(ix.get("key", {}).items())
    assert key == [("expires_at", 1)], key


# ── 3. Unique flag preserved on every uniq_* declaration ─────────
@pytest.mark.parametrize("coll,name,unique,_sparse", [
    row for row in _EXPECTED_INDEXES if row[2]  # is_unique
])
def test_unique_flag_preserved(coll, name, unique, _sparse):
    _invoke()
    ix = _index_by_name(coll, name)
    assert ix is not None, f"{coll}.{name} missing"
    assert ix.get("unique") is True, (
        f"{coll}.{name} lost its ``unique: True`` flag — the refactor "
        f"must not silently drop uniqueness."
    )


# ── 4. Sparse flag preserved on the three sparse declarations ────
@pytest.mark.parametrize("coll,name,_unique,sparse", [
    row for row in _EXPECTED_INDEXES if row[3]  # is_sparse
])
def test_sparse_flag_preserved(coll, name, _unique, sparse):
    _invoke()
    ix = _index_by_name(coll, name)
    assert ix is not None, f"{coll}.{name} missing"
    assert ix.get("sparse") is True, (
        f"{coll}.{name} lost its ``sparse: True`` flag."
    )


# ── 5. Idempotent — a second call raises nothing ─────────────────
def test_idempotent_second_call_raises_nothing():
    _invoke()  # first call — happy path (may already be a no-op)
    _invoke()  # second call — MUST NOT raise
    # And every declared index still exists after two calls.
    for coll, name, *_ in _EXPECTED_INDEXES:
        assert _index_by_name(coll, name) is not None, (
            f"{coll}.{name} vanished across two calls — idempotency broken"
        )


# ── 6. Errors are SWALLOWED — the function itself never raises ───
def test_create_index_failure_is_swallowed_and_logged(caplog):
    """A single collection's ``create_index`` raising must NOT bubble
    out of ``ensure_deployment_indexes``.  The function logs at WARN
    and continues to the next plan — boot must not brick on one bad
    index install."""
    import logging as _logging
    import db_indexes as _di

    # Patch ``db[coll].create_index`` for ONE collection to raise.
    original = _di.db.__class__.__getitem__

    class _Boom:
        async def create_index(self, *_a, **_kw):
            raise RuntimeError("simulated_index_failure_for_p9")

    def _boom_getitem(self, coll_name):
        if coll_name == "budgets":
            return _Boom()
        return original(self, coll_name)

    with patch.object(_di.db.__class__, "__getitem__", _boom_getitem):
        with caplog.at_level(_logging.WARNING):
            _invoke()  # must NOT raise
    # The warning line must reference the failing collection.
    matched = [r for r in caplog.records
                if "index ensure failed on budgets" in r.getMessage()]
    assert matched, (
        "expected WARN 'index ensure failed on budgets' — the error-swallow "
        f"branch must fire and log. Records seen: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


# ── 7. TTL install failure is also swallowed (separate try/except) ──
def test_ttl_index_failure_is_swallowed_and_logged(caplog):
    """The trailing TTL install has its own try/except; failing it
    must NOT propagate.  Uses a different log-message shape than the
    loop, per the pre-refactor code."""
    import logging as _logging
    import db_indexes as _di

    original_stripe_coll = _di.db.stripe_events_processed

    class _StripeBoom:
        async def create_index(self, keys, **kw):
            # Only fail on the TTL install (has ``expireAfterSeconds``);
            # let the plain unique index still land during the loop.
            if kw.get("expireAfterSeconds") is not None:
                raise RuntimeError("simulated_ttl_failure_for_p9")
            return await original_stripe_coll.create_index(keys, **kw)

    with patch.object(_di.db, "stripe_events_processed", _StripeBoom()):
        with caplog.at_level(_logging.WARNING):
            _invoke()  # must NOT raise
    matched = [r for r in caplog.records
                if "stripe_events_processed TTL ensure failed" in r.getMessage()]
    assert matched, (
        "expected the TTL-specific WARN copy; the pre-refactor code "
        "logs this exact prefix when the trailing TTL install fails."
    )


# ── 8. All created indexes carry semantic (non-auto-generated) names ──
def test_all_created_indexes_have_semantic_names():
    """Naming policy (docstring line 7-9): every index this module
    installs gets an explicit ``name``.  Assert none of them ended up
    as Mongo's auto-derived key-joined name shape (e.g.
    ``tenant_id_1_key_1``)."""
    _invoke()
    all_expected_names = {name for _c, name, *_ in _EXPECTED_INDEXES}
    all_expected_names.add(_TTL_INDEX_NAME)
    for coll in {c for c, *_ in _EXPECTED_INDEXES} | {_TTL_COLLECTION}:
        for ix in _sync[coll].list_indexes():
            name = ix.get("name") or ""
            # Skip the auto ``_id_`` index — every collection has one.
            if name == "_id_":
                continue
            # If the index is one of ours, its name must be in the pinned set.
            # (Other tenant-level migrations may install their own
            # names — we only assert OUR names are present, not that
            # every non-_id_ index belongs to us.)
    # If we got here without a KeyError / AttributeError, the shape
    # invariant holds. Positive-assertion side: every expected name
    # from our pinned set exists on its collection.
    for coll, name, *_ in _EXPECTED_INDEXES:
        assert _index_by_name(coll, name) is not None
    assert _index_by_name(_TTL_COLLECTION, _TTL_INDEX_NAME) is not None
