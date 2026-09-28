"""MTH-A · Feb-2026 — Lazy-init contract for ``get_tenant_rules``.

Covers the on-first-read insert:

  * A fresh tenant with no existing row → single doc inserted,
    ``lazy_initialized_from_platform_defaults=True``, provenance
    logger emits ``tenant_ai_rules.lazy_init: tenant_id=<X>``.
  * Subsequent read does NOT insert a second row.
  * ``lazy_init=False`` returns ``None`` when no row exists — used
    by ops paths that need to know whether the tenant is
    initialized.
"""
from __future__ import annotations

import logging

import pytest

from services.tenant_ai_rules import cache, store
from tests._mth_a_helpers import FakeDB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(store, "db", fake, raising=False)
    cache.invalidate_all()
    return fake


def test_first_read_lazy_inserts_defaults(fake_db, caplog):
    caplog.set_level(logging.INFO)
    assert fake_db.tenant_ai_rules.rows == []
    doc = run(store.get_tenant_rules("t1"))
    assert doc is not None
    assert doc["tenant_id"] == "t1"
    assert doc["lazy_initialized_from_platform_defaults"] is True
    assert doc["master_ai_send_live_comms"] is False        # safety-first
    assert doc["rules"] == {}                                # empty overrides
    assert len(fake_db.tenant_ai_rules.rows) == 1
    # Provenance log emitted.
    assert any(
        "tenant_ai_rules.lazy_init" in r.getMessage()
        and "tenant_id=t1" in r.getMessage()
        for r in caplog.records
    )


def test_second_read_is_idempotent(fake_db):
    run(store.get_tenant_rules("t1"))
    run(store.get_tenant_rules("t1"))
    assert len(fake_db.tenant_ai_rules.rows) == 1


def test_lazy_init_false_returns_none_when_missing(fake_db):
    doc = run(store.get_tenant_rules("t-missing",
                                        lazy_init=False))
    assert doc is None
    assert fake_db.tenant_ai_rules.rows == []


def test_lazy_init_seed_snapshots_platform_revision(fake_db):
    # Bootstrapping the platform defaults yields revision 1.
    run(store.get_platform_defaults())
    doc = run(store.get_tenant_rules("t1"))
    assert doc["platform_revision_at_init"] == 1


def test_lazy_init_flag_flips_off_on_first_save(fake_db):
    run(store.get_tenant_rules("t1"))
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "formal", "custom_directive": ""},
        actor={"id": "u", "email": "a@b"},
        reason="first-explicit-override-please",
    ))
    doc = run(store.get_tenant_rules("t1"))
    assert doc["lazy_initialized_from_platform_defaults"] is False
