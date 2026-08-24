"""Feb-2026 · Normalize legacy ``users.department`` tokens.

**Problem**
The current ``PUT /api/admin/users/{uid}/department`` handler (see
``backend/routers/inventory_reports.py:293``) validates the payload
against ``^(pool_tech|landscape_tech|both)$``, but the demo seed
pipeline historically stored:

  * ``"pool"``       — for pool techs (Mike Rivera & friends)
  * ``"landscaping"`` — for landscape techs (Carlos Rivera, Luis Marquez)

Any admin trying to touch such a row via the new inline dropdown
would face a confused UI (the row's stored value is not in the enum
so it renders as "Unassigned"), and separately, ANY consumer that
reads ``department`` expecting the modern enum will silently
mis-route cross-trained techs.

**Fix**
Idempotent one-shot migration that remaps stored legacy tokens in
``users`` (case-insensitive) to the modern enum:

    "pool"       → "pool_tech"
    "landscape"  → "landscape_tech"   ← rare defensive alias
    "landscaping" → "landscape_tech"

Also mirrors the same fix onto the linked ``technicians`` docs, so
downstream checklist-kind derivation (``routers/jobs.py``) stays
consistent.  Does NOT touch rows already in the modern enum or with
``department = null / missing``.

**Guarantees**
* Idempotent — second run reports 0 updates and touches nothing.
* Case-insensitive match on the STORED value (so ``"POOL"`` / ``"Pool"``
  drift also gets normalized).
* No user-facing rows lost — only the enum token is rewritten.
* Runs unconditionally on boot alongside the other one-shot
  migrations (see ``backend/server.py`` ``_background_seed``).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from config import db as _default_db, logger

# Legacy → modern enum mapping.  Keys are match-normalized (lower).
LEGACY_MAP: Dict[str, str] = {
    "pool":        "pool_tech",
    "landscape":   "landscape_tech",   # defensive alias — not seen live
    "landscaping": "landscape_tech",
}


async def _normalize_collection(db_, coll_name: str) -> Dict[str, int]:
    """Return per-collection counts ``{matched, updated}``.

    Iterates in Python (not a $switch pipeline) so we can also do
    the case-insensitive normalization and log per-row changes for
    the migration's audit line.
    """
    coll = db_[coll_name]
    matched = 0
    updated = 0
    async for row in coll.find(
        {"department": {"$type": "string"}},
        {"_id": 0, "id": 1, "email": 1, "department": 1},
    ):
        raw = (row.get("department") or "")
        norm = raw.strip().lower()
        if norm not in LEGACY_MAP:
            continue
        matched += 1
        new_dept = LEGACY_MAP[norm]
        # Never a no-op write — LEGACY_MAP values are always DIFFERENT
        # from the modern enum ``pool_tech`` / ``landscape_tech``
        # only via the aliased legacy key.  Even so, guard against a
        # silly future edit that adds an identity mapping.
        if new_dept == raw:
            continue
        await coll.update_one(
            {"id": row["id"]},
            {"$set": {"department": new_dept}},
        )
        updated += 1
        who = row.get("email") or row.get("id") or "?"
        logger.info(
            f"[normalize_dept] {coll_name}: {who}  "
            f"{raw!r} → {new_dept!r}"
        )
    return {"matched": matched, "updated": updated}


async def run(db: Optional[Any] = None) -> Dict[str, Any]:
    """Entry point invoked from ``server._background_seed``.

    Optional ``db`` override is used by unit tests to bind the
    migration to their own event-loop-scoped Motor client.  Prod
    boot passes nothing and picks up ``config.db``.
    """
    db_ = db if db is not None else _default_db
    users_counts = await _normalize_collection(db_, "users")
    techs_counts = await _normalize_collection(db_, "technicians")
    total_updated = users_counts["updated"] + techs_counts["updated"]
    logger.info(
        f"[normalize_dept] complete — users: {users_counts}, "
        f"technicians: {techs_counts}"
    )
    return {
        "ok": True,
        "users":       users_counts,
        "technicians": techs_counts,
        "total_updated": total_updated,
    }
