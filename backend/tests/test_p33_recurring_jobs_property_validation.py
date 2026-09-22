"""Phase P33 · Feb-2026 — Recurring-jobs router property validation.

Covers the P33 back-half contract:

1. Happy path — create with valid customer + valid property.
2. Cross-customer property → 400 ``property_not_on_customer``.
3. Unknown property_id → 404 ``property_not_found``.
4. Multi-property customer, no property_id → 400 ``property_required``.
5. Single-property customer, no property_id → 200, server auto-fills.
6. Zero-property customer + any property_id → 400
   ``customer_has_no_properties``.
7. PATCH changing property_id to another customer's property → 400.
8. PATCH changing customer_id AND property_id in same request →
   validator runs on the new pair.
9. Tenant isolation — a property from a different tenant is a 404.

Uses the F7 loop-bound Mongo via direct function calls (no HTTP
stack) so the assertions bind to the router's Python contract.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


# ═════════════════════════════════════════════════════════════════════
# Seed helpers.
# ═════════════════════════════════════════════════════════════════════
async def _seed_customer(db, tenant_id, *, cid=None):
    cid = cid or f"c-{uuid.uuid4().hex[:8]}"
    await db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "P33 Customer", "email": "p33@example.test",
        "is_active": True,
    })
    return cid


async def _seed_property(db, tenant_id, customer_id, *, pid=None,
                          label="Home", line1="123 Main St",
                          sort_order=0):
    pid = pid or f"p-{uuid.uuid4().hex[:8]}"
    await db.properties.insert_one({
        "id": pid, "tenant_id": tenant_id, "customer_id": customer_id,
        "label": label, "active": True, "sort_order": sort_order,
        "address": {"line1": line1, "city": "Anytown"},
        "created_at": "2026-02-01T00:00:00Z",
    })
    return pid


def _body(**overrides):
    """Return kwargs for ``RecurringJobIn`` — start from a valid
    weekly template so tests only override the P33-relevant fields."""
    base: Dict[str, Any] = {
        "customer_id": None,
        "service_type": "Pool Cleaning",
        "frequency": "weekly",
        "day_of_week": 1,
        "start_date": "2026-02-05",
        "price_cents": 12000,
        "assigned_tech_id": None,
        "crew_id": None,
        "active": True,
        "is_active": False,
        "notes": "",
        "recurrence_never_ends": True,
        "end_date": None,
        "property_id": None,
    }
    base.update(overrides)
    return base


def _admin_user():
    return {"id": "u-adm", "role": "admin", "email": "adm@p33.test"}


# ═════════════════════════════════════════════════════════════════════
# 1. Happy path.
# ═════════════════════════════════════════════════════════════════════
def test_p33_create_with_valid_customer_and_property_persists_property_id():
    from routers.recurring_jobs import create_recurring, RecurringJobIn

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid = await _seed_customer(db, tid)
        pid_a = await _seed_property(db, tid, cid)
        pid_b = await _seed_property(db, tid, cid, label="Vacation",
                                        line1="9 Beach Rd",
                                        sort_order=1)
        try:
            payload = _body(customer_id=cid, property_id=pid_b)
            body_obj = RecurringJobIn(**payload)
            res = await create_recurring(
                body_obj, user=_admin_user(),
                tenant={"id": tid, "name": "P33"},
            )
            assert res["property_id"] == pid_b
            assert res["customer_id"] == cid
            # DB row also carries it.
            row = await db.recurring_job_templates.find_one(
                {"id": res["id"]}, {"_id": 0, "property_id": 1},
            )
            assert row["property_id"] == pid_b
        finally:
            await db.recurring_job_templates.delete_many({"customer_id": cid})
            await db.properties.delete_many({"id": {"$in": [pid_a, pid_b]}})
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 2. Cross-customer property → 400.
# ═════════════════════════════════════════════════════════════════════
def test_p33_create_with_property_from_different_customer_rejects_400():
    from routers.recurring_jobs import create_recurring, RecurringJobIn

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid_a = await _seed_customer(db, tid)
        cid_b = await _seed_customer(db, tid)
        pid_a = await _seed_property(db, tid, cid_a)   # owned by A
        pid_b = await _seed_property(db, tid, cid_b)   # owned by B
        try:
            payload = _body(customer_id=cid_a, property_id=pid_b)
            body_obj = RecurringJobIn(**payload)
            with pytest.raises(HTTPException) as ei:
                await create_recurring(
                    body_obj, user=_admin_user(),
                    tenant={"id": tid, "name": "P33"},
                )
            assert ei.value.status_code == 400
            assert ei.value.detail["code"] == "property_not_on_customer"
        finally:
            await db.properties.delete_many(
                {"id": {"$in": [pid_a, pid_b]}},
            )
            await db.customers.delete_many({"id": {"$in": [cid_a, cid_b]}})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 3. Unknown property_id → 404.
# ═════════════════════════════════════════════════════════════════════
def test_p33_create_with_unknown_property_id_returns_404():
    from routers.recurring_jobs import create_recurring, RecurringJobIn

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid = await _seed_customer(db, tid)
        pid_real = await _seed_property(db, tid, cid)
        bogus_pid = f"p-bogus-{uuid.uuid4().hex[:8]}"
        try:
            payload = _body(customer_id=cid, property_id=bogus_pid)
            body_obj = RecurringJobIn(**payload)
            with pytest.raises(HTTPException) as ei:
                await create_recurring(
                    body_obj, user=_admin_user(),
                    tenant={"id": tid, "name": "P33"},
                )
            assert ei.value.status_code == 404
            assert ei.value.detail["code"] == "property_not_found"
        finally:
            await db.properties.delete_one({"id": pid_real})
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 4. Multi-property customer, no property_id → 400 property_required.
# ═════════════════════════════════════════════════════════════════════
def test_p33_create_multi_property_customer_without_property_id_400():
    from routers.recurring_jobs import create_recurring, RecurringJobIn

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid = await _seed_customer(db, tid)
        pid_a = await _seed_property(db, tid, cid)
        pid_b = await _seed_property(db, tid, cid,
                                        label="Vacation")
        try:
            payload = _body(customer_id=cid, property_id=None)
            body_obj = RecurringJobIn(**payload)
            with pytest.raises(HTTPException) as ei:
                await create_recurring(
                    body_obj, user=_admin_user(),
                    tenant={"id": tid, "name": "P33"},
                )
            assert ei.value.status_code == 400
            assert ei.value.detail["code"] == "property_required"
        finally:
            await db.properties.delete_many(
                {"id": {"$in": [pid_a, pid_b]}},
            )
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 5. Single-property customer, no property_id → server auto-fills.
# ═════════════════════════════════════════════════════════════════════
def test_p33_create_single_property_customer_auto_fills_property_id():
    from routers.recurring_jobs import create_recurring, RecurringJobIn

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid = await _seed_customer(db, tid)
        pid = await _seed_property(db, tid, cid)
        try:
            payload = _body(customer_id=cid, property_id=None)
            body_obj = RecurringJobIn(**payload)
            res = await create_recurring(
                body_obj, user=_admin_user(),
                tenant={"id": tid, "name": "P33"},
            )
            # Server-side auto-fill.
            assert res["property_id"] == pid
        finally:
            await db.recurring_job_templates.delete_many({"customer_id": cid})
            await db.properties.delete_one({"id": pid})
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 6. Zero-property customer + any property_id → 400
#    customer_has_no_properties.
# ═════════════════════════════════════════════════════════════════════
def test_p33_create_zero_property_customer_with_pid_rejects_400():
    from routers.recurring_jobs import create_recurring, RecurringJobIn

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid = await _seed_customer(db, tid)
        # NO properties seeded for this customer.
        # But a property that BELONGS to nobody-here — we need any
        # property_id that could be sent; use a bogus id which
        # will fail on "no properties" gate BEFORE the ownership
        # check.
        bogus_pid = f"p-{uuid.uuid4().hex[:8]}"
        try:
            payload = _body(customer_id=cid, property_id=bogus_pid)
            body_obj = RecurringJobIn(**payload)
            with pytest.raises(HTTPException) as ei:
                await create_recurring(
                    body_obj, user=_admin_user(),
                    tenant={"id": tid, "name": "P33"},
                )
            assert ei.value.status_code == 400
            assert ei.value.detail["code"] == "customer_has_no_properties"
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 6b. Zero-property customer AND no property_id → allow-through
#     (legacy path — templates predating properties keep working).
# ═════════════════════════════════════════════════════════════════════
def test_p33_create_zero_property_customer_without_pid_is_allow_through():
    from routers.recurring_jobs import create_recurring, RecurringJobIn

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid = await _seed_customer(db, tid)
        try:
            payload = _body(customer_id=cid, property_id=None)
            body_obj = RecurringJobIn(**payload)
            res = await create_recurring(
                body_obj, user=_admin_user(),
                tenant={"id": tid, "name": "P33"},
            )
            # Legacy allow-through — property_id stays None.
            assert res.get("property_id") is None
        finally:
            await db.recurring_job_templates.delete_many({"customer_id": cid})
            await db.customers.delete_one({"id": cid})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 7. PATCH swap to another customer's property → 400.
# ═════════════════════════════════════════════════════════════════════
def test_p33_patch_property_swap_to_other_customer_rejects_400():
    from routers.recurring_jobs import (
        create_recurring, patch_recurring,
        RecurringJobIn, RecurringJobPatch,
    )

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid_a = await _seed_customer(db, tid)
        cid_b = await _seed_customer(db, tid)
        pid_a = await _seed_property(db, tid, cid_a)
        pid_b = await _seed_property(db, tid, cid_b)
        # Create a valid template for customer A.
        created = await create_recurring(
            RecurringJobIn(**_body(customer_id=cid_a, property_id=pid_a)),
            user=_admin_user(),
            tenant={"id": tid, "name": "P33"},
        )
        tpl_id = created["id"]
        try:
            # PATCH — swap to customer B's property while staying
            # on customer A.
            patch_body = RecurringJobPatch(property_id=pid_b)
            with pytest.raises(HTTPException) as ei:
                await patch_recurring(
                    tpl_id, patch_body, user=_admin_user(),
                    tenant={"id": tid, "name": "P33"},
                )
            assert ei.value.status_code == 400
            assert ei.value.detail["code"] == "property_not_on_customer"
        finally:
            await db.recurring_job_templates.delete_one({"id": tpl_id})
            await db.properties.delete_many(
                {"id": {"$in": [pid_a, pid_b]}},
            )
            await db.customers.delete_many({"id": {"$in": [cid_a, cid_b]}})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 8. PATCH changing customer AND property together → validator runs
#    on the new pair, succeeds when the new property owns the new
#    customer.
# ═════════════════════════════════════════════════════════════════════
def test_p33_patch_customer_and_property_together_validates_new_pair():
    from routers.recurring_jobs import (
        create_recurring, patch_recurring,
        RecurringJobIn, RecurringJobPatch,
    )

    async def _go(db):
        tid = f"t-p33-{uuid.uuid4().hex[:6]}"
        cid_a = await _seed_customer(db, tid)
        cid_b = await _seed_customer(db, tid)
        pid_a = await _seed_property(db, tid, cid_a)
        pid_b = await _seed_property(db, tid, cid_b)
        created = await create_recurring(
            RecurringJobIn(**_body(customer_id=cid_a, property_id=pid_a)),
            user=_admin_user(),
            tenant={"id": tid, "name": "P33"},
        )
        tpl_id = created["id"]
        try:
            # PATCH — new (customer_b, property_b) pair → valid.
            patch_body = RecurringJobPatch(
                customer_id=cid_b, property_id=pid_b,
            )
            res = await patch_recurring(
                tpl_id, patch_body, user=_admin_user(),
                tenant={"id": tid, "name": "P33"},
            )
            assert res["customer_id"] == cid_b
            assert res["property_id"] == pid_b
        finally:
            await db.recurring_job_templates.delete_one({"id": tpl_id})
            await db.properties.delete_many(
                {"id": {"$in": [pid_a, pid_b]}},
            )
            await db.customers.delete_many({"id": {"$in": [cid_a, cid_b]}})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 9. Tenant isolation — property from a different tenant is 404.
# ═════════════════════════════════════════════════════════════════════
def test_p33_create_cross_tenant_property_returns_404():
    from routers.recurring_jobs import create_recurring, RecurringJobIn

    async def _go(db):
        tid_a = f"t-p33a-{uuid.uuid4().hex[:6]}"
        tid_b = f"t-p33b-{uuid.uuid4().hex[:6]}"
        # Customer + real property in tenant A (so the "customer
        # has properties" gate passes) — then submit a property_id
        # that lives in tenant B, which the validator MUST 404
        # rather than accept OR enumerate.
        cid = await _seed_customer(db, tid_a)
        pid_a = await _seed_property(db, tid_a, cid)
        pid_b = await _seed_property(db, tid_b, cid,
                                        label="Cross-Tenant Leak",
                                        line1="9 Other Rd")
        try:
            payload = _body(customer_id=cid, property_id=pid_b)
            body_obj = RecurringJobIn(**payload)
            with pytest.raises(HTTPException) as ei:
                await create_recurring(
                    body_obj, user=_admin_user(),
                    # Caller is in tenant A — pid_b is invisible.
                    tenant={"id": tid_a, "name": "P33 A"},
                )
            # Validator returns 404 — pid_b doesn't exist from
            # tenant A's viewpoint (the property lookup is tenant-
            # scoped). NOT 400 property_not_on_customer because
            # the caller must not be able to distinguish "wrong
            # tenant" from "unknown id" (enumeration guard).
            assert ei.value.status_code == 404
            assert ei.value.detail["code"] == "property_not_found"
        finally:
            await db.properties.delete_many(
                {"id": {"$in": [pid_a, pid_b]}},
            )
            await db.customers.delete_one({"id": cid})

    run_test(_go)
