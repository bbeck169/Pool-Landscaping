"""Phase P31 · Feb-2026 — Customer counts aggregation endpoint.

Locks in ``GET /api/customers/counts`` behavior:

1. Returns all 9 counts in a single response envelope.
2. Byte-for-byte parity with the pre-P31 nine-call
   ``count_only=true`` fanout on the same seeded dataset.
3. Tenant isolation — customers in tenant B don't leak into
   tenant A's counts.
4. Chip composition — the four tab counts (``active`` / ``inactive``
   / ``muted`` / ``waitlist``) honor the caller-provided global
   chips (``missing_email`` / ``missing_phone`` / ``missing_address``
   / ``portal_activated`` / ``has_payment_method`` / ``city`` /
   ``tags``); the five standalone badges DON'T compose (stability
   contract preserved).
5. RBAC — technician callers get ``muted``/``waitlist`` as ``None``
   (matches the pre-P31 per-endpoint 403 that the FE handled by
   skipping the calls).

Runs on the F7 loop-bound Mongo via direct function calls.
"""
from __future__ import annotations

import uuid

from tests._f7_loop_fixture import run_test


# ═════════════════════════════════════════════════════════════════════
# Seed helpers — mirror the ``list_customers`` count-branch filters.
# ═════════════════════════════════════════════════════════════════════
async def _seed(db, *, tenant_id, **fields):
    doc = {
        "id": f"c-{uuid.uuid4().hex[:8]}",
        "tenant_id": tenant_id,
        "name": fields.pop("name", "Test Customer"),
        "email": fields.pop("email", "test@example.com"),
        "phone": fields.pop("phone", "+15555550100"),
        "is_active": fields.pop("is_active", True),
    }
    doc.update(fields)
    await db.customers.insert_one(doc)
    return doc["id"]


# ═════════════════════════════════════════════════════════════════════
# 1. Endpoint returns all nine keys — happy path.
# ═════════════════════════════════════════════════════════════════════
def test_p31_counts_endpoint_returns_all_nine_keys():
    from routers.customers import customer_counts

    async def _go(db):
        tid = f"t-p31c-{uuid.uuid4().hex[:6]}"
        cids = []
        # 3 active, 2 inactive, 1 muted, 1 waitlisted.
        for _ in range(3):
            cids.append(await _seed(db, tenant_id=tid, is_active=True))
        for _ in range(2):
            cids.append(await _seed(
                db, tenant_id=tid, is_active=False,
            ))
        cids.append(await _seed(
            db, tenant_id=tid, is_active=True, is_muted=True,
        ))
        cids.append(await _seed(
            db, tenant_id=tid, is_active=True, waitlisted=True,
        ))
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "P31 Counts Tenant"}
            res = await customer_counts(user=user, tenant=tenant)
            # Coerce to dict for easy assertions.
            payload = res.model_dump()
            for key in (
                "active", "inactive", "muted", "waitlist",
                "missing_address", "portal_activated",
                "portal_not_activated", "no_payment_method",
                "never_logged_in",
            ):
                assert key in payload, f"missing key: {key}"
            # Active includes muted + waitlisted (they don't set
            # is_active=False), matching ``list_customers`` behavior.
            assert payload["active"] >= 3
            assert payload["inactive"] == 2
            assert payload["muted"] == 1
            assert payload["waitlist"] == 1
        finally:
            await db.customers.delete_many({"id": {"$in": cids}})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 2. Byte-for-byte parity with pre-P31 fanout.
# ═════════════════════════════════════════════════════════════════════
def test_p31_counts_parity_with_legacy_fanout():
    """The 9-in-1 endpoint MUST return the same numbers as the 9
    separate ``count_only=true`` calls on identical inputs."""
    from routers.customers import customer_counts, list_customers

    async def _go(db):
        tid = f"t-p31p-{uuid.uuid4().hex[:6]}"
        cids = []
        # Mix of statuses to exercise every count.
        for _ in range(4):
            cids.append(await _seed(db, tenant_id=tid, is_active=True))
        for _ in range(3):
            cids.append(await _seed(db, tenant_id=tid, is_active=False))
        cids.append(await _seed(
            db, tenant_id=tid, is_active=True,
            service_address="",  # missing address
            service_street="", service_city="", service_state="",
            service_zip="", street="", city="", state="", zip="",
        ))
        cids.append(await _seed(
            db, tenant_id=tid, is_active=True,
            portal_password_set_at="2026-01-01T00:00:00Z",
        ))
        cids.append(await _seed(
            db, tenant_id=tid, is_active=True,
            saved_payment_methods_count=0,
        ))
        cids.append(await _seed(
            db, tenant_id=tid, is_active=True,
            saved_payment_methods_count=1,
        ))
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "P31 Parity"}

            # Legacy — 9 separate calls with the exact param shapes
            # the pre-P31 FE fired.
            async def _leg(**overrides):
                base = {
                    "user": user, "tenant": tenant,
                    "search": None, "tag": None, "tags": None,
                    "city": None,
                    "waitlisted": None, "unscheduled": None,
                    "is_active": None, "missing_card": None,
                    "missing_email": False, "missing_phone": False,
                    "missing_address": False,
                    "portal_activated": None,
                    "portal_invited": None,
                    "first_access": None,
                    "portal_status": None,
                    "is_muted": None,
                    "has_payment_method": None,
                    "count_only": True,
                    "include_deleted": False, "include_merged": False,
                    "page": None, "page_size": None,
                    "sort": "created_desc",
                }
                base.update(overrides)
                r = await list_customers(**base)
                return int(r["count"]) if isinstance(r, dict) else int(r.count)

            legacy = {
                "active": await _leg(is_active=True),
                "inactive": await _leg(is_active=False),
                "muted": await _leg(is_muted=True),
                "waitlist": await _leg(waitlisted=True),
                "missing_address": await _leg(missing_address=True),
                "portal_activated": await _leg(portal_activated=True),
                "portal_not_activated": await _leg(portal_activated=False),
                "no_payment_method": await _leg(has_payment_method=False),
                "never_logged_in": await _leg(first_access="never"),
            }

            # New endpoint — one call.
            res = await customer_counts(user=user, tenant=tenant)
            new = res.model_dump()

            for k, v in legacy.items():
                assert new[k] == v, (
                    f"Parity mismatch on '{k}': "
                    f"legacy={v} new={new[k]}"
                )
        finally:
            await db.customers.delete_many({"id": {"$in": cids}})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 3. Tenant isolation.
