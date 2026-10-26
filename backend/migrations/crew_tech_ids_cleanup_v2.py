"""TD-crew-expand-silent-drop-to-soft-deleted-users · Feb-2026
================================================================

v2 one-shot cleanup CLI — expands Ticket S's orphan-only predicate
to also strip SOFT-DELETED users from ``db.crews.tech_ids`` across
every tenant.  Mirrors the v1 ladder shape (dry-run / report-only
/ apply / tenant / force) + sentinel pattern.

Scope difference vs v1
----------------------
v1 (``crew_tech_ids_orphan_cleanup_v1``) — orphan only
    An id in ``tech_ids`` that resolves to NO user / technician in
    ANY tenant.
v2 (this file)                            — orphan + soft_deleted
    An id in ``tech_ids`` that:
      * resolves to NO user / technician anywhere, OR
      * resolves to a user / technician IN THE SAME TENANT whose
        ``deleted_at`` is set OR whose ``is_active`` / ``active``
        flag is False.
    Foreign-tenant ids remain LEFT ALONE in both backfills.

Breadcrumb
----------
Each affected crew gains two fields:

* ``tech_ids_cleanup_v2_at`` — ISO stamp of the apply.
* ``tech_ids_cleanup_v2_removed_with_reason`` — list of
  ``{"user_id": <id>, "reason": "orphan"|"soft_deleted"}`` so an
  operator can audit the per-id reason without re-running the scan.
  Queryable via
  ``db.crews.find({tech_ids_cleanup_v2_removed_with_reason:
    {$exists: true}})``.

Operator run ladder (prod)
--------------------------
::

    cd /app/backend
    python -m migrations.crew_tech_ids_cleanup_v2 --dry-run
    python -m migrations.crew_tech_ids_cleanup_v2 --report-only
    python -m migrations.crew_tech_ids_cleanup_v2 \\
        --apply --tenant <tenant_id>   # optional per-tenant first
    python -m migrations.crew_tech_ids_cleanup_v2 --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import db, logger  # noqa: E402

_SENTINEL_KEY = "crew_tech_ids_cleanup_v2"
_SENTINEL_COLLECTION = "_migrations"
_BREADCRUMB_LIST = "tech_ids_cleanup_v2_removed_with_reason"
_BREADCRUMB_AT = "tech_ids_cleanup_v2_at"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _live_user_filter() -> Dict[str, Any]:
    """Mirror the ``routers/ops._resolve_tenant_members`` live-user
    predicate: deleted_at null/missing AND is_active != False AND
    active != False."""
    return {"$and": [
        {"$or": [{"deleted_at": None},
                   {"deleted_at": {"$exists": False}}]},
        {"$or": [{"is_active": {"$ne": False}},
                   {"is_active": None}]},
        {"$or": [{"active": {"$ne": False}},
                   {"active": None}]},
    ]}


def _not_deleted_tech() -> Dict[str, Any]:
    return {"$or": [{"deleted_at": None},
                     {"deleted_at": {"$exists": False}}]}


async def _tenant_ids(scoped: Optional[str]) -> List[str]:
    if scoped:
        return [scoped]
    out: List[str] = []
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        if t.get("id"):
            out.append(t["id"])
    return out


async def _scan_crew(
    *, crew: Dict[str, Any], tenant_id: str,
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Return ``(drops, foreign_ids)``.

    drops       — list of ``{"user_id": <id>, "reason":
                   "orphan"|"soft_deleted"}`` safe to remove.
    foreign_ids — ids that resolve to a user/technician in a
                   DIFFERENT tenant; LEFT ALONE.
    """
    tech_ids = crew.get("tech_ids") or []
    if not tech_ids:
        return [], []

    live_in_tenant: Set[str] = set()
    async for u in db.users.find(
        {"tenant_id": tenant_id, "id": {"$in": tech_ids},
         **_live_user_filter()},
        {"_id": 0, "id": 1},
    ):
        live_in_tenant.add(u["id"])
    async for t in db.technicians.find(
        {"tenant_id": tenant_id, "id": {"$in": tech_ids},
         **_not_deleted_tech()},
        {"_id": 0, "id": 1},
    ):
        live_in_tenant.add(t["id"])
    missing = [x for x in tech_ids if x not in live_in_tenant]
    if not missing:
        return [], []

    # soft-deleted-in-tenant probe — hits any row in this tenant
    # that the live-user predicate above filtered out.
    soft_deleted: Set[str] = set()
    async for u in db.users.find(
        {"tenant_id": tenant_id, "id": {"$in": missing}},
        {"_id": 0, "id": 1},
    ):
        soft_deleted.add(u["id"])
    async for t in db.technicians.find(
        {"tenant_id": tenant_id, "id": {"$in": missing}},
        {"_id": 0, "id": 1},
    ):
        soft_deleted.add(t["id"])

    # Foreign-tenant probe for the remainder.
    foreign: Set[str] = set()
    remainder = [x for x in missing if x not in soft_deleted]
    async for u in db.users.find(
        {"id": {"$in": remainder}},
        {"_id": 0, "id": 1, "tenant_id": 1},
    ):
        if u.get("tenant_id") and u["tenant_id"] != tenant_id:
            foreign.add(u["id"])
    still_remainder = [x for x in remainder if x not in foreign]
    if still_remainder:
        async for t in db.technicians.find(
            {"id": {"$in": still_remainder}},
            {"_id": 0, "id": 1, "tenant_id": 1},
        ):
            if t.get("tenant_id") and t["tenant_id"] != tenant_id:
                foreign.add(t["id"])

    drops: List[Dict[str, str]] = []
    for mid in missing:
        if mid in soft_deleted:
            drops.append({"user_id": mid, "reason": "soft_deleted"})
        elif mid in foreign:
            continue
        else:
            drops.append({"user_id": mid, "reason": "orphan"})
    return drops, sorted(foreign)


