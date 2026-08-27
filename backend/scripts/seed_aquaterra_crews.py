"""Feb-2026 · One-shot seed — AquaTerra demo crews.

Populates two demo crews on the AquaTerra tenant so the Schedule
"New Job" + Edit-modal crew pickers have something to select. Safe
to re-run — idempotent by ``(tenant_id, name)``.

* **Blue Crew**  — Mike Rivera + Carlos Rivera
* **Green Crew** — Luis Marquez + Sara Nguyen

Guardrails:
* Only touches the AquaTerra tenant (slug=aquaterra, alias=plofv).
* Only assigns tech_ids that actually exist in the same tenant —
  missing techs are skipped with a warning so a partial-preview
  seed still yields a usable crew.
* Leaves EVERY other tenant untouched.

Usage::

    python -m scripts.seed_aquaterra_crews

Safe to re-run.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso


CREW_DEFS: List[Dict[str, Any]] = [
    {
        "name": "Blue Crew",
        "color": "#3B82F6",
        "member_names": ["Mike Rivera", "Carlos Rivera"],
    },
    {
        "name": "Green Crew",
        "color": "#16A34A",
        "member_names": ["Luis Marquez", "Sara Nguyen"],
    },
]


async def _resolve_tech_ids(tenant_id: str,
                              names: List[str]) -> List[str]:
    """Case-insensitive best-effort name → id resolution against the
    tenant's technicians collection. Missing names are logged and
    skipped."""
    if not names:
        return []
    rows = await db.technicians.find(
        {"tenant_id": tenant_id},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(500)
    by_name = {(r.get("name") or "").strip().lower(): r["id"]
               for r in rows if r.get("id")}
    ids: List[str] = []
    for n in names:
        tid = by_name.get((n or "").strip().lower())
        if not tid:
            logger.warning(
                f"[seed_aquaterra_crews] technician {n!r} not found "
                "in this tenant — skipping"
            )
            continue
        if tid not in ids:
            ids.append(tid)
    return ids


async def seed_aquaterra_crews() -> Dict[str, Any]:
    tenant = await db.tenants.find_one(
        {"$or": [{"slug": "aquaterra"}, {"slug_aliases": "plofv"}]},
        {"_id": 0, "id": 1, "slug": 1},
    )
    if not tenant:
        logger.warning("[seed_aquaterra_crews] no aquaterra tenant found — skipping")
        return {"ok": False, "reason": "aquaterra_tenant_missing"}

    tenant_id = tenant["id"]
    created: List[str] = []
    updated: List[str] = []
    skipped: List[str] = []

    for crew_def in CREW_DEFS:
        name = crew_def["name"]
        color = crew_def["color"]
        tech_ids = await _resolve_tech_ids(tenant_id,
                                              crew_def["member_names"])

        existing = await db.crews.find_one(
            {"tenant_id": tenant_id, "name": name},
            {"_id": 0},
        )
        if existing:
            # Update tech_ids only if the crew's current membership is
            # empty (respect any manual admin edits).
            current_members = existing.get("tech_ids") or []
            if not current_members and tech_ids:
                await db.crews.update_one(
                    {"id": existing["id"], "tenant_id": tenant_id},
                    {"$set": {"tech_ids": tech_ids,
                                "color": color,
                                "updated_at": now_iso()}},
                )
                updated.append(name)
            else:
                skipped.append(name)
        else:
            await db.crews.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "name": name,
                "color": color,
                "tech_ids": tech_ids,
                "created_at": now_iso(),
                "updated_at": now_iso(),
            })
            created.append(name)

    result = {
        "ok": True,
        "tenant_id": tenant_id,
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }
    logger.info(f"[seed_aquaterra_crews] {result}")
    return result


def _main() -> int:
    result = asyncio.get_event_loop().run_until_complete(seed_aquaterra_crews())
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(_main())
