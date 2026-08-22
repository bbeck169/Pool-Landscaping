"""Feb-2026 · P34 — Backfill quiet-hours defaults on every tenant.

Ensures every existing tenant carries the four new fields so the
settings PATCH endpoint always has stable ground truth:

    quiet_hours_enabled: false      # OFF by default (safe rollout)
    quiet_hours_start:   "08:00"
    quiet_hours_end:     "20:00"
    quiet_hours_timezone: null      # (falls back to tenants.timezone)

Idempotent — tenants that already carry the ``quiet_hours_enabled``
field are skipped. Warns (does NOT fail) if any tenant is missing a
``timezone`` field.

Usage
-----
    $ python -m migrations.task_p34_quiet_hours_defaults          # dry-run
    $ python -m migrations.task_p34_quiet_hours_defaults --commit # write
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List

from config import db, logger


async def main(commit: bool) -> Dict[str, Any]:
    tenants: List[Dict[str, Any]] = await db.tenants.find(
        {}, {"_id": 0, "id": 1, "name": 1, "timezone": 1,
              "quiet_hours_enabled": 1},
    ).to_list(500)

    to_backfill: List[str] = []
    missing_tz: List[str] = []
    for t in tenants:
        if "quiet_hours_enabled" not in t:
            to_backfill.append(t.get("id"))
        if not t.get("timezone"):
            missing_tz.append(t.get("id") or "?")

    inserted = 0
    if commit and to_backfill:
        r = await db.tenants.update_many(
            {"id": {"$in": to_backfill}},
            {"$set": {
                "quiet_hours_enabled": False,
                "quiet_hours_start": "08:00",
                "quiet_hours_end": "20:00",
                "quiet_hours_timezone": None,
            }},
        )
        inserted = int(r.modified_count)

    for tid in missing_tz:
        logger.warning("[p34] tenant=%s has no ``timezone`` field — will "
                          "fall back to America/Phoenix at read time.", tid)

    return {
        "committed": bool(commit),
        "total_tenants": len(tenants),
        "would_backfill": len(to_backfill),
        "backfilled": inserted if commit else 0,
        "missing_timezone_warnings": len(missing_tz),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    out = asyncio.run(main(commit=args.commit))
    print("─── task_p34_quiet_hours_defaults ───")
    print(f"committed:                {out['committed']}")
    print(f"total_tenants:            {out['total_tenants']}")
    if args.commit:
        print(f"backfilled:               {out['backfilled']}")
    else:
        print(f"would_backfill:           {out['would_backfill']}")
    print(f"missing_timezone_warnings: {out['missing_timezone_warnings']}")
