"""TD-crew-silently-drop-orphan-members-and-backfill · Feb-2026
================================================================

One-shot cleanup CLI that strips orphan ``tech_ids`` from every
``db.crews`` doc across every tenant.

Scope — orphan ONLY
-------------------
An orphan tech_id is a value in ``crews.tech_ids`` that does not
resolve to a live user or technician row in ANY tenant.  Foreign-
tenant tech_ids (resolve to a user in a different tenant) are
LEFT ALONE — they're a security concern handled by the live save
path (``routers/ops.py::create_crew`` + ``update_crew`` still 400
on foreign-tenant ids) and the pre-existing
``scripts/cleanup_crew_cross_tenant_tech_ids.py`` script.

Per-doc writes
--------------
For each affected crew:

  1. ``tech_ids`` — orphan ids removed; array shortened.
  2. ``member_added_at`` — matching keys dropped in lockstep so
     the two shapes stay consistent (TD-86 §7 contract).
  3. ``tech_ids_orphan_cleanup_v1_removed`` — NEW array breadcrumb
     listing the dropped user_ids so operators can audit via
     ``db.crews.find({tech_ids_orphan_cleanup_v1_removed:
       {$exists: true}})``.
  4. ``tech_ids_orphan_cleanup_v1_at`` — ISO timestamp of the apply.

Idempotency
-----------
Re-running on a crew that already carries the breadcrumb is a
no-op — Pass A pre-check skips any crew whose
``tech_ids_orphan_cleanup_v1_at`` is already stamped (unless
``--force`` is passed).  Also exits with ``skipped (sentinel-clean)``
when the sentinel in ``db._migrations`` says the last full-scope
apply left zero remaining orphans.

Flags
-----
``--dry-run``     (default) — counts only; no writes.
``--report-only``           — per-tenant / per-crew table on stdout;
                              no writes.
``--apply``                 — perform writes + record sentinel.
``--tenant <id>``           — scope to a single tenant.
``--force``                 — bypass the sentinel short-circuit on
                              ``--apply`` AND the per-doc breadcrumb
                              skip.

Operator run ladder (prod)
--------------------------
::

    cd /app/backend

    # 1. Baseline dry-run — see how many crews across how many
    #    tenants are affected.  Zero expected on preview; non-zero
    #    on prod per operator report.
    python -m migrations.crew_tech_ids_orphan_cleanup_v1 --dry-run

    # 2. Per-tenant table.
    python -m migrations.crew_tech_ids_orphan_cleanup_v1 --report-only

    # 3. (Optional) Narrow to one tenant first.
    python -m migrations.crew_tech_ids_orphan_cleanup_v1 \\
        --apply --tenant <tenant_id>

    # 4. Full apply across every tenant.
    python -m migrations.crew_tech_ids_orphan_cleanup_v1 --apply
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

_SENTINEL_KEY = "crew_tech_ids_orphan_cleanup_v1"
_SENTINEL_COLLECTION = "_migrations"
_BREADCRUMB_IDS = "tech_ids_orphan_cleanup_v1_removed"
_BREADCRUMB_AT = "tech_ids_orphan_cleanup_v1_at"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
) -> Tuple[List[str], List[str]]:
    """Return ``(orphan_ids, foreign_ids)`` for one crew doc.

    orphan_ids   — tech_ids that resolve to NO user / technician
                   in any tenant (safe to drop).
    foreign_ids  — tech_ids that resolve to a user / technician in
                   a DIFFERENT tenant (LEFT ALONE; this backfill
                   does not touch them).
    """
    tech_ids = crew.get("tech_ids") or []
    if not tech_ids:
        return [], []
    in_tenant: Set[str] = set()
    async for u in db.users.find(
        {"tenant_id": tenant_id, "id": {"$in": tech_ids}},
        {"_id": 0, "id": 1},
    ):
        in_tenant.add(u["id"])
    async for t in db.technicians.find(
        {"tenant_id": tenant_id, "id": {"$in": tech_ids}},
        {"_id": 0, "id": 1},
    ):
        in_tenant.add(t["id"])
    missing = [x for x in tech_ids if x not in in_tenant]
    if not missing:
        return [], []
    foreign: Set[str] = set()
    async for u in db.users.find(
        {"id": {"$in": missing}},
        {"_id": 0, "id": 1, "tenant_id": 1},
    ):
        if (u.get("tenant_id") and u["tenant_id"] != tenant_id):
            foreign.add(u["id"])
    remainder = [x for x in missing if x not in foreign]
    if remainder:
        async for t in db.technicians.find(
            {"id": {"$in": remainder}},
            {"_id": 0, "id": 1, "tenant_id": 1},
        ):
            if (t.get("tenant_id") and t["tenant_id"] != tenant_id):
                foreign.add(t["id"])
    orphan = [x for x in missing if x not in foreign]
    return orphan, sorted(foreign)


async def _apply_crew(
    *, crew: Dict[str, Any], tenant_id: str, orphan_ids: List[str],
) -> None:
    tech_ids = [
        x for x in (crew.get("tech_ids") or []) if x not in orphan_ids
    ]
    now = _now_iso()
    member_added_at = {
        k: v for k, v in (crew.get("member_added_at") or {}).items()
        if k not in orphan_ids
    }
    await db.crews.update_one(
        {"id": crew["id"], "tenant_id": tenant_id},
        {"$set": {
            "tech_ids": tech_ids,
            "member_added_at": member_added_at,
            _BREADCRUMB_IDS: orphan_ids,
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
            "phase": "TD-crew-silently-drop-orphan-members-and-backfill",
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
        "orphan_ids_removed": 0,
        "foreign_ids_left_alone": 0,
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
             "member_added_at": 1, _BREADCRUMB_IDS: 1,
             _BREADCRUMB_AT: 1},
        ):
            totals["crews_scanned"] += 1
            if crew.get(_BREADCRUMB_AT) and not force:
                totals["crews_skipped_already_cleaned"] += 1
                continue
            orphan_ids, foreign_ids = await _scan_crew(
                crew=crew, tenant_id=tid,
            )
            totals["foreign_ids_left_alone"] += len(foreign_ids)
            if not orphan_ids:
                continue
            tenant_report["affected"].append({
                "crew_id": crew["id"],
                "crew_name": crew.get("name"),
                "orphan_ids": orphan_ids,
                "foreign_ids": foreign_ids,
            })
            totals["crews_affected"] += 1
            totals["orphan_ids_removed"] += len(orphan_ids)
            if apply:
                await _apply_crew(
                    crew=crew, tenant_id=tid,
                    orphan_ids=orphan_ids,
                )
        if tenant_report["affected"]:
            reports.append(tenant_report)

    logger.info(
        "[crew-orphan-cleanup] apply=%s tenants=%s crews_scanned=%s "
        "crews_affected=%s orphan_ids_removed=%s "
        "foreign_ids_left_alone=%s",
        apply, totals["tenants"], totals["crews_scanned"],
        totals["crews_affected"], totals["orphan_ids_removed"],
        totals["foreign_ids_left_alone"],
    )

    if apply:
        # Second-pass scan to confirm clean.
        remaining = 0
        for tid in tenant_ids:
            async for crew in db.crews.find(
                {"tenant_id": tid, "tech_ids": {"$exists": True,
                                                     "$ne": []}},
                {"_id": 0, "id": 1, "tech_ids": 1},
            ):
                orphan_ids, _ = await _scan_crew(
                    crew=crew, tenant_id=tid,
                )
                remaining += len(orphan_ids)
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
        "TD-crew-silently-drop-orphan-members-and-backfill · report-only",
        "=" * 78,
        f"tenants scanned:                {s['tenants']}",
        f"crews scanned:                  {s['crews_scanned']}",
        f"crews affected (orphan found):  {s['crews_affected']}",
        f"orphan ids to remove:           {s['orphan_ids_removed']}",
        f"foreign ids left alone:         {s['foreign_ids_left_alone']}",
        f"crews skipped (already clean):  "
        f"{s['crews_skipped_already_cleaned']}",
        "-" * 78,
    ]
    for rep in out["reports"]:
        for row in rep["affected"]:
            lines.append(
                f"[tenant={rep['tenant_id']}] crew={row['crew_name']} "
                f"({row['crew_id'][:8]}…) "
                f"orphan={row['orphan_ids']}  "
                f"foreign-left={row['foreign_ids']}"
            )
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Strip orphan tech_ids from db.crews across all tenants. "
            "Scope: ORPHAN ONLY. Foreign-tenant ids are LEFT ALONE "
            "(security — handled by live save path)."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true",
                        help="Perform writes (default: dry-run)")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--report-only", action="store_true")
    parser.add_argument("--tenant", default=None,
                        help="Restrict to a single tenant id")
    parser.add_argument("--force", action="store_true",
                        help=("Bypass sentinel + per-doc breadcrumb "
                              "skip on --apply"))
    ns = parser.parse_args()
    out = asyncio.run(run(
        apply=ns.apply,
        report_only=ns.report_only,
        tenant_id=ns.tenant,
        force=ns.force,
    ))
    if ns.report_only:
        print(_format_report(out))
    else:
        print(json.dumps(out, indent=2, default=str))
