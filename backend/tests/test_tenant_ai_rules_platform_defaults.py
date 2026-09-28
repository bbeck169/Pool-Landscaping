"""MTH-A · Feb-2026 — Platform-defaults CRUD via the store layer.

Locks:

  * Bootstrap ``get_platform_defaults`` seeds the singleton on
    first read and returns a coherent payload afterward.
  * ``save_platform_category`` increments the platform revision
    counter monotonically.
  * ``save_platform_category`` invalidates every per-tenant cache
    entry (platform change → every resolved view must re-read).
  * ``save_platform_category`` validates the payload against the
    same schema that tenant saves use — a bad action key is
    rejected with ``validation_failed``.
  * Reason gate applies to platform saves too.

The RBAC layer (platform PUT super-only, tenant PUT admin-allowed)
is enforced by the FastAPI dependency wrappers — asserted here via
direct import checks so we don't have to spin up TestClient.
"""
from __future__ import annotations

import inspect

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
    return {"id": "u-super", "email": "super@ops"}


# ─── Bootstrap ────────────────────────────────────────────────────

def test_bootstrap_seed_on_first_read(fake_db):
    assert fake_db.platform_ai_rule_defaults.rows == []
    doc = run(store.get_platform_defaults())
    assert doc["revision_number"] == 1
    assert doc["rules"]["tone_voice"]["style"] == "friendly"
    assert len(fake_db.platform_ai_rule_defaults.rows) == 1
    # Second read is idempotent.
    run(store.get_platform_defaults())
    assert len(fake_db.platform_ai_rule_defaults.rows) == 1


# ─── Save ─────────────────────────────────────────────────────────

def test_save_platform_category_bumps_revision(fake_db):
    run(store.get_platform_defaults())                          # seed
    run(store.save_platform_category(
        category="tone_voice",
        value={"style": "formal", "custom_directive": "corp"},
        actor=_actor(),
        reason="platform-tone-shift-all-corp",
    ))
    doc = run(store.get_platform_defaults())
    assert doc["revision_number"] == 2
    assert doc["rules"]["tone_voice"]["style"] == "formal"


def test_save_platform_invalidates_all_tenant_cache(fake_db):
    run(resolve_rules_for_tenant("t1"))
    run(resolve_rules_for_tenant("t2"))
    assert cache.size() == 2
    run(store.save_platform_category(
        category="tone_voice",
        value={"style": "technical", "custom_directive": ""},
        actor=_actor(),
        reason="platform-tone-shift-technical",
    ))
    assert cache.size() == 0


def test_save_platform_validates_payload(fake_db):
    with pytest.raises(Exception) as exc:
        run(store.save_platform_category(
            category="auto_action_allowlist",
            value={"unknown.action": "auto"},
            actor=_actor(),
            reason="attempt-to-add-unknown-action",
        ))
    assert "unknown action" in str(exc.value).lower()


def test_save_platform_requires_reason(fake_db):
    with pytest.raises(store.RuleStoreError) as exc:
        run(store.save_platform_category(
            category="tone_voice",
            value={"style": "friendly", "custom_directive": ""},
            actor=_actor(), reason="short",
        ))
    assert exc.value.error_code == "reason_too_short"


# ─── RBAC — dependency contract ──────────────────────────────────

def test_platform_put_requires_super_admin():
    """Static-inspection: the platform-PUT endpoint declares
    ``require_super_admin`` as the ``user`` dependency."""
    from routers.tenant_ai_rules import put_platform_default_category
    from utils import require_super_admin
    sig = inspect.signature(put_platform_default_category)
    param = sig.parameters["user"]
    dep = param.default
    assert dep is not None
    assert getattr(dep, "dependency", None) is require_super_admin


def test_tenant_put_requires_admin():
    """Tenant PUT allows ``require_admin`` (admin or super)."""
    from routers.tenant_ai_rules import put_tenant_rule_category
    from utils import require_admin
    sig = inspect.signature(put_tenant_rule_category)
    param = sig.parameters["user"]
    dep = param.default
    assert getattr(dep, "dependency", None) is require_admin


def test_master_switch_requires_super_admin():
    """Master switch is super-only per the SAFE-SEND-A convention."""
    from routers.tenant_ai_rules import put_master_switch
    from utils import require_super_admin
    sig = inspect.signature(put_master_switch)
    param = sig.parameters["user"]
    dep = param.default
    assert getattr(dep, "dependency", None) is require_super_admin
