"""LDM-A · Feb-2026 — Tenant automation_rules migration + PATCH endpoint.

Locks the seven invariants of Sub-phase A of the AI Live Dispatcher +
Predictive Maintenance track (see
``memory/SPEC_LIVE_DISPATCHER_AND_MAINTENANCE.md``):

    (a) migration adds the ``settings.automation_rules`` sub-doc
        with all four canonical keys on a fresh tenant.
    (b) PATCH endpoint's role gate — technician / member cannot
        flip automation rules (403). Admin passes.
    (c) Cross-tenant safety — body-supplied ``tenant_id`` in a
        PATCH raises 403 loud (even when it matches the caller's
        own tenant, so the FE never grows the habit of sending it).
    (d) Migration is idempotent — a second run behind an existing
        sentinel row returns ``skipped_by_marker=True`` with a
        zero cursor drain.
    (e) Default values are correct — the four seeded fields match
        ``AUTOMATION_RULE_DEFAULTS`` verbatim.
    (f) Pydantic range validation on ``dispatch_sms_customer_count``
        — 0 / 11 → ValidationError (422 at the API boundary).
    (g) Pydantic range validation on the OTHER three fields —
        boundary edges pass, over/under fails.

Test-loop convention mirrors P52 / marco_orchestrator_seed_v1 / etc:
sync ``pymongo`` for seeding + cleanup, per-test fresh asyncio loop
+ Motor client for the SUT call. Handler invoked directly (no
TestClient) — the auth dep chain is swapped by passing a synthetic
``user`` dict, matching the pattern in
``test_p52_tenant_default_locale.py``.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


_BE = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
MONGO_URL = _BE.get("MONGO_URL")
DB_NAME = _BE.get("DB_NAME")

TAG = "LDMA_"


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def dbc() -> MongoClient:
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture
def cleanup(dbc):
    """Track LDMA_-tagged tenant + sentinel rows and drop them on
    teardown so full-suite runs stay hermetic."""
    seeded_tenant_ids: List[str] = []
    yield seeded_tenant_ids
    if seeded_tenant_ids:
        dbc.tenants.delete_many({"id": {"$in": seeded_tenant_ids}})


def _fresh(prefix: str) -> str:
    return f"{TAG}{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_tenant(dbc, *, with_rules: Optional[Dict[str, Any]] = None) -> str:
    """Insert a tenant with optional pre-existing automation_rules.

    ``with_rules=None`` → tenant has no automation_rules block at
    all (the migration should backfill defaults).
    ``with_rules={...}`` → tenant already carries a rules sub-doc
    (the migration should NOT overwrite existing keys).
    """
    tid = _fresh("TEN")
    doc: Dict[str, Any] = {
        "id": tid,
        "name": f"LDMA seed tenant {tid[-8:]}",
        "timezone": "America/Phoenix",
        "created_at": "2026-02-15T00:00:00Z",
    }
    if with_rules is not None:
        doc["settings"] = {"automation_rules": with_rules}
    dbc.tenants.insert_one(doc)
    return tid


# ═════════════════════════════════════════════════════════════════════
# Per-test async loop + Motor db handle
# ═════════════════════════════════════════════════════════════════════
def _run(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = AsyncIOMotorClient(MONGO_URL, io_loop=loop)
    adb = client[DB_NAME]
    try:
        return loop.run_until_complete(coro_factory(adb))
    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# (a) Migration adds the automation_rules sub-doc on a fresh tenant.
# ═════════════════════════════════════════════════════════════════════
def test_a_migration_adds_automation_rules_subdoc(dbc, cleanup):
    """A fresh tenant (no ``settings.automation_rules`` at all) is
    backfilled with the full sub-document — all four canonical keys
    present after the sweep."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.automation_rules_v1 import run
        # ``force=True`` so a prior full-DB pass doesn't short-circuit us.
        return await run(dry_run=False, force=True, db_client=adb)

    _run(_apply)
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    rules = (row.get("settings") or {}).get("automation_rules") or {}
    for key in (
        "dispatch_delay_threshold_mins",
        "dispatch_sms_customer_count",
        "filter_clean_interval_months",
        "salt_cell_replacement_months",
    ):
        assert key in rules, (
            f"automation_rules.{key} missing after migration; got {rules!r}"
        )


# ═════════════════════════════════════════════════════════════════════
# (b) PATCH role gate — technician / member cannot flip rules.
# ═════════════════════════════════════════════════════════════════════
class _FakeReq:
    """Duck-typed replacement for starlette.requests.Request — only
    the ``.json()`` coroutine is called by the handler."""
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    async def json(self) -> Dict[str, Any]:
        return dict(self._payload)


