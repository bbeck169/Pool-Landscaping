"""MARKETPLACE-ROLE-BYPASS · Feb-2026 — contract pytest.

Covers the subscription-gate bypass added to
``POST /tenants/mine/feature-marketplace/{feature_key}/enable``:
``super_admin`` and ``owner`` roles can enable marketplace
features without an active Stripe subscription (so the business
owner can validate add-ons in production without triggering the
billing gate).  Every other admin-tier role still receives the
pre-bypass 409 ``no_active_subscription`` response.

Test matrix:
    1. super_admin · no subscription → 200 + sandbox bypass item
    2. owner · no subscription       → 200 + sandbox bypass item
    3. admin · no subscription       → 409 no_active_subscription
    4. manager · no subscription     → 409 (no bypass widening)
    5. admin · WITH subscription     → 200 (bypass does NOT break
                                           the pre-existing happy path)
    6. Tenant isolation — super_admin of tenant A writes ONLY to
       tenant A's entitlement row.

Invokes the route function directly rather than through HTTP so
the test is independent of the ambient server env (the Stripe
price-id env is required for the full-HTTP path to clear the
``feature_not_configured`` 503 — out of scope for a role-bypass
contract test).  Production code paths (``require_admin``,
``_load_entitlement``, ``add_feature_item_to_subscription``,
``_write_audit``) all run unmodified.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from tests._shared_mongo import shared_db as _shared_db


os.environ.setdefault("ALLOW_TEST_HOOKS", "1")

_sync = _shared_db()
_FEATURE = "seo_heatmap"
_FAKE_PRICE_ID = "price_sandbox_marketplace_bypass_tests"

# Patch the Stripe price-id resolver at module scope so every test
# in this file sees ``seo_heatmap`` as "configured".  Mirrors the
# env flip pattern the existing marketplace test suite uses, but
# does it in-process so we don't rely on the server env.
pytestmark = pytest.mark.usefixtures("_patch_price_resolver")


@pytest.fixture(autouse=True)
def _patch_price_resolver():
    """Force ``resolve_stripe_price_id`` to return a sandbox-prefixed
    id for ``seo_heatmap`` so the route reaches the subscription
    gate.  The sandbox prefix routes the Stripe-ops helper through
    its deterministic in-process branch (no real Stripe calls)."""
    import services.entitlements.registry as _reg
    import routers.feature_marketplace as _fm
    original = _reg.resolve_stripe_price_id

    def _resolve(feature_key):
        if feature_key == _FEATURE:
            return _FAKE_PRICE_ID
        return original(feature_key)

    with patch.object(_reg, "resolve_stripe_price_id", _resolve), \
         patch.object(_fm, "resolve_stripe_price_id", _resolve):
        yield


def _run(coro):
    """Run an async callable from a sync test body."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed_tenant():
    tid = f"mrbp-{uuid.uuid4().hex[:8]}"
    _sync.tenants.insert_one({
        "id": tid, "name": "MRBP smoke", "slug": tid, "active": True,
    })
    return tid


def _seed_user(tenant_id, role, email_prefix):
    uid = f"{email_prefix}-{uuid.uuid4().hex[:8]}"
    _sync.users.insert_one({
        "id": uid, "tenant_id": tenant_id, "role": role,
        "name": f"MRBP {role}", "email": f"{uid}@mrbp.test",
    })
    return {"id": uid, "role": role, "tenant_id": tenant_id,
            "email": f"{uid}@mrbp.test"}


