"""Task J · Commit 3 · Feb-2026 — Super-admin force-on endpoint tests.

Covers the 8 cases required by the Commit-3 brief:

  1. Super-admin + ``bypass_billing=true`` + valid ``feature_key``
     → 200; row upserted with ``billing_status="manual_override"``,
     ``enabled=True``, ``enabled_at`` stamped, ``enabled_by``
     stamped, ``enabled_reason`` echoed. Audit-log row written.
  2. Super-admin + missing / falsy ``bypass_billing`` → 400 with
     the exact copy from the brief.
  3. Non-super-admin (admin role) → 403 (matches the force-off
     RBAC gate).
  4. Non-authenticated → 401 / 403 depending on how the auth gate
     fires — accept either since the intent is "unauth cannot
     hit this endpoint".
  5. Idempotent — 2 calls yield 1 entitlement row, ``enabled_at``
     is refreshed on the 2nd call, and 2 audit rows are written
     (audit history intentionally not idempotent so ops history
     is preserved).
  6. Preserves adjacent fields — pre-seed a row with
     ``stripe_subscription_item_id``; force-on preserves that
     field on the upsert.
  7. Cross-tenant isolation — a super-admin from tenant A
     force-on's a feature for a synthetic tenant B; the row
     lives on B's ``(tenant_id, feature_key)`` bucket, not A's.
  8. Unknown ``feature_key`` → 404 (matches force-off symmetry;
     writing arbitrary keys would produce ghost rows no
     ``has_feature()`` check will ever consume).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


# ── Fixtures ────────────────────────────────────────────────────
_FE = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
BASE = (_FE.get("EXPO_PUBLIC_BACKEND_URL")
        or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
        or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
MONGO_URL = _BE.get("MONGO_URL") or os.environ.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME") or os.environ.get("DB_NAME")

FEATURE_KEY = "seo_heatmap"


@pytest.fixture(scope="module")
def dbc():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def aquaterra_id(dbc):
    return dbc.tenants.find_one({"slug": "aquaterra"}, {"id": 1})["id"]


@pytest.fixture(scope="module")
def secondary_tenant_id(dbc):
    """Ephemeral second tenant used ONLY for the cross-tenant
    isolation test. Inserted once per module + torn down at
    teardown so we don't rely on the shared fixture tenants."""
    tid = f"TEST-task-j-force-on-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    dbc.tenants.insert_one({
        "id":         tid,
        "slug":       tid.lower(),
        "name":       "Task-J force-on isolation tenant",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield tid
    dbc.tenants.delete_many({"id": tid})
    dbc.feature_entitlements.delete_many({"tenant_id": tid})
    dbc.audit_logs.delete_many({"tenant_id": tid})


def _login(email: str, password: str = "password123") -> Dict:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_h():
    tok = _login("admin@aquaterra.com")["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def super_h():
    tok = _login("super@aquaterra.com")["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(autouse=True)
def _reset(dbc, aquaterra_id):
    """Fresh state per test — matches the force-off suite's
    autouse-reset pattern."""
    dbc.feature_entitlements.delete_many(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY},
    )
    dbc.audit_logs.delete_many(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY,
         "event": "feature_force_on"},
    )
    yield
    dbc.feature_entitlements.delete_many(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY},
    )
    dbc.audit_logs.delete_many(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY,
         "event": "feature_force_on"},
    )


def _post_force_on(headers, tenant_id, feature_key, **body):
    return requests.post(
        f"{API}/admin/entitlements/{tenant_id}/{feature_key}/force-on",
        headers=headers, json=body or None, timeout=15,
    )


# ── (1) Happy path ─────────────────────────────────────────────
def test_force_on_happy_path(super_h, dbc, aquaterra_id):
    r = _post_force_on(
        super_h, aquaterra_id, FEATURE_KEY,
        bypass_billing=True, reason="preview bootstrap",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "forced_on"
    assert body["feature_key"] == FEATURE_KEY
    assert body["tenant_id"] == aquaterra_id

    ent = body["entitlement"]
    assert ent["enabled"] is True
    assert ent["billing_status"] == "manual_override"
    assert ent["enabled_at"] is not None
    assert ent["enabled_by"]  # non-empty super_admin user_id
    assert ent["enabled_reason"] == "preview bootstrap"

    # Audit line written.
    audit = dbc.audit_logs.find_one(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY,
         "event": "feature_force_on"},
        sort=[("at", -1)],
    )
    assert audit is not None
    assert audit["actor_user_id"]
    assert audit["reason"] == "preview bootstrap"
    assert audit["bypass_billing"] is True


# ── (2) Missing / false bypass_billing → 400 ───────────────────
def test_force_on_missing_bypass_billing_400(super_h, aquaterra_id):
    r = _post_force_on(super_h, aquaterra_id, FEATURE_KEY)
    assert r.status_code == 400
    body = r.json()
    assert body["detail"] == (
        "Force-on bypasses billing; pass bypass_billing=true "
        "to acknowledge."
    )


def test_force_on_false_bypass_billing_400(super_h, aquaterra_id):
    r = _post_force_on(
        super_h, aquaterra_id, FEATURE_KEY, bypass_billing=False,
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"] == (
        "Force-on bypasses billing; pass bypass_billing=true "
        "to acknowledge."
    )