async def _apply_crew(
    *, crew: Dict[str, Any], tenant_id: str,
    drops: List[Dict[str, str]],
) -> None:
    drop_ids = {d["user_id"] for d in drops}
    tech_ids = [
        x for x in (crew.get("tech_ids") or []) if x not in drop_ids
    ]
    member_added_at = {
        k: v for k, v in (crew.get("member_added_at") or {}).items()
        if k not in drop_ids
    }
    now = _now_iso()
    await db.crews.update_one(
        {"id": crew["id"], "tenant_id": tenant_id},
        {"$set": {
            "tech_ids": tech_ids,
            "member_added_at": member_added_at,
            _BREADCRUMB_LIST: drops,
            _BREADCRUMB_AT: now,
            "updated_at": now,
        }},
    )


async def _is_sentinel_clean() -> bool:
    doc = await db[_SENTINEL_COLLECTION].find_one({"key": _SENTINEL_KEY})
    if not doc or doc.get("mode") != "apply":
        return False
    return int((doc.get("stats") or {}).get("remaining_after", 1)) == 0


async def _write_sentinel(stats: Dict[str, Any]) -> None:
    await db[_SENTINEL_COLLECTION].update_one(
        {"key": _SENTINEL_KEY},
        {"$set": {
            "id": _SENTINEL_KEY,
            "key": _SENTINEL_KEY,
            "phase": "TD-crew-expand-silent-drop-to-soft-deleted-users",
            "mode": "apply",
            "completed_at": _now_iso(),
            "stats": stats,
        }},
        upsert=True,
    )