def _seed_active_subscription(tenant_id):
    _sync.stripe_subscriptions.update_one(
        {"tenant_id": tenant_id,
         "stripe_subscription_id": f"sub_mrbp_{tenant_id[:8]}"},
        {"$setOnInsert": {
            "id": f"sub_mirror_mrbp_{tenant_id[:8]}",
            "tenant_id": tenant_id,
            "customer_id": f"cust_mrbp_{tenant_id[:8]}",
            "stripe_customer_id": f"cus_mrbp_{tenant_id[:8]}",
            "stripe_subscription_id": f"sub_mrbp_{tenant_id[:8]}",
            "status": "active",
            "current_period_end":
                (datetime.now(timezone.utc)
                  + timedelta(days=25)).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


@pytest.fixture
def tenant_id():
    tid = _seed_tenant()
    yield tid
    for col in ("tenants", "users", "feature_entitlements",
                 "stripe_subscriptions", "audit_logs"):
        _sync[col].delete_many({"tenant_id": tid})


async def _call_enable(user_dict, tenant_dict):
    """Invoke the enable_feature route function directly, bypassing
    the HTTP layer and the ``Depends(require_admin)`` plumbing (the
    role gate behaviour for non-admin roles is covered by a separate
    integration test — see ``test_feature_marketplace.py``)."""
    from routers.feature_marketplace import enable_feature
    return await enable_feature(
        feature_key=_FEATURE,
        user=user_dict,
        tenant=tenant_dict,
    )


# ══════════════════════════════════════════════════════════════════
# 1 · super_admin · no subscription → 200 + bypass item
# ══════════════════════════════════════════════════════════════════
def test_super_admin_bypass_without_subscription(tenant_id):
    sup = _seed_user(tenant_id, "super_admin", "sup")
    tenant = {"id": tenant_id}
    body = _run(_call_enable(sup, tenant))
    assert body["status"] == "enabled"
    assert body["enabled"] is True
    assert body["billing_status"] == "active"

    ent = _sync.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": _FEATURE},
    )
    assert ent is not None
    # Bypass synthesized ids reuse the ``si_sandbox_`` prefix so
    # the disable path's sandbox-item detection round-trips cleanly.
    assert ent["stripe_subscription_item_id"].startswith(
        "si_sandbox_bypass_"
    )
    # Audit trail records ``bypass_reason="role"`` so ops can
    # distinguish these from genuine sandbox items.
    audit = _sync.audit_logs.find_one(
        {"tenant_id": tenant_id, "feature_key": _FEATURE,
         "event": "feature_enabled"},
    )
    assert audit is not None
    assert audit.get("bypass_reason") == "role"


# ══════════════════════════════════════════════════════════════════
# 2 · owner · no subscription → 200 + bypass item
# ══════════════════════════════════════════════════════════════════
def test_owner_bypass_without_subscription(tenant_id):
    own = _seed_user(tenant_id, "owner", "own")
    body = _run(_call_enable(own, {"id": tenant_id}))
    assert body["status"] == "enabled"

    ent = _sync.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": _FEATURE},
    )
    assert ent is not None
    assert ent["stripe_subscription_item_id"].startswith(
        "si_sandbox_bypass_"
    )
    audit = _sync.audit_logs.find_one(
        {"tenant_id": tenant_id, "feature_key": _FEATURE,
         "event": "feature_enabled"},
    )
    assert audit.get("bypass_reason") == "role"


# ══════════════════════════════════════════════════════════════════
# 3 · admin · no subscription → 409 no_active_subscription
# ══════════════════════════════════════════════════════════════════
def test_admin_without_subscription_still_gated(tenant_id):
    adm = _seed_user(tenant_id, "admin", "adm")
    with pytest.raises(HTTPException) as exc:
        _run(_call_enable(adm, {"id": tenant_id}))
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("detail") == "no_active_subscription"

    # No entitlement row written — subscription gate failed BEFORE
    # the upsert, pre-bypass behavior preserved for non-privileged
    # admin-tier roles.
    ent = _sync.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": _FEATURE},
    )
    assert ent is None


# ══════════════════════════════════════════════════════════════════
# 4 · manager · no subscription → 409 (no bypass widening)
# ══════════════════════════════════════════════════════════════════
def test_manager_without_subscription_still_gated(tenant_id):
    mgr = _seed_user(tenant_id, "manager", "mgr")
    with pytest.raises(HTTPException) as exc:
        _run(_call_enable(mgr, {"id": tenant_id}))
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail.get("detail") == "no_active_subscription"


# ══════════════════════════════════════════════════════════════════
# 5 · admin · WITH active subscription → 200 (bypass doesn't
#     break the pre-existing happy path).
# ══════════════════════════════════════════════════════════════════
def test_admin_with_subscription_happy_path(tenant_id):
    adm = _seed_user(tenant_id, "admin", "adm")
    _seed_active_subscription(tenant_id)
    body = _run(_call_enable(adm, {"id": tenant_id}))
    assert body["status"] == "enabled"

    ent = _sync.feature_entitlements.find_one(
        {"tenant_id": tenant_id, "feature_key": _FEATURE},
    )
    assert ent is not None
    sii = ent["stripe_subscription_item_id"]
    # Non-bypass synthesized ids use the plain
    # ``si_sandbox_<tenant[:6]>_<feature>`` shape — ``bypass``
    # prefix MUST NOT appear.
    assert sii.startswith("si_sandbox_")
    assert not sii.startswith("si_sandbox_bypass_")

    audit = _sync.audit_logs.find_one(
        {"tenant_id": tenant_id, "feature_key": _FEATURE,
         "event": "feature_enabled"},
    )
    assert audit is not None
    # No ``bypass_reason`` on the natural happy path.
    assert audit.get("bypass_reason") is None


# ══════════════════════════════════════════════════════════════════
# 6 · Tenant isolation — super_admin of tenant A writes ONLY to
#     tenant A's entitlement row.
# ══════════════════════════════════════════════════════════════════
def test_tenant_isolation_super_admin_bypass(tenant_id):
    tid_b = _seed_tenant()
    try:
        sup_a = _seed_user(tenant_id, "super_admin", "sup")
        body = _run(_call_enable(sup_a, {"id": tenant_id}))
        assert body["status"] == "enabled"

        ent_a = _sync.feature_entitlements.find_one(
            {"tenant_id": tenant_id, "feature_key": _FEATURE},
        )
        assert ent_a is not None
        # Tenant B stays clean despite super_admin role —
        # ``tenant`` dependency scopes the write.
        ent_b = _sync.feature_entitlements.find_one(
            {"tenant_id": tid_b, "feature_key": _FEATURE},
        )
        assert ent_b is None
    finally:
        for col in ("tenants", "users", "feature_entitlements",
                     "stripe_subscriptions", "audit_logs"):
            _sync[col].delete_many({"tenant_id": tid_b})
