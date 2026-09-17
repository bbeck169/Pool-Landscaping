"""Feb-2026 · Business Signup SP3 — canonical industry slug backfill.

Normalises historical tenant records that were written by SP1/SP2
with the legacy plural slug ``"pools"`` to the D1 canonical singular
``"pool"``. Also normalises the ``industries`` array (multi-select
step 4) so downstream cross-references never see the plural form.

Idempotent — a second run finds nothing to update and returns
``{"matched_primary": 0, "modified_primary": 0,
 "matched_array": 0, "modified_array": 0}``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("backfill_industry_slug_pools_to_pool")


async def run_backfill_industry_slug_pools_to_pool(db: Any) -> Dict[str, int]:
    """Convert every ``primary_industry == "pools"`` to ``"pool"``
    and rewrite ``industries`` arrays that contain ``"pools"`` to
    contain ``"pool"`` instead (dedup preserved)."""

    # 1) Primary-industry scalar field.
    primary_res = await db.tenants.update_many(
        {"primary_industry": "pools"},
        {"$set": {"primary_industry": "pool"}},
    )

    # 2) ``industries`` array — MongoDB's ``$[]`` positional-all
    # operator only rewrites in-place, so if a tenant already had
    # ``["pools", "pool"]`` we'd end up with ``["pool", "pool"]``.
    # Load-then-write per tenant is cheap here (this is a one-shot
    # backfill on a small collection).
    matched_array = 0
    modified_array = 0
    cursor = db.tenants.find(
        {"industries": "pools"}, {"_id": 0, "id": 1, "industries": 1},
    )
    async for doc in cursor:
        matched_array += 1
        raw = list(doc.get("industries") or [])
        seen = set()
        new_arr = []
        for s in raw:
            v = "pool" if s == "pools" else s
            if v in seen:
                continue
            seen.add(v)
            new_arr.append(v)
        if new_arr != raw:
            await db.tenants.update_one(
                {"id": doc["id"]}, {"$set": {"industries": new_arr}},
            )
            modified_array += 1

    logger.info(
        "[backfill_industry_slug_pools_to_pool] "
        "primary matched=%s modified=%s | array matched=%s modified=%s",
        primary_res.matched_count, primary_res.modified_count,
        matched_array, modified_array,
    )
    return {
        "matched_primary":  primary_res.matched_count,
        "modified_primary": primary_res.modified_count,
        "matched_array":    matched_array,
        "modified_array":   modified_array,
    }