# ═════════════════════════════════════════════════════════════════════
def test_p31_counts_tenant_isolation():
    from routers.customers import customer_counts

    async def _go(db):
        tid_a = f"t-p31a-{uuid.uuid4().hex[:6]}"
        tid_b = f"t-p31b-{uuid.uuid4().hex[:6]}"
        cids_a, cids_b = [], []
        for _ in range(2):
            cids_a.append(await _seed(db, tenant_id=tid_a, is_active=True))
        for _ in range(5):
            cids_b.append(await _seed(db, tenant_id=tid_b, is_active=True))
        try:
            user = {"id": "u-adm", "role": "admin"}
            res_a = await customer_counts(
                user=user, tenant={"id": tid_a, "name": "A"},
            )
            res_b = await customer_counts(
                user=user, tenant={"id": tid_b, "name": "B"},
            )
            assert res_a.model_dump()["active"] == 2
            assert res_b.model_dump()["active"] == 5
        finally:
            await db.customers.delete_many(
                {"id": {"$in": cids_a + cids_b}},
            )

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 4. Chip composition on tab counts + stability on badges.
# ═════════════════════════════════════════════════════════════════════
def test_p31_counts_tab_composes_but_standalone_stable():
    """Passing ``missing_address=true`` narrows the ``active`` count
    (tab counts compose) but the ``missing_address`` badge stays
    at the tenant total (standalone stability)."""
    from routers.customers import customer_counts

    async def _go(db):
        tid = f"t-p31s-{uuid.uuid4().hex[:6]}"
        cids = []
        # 5 active customers; give 3 a real service_address (so they
        # DON'T match the missing-address predicate) and 2 blank.
        for i in range(5):
            if i < 3:
                # Populated address — doesn't match "missing address".
                addr_fields = {
                    "service_address": "123 Main St",
                    "service_street": "123 Main St",
                    "service_city": "Anytown",
                    "service_state": "AZ",
                    "service_zip": "85000",
                }
            else:
                addr_fields = {
                    "service_address": "",
                    "service_street": "", "service_city": "",
                    "service_state": "", "service_zip": "",
                    "street": "", "city": "", "state": "", "zip": "",
                }
            cids.append(await _seed(
                db, tenant_id=tid, is_active=True, **addr_fields,
            ))
        try:
            user = {"id": "u-adm", "role": "admin"}
            tenant = {"id": tid, "name": "P31 Compose"}
            # No chip active.
            r0 = (await customer_counts(user=user, tenant=tenant)).model_dump()
            assert r0["active"] == 5
            assert r0["missing_address"] == 2
            # Chip active — ``active`` narrows to only the missing-
            # address subset (composes); ``missing_address`` badge
            # stays at 2 (does NOT compose).
            r1 = (await customer_counts(
                user=user, tenant=tenant, missing_address=True,
            )).model_dump()
            assert r1["active"] == 2
            assert r1["missing_address"] == 2
        finally:
            await db.customers.delete_many({"id": {"$in": cids}})

    run_test(_go)


# ═════════════════════════════════════════════════════════════════════
# 5. Technician role — muted / waitlist come back as None.
# ═════════════════════════════════════════════════════════════════════
def test_p31_counts_tech_role_omits_admin_only_counts():
    from routers.customers import customer_counts

    async def _go(db):
        tid = f"t-p31t-{uuid.uuid4().hex[:6]}"
        cid = await _seed(db, tenant_id=tid, is_active=True)
        try:
            user = {"id": "u-tech", "role": "technician"}
            tenant = {"id": tid, "name": "P31 Tech"}
            res = await customer_counts(user=user, tenant=tenant)
            payload = res.model_dump()
            assert payload["muted"] is None
            assert payload["waitlist"] is None
            # Non-admin-gated counts still populate.
            assert isinstance(payload["active"], int)
            assert isinstance(payload["missing_address"], int)
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)
