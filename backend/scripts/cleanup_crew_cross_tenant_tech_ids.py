"""TD-86 · Feb-2026 — one-shot cleanup for crew tech_ids drift.

Prunes crew ``tech_ids`` entries that resolve to one of:

  * ``foreign_tenant`` — the id exists in users/technicians but
    under a different ``tenant_id`` than the crew's own.
  * ``orphan`` — the id does not exist in users/technicians in
    any tenant.

The sister-map ``member_added_at`` is pruned in lock-step so the
two shapes on a crew doc stay consistent (see TD-86 audit §7).

Usage
-----
Dry-run default — reports counts without writing::

    python backend/scripts/cleanup_crew_cross_tenant_tech_ids.py

Scope to a single tenant::

    python ...py --tenant <tenant_id>

Apply writes (operator-gated — do NOT run on preview without a
separate greenlight)::

    python ...py --apply

Writes a run summary to ``/app/memory/td86_crew_cleanup.md`` on
every invocation (dry-run or apply).  Idempotent on re-run.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow invocation from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


SUMMARY_DOC = Path("/app/memory/td86_crew_cleanup.md")


def categorise_bad_ids(
    bad_ids: List[str], foreign_lookup: Dict[str, str],
) -> Dict[str, int]:
    """Return per-reason counters for a single crew's bad ids.

    ``foreign_lookup`` maps every id-known-to-exist to its owning
    tenant_id (populated by the caller before invoking this).
    """
    out = {"foreign_tenant": 0, "orphan": 0}
    for bid in bad_ids:
        if bid in foreign_lookup:
            out["foreign_tenant"] += 1
        else:
            out["orphan"] += 1
    return out


async def _build_tenant_valid_ids(db, tenant_id: str) -> set:
    """Return the set of ids present in ``users`` + ``technicians``
    for ``tenant_id``. Shared helper so the predicate is DRY."""
    ids: set = set()
    async for u in db.users.find(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
    ):
        if u.get("id"):
            ids.add(u["id"])
    async for t in db.technicians.find(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
    ):
        if t.get("id"):
            ids.add(t["id"])
    return ids


async def _build_global_foreign_lookup(db, missing_ids: List[str]) -> Dict[str, str]:
    """Return ``{id: owning_tenant_id}`` for every missing id found
    somewhere in users/technicians.  Ids not found remain unmapped
    and are categorised as ``orphan``."""
    out: Dict[str, str] = {}
    if not missing_ids:
        return out
    async for u in db.users.find(
        {"id": {"$in": missing_ids}}, {"_id": 0, "id": 1, "tenant_id": 1},
    ):
        if u.get("id") and u.get("tenant_id"):
            out[u["id"]] = u["tenant_id"]
    rem = [x for x in missing_ids if x not in out]
    if rem:
        async for t in db.technicians.find(
            {"id": {"$in": rem}}, {"_id": 0, "id": 1, "tenant_id": 1},
        ):
            if t.get("id") and t.get("tenant_id"):
                out.setdefault(t["id"], t["tenant_id"])
    return out


async def run_cleanup(
    *, apply: bool = False, tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """Core driver — scan every crew, categorise drift, optionally
    write prunes.  Returns the per-tenant counters + grand totals
    the summary doc + CLI output consume.
    """
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    try:
        if tenant:
            tenants = await db.tenants.find(
                {"id": tenant}, {"_id": 0, "id": 1, "name": 1},
            ).to_list(1)
        else:
            tenants = await db.tenants.find(
                {}, {"_id": 0, "id": 1, "name": 1},
            ).to_list(5000)

        per_tenant: Dict[str, Dict[str, Any]] = {}
        totals = {
            "crews_scanned": 0,
            "crews_with_drift": 0,
            "tech_ids_pruned_orphan": 0,
            "tech_ids_pruned_foreign_tenant": 0,
            "member_added_at_entries_pruned": 0,
            "crews_updated": 0,
            "crews_failed_with_reason": [],
        }

        for t in tenants:
            tid = t["id"]
            tname = t.get("name") or ""
            valid_ids = await _build_tenant_valid_ids(db, tid)
            crews = await db.crews.find(
                {"tenant_id": tid}, {"_id": 0, "id": 1, "name": 1,
                                      "tech_ids": 1, "member_added_at": 1},
            ).to_list(5000)
            if not crews:
                continue

            ten_counters = {
                "name": tname,
                "crews_scanned": len(crews),
                "crews_with_drift": 0,
                "tech_ids_pruned_orphan": 0,
                "tech_ids_pruned_foreign_tenant": 0,
                "member_added_at_entries_pruned": 0,
                "crews_updated": 0,
                "crews_failed": [],
            }

            for c in crews:
                totals["crews_scanned"] += 1
                tids = c.get("tech_ids") or []
                clean = [x for x in tids if x in valid_ids]
                bad = [x for x in tids if x and x not in valid_ids]
                if not bad:
                    continue
                ten_counters["crews_with_drift"] += 1
                totals["crews_with_drift"] += 1

                foreign_lookup = await _build_global_foreign_lookup(db, bad)
                counters = categorise_bad_ids(bad, foreign_lookup)
                ten_counters["tech_ids_pruned_orphan"] += counters["orphan"]
                ten_counters["tech_ids_pruned_foreign_tenant"] += counters[
                    "foreign_tenant"
                ]
                totals["tech_ids_pruned_orphan"] += counters["orphan"]
                totals["tech_ids_pruned_foreign_tenant"] += counters[
                    "foreign_tenant"
                ]

                mem_added = dict(c.get("member_added_at") or {})
                removed_mem = [k for k in mem_added if k not in valid_ids]
                for k in removed_mem:
                    mem_added.pop(k, None)
                ten_counters["member_added_at_entries_pruned"] += len(
                    removed_mem
                )
                totals["member_added_at_entries_pruned"] += len(removed_mem)

                if apply:
                    try:
                        await db.crews.update_one(
                            {"id": c["id"], "tenant_id": tid},
                            {"$set": {"tech_ids": clean,
                                       "member_added_at": mem_added,
                                       "updated_at": datetime.now(
                                           timezone.utc,
                                       ).isoformat()}},
                        )
                        ten_counters["crews_updated"] += 1
                        totals["crews_updated"] += 1
                    except Exception as exc:  # pragma: no cover
                        ten_counters["crews_failed"].append({
                            "crew_id": c["id"], "reason": str(exc),
                        })
                        totals["crews_failed_with_reason"].append({
                            "crew_id": c["id"], "tenant_id": tid,
                            "reason": str(exc),
                        })

            if ten_counters["crews_with_drift"] or ten_counters["crews_scanned"]:
                per_tenant[tid] = ten_counters

        return {"per_tenant": per_tenant, "totals": totals,
                 "apply": apply, "tenant_filter": tenant}
    finally:
        client.close()


def render_summary(result: Dict[str, Any]) -> str:
    """Render the markdown summary written to the memory doc +
    emitted on stdout for the operator receipt."""
    ts = datetime.now(timezone.utc).isoformat()
    mode = "APPLY (writes)" if result["apply"] else "DRY-RUN (read-only)"
    scope = (
        f"single tenant `{result['tenant_filter']}`"
        if result["tenant_filter"] else "every tenant"
    )
    totals = result["totals"]
    lines = [
        f"# TD-86 · crew tech_ids cleanup — {mode}",
        "",
        f"**Timestamp:** {ts}",
        f"**Scope:** {scope}",
        "",
        "## Grand totals",
        "",
        f"- crews_scanned: **{totals['crews_scanned']}**",
        f"- crews_with_drift: **{totals['crews_with_drift']}**",
        f"- tech_ids_pruned_orphan: **{totals['tech_ids_pruned_orphan']}**",
        f"- tech_ids_pruned_foreign_tenant: "
        f"**{totals['tech_ids_pruned_foreign_tenant']}**",
        f"- member_added_at_entries_pruned: "
        f"**{totals['member_added_at_entries_pruned']}**",
        f"- crews_updated: **{totals['crews_updated']}** "
        f"({'writes applied' if result['apply'] else 'no writes — dry-run'})",
        f"- crews_failed_with_reason: {len(totals['crews_failed_with_reason'])}",
        "",
        "## Per-tenant breakdown",
        "",
    ]
    if not result["per_tenant"]:
        lines.append("_No crews with drift found._")
    for tid, c in result["per_tenant"].items():
        lines.append(f"### `{tid}` ({c['name']})")
        lines.append("")
        lines.append(f"- crews_scanned: {c['crews_scanned']}")
        lines.append(f"- crews_with_drift: {c['crews_with_drift']}")
        lines.append(f"- tech_ids_pruned_orphan: {c['tech_ids_pruned_orphan']}")
        lines.append(f"- tech_ids_pruned_foreign_tenant: "
                       f"{c['tech_ids_pruned_foreign_tenant']}")
        lines.append(f"- member_added_at_entries_pruned: "
                       f"{c['member_added_at_entries_pruned']}")
        lines.append(f"- crews_updated: {c['crews_updated']}")
        if c["crews_failed"]:
            lines.append(f"- crews_failed: {len(c['crews_failed'])}")
        lines.append("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="TD-86 crew tech_ids cleanup (prune orphan + "
                    "foreign-tenant ids).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write prunes to Mongo. Default is dry-run.",
    )
    parser.add_argument(
        "--tenant", default=None,
        help="Scope to a single tenant_id. Default scans every tenant.",
    )
    args = parser.parse_args()

    result = await run_cleanup(apply=args.apply, tenant=args.tenant)
    md = render_summary(result)
    print(md)
    SUMMARY_DOC.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_DOC.write_text(md, encoding="utf-8")
    print(f"\n[cleanup] summary written to {SUMMARY_DOC}")


if __name__ == "__main__":
    asyncio.run(main())
