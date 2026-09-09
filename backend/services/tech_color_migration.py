"""Feb-2026 · Live-Tech-Map · Phase 1 — null-fill migration.

Idempotent, boot-time scan. For any technician row where
``display_color_hex`` is null / missing / empty, assign a
deterministic palette color via ``deterministic_color_for_id(user_id)``.
Same treatment for ``db.crews.color``.

Idempotency contract:
  * Only NON-NULL empty rows are touched — an already-assigned
    color (even an off-palette custom one, which the palette-lock
    tolerates on READS) is never overwritten.
  * Same input → same output because
    ``deterministic_color_for_id`` is a pure function of the id.
  * Safe to re-run on every boot; the query is
    ``{"display_color_hex": {"$in": [None, ""]}}`` which is
    index-friendly enough for the tech-row scale (<100 rows per
    tenant in practice).

Guardrails:
  * User row must have a valid ``id`` field (not empty). Rows
    without ids are skipped and logged — they're broken data that
    predates the migration and require ops attention.
  * Only rows with role in the tech-ish set are considered for the
    ``display_color_hex`` fill; admins / customers / super_admin
    don't render on the schedule/dispatch board so filling them
    would be wasted work.

RBAC: internal service — no auth. Invoked from ``server.py::startup``
under a guarded try/except.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from constants.tech_colors import deterministic_color_for_id

logger = logging.getLogger(__name__)

# Roles that render on the schedule / dispatch surfaces and
# therefore need a display color. Kept as a set literal — tiny,
# static, self-documenting.
_TECH_ROLES = {"technician", "landscaper"}


async def fill_missing_tech_colors(db) -> Dict[str, int]:
    """Fill missing ``display_color_hex`` on tech users.

    Returns a summary dict::

        {
            "scanned":  <count of tech rows inspected>,
            "filled":   <count of rows updated in this pass>,
            "skipped":  <count of rows with missing ``id``>,
        }
    """
    scanned = 0
    filled = 0
    skipped = 0
    # Query the small set of eligible rows only. Using $in with
    # None + "" catches both the "field never set" and "field set
    # to empty string" edge cases we've seen in the seed data.
    query: Dict[str, Any] = {
        "role": {"$in": list(_TECH_ROLES)},
        "$or": [
            {"display_color_hex": {"$exists": False}},
            {"display_color_hex": None},
            {"display_color_hex": ""},
        ],
    }
    cursor = db.users.find(query, {"_id": 0, "id": 1})
    async for row in cursor:
        scanned += 1
        uid = row.get("id")
        if not uid:
            skipped += 1
            continue
        color = deterministic_color_for_id(uid)
        r = await db.users.update_one(
            {"id": uid, "display_color_hex": {"$in": [None, "", ]}},
            {"$set": {"display_color_hex": color}},
        )
        # ``matched_count`` may be 0 if a concurrent boot already
        # filled this row — that's fine, treat as "already filled".
        if r.modified_count:
            filled += 1
    return {"scanned": scanned, "filled": filled, "skipped": skipped}


async def fill_missing_crew_colors(db) -> Dict[str, int]:
    """Fill missing ``color`` on crew rows. Same idempotency contract."""
    scanned = 0
    filled = 0
    skipped = 0
    query: Dict[str, Any] = {
        "$or": [
            {"color": {"$exists": False}},
            {"color": None},
            {"color": ""},
        ],
    }
    cursor = db.crews.find(query, {"_id": 0, "id": 1})
    async for row in cursor:
        scanned += 1
        cid = row.get("id")
        if not cid:
            skipped += 1
            continue
        color = deterministic_color_for_id(cid)
        r = await db.crews.update_one(
            {"id": cid, "color": {"$in": [None, ""]}},
            {"$set": {"color": color}},
        )
        if r.modified_count:
            filled += 1
    return {"scanned": scanned, "filled": filled, "skipped": skipped}


async def run_all(db) -> Dict[str, Dict[str, int]]:
    """Run both fills and return a combined summary. Exception-safe
    per-collection — a failure on crews doesn't roll back the users
    fill (they're independent contracts)."""
    summary: Dict[str, Dict[str, int]] = {}
    try:
        summary["users"] = await fill_missing_tech_colors(db)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[tech-color-migration] users pass failed: {e}")
        summary["users"] = {"scanned": 0, "filled": 0, "skipped": 0, "error": str(e)}
    try:
        summary["crews"] = await fill_missing_crew_colors(db)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[tech-color-migration] crews pass failed: {e}")
        summary["crews"] = {"scanned": 0, "filled": 0, "skipped": 0, "error": str(e)}
    return summary


__all__ = [
    "fill_missing_tech_colors",
    "fill_missing_crew_colors",
    "run_all",
]
