"""Feb-2026 · P1 · Normalise ``role='tech'`` → ``role='technician'``.

Five preview users (Morgan Field, Carlos Ochoa, Paolo Ruiz, and two
seeded synth accounts ``tech_p10e_a`` / ``tech_p10e_b``) were written
with the legacy singular ``role='tech'``. They were invisible in
``/api/technicians`` and ``/api/team`` because both endpoints
whitelisted the plural ``'technician'`` only.

Alongside widening the whitelist in the readers (see
``routers/technicians.py`` and ``routers/team.py``), this one-shot
migration rewrites the field at rest so future picker code, RBAC
checks, and role-based counts don't need to keep the alias in mind.

Idempotent: safe to re-run. Second run reports 0 updates.

Usage::

    cd /app/backend && python -m scripts.normalize_role_tech_to_technician
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict


HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from config import db, logger  # noqa: E402


async def run() -> Dict[str, Any]:
    # Snapshot the affected ids for the audit trail.
    affected = await db.users.find(
        {"role": "tech"},
        {"_id": 0, "id": 1, "email": 1, "name": 1, "tenant_id": 1},
    ).to_list(1000)
    if not affected:
        logger.info("[normalize_role_tech_to_technician] no rows to migrate")
        result = {"scanned": 0, "updated": 0, "ids": []}
        print(result)
        return result

    res = await db.users.update_many(
        {"role": "tech"},
        {"$set": {"role": "technician"}},
    )
    logger.info(
        "[normalize_role_tech_to_technician] normalised %d row(s) "
        "role='tech' → role='technician'", res.modified_count,
    )
    result = {
        "scanned": len(affected),
        "updated": res.modified_count,
        "ids": [{"id": u.get("id"),
                    "email": u.get("email"),
                    "name": u.get("name"),
                    "tenant_id": u.get("tenant_id")} for u in affected],
    }
    print(result)
    return result


if __name__ == "__main__":
    asyncio.run(run())