async def run(
    *,
    apply: bool = False,
    report_only: bool = False,
    tenant_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    try:
        from config import client as _client  # noqa: PLC0415
        _client._io_loop = asyncio.get_running_loop()
    except Exception:  # noqa: BLE001
        pass

    if report_only and apply:
        raise ValueError(
            "--report-only and --apply are mutually exclusive"
        )

    if (apply and not force and not tenant_id
            and await _is_sentinel_clean()):
        return {"status": "skipped",
                 "reason": "sentinel-clean"}

    tenant_ids = await _tenant_ids(tenant_id)
    totals = {
        "tenants": len(tenant_ids),
        "crews_scanned": 0,
        "crews_affected": 0,
        "orphan_removed": 0,
        "soft_deleted_removed": 0,
        "foreign_left_alone": 0,
        "crews_skipped_already_cleaned": 0,
    }
    reports: List[Dict[str, Any]] = []
    for tid in tenant_ids:
        tenant_report: Dict[str, Any] = {
            "tenant_id": tid, "affected": [],
        }
        async for crew in db.crews.find(
            {"tenant_id": tid, "tech_ids": {"$exists": True,
                                                "$ne": []}},
            {"_id": 0, "id": 1, "name": 1, "tech_ids": 1,
             "member_added_at": 1, _BREADCRUMB_AT: 1},
        ):
            totals["crews_scanned"] += 1
            if crew.get(_BREADCRUMB_AT) and not force:
                totals["crews_skipped_already_cleaned"] += 1
                continue
            drops, foreign_ids = await _scan_crew(
                crew=crew, tenant_id=tid,
            )
            totals["foreign_left_alone"] += len(foreign_ids)
            if not drops:
                continue
            orphan_count = sum(1 for d in drops
                                 if d["reason"] == "orphan")
            soft_count = sum(1 for d in drops
                                  if d["reason"] == "soft_deleted")
            tenant_report["affected"].append({
                "crew_id": crew["id"],
                "crew_name": crew.get("name"),
                "drops": drops,
                "foreign_ids": foreign_ids,
            })
            totals["crews_affected"] += 1
            totals["orphan_removed"] += orphan_count
            totals["soft_deleted_removed"] += soft_count
            if apply:
                await _apply_crew(
                    crew=crew, tenant_id=tid, drops=drops,
                )
        if tenant_report["affected"]:
            reports.append(tenant_report)

    logger.info(
        "[crew-cleanup-v2] apply=%s tenants=%s crews_scanned=%s "
        "crews_affected=%s orphan_removed=%s "
        "soft_deleted_removed=%s foreign_left_alone=%s",
        apply, totals["tenants"], totals["crews_scanned"],
        totals["crews_affected"], totals["orphan_removed"],
        totals["soft_deleted_removed"],
        totals["foreign_left_alone"],
    )

    if apply:
        remaining = 0
        for tid in tenant_ids:
            async for crew in db.crews.find(
                {"tenant_id": tid, "tech_ids": {"$exists": True,
                                                     "$ne": []}},
                {"_id": 0, "id": 1, "tech_ids": 1},
            ):
                drops, _ = await _scan_crew(
                    crew=crew, tenant_id=tid,
                )
                remaining += len(drops)
        totals["remaining_after"] = remaining
        totals["clean"] = remaining == 0
        await _write_sentinel(totals)

    return {
        "status": (
            "report-only" if report_only
            else "applied" if apply
            else "dry-run"
        ),
        "stats": totals,
        "reports": reports,
    }


def _format_report(out: Dict[str, Any]) -> str:
    s = out["stats"]
    lines = [
        "=" * 78,
        "TD-crew-expand-silent-drop-to-soft-deleted-users · "
        "report-only",
        "=" * 78,
        f"tenants scanned:                {s['tenants']}",
        f"crews scanned:                  {s['crews_scanned']}",
        f"crews affected:                 {s['crews_affected']}",
        f"orphan ids to remove:           {s['orphan_removed']}",
        f"soft-deleted ids to remove:     "
        f"{s['soft_deleted_removed']}",
        f"foreign ids left alone:         "
        f"{s['foreign_left_alone']}",
        f"crews skipped (already clean):  "
        f"{s['crews_skipped_already_cleaned']}",
        "-" * 78,
    ]
    for rep in out["reports"]:
        for row in rep["affected"]:
            drops_fmt = ", ".join(
                f"{d['user_id'][:8]}…[{d['reason']}]"
                for d in row["drops"]
            )
            lines.append(
                f"[tenant={rep['tenant_id']}] "
                f"crew={row['crew_name']} "
                f"({row['crew_id'][:8]}…) "
                f"drops=[{drops_fmt}] "
                f"foreign-left={row['foreign_ids']}"
            )
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Strip orphan + soft-deleted tech_ids from db.crews "
            "across all tenants.  Foreign-tenant ids LEFT ALONE."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--report-only", action="store_true")
    parser.add_argument("--tenant", default=None)
    parser.add_argument("--force", action="store_true")
    ns = parser.parse_args()
    out = asyncio.run(run(
        apply=ns.apply, report_only=ns.report_only,
        tenant_id=ns.tenant, force=ns.force,
    ))
    if ns.report_only:
        print(_format_report(out))
    else:
        print(json.dumps(out, indent=2, default=str))
