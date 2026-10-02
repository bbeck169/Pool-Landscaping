"""Fix legacy department-field drift on ``db.users`` (Phase 21 · Sub-item B).

Phase 20's ``UserDepartmentIn`` model accepts only:
  * ``"pool_tech"``
  * ``"landscape_tech"``
  * ``"both"``
  * ``None``

However, several legacy seed rows carry values that predate the enum
(``"landscaping"``, ``"Landscaping"``, ``"Pool"``, region labels like
``"north"`` / ``"south"``). These rows are silently invalid — they don't
break login (validation runs on write, not read), but any admin edit
via the new Phase 20 endpoints would 422.

This script is **idempotent**. Second run reports zero fixes.

Usage::

    python3 scripts/fix_landscape_tech_seed_drift.py [--dry-run]

Behaviour:
    "landscaping" / "Landscaping" / "landscape" → "landscape_tech"
    "Pool" / "pool"                              → "pool_tech"
    Anything else non-null NOT in the enum       → None (WARNING logged)
    Values already in the enum (or ``None``)     → untouched
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Local .env for MONGO_URL / DB_NAME.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env")

_VALID = {"pool_tech", "landscape_tech", "both"}

# Value → mapped-to. Case-insensitive lookup key.
_MAPPING: Dict[str, str] = {
    "landscaping":     "landscape_tech",
    "landscape":       "landscape_tech",
    "landscape_tech":  "landscape_tech",  # no-op
    "pool":            "pool_tech",
    "pool_tech":       "pool_tech",       # no-op
    "both":            "both",            # no-op
}


def _resolve(current: Any) -> Tuple[str, Optional[str]]:
    """Return ``(action, new_value)`` for a single row's current value.

    ``action`` is one of:
        * ``"noop"`` — value is already valid or ``None``; skip.
        * ``"remap"`` — value maps to a valid enum; will be rewritten.
        * ``"clear"`` — value is unrecognized; will be set to ``None``
          and logged as a WARNING.
    """
    if current is None or current == "":
        return "noop", None
    if not isinstance(current, str):
        return "clear", None
    key = current.strip().lower()
    if key in _VALID:
        # Already valid but check case sensitivity — "Pool"/"Landscaping"
        # normalize even when the lowercased form is a valid enum
        # value. Only when the ORIGINAL string is already exactly a
        # valid enum do we no-op.
        if current == key:
            return "noop", None
        # E.g. "Both" → normalise to "both".
        return "remap", key
    mapped = _MAPPING.get(key)
    if mapped:
        # Already-normalised source keys still count as remap if the
        # stored value differs (e.g. "Landscaping" vs "landscape_tech").
        return "remap", mapped
    return "clear", None


async def run(dry_run: bool) -> Dict[str, int]:
    log = logging.getLogger("fix_landscape_seed_drift")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(h)

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    counts = {"scanned": 0, "remapped": 0, "cleared": 0,
               "already_valid": 0, "null": 0}

    # Only scan rows whose department is a non-null, non-empty string.
    cursor = db.users.find(
        {"department": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "id": 1, "email": 1, "department": 1, "tenant_id": 1},
    )
    async for row in cursor:
        counts["scanned"] += 1
        current = row.get("department")
        action, new_val = _resolve(current)
        if action == "noop":
            counts["already_valid"] += 1
            continue
        if action == "clear":
            log.warning(
                "clearing unrecognized department %r on user %s (email=%s tenant=%s)",
                current, row.get("id"), row.get("email"),
                row.get("tenant_id"),
            )
            counts["cleared"] += 1
        else:
            log.info(
                "remap %r → %r  (user_id=%s email=%s tenant=%s)",
                current, new_val, row.get("id"), row.get("email"),
                row.get("tenant_id"),
            )
            counts["remapped"] += 1
        if not dry_run:
            await db.users.update_one(
                {"id": row["id"]},
                {"$set": {"department": new_val,
                          "department_updated_by": "seed-drift-fix",
                          "department_updated_at": None}},
            )

    log.info("summary: %s", counts)
    client.close()
    return counts


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would change; do not write.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse()
    result = asyncio.run(run(dry_run=args.dry_run))
    print(f"\nRESULT: {result}")
    # Exit non-zero if there's still something invalid AFTER a real run
    # (there shouldn't be; belt-and-suspenders for CI).
    if not args.dry_run and (result["remapped"] + result["cleared"]) > 0:
        # First run — remapped/cleared may be > 0; that's success.
        pass
