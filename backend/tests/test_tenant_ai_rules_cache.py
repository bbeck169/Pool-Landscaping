"""MTH-A · Feb-2026 — Cache contract.

Locks:

  * A fresh resolve fills the cache; the second call is served
    from cache and carries ``cached=True``.
  * TTL is 30 s — expiring the entry triggers a re-read.
  * Any tenant-scoped save invalidates the tenant's entry.
  * A platform save invalidates EVERY tenant entry.
  * ``use_cache=False`` bypasses the cache without side effects.
"""
from __future__ import annotations

import time

import pytest

from services.tenant_ai_rules import cache, store
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant
from tests._mth_a_helpers import FakeDB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(store, "db", fake, raising=False)
    cache.invalidate_all()
    return fake


def _actor():
    return {"id": "u1", "email": "a@t1"}


def test_second_read_is_cached(fake_db):
    first = run(resolve_rules_for_tenant("t1"))
    assert first["cached"] is False
    second = run(resolve_rules_for_tenant("t1"))
    assert second["cached"] is True
    assert first["rules"] == second["rules"]


def test_use_cache_false_bypasses_cache(fake_db):
    run(resolve_rules_for_tenant("t1"))
    fresh = run(resolve_rules_for_tenant("t1", use_cache=False))
    assert fresh["cached"] is False


def test_ttl_expires_after_30s(fake_db, monkeypatch):
    run(resolve_rules_for_tenant("t1"))
    # Fast-forward the cache's clock by mutating the timestamp.
    snap = cache._debug_snapshot()                              # noqa: SLF001
    for k in snap:
        cache._CACHE[k]["ts"] -= 31                             # noqa: SLF001
    reread = run(resolve_rules_for_tenant("t1"))
    assert reread["cached"] is False


def test_save_invalidates_that_tenant_only(fake_db):
    run(resolve_rules_for_tenant("t1"))
    run(resolve_rules_for_tenant("t2"))
    assert cache.size() == 2
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "formal", "custom_directive": ""},
        actor=_actor(), reason="tone-switch-formal-brand",
    ))
    assert cache.size() == 1
    # T2 was NOT invalidated.
    reread2 = run(resolve_rules_for_tenant("t2"))
    assert reread2["cached"] is True


def test_master_switch_invalidates_tenant_cache(fake_db):
    run(resolve_rules_for_tenant("t1"))
    assert cache.size() == 1
    run(store.save_master_switch(
        "t1", True, actor=_actor(),
        reason="going-live-with-ai-please",
    ))
    assert cache.size() == 0


def test_revert_invalidates_tenant_cache(fake_db):
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "formal", "custom_directive": ""},
        actor=_actor(),
        reason="switching-tone-to-formal-corp",
    ))
    run(resolve_rules_for_tenant("t1"))
    assert cache.size() == 1
    run(store.revert_to_revision(
        "t1", 1, actor=_actor(),
        reason="revert-to-first-revision-t1",
    ))
    assert cache.size() == 0


def test_platform_save_wipes_all_tenants(fake_db):
    run(resolve_rules_for_tenant("t1"))
    run(resolve_rules_for_tenant("t2"))
    run(resolve_rules_for_tenant("t3"))
    assert cache.size() == 3
    run(store.save_platform_category(
        category="escalation_rules",
        value=[{"keyword": "cancel", "is_regex": False,
                 "target_role": "admin", "sla_minutes": 10,
                 "notify_channel": "email"}],
        actor=_actor(),
        reason="platform-esc-rules-cancel-add",
    ))
    assert cache.size() == 0


def test_cache_returns_deep_copies(fake_db):
    """A caller mutating the returned dict must NOT poison the
    cached entry."""
    first = run(resolve_rules_for_tenant("t1"))
    first["rules"]["tone_voice"]["style"] = "MUTATED"
    second = run(resolve_rules_for_tenant("t1"))
    assert second["rules"]["tone_voice"]["style"] == "friendly"
