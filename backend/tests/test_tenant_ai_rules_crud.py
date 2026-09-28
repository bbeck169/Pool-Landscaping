"""MTH-A · Feb-2026 — CRUD contract tests for the rule store.

Covers the ``services.tenant_ai_rules.store`` mutation API + the
lazy-init read semantics via the shared fake Motor DB in
``tests._mth_a_helpers``.

Assertions:

  * ``save_category`` normalises + persists + increments the
    tenant's ``revision_number`` monotonically.
  * ``reason`` shorter than 8 chars → ``reason_too_short``.
  * ``reason`` missing → ``reason_required``.
  * Every save writes a snapshot to ``tenant_ai_rules_revisions``.
  * ``reset_category`` removes the tenant's override.
  * ``revert_to_revision`` restores rules + master switch to a
    prior snapshot and emits ONE new revision.
  * ``list_revisions`` returns rows newest-first.
  * ``save_category`` invalidates the resolver cache.
  * Tenant isolation — a save on tenant B does NOT leak to
    tenant A's docs.
  * 50 KiB payload rejected as ``rule_doc_too_large``.
"""
from __future__ import annotations

import pytest

from services.tenant_ai_rules import cache, store
from services.tenant_ai_rules.resolver import resolve_rules_for_tenant
from tests._mth_a_helpers import FakeDB, run


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(store, "db", fake, raising=False)
    from services.tenant_ai_rules import resolver as _resolver
    monkeypatch.setattr(_resolver, "store",
                          store, raising=False)         # re-bind
    cache.invalidate_all()
    return fake


def _admin():
    return {"id": "u-adm", "email": "adm@t1", "name": "Alice Admin"}


# ─── Reason gate ──────────────────────────────────────────────────

def test_save_category_requires_reason_8_chars(fake_db):
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.save_category(
            "t1", "tone_voice",
            {"style": "friendly", "custom_directive": ""},
            actor=_admin(), reason="short",
        ))
    assert exc.value.error_code == "reason_too_short"


def test_save_category_reason_required_is_string(fake_db):
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.save_category(
            "t1", "tone_voice",
            {"style": "friendly", "custom_directive": ""},
            actor=_admin(), reason=None,
        ))
    assert exc.value.error_code == "reason_required"


# ─── Monotonic revisions + snapshot ───────────────────────────────

def test_save_category_bumps_revision_and_writes_snapshot(fake_db):
    for i, style in enumerate(("friendly", "technical", "formal")):
        run(store.save_category(
            "t1", "tone_voice",
            {"style": style, "custom_directive": f"iter{i}"},
            actor=_admin(),
            reason=f"iter{i}-reason-please-pass",
        ))
    head = run(store.get_tenant_rules("t1"))
    assert head["revision_number"] == 3
    revs = run(store.list_revisions("t1"))
    assert [r["revision_number"] for r in revs] == [3, 2, 1]
    assert revs[0]["rules"]["tone_voice"]["style"] == "formal"


def test_revisions_rows_scope_by_tenant(fake_db):
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "friendly", "custom_directive": ""},
        actor=_admin(), reason="tenant-1-first-save",
    ))
    run(store.save_category(
        "t2", "tone_voice",
        {"style": "formal", "custom_directive": ""},
        actor=_admin(), reason="tenant-2-first-save",
    ))
    revs1 = run(store.list_revisions("t1"))
    revs2 = run(store.list_revisions("t2"))
    assert all(r["tenant_id"] == "t1" for r in revs1)
    assert all(r["tenant_id"] == "t2" for r in revs2)
    assert len(revs1) == 1 and len(revs2) == 1


# ─── Reset ────────────────────────────────────────────────────────

def test_reset_category_removes_override(fake_db):
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "formal", "custom_directive": "very-corp"},
        actor=_admin(), reason="corporate-brand-switch-please",
    ))
    row_before = run(store.get_tenant_rules("t1"))
    assert row_before["rules"]["tone_voice"]["style"] == "formal"
    run(store.reset_category(
        "t1", "tone_voice",
        actor=_admin(), reason="rolling-back-tone-change",
    ))
    row_after = run(store.get_tenant_rules("t1"))
    assert "tone_voice" not in row_after["rules"]
    # Revision still bumped — reset counts as a save.
    assert row_after["revision_number"] == 2


# ─── Revert ───────────────────────────────────────────────────────

