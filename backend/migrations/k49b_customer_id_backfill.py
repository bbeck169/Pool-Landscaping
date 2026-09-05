"""Phase K49b · Feb-2026 — Backfill ``customers.id`` from ``_id``.

Bug (K49b hotfix)
────────────────
``GET /api/customers`` 500's with ``KeyError: 'id'`` when the query
returns a customer doc that lacks a top-level ``id`` field.  The
crash is at ``routers/customers.py:768`` inside the properties_count
hydration block; every subsequent hydration in the handler indexes
``d["id"]`` too.  Root cause: legacy rows written before the codebase
enforced ``id = str(_id)`` at insert time (``P42``-era imports and a
few one-off scripts).

Fix (two-part)
──────────────
1. Router-side guard — every ``d["id"]`` access in the customers list
   handler now filters on ``d.get("id")`` so a bad doc no longer
   500s the endpoint.  Landed in the same K49b patch as this file.
2. Data-side backfill (this file) — scan the ``customers`` collection
   for docs where ``id`` is missing / ``None`` / empty string, and
   set ``id = str(_id)``.  Reports counts per tenant.  Idempotent.
   Sentinel-guarded via the ``migrations`` collection so the K33
   boot-check picks it up.

Usage
─────
    # Dry-run (default) — no writes.
    cd /app/backend && python -m migrations.k49b_customer_id_backfill

    # Apply.
    cd /app/backend && python -m migrations.k49b_customer_id_backfill --apply

    # Scope to a single tenant.
    cd /app/backend && python -m migrations.k49b_customer_id_backfill \\
        --tenant <tenant_id> --apply

Boot integration
────────────────
Wired into ``server.py``'s startup pipeline behind
``asyncio.create_task`` so a failure never blocks boot.  Sentinel
gating skips the scan on subsequent boots once the migration has
recorded a clean run.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the backend package root is on sys.path when invoked via
# ``python -m migrations.k49b_customer_id_backfill``.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import db, logger  # noqa: E402

_SENTINEL_KEY = "k49b_customer_id_backfill_v1"

# The three shapes we consider "missing id".  A bare ``$exists`` check
# would miss the ``id: null`` shape (which pymongo returns) and the
# empty-string case (which some legacy insert paths use).
_MISSING_ID_FILTER = {
    "$or": [
        {"id": {"$exists": False}},
        {"id": None},
        {"id": ""},
    ],
}


async def _load_tenant_ids(scoped: Optional[str]) -> List[str]:
    if scoped:
        return [scoped]
    return [
        t["id"] async for t in db.tenants.find({}, {"_id": 0, "id": 1})
        if t.get("id")
    ]


async def _scan_tenant(tenant_id: str) -> Dict[str, Any]:
    q = {"tenant_id": tenant_id, **_MISSING_ID_FILTER}
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "customers_scanned": 0,
        "customers_needing_backfill": 0,
        "samples": [],
    }
    total = await db.customers.count_documents({"tenant_id": tenant_id})
    report["customers_scanned"] = total
    async for d in db.customers.find(q, {"_id": 1, "id": 1,
                                            "name": 1}):
        report["customers_needing_backfill"] += 1
        if len(report["samples"]) < 5:
            report["samples"].append({
                "_id": str(d.get("_id")),
                "id_before": d.get("id"),
                "name": d.get("name"),
            })
    return report


async def _apply_tenant(tenant_id: str) -> int:
    """Write ``id = str(_id)`` for every offending doc in the tenant.

    Idempotency guard — the filter still requires the missing-id
    shape so a concurrent re-run cannot double-write.  The update is
    a bulk ``update_many`` under a Mongo aggregation pipeline so we
    only pay one round-trip per tenant.
    """
    q = {"tenant_id": tenant_id, **_MISSING_ID_FILTER}
    now = datetime.now(timezone.utc).isoformat()
    # Pipeline update — sets ``id`` to the string form of ``_id``.
    # Requires MongoDB 4.2+; every deployment we ship is on 6.x.
    res = await db.customers.update_many(
        q,
        [{"$set": {
            "id": {"$toString": "$_id"},
            "k49b_id_backfilled_at": now,
        }}],
    )
    return int(res.modified_count or 0)


async def _write_sentinel(stats: Dict[str, Any], mode: str) -> None:
    doc = {
        "id": _SENTINEL_KEY,
        "key": _SENTINEL_KEY,
        "phase": "K49b",
        "mode": mode,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }
    await db.migrations.update_one(
        {"key": _SENTINEL_KEY},
        {"$set": doc},
        upsert=True,
    )


async def _is_already_applied() -> bool:
    """Sentinel check for the boot-wired path.  A prior clean apply
    (with ``customers_needing_backfill == 0`` on re-scan) short-
    circuits the scan on subsequent boots."""
    doc = await db.migrations.find_one({"key": _SENTINEL_KEY})
    if not doc or doc.get("mode") != "apply":
        return False
    stats = doc.get("stats") or {}
    # We only trust the sentinel when the LAST apply left zero
    # offenders behind — otherwise a partial run could hide new
    # offenders inserted after the sentinel was written.
    return int(stats.get("customers_needing_backfill", 1)) == 0


async def run(apply: bool = True, tenant_id: Optional[str] = None,
              force: bool = False) -> Dict[str, Any]:
    """Public entry point.

    Args:
        apply: Set to ``False`` for a dry-run (no writes, no sentinel).
        tenant_id: Restrict to a single tenant when set.
        force: Bypass the sentinel short-circuit even when the last
            recorded run was clean.  Boot wiring passes
            ``force=False``.
    """
    # K49b · Feb-2026 — rebind Motor's shared ``_io_loop`` to whichever
    # loop is currently driving us before we touch the DB.  The regression
    # suite calls ``asyncio.run(run(...))`` per-test, which creates a
    # fresh event loop; without this rebind Motor's futures stay attached
    # to whatever loop was current when ``config`` was first imported
    # and every subsequent ``await db.…`` raises
    # ``RuntimeError: … attached to a different loop``.  Boot-time
    # callers pass through unchanged (same running loop before/after).
    try:
        from config import client as _client  # noqa: PLC0415
        _client._io_loop = asyncio.get_running_loop()
    except Exception:  # noqa: BLE001 — best-effort loop rebind.
        pass
    if apply and not force and not tenant_id:
        if await _is_already_applied():
            return {
                "status": "skipped",
                "reason": "sentinel-clean",
            }
    tenant_ids = await _load_tenant_ids(tenant_id)
    total_scanned = 0
    total_backfilled = 0
    total_applied = 0
    all_reports: List[Dict[str, Any]] = []
    for tid in tenant_ids:
        rep = await _scan_tenant(tid)
        all_reports.append(rep)
        total_scanned += rep["customers_scanned"]
        total_backfilled += rep["customers_needing_backfill"]
        if apply and rep["customers_needing_backfill"]:
            applied = await _apply_tenant(tid)
            total_applied += applied
            rep["applied"] = applied
        else:
            rep["applied"] = 0
    stats = {
        "tenants": len(tenant_ids),
        "customers_scanned": total_scanned,
        "customers_needing_backfill": total_backfilled,
        "customers_applied": total_applied,
    }
    logger.info(
        "[k49b] apply=%s scanned=%s needing_backfill=%s applied=%s",
        apply, total_scanned, total_backfilled, total_applied,
    )
    if apply:
        # Re-scan the offender count post-apply so the sentinel
        # reflects the true final state.  Cheap — one aggregation.
        remaining = await db.customers.count_documents(_MISSING_ID_FILTER)
        stats["customers_needing_backfill_after"] = remaining
        await _write_sentinel(stats, "apply")
    return {
        "status": "applied" if apply else "dry-run",
        "stats": stats,
        "reports": all_reports,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                          help="Perform writes (default: dry-run)")
    parser.add_argument("--tenant", default=None,
                          help="Restrict to a single tenant id")
    parser.add_argument("--force", action="store_true",
                          help="Bypass the sentinel short-circuit")
    ns = parser.parse_args()
    out = asyncio.run(run(apply=ns.apply, tenant_id=ns.tenant,
                              force=ns.force))
    import json
    print(json.dumps(out, indent=2, default=str))
