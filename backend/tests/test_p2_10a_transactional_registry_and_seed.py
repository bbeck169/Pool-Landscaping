"""P2 #10a · Feb-2026 — Transactional registry + seed migration
regression suite.

Covers:
  1. ``TRANSACTIONAL_SLUGS`` enumeration pin — the exact 11 slugs,
     alphabetically ordered. Guards against silent slug additions
     breaking the admin UI.
  2. ``REGISTRY`` completeness — every enumerated slug has a
     ``channel``, ``required_tags`` (list), ``description``, and the
     ``required_tags`` list is non-empty for every slug.
  3. ``get_slug`` + ``all_slugs`` helper contract.
  4. Seed migration · per-tenant · 3 MVP slug inserts on a clean
     tenant.
  5. Seed migration · per-tenant · idempotency — second run on the
     same tenant inserts nothing.
  6. Seed migration · all-tenants · boot sentinel.

Harness — fake ``db`` on the ``config`` module via monkeypatch of
the attribute refs (same pattern as Phase 34 async stubs).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Registry pin tests ──────────────────────────────────────────

def test_transactional_slugs_enumeration_pin():
    """Pin the exact slug list. Any addition / removal must be a
    deliberate, test-visible change."""
    from services.transactional_templates_registry import TRANSACTIONAL_SLUGS
    assert TRANSACTIONAL_SLUGS == sorted(TRANSACTIONAL_SLUGS), (
        "TRANSACTIONAL_SLUGS must stay alphabetical for grep stability"
    )
    assert TRANSACTIONAL_SLUGS == [
        "completion_followup_sms",
        "estimate_reminder_email",
        "invoice_past_due_email",
        "lead_conversion_welcome_email",
        "lead_conversion_welcome_sms",
        "password_reset_email",
        "portal_chat_admin_notify_sms",
        "portal_invite_email",
        "quote_decline_admin_email",
        "quote_decline_admin_sms",
        "welcome_on_first_accept_email",
    ]


def test_registry_completeness_per_slug():
    from services.transactional_templates_registry import (
        TRANSACTIONAL_SLUGS, REGISTRY,
    )
    for slug in TRANSACTIONAL_SLUGS:
        entry = REGISTRY.get(slug)
        assert entry is not None, f"REGISTRY missing slug: {slug}"
        assert entry["channel"] in ("email", "sms"), (
            f"{slug}: channel must be email or sms, got {entry.get('channel')}"
        )
        assert isinstance(entry.get("required_tags"), list), (
            f"{slug}: required_tags must be a list"
        )
        assert len(entry["required_tags"]) > 0, (
            f"{slug}: required_tags must be non-empty — every "
            "transactional template needs at least one tag that the "
            "fail-closed validator can enforce"
        )
        assert isinstance(entry.get("optional_tags", []), list)
        assert isinstance(entry.get("description"), str) and entry["description"]


def test_get_slug_and_all_slugs_helpers():
    from services.transactional_templates_registry import (
        get_slug, all_slugs, TRANSACTIONAL_SLUGS,
    )
    # Known slug
    e = get_slug("welcome_on_first_accept_email")
    assert e is not None and e["channel"] == "email"
    # Unknown slug / empty / None → None
    assert get_slug("not_a_real_slug") is None
    assert get_slug("") is None
    assert get_slug(None) is None  # type: ignore[arg-type]
    # all_slugs returns full set with ``code`` injected, alphabetical
    rows = all_slugs()
    assert [r["code"] for r in rows] == TRANSACTIONAL_SLUGS
    assert all("required_tags" in r for r in rows)


# ─── Seed migration stubs ────────────────────────────────────────

class _CollectionStub:
    def __init__(self):
        self._docs: List[Dict[str, Any]] = []

    async def find_one(self, flt, projection=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in flt.items()):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self._docs.append(dict(doc))
        return None

    def find(self, flt=None, projection=None):
        docs = self._docs
        class _Cursor:
            def __aiter__(self_inner):
                async def _gen():
                    for d in docs:
                        yield dict(d)
                return _gen()
        return _Cursor()


class _FakeDB:
    def __init__(self):
        self.marketing_templates = _CollectionStub()
        self.tenants = _CollectionStub()
        self.migrations = _CollectionStub()


def _patched_seed_run(fn_name: str, *args):
    """Invoke the seed-migration module with ``config.db`` + the
    module-level ``db`` ref swapped to a fresh ``_FakeDB``. Returns
    ``(result, fake_db)``."""
    import importlib
    import config
    orig = config.db
    fake = _FakeDB()
    try:
        config.db = fake
        # Reload so the module-level ``from config import db``
        # re-binds to the fake.
        mod = importlib.import_module(
            "services.migrations.seed_transactional_templates_v1"
        )
        importlib.reload(mod)
        fn = getattr(mod, fn_name)
        result = _run(fn(*args))
    finally:
        config.db = orig
    return result, fake


# ─── Case 4 · per-tenant · clean seed ────────────────────────────

def test_seed_transactional_templates_for_tenant_clean():
    result, fake = _patched_seed_run(
        "seed_transactional_templates_for_tenant", "t-clean",
    )
    assert result["tenant_id"] == "t-clean"
    # All 3 MVP slugs inserted on a clean tenant.
    assert sorted(result["inserted"]) == sorted([
        "welcome_on_first_accept_email",
        "quote_decline_admin_email",
        "quote_decline_admin_sms",
    ])
    assert result["skipped"] == []
    # Rows carry the discriminator ``code`` + ``system: true``.
    for row in fake.marketing_templates._docs:
        assert row["code"] in {s["code"] for s in _get_mvp_seeds()}
        assert row["system"] is True
        assert row["active"] is True
        assert row["tenant_id"] == "t-clean"


# ─── Case 5 · per-tenant · idempotency ───────────────────────────

def test_seed_transactional_templates_for_tenant_idempotent():
    import importlib
    import config
    orig = config.db
    fake = _FakeDB()
    try:
        config.db = fake
        mod = importlib.import_module(
            "services.migrations.seed_transactional_templates_v1"
        )
        importlib.reload(mod)
        # First run — all 3 inserted.
        r1 = _run(mod.seed_transactional_templates_for_tenant("t-idem"))
        assert len(r1["inserted"]) == 3
        assert len(r1["skipped"]) == 0
        # Second run — all 3 skipped, zero new inserts.
        r2 = _run(mod.seed_transactional_templates_for_tenant("t-idem"))
        assert len(r2["inserted"]) == 0
        assert len(r2["skipped"]) == 3
        # Collection size unchanged (still exactly 3 rows).
        assert len(fake.marketing_templates._docs) == 3
    finally:
        config.db = orig


# ─── Case 6 · all-tenants · boot sentinel ─────────────────────────

def test_seed_all_tenants_boot_sentinel_fires_once():
    import importlib
    import config
    orig = config.db
    fake = _FakeDB()
    # Seed 2 active tenants into the fake.
    _run(fake.tenants.insert_one({"id": "t-A", "active": True}))
    _run(fake.tenants.insert_one({"id": "t-B", "active": True}))
    try:
        config.db = fake
        mod = importlib.import_module(
            "services.migrations.seed_transactional_templates_v1"
        )
        importlib.reload(mod)
        # First run.
        r1 = _run(mod.seed_transactional_templates_all_tenants())
        assert r1.get("skipped") is not True
        assert r1["tenants_processed"] == 2
        assert r1["total_inserted"] == 6, (
            "2 tenants × 3 slugs each = 6 inserts on first run"
        )
        # Sentinel stamped.
        s = _run(fake.migrations.find_one({"id": r1["sentinel_id"]}))
        assert s is not None
        # Second run — sentinel short-circuits with ``skipped: True``.
        r2 = _run(mod.seed_transactional_templates_all_tenants())
        assert r2.get("skipped") is True
        assert r2["reason"] == "sentinel_already_stamped"
        # No new rows inserted on second call.
        assert len(fake.marketing_templates._docs) == 6
    finally:
        config.db = orig


# Helper for Case 4.
def _get_mvp_seeds():
    import importlib
    mod = importlib.import_module(
        "services.migrations.seed_transactional_templates_v1"
    )
    return mod._MVP_SEEDS
