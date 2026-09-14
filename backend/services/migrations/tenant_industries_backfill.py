"""Feb-2026 · Multi-industry Phase A — one-time idempotent
seed of ``tenants.industries`` for every tenant that predates the
new field.

Contract:
  * For every ``tenants`` row WITHOUT an ``industries`` field:
    stamp ``industries = [<DEFAULT_INDUSTRY>]`` (currently
    ``["pools"]``).  If the tenant document happens to already
    carry a legacy single-industry hint (``industry`` or
    ``industry_type`` string field), that value is preferred over
    the default when it maps to a canonical slug.
  * Rows whose ``industries`` array is already present (even
    empty) are left alone — the field is admin-editable via
    ``PATCH /api/tenants/mine/settings`` and an intentional
    empty array must survive a boot pass.

Idempotent — safe to re-run on every pod boot.  The first pass
does the write; subsequent passes find zero candidates and
return ``{"scanned": …, "backfilled": 0}``.

Wired via ``server.py`` startup pipeline; see the ``step(...)``
call next to the other Feb-2026 migrations.
"""
from __future__ import annotations

from typing import Any, Dict

from config import db, logger
from services.industries import (
    DEFAULT_INDUSTRY,
    is_valid_industry,
)


async def backfill_tenant_industries() -> Dict[str, Any]:
    scanned = 0
    backfilled = 0
    inferred_from_legacy = 0

    async for row in db.tenants.find(
        {"industries": {"$exists": False}},
        {"_id": 0, "id": 1, "industry": 1, "industry_type": 1,
         "primary_service": 1},
    ):
        scanned += 1
        # Best-effort: honour a legacy single-industry hint if one
        # exists and maps to the canonical enum. Otherwise default.
        seed = None
        for key in ("industry", "industry_type", "primary_service"):
            v = row.get(key)
            if isinstance(v, str) and is_valid_industry(v.strip().lower()):
                seed = v.strip().lower()
                inferred_from_legacy += 1
                break
        if seed is None:
            seed = DEFAULT_INDUSTRY

        r = await db.tenants.update_one(
            {"id": row["id"], "industries": {"$exists": False}},
            {"$set": {"industries": [seed]}},
        )
        if r.modified_count:
            backfilled += 1

    result = {
        "scanned": scanned,
        "backfilled": backfilled,
        "inferred_from_legacy": inferred_from_legacy,
    }
    logger.info(
        "[migration:tenant_industries] scanned=%d backfilled=%d "
        "inferred_from_legacy=%d",
        scanned, backfilled, inferred_from_legacy,
    )
    return result


__all__ = ["backfill_tenant_industries"]
