"""Feb-2026 · Property ``service_category`` inheritance migration.

One-time boot migration that stamps ``service_category`` on every
existing ``db.properties`` row by inheriting the value from the
parent customer:

    customer.service_category == "pool"        → property.service_category = "pool"
    customer.service_category == "landscaping" → property.service_category = "landscaping"
    customer.service_category == "both"        → property.service_category = "both"
    customer.service_category null/missing     → property.service_category stays unset

Idempotent via ``db.migrations`` sentinel ``feb2026_property_service_category_inheritance_v1``.
Second boot = no-op. ``force=True`` bypasses the sentinel for an
admin re-run.

The migration only STAMPS properties where ``service_category`` is
unset — properties where an admin has already pinned a value via
the ``PATCH /properties/{pid}`` endpoint are preserved untouched.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from config import db
from utils import new_id


logger = logging.getLogger("property_service_category")

_SENTINEL_ID = "feb2026_property_service_category_inheritance_v1"

_VALID_CATEGORIES = frozenset({"pool", "landscaping", "both"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_category(raw: Any) -> str:
    """Return the lowercase canonical category or ``""`` for unset.
    Case-insensitive — legacy ``"Pool"`` / ``"POOL"`` land as ``"pool"``.
    """
    if not raw or not isinstance(raw, str):
        return ""
    low = raw.strip().lower()
    if low in _VALID_CATEGORIES:
        return low
    return ""


async def run_property_service_category_inheritance(
    *, force: bool = False,
) -> Dict[str, Any]:
    """Idempotent one-time migration. Returns a summary dict:

        {
            "already_ran": bool,
            "ran_at": iso-ts,
            "run_id": uuid,
            "processed": int,
            "inherited_pool": int,
            "inherited_landscaping": int,
            "inherited_both": int,
            "left_unset": int,
            "duration_ms": int,
        }
    """
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sentinel and not force:
        return {
            "already_ran": True,
            "ran_at": sentinel.get("ran_at"),
            "summary": sentinel.get("summary") or {},
        }

    t0 = time.perf_counter()
    run_id = new_id()
    stats = {
        "processed": 0,
        "inherited_pool": 0,
        "inherited_landscaping": 0,
        "inherited_both": 0,
        "left_unset": 0,
    }

    # Scan every property that has NO ``service_category`` set yet.
    cursor = db.properties.find(
        {"$or": [
            {"service_category": {"$exists": False}},
            {"service_category": None},
            {"service_category": ""},
        ]},
        {"_id": 0, "id": 1, "tenant_id": 1, "customer_id": 1},
    )
    async for prop in cursor:
        stats["processed"] += 1
        cid = prop.get("customer_id")
        tid = prop.get("tenant_id")
        pid = prop.get("id")
        if not (cid and tid and pid):
            stats["left_unset"] += 1
            continue
        cust = await db.customers.find_one(
            {"id": cid, "tenant_id": tid},
            {"_id": 0, "service_category": 1},
        )
        inherited = _canonical_category(
            (cust or {}).get("service_category"),
        )
        if not inherited:
            stats["left_unset"] += 1
            continue
        await db.properties.update_one(
            {"id": pid, "tenant_id": tid},
            {"$set": {
                "service_category": inherited,
                "service_category_source": "inherited_from_customer",
                "service_category_set_at": _now_iso(),
            }},
        )
        stats[f"inherited_{inherited}"] += 1

    duration_ms = int((time.perf_counter() - t0) * 1000)
    summary = {**stats, "run_id": run_id, "duration_ms": duration_ms}

    if sentinel and force:
        await db.migrations.update_one(
            {"id": _SENTINEL_ID},
            {"$set": {"last_forced_run_at": _now_iso(),
                       "last_forced_summary": summary}},
        )
    else:
        await db.migrations.insert_one({
            "id": _SENTINEL_ID,
            "ran_at": _now_iso(),
            "summary": summary,
        })

    logger.info(
        "[migration.property_service_category] run_id=%s processed=%d "
        "inherited_pool=%d inherited_landscaping=%d inherited_both=%d "
        "left_unset=%d duration_ms=%d",
        run_id, stats["processed"], stats["inherited_pool"],
        stats["inherited_landscaping"], stats["inherited_both"],
        stats["left_unset"], duration_ms,
    )
    return {"already_ran": False, "ran_at": _now_iso(),
             "summary": summary}