# ── (3) Non-super-admin → 403 ──────────────────────────────────
def test_force_on_admin_403(admin_h, aquaterra_id):
    r = _post_force_on(
        admin_h, aquaterra_id, FEATURE_KEY, bypass_billing=True,
    )
    assert r.status_code == 403
    body = r.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "super_admin_required"


# ── (4) Non-authenticated → 401 or 403 ─────────────────────────
def test_force_on_unauthenticated(aquaterra_id):
    r = _post_force_on({}, aquaterra_id, FEATURE_KEY, bypass_billing=True)
    # Accept either — depends on whether get_current_user's missing-
    # header path raises 401 (bearer required) or 403 (auth failed).
    assert r.status_code in (401, 403), r.text


# ── (5) Idempotent — 2 calls, 1 row, refreshed enabled_at ──────
def test_force_on_idempotent(super_h, dbc, aquaterra_id):
    r1 = _post_force_on(
        super_h, aquaterra_id, FEATURE_KEY,
        bypass_billing=True, reason="first call",
    )
    assert r1.status_code == 200
    first_enabled_at = r1.json()["entitlement"]["enabled_at"]

    # Wait a tick so the timestamp can differ.
    import time; time.sleep(0.05)

    r2 = _post_force_on(
        super_h, aquaterra_id, FEATURE_KEY,
        bypass_billing=True, reason="second call",
    )
    assert r2.status_code == 200
    second_enabled_at = r2.json()["entitlement"]["enabled_at"]

    # Single entitlement row.
    rows = list(dbc.feature_entitlements.find(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY},
    ))
    assert len(rows) == 1, rows

    # enabled_at refreshed.
    assert second_enabled_at >= first_enabled_at
    # reason updated to reflect the latest call.
    assert rows[0]["enabled_reason"] == "second call"

    # Two audit rows — one per call.
    audits = list(dbc.audit_logs.find(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY,
         "event": "feature_force_on"},
    ))
    assert len(audits) == 2, audits


# ── (6) Preserves adjacent fields (stripe_subscription_item_id) ─
def test_force_on_preserves_stripe_ids(super_h, dbc, aquaterra_id):
    # Pre-seed a "previously Stripe-enabled" row.
    dbc.feature_entitlements.insert_one({
        "id":                          "row-preserve-test",
        "tenant_id":                   aquaterra_id,
        "feature_key":                 FEATURE_KEY,
        "enabled":                     False,  # currently off — will flip on
        "billing_status":              "cancelled_end_of_cycle",
        "cancels_at":                  (datetime.now(timezone.utc)
                                          + timedelta(days=25)).isoformat(),
        "stripe_subscription_item_id": "si_test_preserve_123",
        "stripe_subscription_id":      "sub_test_preserve_123",
    })
    r = _post_force_on(
        super_h, aquaterra_id, FEATURE_KEY, bypass_billing=True,
    )
    assert r.status_code == 200

    row = dbc.feature_entitlements.find_one(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY},
        {"_id": 0},
    )
    # Force-on flipped the state cleanly ...
    assert row["enabled"] is True
    assert row["billing_status"] == "manual_override"
    assert row["cancels_at"] is None  # stale marker cleared
    # ... while preserving the Stripe identifiers.
    assert row["stripe_subscription_item_id"] == "si_test_preserve_123"
    assert row["stripe_subscription_id"] == "sub_test_preserve_123"


# ── (7) Cross-tenant isolation ─────────────────────────────────
def test_force_on_cross_tenant_isolation(
    super_h, dbc, aquaterra_id, secondary_tenant_id,
):
    """Super-admin (auth'd as aquaterra tenant A) force-on's a
    feature for tenant B. Row lives on B's bucket, not A's."""
    r = _post_force_on(
        super_h, secondary_tenant_id, FEATURE_KEY,
        bypass_billing=True, reason="isolation test",
    )
    assert r.status_code == 200, r.text
    ent = r.json()["entitlement"]
    assert ent["tenant_id"] == secondary_tenant_id
    assert ent["enabled"] is True

    # Aquaterra bucket is untouched — has NO row for this key.
    aq_row = dbc.feature_entitlements.find_one(
        {"tenant_id": aquaterra_id, "feature_key": FEATURE_KEY},
    )
    assert aq_row is None, aq_row

    # Secondary bucket HAS the row.
    b_row = dbc.feature_entitlements.find_one(
        {"tenant_id": secondary_tenant_id, "feature_key": FEATURE_KEY},
    )
    assert b_row is not None
    assert b_row["billing_status"] == "manual_override"


# ── (8) Unknown feature_key → 404 (matches force-off) ──────────
def test_force_on_unknown_feature_404(super_h, aquaterra_id):
    r = _post_force_on(
        super_h, aquaterra_id, "nonexistent_feature",
        bypass_billing=True,
    )
    assert r.status_code == 404, r.text
    body = r.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "feature_not_found"
    assert detail.get("feature_key") == "nonexistent_feature"


# ── (Bonus) Unknown tenant → 404 ────────────────────────────────
def test_force_on_unknown_tenant_404(super_h):
    r = _post_force_on(
        super_h, "tenant_that_does_not_exist", FEATURE_KEY,
        bypass_billing=True,
    )
    assert r.status_code == 404
    body = r.json()
    detail = body.get("detail") if isinstance(body.get("detail"), dict) else body
    assert detail.get("detail") == "tenant_not_found"
