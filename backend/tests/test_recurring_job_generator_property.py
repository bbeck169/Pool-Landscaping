"""Feb-2026 · Part 2 · Recurring-job generator stamps property_id.

Regression coverage for the generator loop at
``backend/routers/recurring_jobs.py:_generate_from_template`` — the
loop used to copy ``cust.address`` (a text string) onto each new
job and never stamped ``property_id``, so every downstream
consumer (visit email, portal, invoicing) had to text-fallback.

Locks:
  1. Template with explicit ``property_id`` → generated job
     carries the same FK + the property's composed address.
  2. Template without ``property_id`` but customer has
     ``primary_property_id`` → job stamps that FK + address.
  3. Property was edited between template creation and job
     generation → generated job carries the CURRENT address.
  4. Neither template nor customer carries a property → job
     created without ``property_id`` and a warning logs.
  5. Template ``property_id`` points at a soft-deleted /
     cross-tenant property → falls back to ``cust.address``
     text + warning; no FK is fabricated.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import Any, Dict, Optional

import pytest

from tests._f7_loop_fixture import run_test


TENANT_MARKER_PREFIX = "cust-p2gen-"
TEMPLATE_MARKER_PREFIX = "tpl-p2gen-"


async def _tenant_id(db) -> str:
    row = await db.tenants.find_one(
        {"slug": "aquaterra"}, {"_id": 0, "id": 1},
    )
    return row["id"]


async def _seed_customer(db, tid: str, *,
                          primary_property_id: Optional[str] = None,
                          address: str = "TEXT ADDRESS 1") -> str:
    cid = f"{TENANT_MARKER_PREFIX}{uuid.uuid4().hex[:8]}"
    doc: Dict[str, Any] = {
        "id": cid, "tenant_id": tid,
        "name": "P2 gen fixture", "is_active": True,
        "address": address,
    }
    if primary_property_id:
        doc["primary_property_id"] = primary_property_id
    await db.customers.insert_one(doc)
    return cid


async def _seed_property(db, tid: str, cid: str, *,
                          line1: str, city: str = "Phoenix",
                          state: str = "AZ",
                          postal: str = "85027",
                          deleted: bool = False,
                          alt_tenant: Optional[str] = None,
                          ) -> str:
    pid = f"prop-p2gen-{uuid.uuid4().hex[:8]}"
    doc: Dict[str, Any] = {
        "id": pid, "tenant_id": alt_tenant or tid,
        "customer_id": cid,
        "label": "Main", "sort_order": 0, "is_primary": True,
        "address": {"line1": line1, "line2": None,
                    "city": city, "state": state,
                    "postal_code": postal, "country": "US"},
    }
    if deleted:
        doc["deleted_at"] = "2026-01-01T00:00:00Z"
    await db.properties.insert_one(doc)
    return pid


async def _seed_template(db, tid: str, cid: str, *,
                          property_id: Optional[str] = None,
                          ) -> str:
    tpl_id = f"{TEMPLATE_MARKER_PREFIX}{uuid.uuid4().hex[:8]}"
    doc: Dict[str, Any] = {
        "id": tpl_id, "tenant_id": tid, "customer_id": cid,
        "service_type": "Weekly service", "frequency": "weekly",
        "day_of_week": 0,
        "start_date": (date.today() - timedelta(days=7)).isoformat(),
        "price_cents": 12000, "active": True, "is_active": True,
        "recurrence_never_ends": True, "notes": "",
    }
    if property_id:
        doc["property_id"] = property_id
    await db.recurring_job_templates.insert_one(doc)
    return tpl_id


async def _cleanup(db, tid: str, *, cust_ids: list[str],
                    tpl_ids: list[str], prop_ids: list[str]):
    if cust_ids:
        await db.customers.delete_many(
            {"tenant_id": tid, "id": {"$in": cust_ids}})
        await db.jobs.delete_many(
            {"tenant_id": tid, "customer_id": {"$in": cust_ids}})
    if tpl_ids:
        await db.recurring_job_templates.delete_many(
            {"tenant_id": tid, "id": {"$in": tpl_ids}})
    if prop_ids:
        await db.properties.delete_many(
            {"id": {"$in": prop_ids}})


# ═══════════════════════════════════════════════════════════════════
# 1 · Explicit template.property_id → job carries FK + address.
# ═══════════════════════════════════════════════════════════════════
def test_generator_uses_template_property_id():
    from routers.recurring_jobs import _generate_from_template

    async def _go(db):
        tid = await _tenant_id(db)
        cid = await _seed_customer(db, tid)
        pid = await _seed_property(db, tid, cid,
                                       line1="3112 W Adobe Dam Rd")
        tpl_id = await _seed_template(db, tid, cid, property_id=pid)
        try:
            tpl = await db.recurring_job_templates.find_one(
                {"id": tpl_id}, {"_id": 0})
            through = date.today() + timedelta(days=14)
            result = await _generate_from_template(tpl, through)
            assert result["inserted"] >= 1
            jobs = await db.jobs.find(
                {"tenant_id": tid, "recurring_template_id": tpl_id},
                {"_id": 0, "property_id": 1, "address": 1},
            ).to_list(50)
            assert jobs, "expected at least one generated job"
            for j in jobs:
                assert j.get("property_id") == pid, (
                    f"FK not stamped: {j}")
                # Composed address uses the CURRENT property, not
                # ``cust.address`` text.
                assert j.get("address", "").startswith(
                    "3112 W Adobe Dam Rd"), j
        finally:
            await _cleanup(db, tid, cust_ids=[cid],
                              tpl_ids=[tpl_id], prop_ids=[pid])

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 2 · No template property_id → falls to customer.primary_property_id.
# ═══════════════════════════════════════════════════════════════════
def test_generator_falls_back_to_customer_primary_property_id():
    from routers.recurring_jobs import _generate_from_template

    async def _go(db):
        tid = await _tenant_id(db)
        # First seed the customer without a primary → we need the
        # customer id to attach the property.
        cid = await _seed_customer(db, tid)
        pid = await _seed_property(db, tid, cid,
                                       line1="500 Fallback Ln")
        # Now stamp primary_property_id onto the customer.
        await db.customers.update_one(
            {"id": cid},
            {"$set": {"primary_property_id": pid}},
        )
        tpl_id = await _seed_template(db, tid, cid, property_id=None)
        try:
            tpl = await db.recurring_job_templates.find_one(
                {"id": tpl_id}, {"_id": 0})
            through = date.today() + timedelta(days=14)
            await _generate_from_template(tpl, through)
            jobs = await db.jobs.find(
                {"tenant_id": tid, "recurring_template_id": tpl_id},
                {"_id": 0, "property_id": 1, "address": 1},
            ).to_list(50)
            for j in jobs:
                assert j.get("property_id") == pid
                assert j.get("address", "").startswith("500 Fallback Ln")
        finally:
            await _cleanup(db, tid, cust_ids=[cid],
                              tpl_ids=[tpl_id], prop_ids=[pid])

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 3 · Property edited between template creation + job generation →
# generated jobs carry the CURRENT address.
# ═══════════════════════════════════════════════════════════════════
def test_generator_reads_current_property_address():
    from routers.recurring_jobs import _generate_from_template

    async def _go(db):
        tid = await _tenant_id(db)
        cid = await _seed_customer(db, tid)
        pid = await _seed_property(db, tid, cid,
                                       line1="OLD PLACEHOLDER")
        tpl_id = await _seed_template(db, tid, cid, property_id=pid)
        try:
            # Admin edits the property AFTER the template was
            # created but BEFORE the nightly generator fires.
            await db.properties.update_one(
                {"id": pid},
                {"$set": {"address.line1": "3112 W Adobe Dam Rd"}},
            )
            tpl = await db.recurring_job_templates.find_one(
                {"id": tpl_id}, {"_id": 0})
            through = date.today() + timedelta(days=14)
            await _generate_from_template(tpl, through)
            jobs = await db.jobs.find(
                {"tenant_id": tid, "recurring_template_id": tpl_id},
                {"_id": 0, "property_id": 1, "address": 1},
            ).to_list(50)
            for j in jobs:
                assert j.get("property_id") == pid
                assert "OLD PLACEHOLDER" not in j.get("address", ""), j
                assert j.get("address", "").startswith(
                    "3112 W Adobe Dam Rd"), j
        finally:
            await _cleanup(db, tid, cust_ids=[cid],
                              tpl_ids=[tpl_id], prop_ids=[pid])

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 4 · Zero-property customer → job created without property_id
# AND a warning logs.
# ═══════════════════════════════════════════════════════════════════
def test_generator_zero_property_customer_logs_and_no_fk(caplog):
    from routers.recurring_jobs import _generate_from_template

    async def _go(db):
        tid = await _tenant_id(db)
        cid = await _seed_customer(db, tid, address="123 Bare St")
        # Note: NO property is seeded for this customer, and no
        # ``primary_property_id`` on the customer doc.
        tpl_id = await _seed_template(db, tid, cid, property_id=None)
        try:
            tpl = await db.recurring_job_templates.find_one(
                {"id": tpl_id}, {"_id": 0})
            through = date.today() + timedelta(days=14)
            with caplog.at_level(logging.WARNING, logger="server_api"):
                await _generate_from_template(tpl, through)
            jobs = await db.jobs.find(
                {"tenant_id": tid, "recurring_template_id": tpl_id},
                {"_id": 0, "property_id": 1, "address": 1},
            ).to_list(50)
            for j in jobs:
                assert "property_id" not in j, (
                    f"FK unexpectedly stamped on zero-property "
                    f"customer: {j}")
                # Falls back to the customer's text address.
                assert j.get("address") == "123 Bare St"
            assert any(
                "recurring_job.generator.no_property" in r.getMessage()
                for r in caplog.records
            ), "expected structured warning"
        finally:
            await _cleanup(db, tid, cust_ids=[cid],
                              tpl_ids=[tpl_id], prop_ids=[])

    run_test(_go)


# ═══════════════════════════════════════════════════════════════════
# 5 · Template property_id points at a soft-deleted property →
# falls back to text; no FK stamped; warning logs.
# ═══════════════════════════════════════════════════════════════════
def test_generator_soft_deleted_property_is_ignored(caplog):
    from routers.recurring_jobs import _generate_from_template

    async def _go(db):
        tid = await _tenant_id(db)
        cid = await _seed_customer(db, tid, address="OLD TEXT")
        pid = await _seed_property(db, tid, cid,
                                       line1="soft-deleted line",
                                       deleted=True)
        tpl_id = await _seed_template(db, tid, cid, property_id=pid)
        try:
            tpl = await db.recurring_job_templates.find_one(
                {"id": tpl_id}, {"_id": 0})
            through = date.today() + timedelta(days=14)
            with caplog.at_level(logging.WARNING, logger="server_api"):
                await _generate_from_template(tpl, through)
            jobs = await db.jobs.find(
                {"tenant_id": tid, "recurring_template_id": tpl_id},
                {"_id": 0, "property_id": 1, "address": 1},
            ).to_list(50)
            for j in jobs:
                assert "property_id" not in j
                assert j.get("address") == "OLD TEXT"
            assert any(
                "property_unresolved" in r.getMessage()
                and "not_found_or_deleted" in r.getMessage()
                for r in caplog.records
            )
        finally:
            await _cleanup(db, tid, cust_ids=[cid],
                              tpl_ids=[tpl_id], prop_ids=[pid])

    run_test(_go)
