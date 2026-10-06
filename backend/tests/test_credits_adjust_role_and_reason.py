"""CUSTOMER-PROFILE-ACTION-BAR · Feb-2026 — regression guards for
the widened role gate + relaxed reason validation on the
``POST /api/customers/{cid}/credits/adjust`` endpoint.

Context: the endpoint historically used ``require_admin`` and
rejected any ``reason`` shorter than 5 chars.  The action-bar
shortcut on the customer-detail page required:
  * Role gate widened to ``{admin, super_admin, manager, owner}``.
  * ``reason`` relaxed to accept blank / missing.

The HTTP-level live-preview tests at
``test_phase10c_pi_and_credits_adjust.py`` already cover the
admin happy path, the floor guard, and the tech-denial via
``mike@aquaterra.com``.  This file layers two kinds of coverage:

1. **Dependency-level unit tests** on ``_require_credit_adjuster``
   covering ``manager`` + ``owner`` — the two roles the live-
   preview env does not have seeded (no ``manager@aquaterra.com``
   / ``owner@aquaterra.com`` user rows).  These tests invoke the
   dep directly with a fake ``user`` dict so we don't need to seed
   accounts or hit the HTTP boundary.
2. **HTTP tech-denial regression** — the sibling file already
   covers this but we re-assert here co-located with the role-
   widening test so a future narrower gate also lands this file's
   suite loudly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import requests
from fastapi import HTTPException

from routers.referrals_phase10 import (
    _CREDIT_ADJUSTER_ROLES,
    _require_credit_adjuster,
)


API = "http://localhost:8001/api"


# ═════════════════════════════════════════════════════════════════
# Guard 1 — dep-level: role set contains the four widened roles
# ═════════════════════════════════════════════════════════════════
def test_credit_adjuster_role_set_includes_widened_four():
    """The widened role set must be exactly the four privileged
    roles — any accidental drop (e.g., someone narrowing the
    frozenset back to just ``admin``) lands this test loudly."""
    assert "admin" in _CREDIT_ADJUSTER_ROLES
    assert "super_admin" in _CREDIT_ADJUSTER_ROLES
    assert "manager" in _CREDIT_ADJUSTER_ROLES
    assert "owner" in _CREDIT_ADJUSTER_ROLES
    assert _CREDIT_ADJUSTER_ROLES == frozenset({
        "admin", "super_admin", "manager", "owner",
    })


# ═════════════════════════════════════════════════════════════════
# Guard 2 — dep-level: direct invocation accepts/denies by role
# ═════════════════════════════════════════════════════════════════
# The dep returns the user dict on success and raises
# ``HTTPException(403)`` on denial — mirroring the ``require_admin``
# shape so downstream handler code can read ``user.get("id")`` /
# ``email`` without a code-path split.
import asyncio


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.mark.parametrize("role", ["admin", "super_admin", "manager", "owner"])
def test_credit_adjuster_dep_accepts_all_four_privileged_roles(role):
    user = {"id": f"u-{role}", "email": f"{role}@test.com", "role": role}
    out = _run(_require_credit_adjuster(user=user))
    assert out is user, (
        f"dep must return the user dict unchanged for {role!r}; "
        f"got {out!r}"
    )


@pytest.mark.parametrize("role", ["technician", "employee", "customer",
                                     "viewer", "", None])
def test_credit_adjuster_dep_rejects_other_roles_with_403(role):
    user = {"id": "u-other", "email": "o@test.com", "role": role}
    with pytest.raises(HTTPException) as exc:
        _run(_require_credit_adjuster(user=user))
    assert exc.value.status_code == 403


def test_credit_adjuster_dep_is_case_insensitive():
    """Mixed-case role strings (e.g. ``"Admin"`` from a legacy
    tenant row) must still pass.  Preserves the pre-fix behaviour
    where ``require_admin`` lower-cased before comparison."""
    user = {"id": "u-admin", "email": "a@test.com", "role": "Admin"}
    out = _run(_require_credit_adjuster(user=user))
    assert out is user


# ═════════════════════════════════════════════════════════════════
# Guard 3 — HTTP: tech still 403 (regression on narrow side)
# ═════════════════════════════════════════════════════════════════
def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw},
                       timeout=15)
    return r.json()["access_token"]


def _hdr(t):
    return {"Authorization": f"Bearer {t}", "Content-Type": "application/json"}


def _preview_available() -> bool:
    try:
        r = requests.get(f"{API}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _preview_available(),
                    reason="live preview backend not reachable")
def test_credits_adjust_still_denies_technician_http():
    """CUSTOMER-PROFILE-ACTION-BAR · Feb-2026 — role gate widened
    to include manager + owner but MUST NOT accidentally admit
    technicians / employees / customers.  Re-asserted here so
    narrowing-the-widening regressions land this file's suite."""
    tok = _login("mike@aquaterra.com")  # seeded technician
    # Find any customer id — if none, skip.
    r = requests.get(f"{API}/customers?limit=1",
                       headers=_hdr(tok), timeout=15)
    if r.status_code != 200:
        pytest.skip("tech couldn't list customers for id discovery")
    rows = r.json() if isinstance(r.json(), list) else r.json().get("data", [])
    if not rows:
        pytest.skip("no customer rows available for test")
    cid = rows[0]["id"]
    r = requests.post(f"{API}/customers/{cid}/credits/adjust",
                       headers=_hdr(tok),
                       json={"delta_cents": 100, "reason": "tech attempt"},
                       timeout=15)
    assert r.status_code in (401, 403), r.text


@pytest.mark.skipif(not _preview_available(),
                    reason="live preview backend not reachable")
def test_credits_adjust_accepts_missing_reason_key_http():
    """Payload entirely omits the ``reason`` key — must still 200
    now that the field is ``Optional[str] = ""`` on the schema."""
    from pymongo import MongoClient
    from dotenv import dotenv_values
    _env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    _sync_client = MongoClient(_env["MONGO_URL"])
    _sync = _sync_client[_env.get("DB_NAME") or "pool_crm"]
    try:
        tok = _login("admin@aquaterra.com")
        tid = _sync.tenants.find_one({}, {"_id": 0, "id": 1})["id"]
        cid = _sync.customers.find_one(
            {"tenant_id": tid}, {"_id": 0, "id": 1})["id"]
        _sync.customer_credits_balance.update_one(
            {"tenant_id": tid, "customer_id": cid},
            {"$set": {"balance_cents": 0, "balance": 0}}, upsert=True,
        )
        try:
            r = requests.post(f"{API}/customers/{cid}/credits/adjust",
                               headers=_hdr(tok),
                               json={"delta_cents": 100},  # NO reason key
                               timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["balance_cents"] == 100
        finally:
            _sync.customer_credits.delete_many(
                {"tenant_id": tid, "customer_id": cid,
                 "delta_cents": 100, "reason": ""})
            _sync.customer_credits_balance.update_one(
                {"tenant_id": tid, "customer_id": cid},
                {"$set": {"balance_cents": 0, "balance": 0}})
    finally:
        _sync_client.close()