def test_revert_to_prior_revision(fake_db):
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "friendly", "custom_directive": "v1"},
        actor=_admin(), reason="initial-friendly-tone-v1",
    ))
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "formal", "custom_directive": "v2"},
        actor=_admin(), reason="switching-to-formal-tone-v2",
    ))
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "technical", "custom_directive": "v3"},
        actor=_admin(), reason="switching-to-technical-tone-v3",
    ))
    # Now revert to revision 1 (friendly / v1).
    result = run(store.revert_to_revision(
        "t1", 1, actor=_admin(),
        reason="reverting-to-brand-v1",
    ))
    assert result["revision_number"] == 4
    head = run(store.get_tenant_rules("t1"))
    assert head["rules"]["tone_voice"] == {
        "style": "friendly", "custom_directive": "v1",
    }
    # The revert reason retains the target revision hint.
    assert "revert_to_revision=1" in head["last_update_reason"]


def test_revert_unknown_revision_returns_404_error(fake_db):
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "friendly", "custom_directive": ""},
        actor=_admin(), reason="first-revision-please",
    ))
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.revert_to_revision(
            "t1", 99, actor=_admin(),
            reason="revert-to-missing-revision",
        ))
    assert exc.value.error_code == "revision_not_found"
    assert exc.value.status_code == 404


# ─── Cache invalidation ───────────────────────────────────────────

def test_save_invalidates_cache_entry(fake_db):
    # Prime the cache.
    run(resolve_rules_for_tenant("t1"))
    assert cache.size() == 1
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "formal", "custom_directive": ""},
        actor=_admin(), reason="tone-change-formal-req",
    ))
    assert cache.size() == 0                            # invalidated


def test_platform_save_invalidates_all_cache(fake_db):
    run(resolve_rules_for_tenant("t1"))
    run(resolve_rules_for_tenant("t2"))
    assert cache.size() == 2
    run(store.save_platform_category(
        category="tone_voice",
        value={"style": "friendly", "custom_directive": "platform"},
        actor=_admin(), reason="platform-tone-switch-req",
    ))
    assert cache.size() == 0


# ─── 50 KiB doc size gate ─────────────────────────────────────────

def test_oversized_rule_doc_rejected(fake_db):
    big = "x" * 60000                                    # ~60 KB directive
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.save_category(
            "t1", "tone_voice",
            {"style": "friendly", "custom_directive": big},
            actor=_admin(), reason="attempting-oversized-directive",
        ))
    # ``custom_directive`` max is 2000 chars — validation catches
    # this before the size guard.
    assert exc.value.error_code == "validation_failed"
    assert "custom_directive" in exc.value.message


def test_size_gate_rejects_unknown_actions(fake_db):
    """Force validation rejection with unknown action keys — same
    kind of failure the 50 KiB gate protects against, one layer up."""
    from services.tenant_ai_rules.schema import ACTION_INVENTORY
    huge_extra_actions = {
        f"marco.dummy_action_{i}": "auto" for i in range(100)
    }
    payload = {
        **{action: "admin_approval" for action in ACTION_INVENTORY},
        **huge_extra_actions,
    }
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.save_category(
            "t1", "auto_action_allowlist", payload,
            actor=_admin(),
            reason="attempt-oversized-allowlist-inject",
        ))
    assert exc.value.error_code == "validation_failed"
    assert "unknown action" in exc.value.message.lower()


def test_size_gate_rejects_true_50kb_doc(fake_db):
    """Push the tenant doc past 50 KiB via the ``notes`` field on
    a valid escalation-rules payload — the size guard fires."""
    long_keyword = "a" * 55_000
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.save_category(
            "t1", "escalation_rules",
            [{"keyword": long_keyword, "is_regex": False,
              "target_role": "admin", "sla_minutes": 5,
              "notify_channel": "email"}],
            actor=_admin(),
            reason="attempt-oversized-escalation-payload",
        ))
    assert exc.value.error_code == "rule_doc_too_large"
    assert exc.value.status_code == 400


# ─── Tenant isolation ────────────────────────────────────────────

def test_tenant_isolation_between_saves(fake_db):
    run(store.save_category(
        "t1", "tone_voice",
        {"style": "friendly", "custom_directive": "t1"},
        actor=_admin(), reason="t1-first-tone-config",
    ))
    run(store.save_category(
        "t2", "tone_voice",
        {"style": "formal", "custom_directive": "t2"},
        actor=_admin(), reason="t2-first-tone-config",
    ))
    t1 = run(store.get_tenant_rules("t1"))
    t2 = run(store.get_tenant_rules("t2"))
    assert t1["rules"]["tone_voice"]["custom_directive"] == "t1"
    assert t2["rules"]["tone_voice"]["custom_directive"] == "t2"
