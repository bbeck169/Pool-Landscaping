"""Phase K42 · Feb-2026 — Normalize ``jobs.technician_id`` values.

Bug: filtering the Schedule by a tech returns zero jobs because the
codebase has TWO id-spaces for the same person (see
``services/tech_id_resolver.py``).  Some jobs were written with
``jobs.technician_id = users.id`` while others were written with
``jobs.technician_id = technicians.id``.  A read-side ``$or`` resolver
was added in K42 to catch both at query time, but this script
converges the WRITE side so every non-null ``jobs.technician_id`` in
the DB stores ``technicians.id`` going forward.

Behaviour
─────────
1. Dry-run (default) — scans and reports per-tenant counts.
2. ``--apply`` — swaps every ``jobs.technician_id`` that holds a
   ``users.id`` for the linked ``users.technician_id``.  The old
   value is preserved in ``jobs.technician_id_k42_before`` for audit /
   rollback.  The alias fields (``assigned_to``, ``tech_user_id``,
   ``assigned_technician_id``) are LEFT AS-IS — they intentionally
   store ``users.id`` for the modern write path and the K42 read
   resolver treats them equally.  Rewriting them would risk breaking
   downstream consumers we haven't audited.
3. Idempotent — the script is safe to re-run.  Records already
   normalized (i.e. those with a ``technician_id_k42_before`` set) are
   skipped.
4. Migration sentinel — writes a row into ``migrations`` at completion
   so the K33 boot-check picks it up.

Usage
─────
    # Dry-run (default)
    cd /app/backend && python -m migrations.k42_normalize_job_tech_id

    # Apply
    cd /app/backend && python -m migrations.k42_normalize_job_tech_id --apply

    # One-tenant scope
    cd /app/backend && python -m migrations.k42_normalize_job_tech_id \\
        --tenant <tenant_id>
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the backend package root is on sys.path so ``config`` /
# ``services`` imports resolve when invoked via ``python -m``.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from config import db, logger  # noqa: E402
from services.tech_id_resolver import JOB_TECH_FIELDS  # noqa: E402

_SENTINEL_KEY = "k42_normalize_job_tech_id_v1"


async def _load_tenant_ids(scoped: Optional[str]) -> List[str]:
    if scoped:
        return [scoped]
    return [t["id"] async for t in db.tenants.find({}, {"_id": 0, "id": 1})]


async def _tech_id_map(tenant_id: str) -> Dict[str, Dict[str, Any]]:
    """Build lookup maps for one tenant.

    Returns a dict keyed by id-variant (both technicians.id and
    users.id) → ``{technicians_id, users_id, name}``.  Callers plug in
    the raw ``jobs.technician_id`` and get the authoritative
    technicians.id in return (or ``None`` if unknown).
    """
    m: Dict[str, Dict[str, Any]] = {}
    # 1) technicians rows
    async for t in db.technicians.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "user_id": 1, "name": 1},
    ):
        entry = {
            "technicians_id": t["id"],
            "users_id": t.get("user_id"),
            "name": t.get("name") or "",
        }
        m[t["id"]] = entry
        if t.get("user_id"):
            m.setdefault(t["user_id"], entry)
    # 2) users with role=technician who don't have a technicians row
    async for u in db.users.find(
        {"tenant_id": tenant_id,
          "role": {"$in": ["technician", "tech",
                            "landscaper", "landscape_tech",
                            "pool_tech", "tech_both"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "technician_id": 1},
    ):
        techs_id = u.get("technician_id")
        entry = {
            "technicians_id": techs_id or u["id"],
            "users_id": u["id"],
            "name": u.get("name") or u.get("email") or "",
        }
        # Only add if we don't already have an authoritative mapping.
        m.setdefault(u["id"], entry)
        if techs_id:
            m.setdefault(techs_id, entry)
    return m


async def _scan_tenant(tenant_id: str) -> Dict[str, Any]:
    lookup = await _tech_id_map(tenant_id)
    report: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "jobs_scanned": 0,
        "jobs_needing_swap": 0,
        "jobs_already_normalized": 0,
        "jobs_unresolvable": 0,
        "swaps": [],
    }
    async for j in db.jobs.find(
        {"tenant_id": tenant_id,
          "technician_id": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "technician_id": 1,
          "technician_id_k42_before": 1},
    ):
        report["jobs_scanned"] += 1
        current = j.get("technician_id")
        if j.get("technician_id_k42_before"):
            report["jobs_already_normalized"] += 1
            continue
        entry = lookup.get(current)
        if not entry:
            report["jobs_unresolvable"] += 1
            continue
        authoritative = entry["technicians_id"]
        if not authoritative or authoritative == current:
            continue  # already on the authoritative variant
        report["jobs_needing_swap"] += 1
        report["swaps"].append({
            "job_id": j.get("id"),
            "from": current,
            "to": authoritative,
            "person": entry.get("name"),
        })
    return report


async def _apply_tenant(tenant_id: str, report: Dict[str, Any]) -> int:
    applied = 0
    now = datetime.now(timezone.utc).isoformat()
    for swap in report["swaps"]:
        res = await db.jobs.update_one(
            {"id": swap["job_id"],
              # Idempotency guard — only rewrite if the current value
              # is still the ``from`` we recorded during scan.
              "technician_id": swap["from"],
              "technician_id_k42_before": {"$exists": False}},
            {"$set": {
                "technician_id": swap["to"],
                "technician_id_k42_before": swap["from"],
                "technician_id_k42_applied_at": now,
            }},
        )
        applied += res.modified_count
    return applied


async def _write_sentinel(stats: Dict[str, Any], mode: str) -> None:
    doc = {
        "id": _SENTINEL_KEY,
        "key": _SENTINEL_KEY,
        "phase": "K42",
        "mode": mode,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
    }
    await db.migrations.update_one(
        {"key": _SENTINEL_KEY},
        {"$set": doc},
        upsert=True,
    )


async def main(apply: bool = False, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tenant_ids = await _load_tenant_ids(tenant_id)
    print(f"[k42] tenants: {len(tenant_ids)} · apply={apply}")
    total_swaps = 0
    total_scanned = 0
    total_unresolvable = 0
    all_reports: List[Dict[str, Any]] = []
    for tid in tenant_ids:
        rep = await _scan_tenant(tid)
        all_reports.append(rep)
        total_scanned += rep["jobs_scanned"]
        total_swaps += rep["jobs_needing_swap"]
        total_unresolvable += rep["jobs_unresolvable"]
        print(
            f"[k42] tenant={tid}: scanned={rep['jobs_scanned']} "
            f"needs_swap={rep['jobs_needing_swap']} "
            f"already_normalized={rep['jobs_already_normalized']} "
            f"unresolvable={rep['jobs_unresolvable']}"
        )
        for s in rep["swaps"][:5]:
            print(f"    · {s['job_id'][:8]}… {s['from'][:8]}… → {s['to'][:8]}… ({s['person']})")
        if apply and rep["swaps"]:
            applied = await _apply_tenant(tid, rep)
            print(f"[k42] tenant={tid}: applied={applied}")

    stats = {
        "tenants": len(tenant_ids),
        "jobs_scanned": total_scanned,
        "jobs_needing_swap": total_swaps,
        "jobs_unresolvable": total_unresolvable,
    }
    print(f"[k42] SUMMARY: {stats}")
    if apply:
        await _write_sentinel(stats, "apply")
    return {"stats": stats, "reports": all_reports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--tenant", default=None)
    ns = parser.parse_args()
    asyncio.run(main(apply=ns.apply, tenant_id=ns.tenant))
