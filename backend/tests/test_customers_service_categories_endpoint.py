"""Feb-2026 · Customers list — Service Category distinct-values pytest.

Covers ``GET /api/customers/service-categories``:

  1. Returns distinct in-use values + per-value counts.
  2. Sorted by count desc, value asc.
  3. ``uncategorized_count`` captures null / missing / empty-string
     / whitespace-only buckets (NOT counted inside ``categories``).
  4. Cross-tenant isolation — values from tenant B don't leak into
     tenant A's response.
  5. Soft-deleted customers excluded.
  6. Custom (non-canonical) service_category values surface in
     the distinct list — defensive for legacy data.
  7. Empty-tenant → ``{categories: [], uncategorized_count: 0}``.

Synthetic data only.
"""
from __future__ import annotations

import uuid

from dotenv import load_dotenv

from tests._f7_loop_fixture import run_test


load_dotenv("/app/backend/.env")


def _tid() -> str:
    return f"test-sc-cat-{uuid.uuid4()}"


async def _seed_customer(
    db, tenant_id: str, *, service_category=None,
    deleted: bool = False,
) -> str:
    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "name": f"Cust {uuid.uuid4().hex[:6]}",
    }
    # Only set the key when the caller explicitly passed something
    # (including an empty string) so we can also exercise the
    # "key missing entirely" branch by passing ``service_category
    # =_SENTINEL_MISSING``.
    if service_category is not _SENTINEL_MISSING:
        doc["service_category"] = service_category
    if deleted:
        doc["deleted_at"] = "2026-01-01T00:00:00Z"
    await db.customers.insert_one(doc)
    return doc["id"]


_SENTINEL_MISSING = object()


async def _cleanup(db, *tids: str):
    for tid in tids:
        await db.customers.delete_many({"tenant_id": tid})


async def _call_endpoint(tenant_id: str):
    """Exercise the endpoint fn directly with injected deps."""
    from routers.customers import list_customer_service_categories
    return await list_customer_service_categories(
        user={"id": "u1", "role": "admin"},
        tenant={"id": tenant_id},
    )


# ─── 1 · distinct in-use values + counts ─────────────────────────
def test_distinct_values_with_counts():
    tid = _tid()

    async def _run(db):
        try:
            for _ in range(3):
                await _seed_customer(
                    db, tid, service_category="pool",
                )
            for _ in range(2):
                await _seed_customer(
                    db, tid, service_category="landscaping",
                )
            await _seed_customer(
                db, tid, service_category="both",
            )
            resp = await _call_endpoint(tid)
            values = {c["value"]: c["count"] for c in resp["categories"]}
            assert values == {"pool": 3, "landscaping": 2, "both": 1}
            assert resp["uncategorized_count"] == 0
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 2 · sort order · count desc, value asc ──────────────────────
def test_sort_order_count_desc_then_value_asc():
    tid = _tid()

    async def _run(db):
        try:
            # 2 "pool", 2 "both" → tied counts; must break on value asc.
            for _ in range(2):
                await _seed_customer(
                    db, tid, service_category="pool",
                )
                await _seed_customer(
                    db, tid, service_category="both",
                )
            await _seed_customer(
                db, tid, service_category="landscaping",
            )
            resp = await _call_endpoint(tid)
            order = [c["value"] for c in resp["categories"]]
            # 2:both, 2:pool (tie → value asc), 1:landscaping.
            assert order == ["both", "pool", "landscaping"]
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 3 · uncategorized bucket captures null / missing / empty ────
def test_uncategorized_captures_null_missing_empty_and_whitespace():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_customer(
                db, tid, service_category="pool",
            )
            # null
            await _seed_customer(db, tid, service_category=None)
            # missing entirely
            await _seed_customer(
                db, tid, service_category=_SENTINEL_MISSING,
            )
            # empty string
            await _seed_customer(db, tid, service_category="")
            # whitespace only
            await _seed_customer(db, tid, service_category="   ")
            resp = await _call_endpoint(tid)
            # 1 "pool", 4 uncategorized.
            assert resp["uncategorized_count"] == 4
            vals = {c["value"] for c in resp["categories"]}
            assert vals == {"pool"}
            # Uncategorized does NOT leak into categories[] as null,
            # empty, or whitespace keys.
            assert not any(
                not (c["value"] or "").strip()
                for c in resp["categories"]
            )
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 4 · cross-tenant isolation ──────────────────────────────────
def test_cross_tenant_values_do_not_bleed():
    tid_a = _tid()
    tid_b = _tid()

    async def _run(db):
        try:
            await _seed_customer(
                db, tid_a, service_category="pool",
            )
            # Tenant B has a totally different custom category.
            for _ in range(5):
                await _seed_customer(
                    db, tid_b, service_category="HVAC",
                )
            resp_a = await _call_endpoint(tid_a)
            vals_a = {c["value"] for c in resp_a["categories"]}
            assert vals_a == {"pool"}
            assert "HVAC" not in vals_a
        finally:
            await _cleanup(db, tid_a, tid_b)

    run_test(_run)


# ─── 5 · soft-deleted customers excluded ─────────────────────────
def test_soft_deleted_customers_excluded_from_distinct_values():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_customer(
                db, tid, service_category="pool",
            )
            await _seed_customer(
                db, tid, service_category="pool", deleted=True,
            )
            await _seed_customer(
                db, tid, service_category=None, deleted=True,
            )
            resp = await _call_endpoint(tid)
            # Only the one live customer counts.
            values = {c["value"]: c["count"] for c in resp["categories"]}
            assert values == {"pool": 1}
            assert resp["uncategorized_count"] == 0
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 6 · custom (non-canonical) values surface ───────────────────
def test_custom_values_surface_in_distinct_list():
    tid = _tid()

    async def _run(db):
        try:
            await _seed_customer(
                db, tid, service_category="pool",
            )
            for _ in range(3):
                await _seed_customer(
                    db, tid, service_category="HVAC",
                )
            await _seed_customer(
                db, tid, service_category="Chemical Only",
            )
            resp = await _call_endpoint(tid)
            values = {c["value"]: c["count"] for c in resp["categories"]}
            assert values == {
                "HVAC": 3, "pool": 1, "Chemical Only": 1,
            }
            # Sort: HVAC first (3), then tie-break between "Chemical
            # Only" and "pool" on value asc → "Chemical Only", "pool".
            order = [c["value"] for c in resp["categories"]]
            assert order == ["HVAC", "Chemical Only", "pool"]
        finally:
            await _cleanup(db, tid)

    run_test(_run)


# ─── 7 · empty tenant ────────────────────────────────────────────
def test_empty_tenant_returns_empty_response():
    tid = _tid()

    async def _run(db):
        try:
            resp = await _call_endpoint(tid)
            assert resp == {
                "categories": [],
                "uncategorized_count": 0,
            }
        finally:
            await _cleanup(db, tid)

    run_test(_run)