@pytest.mark.parametrize("bad_role", ["technician", "member", "customer"])
def test_b_patch_rejects_non_admin_role(dbc, cleanup, bad_role):
    """Non-admin roles get 403 from the PATCH endpoint. Locks the
    role gate so a future refactor that accidentally opens the surface
    to techs shows up as a green-to-red flip."""
    from fastapi import HTTPException
    tid = _seed_tenant(dbc, with_rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import (
            patch_own_automation_rules,
            AutomationRulesPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = AutomationRulesPatch(dispatch_delay_threshold_mins=45)
            req = _FakeReq({"dispatch_delay_threshold_mins": 45})
            return await patch_own_automation_rules(
                request=req,
                body=body,
                user={"role": bad_role, "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    with pytest.raises(HTTPException) as excinfo:
        _run(_apply)
    assert excinfo.value.status_code == 403


def test_b_patch_admin_can_flip_rules(dbc, cleanup):
    """Positive-case counterpart: admin role passes the gate and the
    PATCH persists the new value on the caller's tenant."""
    tid = _seed_tenant(dbc, with_rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    cleanup.append(tid)

    async def _apply(adb):
        from routers.tenants import (
            patch_own_automation_rules,
            AutomationRulesPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = AutomationRulesPatch(dispatch_delay_threshold_mins=45)
            req = _FakeReq({"dispatch_delay_threshold_mins": 45})
            return await patch_own_automation_rules(
                request=req,
                body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid},
            )
        finally:
            _t.db = _t._orig_db

    out = _run(_apply)
    assert out.get("dispatch_delay_threshold_mins") == 45
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    rules = (row.get("settings") or {}).get("automation_rules") or {}
    assert rules.get("dispatch_delay_threshold_mins") == 45


# ═════════════════════════════════════════════════════════════════════
# (c) Cross-tenant safety — body-supplied tenant_id → 403.
# ═════════════════════════════════════════════════════════════════════
def test_c_patch_rejects_body_supplied_tenant_id(dbc, cleanup):
    """A payload that carries ``tenant_id`` (even matching the
    caller's own JWT tenant) raises 403. Prevents the frontend from
    ever growing a habit of trusting body-derived tenant scoping."""
    from fastapi import HTTPException
    tid_a = _seed_tenant(dbc, with_rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    tid_b = _seed_tenant(dbc, with_rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    cleanup.extend([tid_a, tid_b])

    async def _apply(adb):
        from routers.tenants import (
            patch_own_automation_rules,
            AutomationRulesPatch,
        )
        from routers import tenants as _t
        _t._orig_db = getattr(_t, "_orig_db", _t.db)
        _t.db = adb
        try:
            body = AutomationRulesPatch(dispatch_delay_threshold_mins=90)
            # Caller is tenant A's admin, but the body claims tenant B.
            # Handler MUST reject at the ``tenant_id in raw`` guard.
            req = _FakeReq({
                "tenant_id": tid_b,
                "dispatch_delay_threshold_mins": 90,
            })
            return await patch_own_automation_rules(
                request=req,
                body=body,
                user={"role": "admin", "id": "u1", "tenant_id": tid_a},
            )
        finally:
            _t.db = _t._orig_db

    with pytest.raises(HTTPException) as excinfo:
        _run(_apply)
    assert excinfo.value.status_code == 403
    # Neither tenant should have been mutated — the guard fires
    # before the mongo update.
    row_a = dbc.tenants.find_one({"id": tid_a}, {"_id": 0})
    row_b = dbc.tenants.find_one({"id": tid_b}, {"_id": 0})
    rules_a = (row_a.get("settings") or {}).get("automation_rules") or {}
    rules_b = (row_b.get("settings") or {}).get("automation_rules") or {}
    assert rules_a.get("dispatch_delay_threshold_mins") == 20
    assert rules_b.get("dispatch_delay_threshold_mins") == 20


# ═════════════════════════════════════════════════════════════════════
# (d) Migration idempotency — sentinel short-circuits the 2nd run.
# ═════════════════════════════════════════════════════════════════════
def test_d_migration_idempotent_second_run_skipped_by_marker(dbc, cleanup):
    """Second run behind an existing sentinel returns
    ``skipped_by_marker=True`` and drains zero rows from
    ``tenants.find``."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.automation_rules_v1 import run
        # First pass stamps the sentinel.
        await run(dry_run=False, force=True, db_client=adb)
        # Second pass respects the sentinel — no --force.
        return await run(dry_run=False, force=False, db_client=adb)

    summary = _run(_apply)
    assert summary["skipped_by_marker"] is True
    assert summary["tenants_scanned"] == 0
    assert summary["tenants_backfilled"] == 0
    assert summary["fields_written"] == 0


# ═════════════════════════════════════════════════════════════════════
# (e) Default values are correct.
# ═════════════════════════════════════════════════════════════════════
def test_e_default_backfill_values_match_canonical_defaults(dbc, cleanup):
    """After the sweep, a previously-unset tenant carries the exact
    canonical default values — not an empty sub-doc, not nulls."""
    tid = _seed_tenant(dbc)
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.automation_rules_v1 import run
        return await run(dry_run=False, force=True, db_client=adb)

    _run(_apply)
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    rules = (row.get("settings") or {}).get("automation_rules") or {}
    assert rules.get("dispatch_delay_threshold_mins") == 20
    assert rules.get("dispatch_sms_customer_count") == 3
    assert rules.get("filter_clean_interval_months") == 6
    assert rules.get("salt_cell_replacement_months") == 36


def test_e_existing_customized_values_preserved(dbc, cleanup):
    """Migration MUST NOT overwrite already-set fields — an admin
    who's already tuned a value keeps it after a re-run."""
    tid = _seed_tenant(dbc, with_rules={
        # dispatch_delay is set to a custom 90 min; other three missing.
        "dispatch_delay_threshold_mins": 90,
    })
    cleanup.append(tid)

    async def _apply(adb):
        from migrations.automation_rules_v1 import run
        return await run(dry_run=False, force=True, db_client=adb)

    _run(_apply)
    row = dbc.tenants.find_one({"id": tid}, {"_id": 0})
    rules = (row.get("settings") or {}).get("automation_rules") or {}
    # Custom value preserved.
    assert rules.get("dispatch_delay_threshold_mins") == 90
    # The other three backfilled with defaults.
    assert rules.get("dispatch_sms_customer_count") == 3
    assert rules.get("filter_clean_interval_months") == 6
    assert rules.get("salt_cell_replacement_months") == 36


# ═════════════════════════════════════════════════════════════════════
# (f) Pydantic range on dispatch_sms_customer_count (1-10).
# ═════════════════════════════════════════════════════════════════════
def test_f_sms_customer_count_out_of_range_rejected():
    """Values outside 1-10 raise ValidationError at the Pydantic
    layer (surfaces as HTTP 422 at the API boundary)."""
    from pydantic import ValidationError
    from routers.tenants import AutomationRulesPatch

    # Under-range.
    with pytest.raises(ValidationError):
        AutomationRulesPatch(dispatch_sms_customer_count=0)
    # Over-range.
    with pytest.raises(ValidationError):
        AutomationRulesPatch(dispatch_sms_customer_count=11)
    # Edges pass (1 and 10).
    m_lo = AutomationRulesPatch(dispatch_sms_customer_count=1)
    m_hi = AutomationRulesPatch(dispatch_sms_customer_count=10)
    assert m_lo.dispatch_sms_customer_count == 1
    assert m_hi.dispatch_sms_customer_count == 10


# ═════════════════════════════════════════════════════════════════════
# (g) Boundary validation on the OTHER three fields.
# ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "field,lo,hi,bad_under,bad_over",
    [
        ("dispatch_delay_threshold_mins", 1, 240, 0, 241),
        ("filter_clean_interval_months", 1, 24, 0, 25),
        ("salt_cell_replacement_months", 12, 120, 11, 121),
    ],
)
def test_g_boundary_validation_all_range_fields(
    field, lo, hi, bad_under, bad_over,
):
    """For each of the three remaining range-bounded fields, verify:
      * exact lower edge accepts,
      * exact upper edge accepts,
      * one-under-lower rejects,
      * one-over-upper rejects.
    """
    from pydantic import ValidationError
    from routers.tenants import AutomationRulesPatch

    # Edges pass.
    m_lo = AutomationRulesPatch(**{field: lo})
    m_hi = AutomationRulesPatch(**{field: hi})
    assert getattr(m_lo, field) == lo
    assert getattr(m_hi, field) == hi

    # Over/under fail.
    with pytest.raises(ValidationError):
        AutomationRulesPatch(**{field: bad_under})
    with pytest.raises(ValidationError):
        AutomationRulesPatch(**{field: bad_over})


# ═════════════════════════════════════════════════════════════════════
# GET-endpoint role-gate smoke — companion to the PATCH gate.
# ═════════════════════════════════════════════════════════════════════
def test_get_endpoint_role_gate(dbc, cleanup):
    """Techs / customers / members can't READ automation rules
    either — the GET endpoint mirrors the PATCH's role gate but
    adds ``manager`` to the allow-list."""
    from fastapi import HTTPException
    tid = _seed_tenant(dbc, with_rules={
        "dispatch_delay_threshold_mins": 20,
        "dispatch_sms_customer_count": 3,
        "filter_clean_interval_months": 6,
        "salt_cell_replacement_months": 36,
    })
    cleanup.append(tid)
    tenant_doc = dbc.tenants.find_one({"id": tid}, {"_id": 0})

    async def _apply_bad():
        from routers.tenants import get_own_automation_rules
        return await get_own_automation_rules(
            user={"role": "technician", "id": "u1", "tenant_id": tid},
            tenant=tenant_doc,
        )

    async def _apply_ok():
        from routers.tenants import get_own_automation_rules
        return await get_own_automation_rules(
            user={"role": "manager", "id": "u1", "tenant_id": tid},
            tenant=tenant_doc,
        )

    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(HTTPException) as excinfo:
            loop.run_until_complete(_apply_bad())
        assert excinfo.value.status_code == 403
        out = loop.run_until_complete(_apply_ok())
        assert out["dispatch_delay_threshold_mins"] == 20
    finally:
        loop.close()
