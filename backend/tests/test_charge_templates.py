"""Phase F2 · Feb-2026 — Charge Template Bundles tests.

Covers:
  1. CRUD happy paths (create → get → list → update → soft-delete).
  2. RBAC — admin can create/update/delete, tech is read-only + can apply,
     customer is 403.
  3. Name uniqueness (case-insensitive, per tenant).
  4. Soft-delete — archived rows excluded from default list.
  5. apply-to-job appends without replacing existing line items and
     recomputes job_totals.
  6. Tenant isolation — tenant A cannot see, edit, or apply tenant B's
     templates (404 across the wire).
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException

from tests._f7_loop_fixture import run_test


TEST_PREFIX = "TEST_F2_"


async def _seed_common(db):
    """Load the aquaterra tenant + one admin/tech user.  Returns
    ``(tid, admin, tech, customer)``."""
    tenant = await db.tenants.find_one({"slug": "aquaterra"},
                                         {"_id": 0, "id": 1})
    tid = tenant["id"]
    admin = await db.users.find_one({"email": "admin@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1, "email": 1})
    tech = await db.users.find_one({"email": "carlos@aquaterra.com"},
                                     {"_id": 0, "id": 1, "role": 1, "email": 1})
    customer = {"id": "cust-" + uuid.uuid4().hex[:6],
                "role": "customer",
                "email": "cust@example.com"}
    return tid, admin, tech, customer


async def _cleanup(db, tid):
    await db.charge_templates.delete_many(
        {"tenant_id": tid, "name": {"$regex": f"^{TEST_PREFIX}"}},
    )
    await db.jobs.delete_many(
        {"tenant_id": tid, "id": {"$regex": f"^{TEST_PREFIX}JOB"}},
    )


def _template_body(name_suffix="A") -> dict:
    return {
        "name": f"{TEST_PREFIX}Chlorine Shock Combo {name_suffix}",
        "description": "Standard chlorine shock bundle",
        "category": "chemicals",
        "line_items": [
            {"name": "Cal-Hypo Shock 1lb", "unit_price": 12.5, "quantity": 2,
             "category": "chemicals"},
            {"name": "Brush Service", "unit_price": 15.0, "quantity": 1,
             "category": "labor"},
            {"name": "Labor", "unit_price": 45.0, "quantity": 1,
             "category": "labor"},
        ],
    }


# ─── 1. CRUD happy path ────────────────────────────────────────────────
def test_f2_crud_happy_path():
    from routers.charge_templates import (
        create_charge_template, get_charge_template,
        list_charge_templates, update_charge_template,
        delete_charge_template,
        ChargeTemplateIn, ChargeTemplatePatch,
    )

    async def _go(db):
        tid, admin, _tech, _cust = await _seed_common(db)
        await _cleanup(db, tid)
        try:
            body = _template_body("HAPPY")
            created = await create_charge_template(
                body=ChargeTemplateIn(**body), user=admin, tenant={"id": tid},
            )
            assert created["archived"] is False
            assert created["category"] == "chemicals"
            assert len(created["line_items"]) == 3
            tpl_id = created["id"]

            got = await get_charge_template(
                tid=tpl_id, user=admin, tenant={"id": tid},
            )
            assert got["id"] == tpl_id

            listed = await list_charge_templates(
                include_archived=False, user=admin, tenant={"id": tid},
            )
            names = [r["name"] for r in listed["templates"]]
            assert body["name"] in names

            updated = await update_charge_template(
                tid=tpl_id,
                body=ChargeTemplatePatch(description="Updated bundle desc"),
                user=admin, tenant={"id": tid},
            )
            assert updated["description"] == "Updated bundle desc"

            del_res = await delete_charge_template(
                tid=tpl_id, user=admin, tenant={"id": tid},
            )
            assert del_res["archived"] is True

            # After archive, default list must exclude it.
            listed2 = await list_charge_templates(
                include_archived=False, user=admin, tenant={"id": tid},
            )
            assert tpl_id not in [r["id"] for r in listed2["templates"]]
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── 2. RBAC — tech read-only, customer 403 ────────────────────────────
def test_f2_rbac_tech_cannot_create():
    from routers.charge_templates import (
        create_charge_template, list_charge_templates,
        ChargeTemplateIn,
    )

    async def _go(db):
        tid, admin, tech, _cust = await _seed_common(db)
        await _cleanup(db, tid)
        try:
            # Admin creates one so the tech can list-read it.
            body = _template_body("RBAC")
            created = await create_charge_template(
                body=ChargeTemplateIn(**body),
                user=admin, tenant={"id": tid},
            )

            # Tech CAN list.
            listed = await list_charge_templates(
                include_archived=False, user=tech, tenant={"id": tid},
            )
            assert created["id"] in [r["id"] for r in listed["templates"]]

            # Tech CANNOT create.
            try:
                await create_charge_template(
                    body=ChargeTemplateIn(**_template_body("TECH_BLOCK")),
                    user=tech, tenant={"id": tid},
                )
                raise AssertionError("expected 403 for tech creating")
            except HTTPException as e:
                assert e.status_code == 403
        finally:
            await _cleanup(db, tid)

    run_test(_go)


def test_f2_rbac_customer_is_403():
    from routers.charge_templates import (
        list_charge_templates, create_charge_template,
        ChargeTemplateIn,
    )

    async def _go(db):
        tid, _admin, _tech, cust = await _seed_common(db)
        await _cleanup(db, tid)
        try:
            try:
                await list_charge_templates(
                    include_archived=False, user=cust, tenant={"id": tid},
                )
                raise AssertionError("expected 403 for customer listing")
            except HTTPException as e:
                assert e.status_code == 403
            try:
                await create_charge_template(
                    body=ChargeTemplateIn(**_template_body("CUST_BLOCK")),
                    user=cust, tenant={"id": tid},
                )
                raise AssertionError("expected 403 for customer creating")
            except HTTPException as e:
                assert e.status_code == 403
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── 3. Name uniqueness — case-insensitive, per tenant ────────────────
def test_f2_name_uniqueness_case_insensitive():
    from routers.charge_templates import (
        create_charge_template, ChargeTemplateIn,
    )

    async def _go(db):
        tid, admin, _tech, _cust = await _seed_common(db)
        await _cleanup(db, tid)
        try:
            await create_charge_template(
                body=ChargeTemplateIn(**_template_body("UNQ")),
                user=admin, tenant={"id": tid},
            )
            dup = dict(_template_body("UNQ"))
            # SAME name but upper-cased — still a conflict.
            dup["name"] = dup["name"].upper()
            try:
                await create_charge_template(
                    body=ChargeTemplateIn(**dup),
                    user=admin, tenant={"id": tid},
                )
                raise AssertionError("expected 409 on case-insensitive dup")
            except HTTPException as e:
                assert e.status_code == 409
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── 4. apply-to-job appends without replacing ─────────────────────────
def test_f2_apply_to_job_appends_line_items():
    from routers.charge_templates import (
        create_charge_template, apply_template_to_job,
        ChargeTemplateIn,
    )

    async def _go(db):
        tid, admin, tech, _cust = await _seed_common(db)
        await _cleanup(db, tid)
        job_id = f"{TEST_PREFIX}JOB_" + uuid.uuid4().hex[:6]
        try:
            # Seed a job with 1 existing line item.
            existing_li = {
                "id": "li-existing",
                "name": "Existing chlorine tabs",
                "unit_price": 9.0, "quantity": 3, "subtotal": 27.0,
            }
            await db.jobs.insert_one({
                "id": job_id, "tenant_id": tid, "customer_id": "x",
                "title": f"{TEST_PREFIX}job", "status": "scheduled",
                "line_items": [existing_li],
            })
            created = await create_charge_template(
                body=ChargeTemplateIn(**_template_body("APPLY")),
                user=admin, tenant={"id": tid},
            )
            # Tech CAN apply (per brief).
            res = await apply_template_to_job(
                tid=created["id"], jid=job_id,
                user=tech, tenant={"id": tid},
            )
            assert res["ok"] is True
            assert res["added_count"] == 3
            # Existing line item still first, template items appended.
            assert res["line_items"][0]["id"] == "li-existing"
            assert len(res["line_items"]) == 1 + 3
            # Totals reflect existing 27.0 + template (12.5*2 + 15 + 45 = 85).
            expected_sub = round(27.0 + 25.0 + 15.0 + 45.0, 2)
            assert res["job_totals"]["subtotal"] == expected_sub

            # DB was persisted.
            job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
            assert len(job["line_items"]) == 4
            # Provenance stamp is present on each appended row.
            appended = [li for li in job["line_items"]
                        if li.get("applied_from_template_id") == created["id"]]
            assert len(appended) == 3
            # Template usage counters bumped.
            tpl = await db.charge_templates.find_one({"id": created["id"]},
                                                       {"_id": 0})
            assert tpl.get("apply_count") == 1
            assert tpl.get("last_used_at") is not None
        finally:
            await _cleanup(db, tid)

    run_test(_go)


# ─── 5. Tenant isolation ───────────────────────────────────────────────
def test_f2_tenant_isolation():
    from routers.charge_templates import (
        create_charge_template, get_charge_template,
        list_charge_templates, apply_template_to_job,
        ChargeTemplateIn,
    )

    async def _go(db):
        tid_a, admin_a, _tech, _cust = await _seed_common(db)
        tid_b = f"{TEST_PREFIX}TENANT_B_" + uuid.uuid4().hex[:6]
        admin_b = {"id": "admin-B", "role": "admin",
                   "email": "b@example.com", "tenant_id": tid_b}
        await _cleanup(db, tid_a)
        try:
            # Seed tenant B row so we can insert into isolated tenant.
            await db.tenants.insert_one({"id": tid_b, "slug": tid_b.lower(),
                                            "name": "Test Tenant B"})
            # Admin A creates a template in tenant A.
            created = await create_charge_template(
                body=ChargeTemplateIn(**_template_body("ISO")),
                user=admin_a, tenant={"id": tid_a},
            )
            # Admin B's list must NOT see tenant A rows.
            listed_b = await list_charge_templates(
                include_archived=False, user=admin_b, tenant={"id": tid_b},
            )
            assert created["id"] not in [r["id"] for r in listed_b["templates"]]
            # Admin B's GET of tenant A's template must 404.
            try:
                await get_charge_template(
                    tid=created["id"], user=admin_b, tenant={"id": tid_b},
                )
                raise AssertionError("expected 404 cross-tenant read")
            except HTTPException as e:
                assert e.status_code == 404
            # apply-to-job across tenants must 404 on the template lookup.
            job_b_id = f"{TEST_PREFIX}JOB_B_" + uuid.uuid4().hex[:6]
            await db.jobs.insert_one({
                "id": job_b_id, "tenant_id": tid_b, "customer_id": "x",
                "title": f"{TEST_PREFIX}job B", "status": "scheduled",
                "line_items": [],
            })
            try:
                await apply_template_to_job(
                    tid=created["id"], jid=job_b_id,
                    user=admin_b, tenant={"id": tid_b},
                )
                raise AssertionError("expected 404 cross-tenant apply")
            except HTTPException as e:
                assert e.status_code == 404
        finally:
            await _cleanup(db, tid_a)
            await db.charge_templates.delete_many({"tenant_id": tid_b})
            await db.jobs.delete_many({"tenant_id": tid_b})
            await db.tenants.delete_many({"id": tid_b})

    run_test(_go)


# ─── 6. Soft-delete excludes from list ─────────────────────────────────
def test_f2_soft_delete_excludes_from_default_list():
    from routers.charge_templates import (
        create_charge_template, delete_charge_template,
        list_charge_templates, ChargeTemplateIn,
    )

    async def _go(db):
        tid, admin, _tech, _cust = await _seed_common(db)
        await _cleanup(db, tid)
        try:
            created = await create_charge_template(
                body=ChargeTemplateIn(**_template_body("SOFT")),
                user=admin, tenant={"id": tid},
            )
            await delete_charge_template(
                tid=created["id"], user=admin, tenant={"id": tid},
            )
            default = await list_charge_templates(
                include_archived=False, user=admin, tenant={"id": tid},
            )
            assert created["id"] not in [r["id"] for r in default["templates"]]
            with_archived = await list_charge_templates(
                include_archived=True, user=admin, tenant={"id": tid},
            )
            assert created["id"] in [r["id"] for r in with_archived["templates"]]
        finally:
            await _cleanup(db, tid)

    run_test(_go)
