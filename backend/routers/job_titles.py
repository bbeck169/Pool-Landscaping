"""Feb 2026 · Job Titles catalog — tenant-scoped, auto-learning.

The New Job / Edit Job UX exposes a combobox that suggests
previously used job titles for the caller's tenant. Every job save
(create + update) upserts the entered title into ``db.job_titles``
so the next tech typing the same prefix sees the completion right
away.  No admin approval — the catalog grows organically.

Collection shape
----------------
``db.job_titles``::

    {
      id:           str,   # UUID (matches the ``id`` convention used
                           # across the rest of the CRM collections)
      tenant_id:    str,
      title:        str,   # exact spelling the user typed the first
                           # time (case + whitespace preserved)
      title_lower:  str,   # ``title.strip().lower()`` — the unique
                           # dedupe key; case-insensitive matching
                           # runs against this
      usage_count:  int,   # incremented every save that uses this
                           # title (create counts as +1; update
                           # counts as +1 only when the title
                           # actually changed)
      created_at:   iso,
      updated_at:   iso,
    }

Unique compound index on ``(tenant_id, title_lower)`` prevents
duplicate rows even if two racing saves upsert the same title.

Endpoints
---------
``GET  /api/job-titles?q=<prefix>&limit=20``
    Return up to ``limit`` titles for the caller's tenant. When
    ``q`` is present, restrict to case-insensitive PREFIX match
    (``^<escaped-q>``); when no prefix results exist, fall back to
    substring match so a typo mid-string still surfaces the row.
    Sorted by ``usage_count DESC`` then ``title ASC``.

``POST /api/job-titles``
    Body ``{title: str}``.  Idempotent upsert — creates the row if
    it doesn't exist, increments ``usage_count`` if it does.
    Returns ``{id, title, usage_count}``.  Called by the ``jobs``
    router on every ``create_job`` / ``update_job`` that ships a
    non-empty title.
"""
from __future__ import annotations

import logging
import re as _re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import db
from utils import get_current_user
from routers.tenants import get_current_tenant


logger = logging.getLogger("job_titles")

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# Indexes
# ─────────────────────────────────────────────────────────────────────
async def ensure_indexes() -> None:
    """Idempotent — create the unique compound index if missing.

    Called on boot via ``scripts.ensure_indexes.ROUTER_ENSURE_INDEXES``
    (see the ensure-indexes registry).  Safe to call repeatedly.
    """
    try:
        await db.job_titles.create_index(
            [("tenant_id", 1), ("title_lower", 1)],
            unique=True,
            name="job_titles_tenant_title_lower_unique",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[job_titles] ensure_indexes failed: %s", exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(raw: str) -> str:
    """Collapse whitespace + strip so ``"  Pool  Cleaning "`` and
    ``"Pool Cleaning"`` dedupe against the same catalog row."""
    return _re.sub(r"\s+", " ", (raw or "").strip())


# ─────────────────────────────────────────────────────────────────────
# Upsert helper — shared by the endpoint AND the jobs.py hook.
# ─────────────────────────────────────────────────────────────────────
async def record_title_usage(tenant_id: str, title: str) -> Optional[Dict[str, Any]]:
    """Idempotent upsert. Returns ``{id, title, usage_count}`` or
    None when the input is empty/whitespace.

    Safe to call from any surface that receives a user-typed
    title. Never raises on a duplicate race — the upsert semantic
    handles the E11000 case natively.
    """
    normalized = _normalize(title)
    if not normalized:
        return None
    lower = normalized.lower()
    now = _now_iso()
    # Use $setOnInsert for the immutable fields (id/created_at/title)
    # so subsequent upserts don't clobber the original casing or id.
    # $inc handles the counter, $set stamps updated_at.
    res = await db.job_titles.find_one_and_update(
        {"tenant_id": tenant_id, "title_lower": lower},
        {
            "$setOnInsert": {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "title": normalized,
                "title_lower": lower,
                "created_at": now,
            },
            "$inc": {"usage_count": 1},
            "$set": {"updated_at": now},
        },
        upsert=True,
        return_document=True,      # motor: ReturnDocument.AFTER-equivalent
        projection={"_id": 0, "id": 1, "title": 1, "usage_count": 1},
    )
    return res


# ─────────────────────────────────────────────────────────────────────
# Pydantic
# ─────────────────────────────────────────────────────────────────────
class _JobTitleIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class _JobTitleOut(BaseModel):
    id: str
    title: str
    usage_count: int


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────
_STAFF_ROLES = {"admin", "super_admin", "owner", "manager", "technician"}


@router.get("/job-titles", response_model=List[_JobTitleOut])
async def list_job_titles(
    q: Optional[str] = Query(
        None,
        description=(
            "Prefix filter (case-insensitive).  Falls back to a "
            "substring match when the prefix has no hits."
        ),
    ),
    limit: int = Query(20, ge=1, le=100),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> List[Dict[str, Any]]:
    role = (user.get("role") or "").lower()
    if role not in _STAFF_ROLES:
        raise HTTPException(403, "Not permitted")
    tid = tenant["id"]
    base = {"tenant_id": tid}
    proj = {"_id": 0, "id": 1, "title": 1, "usage_count": 1}
    sort = [("usage_count", -1), ("title", 1)]

    query = _normalize(q or "")
    if not query:
        rows = await (db.job_titles.find(base, proj)
                        .sort(sort).limit(limit).to_list(limit))
        return rows

    escaped = _re.escape(query.lower())
    # Prefix pass first.
    prefix_q = {**base, "title_lower": {"$regex": f"^{escaped}"}}
    rows = await (db.job_titles.find(prefix_q, proj)
                    .sort(sort).limit(limit).to_list(limit))
    if rows:
        return rows
    # Substring fallback.
    sub_q = {**base, "title_lower": {"$regex": escaped}}
    rows = await (db.job_titles.find(sub_q, proj)
                    .sort(sort).limit(limit).to_list(limit))
    return rows


@router.post("/job-titles", response_model=_JobTitleOut)
async def upsert_job_title(
    body: _JobTitleIn = Body(...),
    user: Dict[str, Any] = Depends(get_current_user),
    tenant: Dict[str, Any] = Depends(get_current_tenant),
) -> Dict[str, Any]:
    role = (user.get("role") or "").lower()
    if role not in _STAFF_ROLES:
        raise HTTPException(403, "Not permitted")
    doc = await record_title_usage(tenant["id"], body.title)
    if doc is None:
        raise HTTPException(400, "title cannot be empty")
    return doc


# ─────────────────────────────────────────────────────────────────────
# Boot-time backfill (idempotent).
# ─────────────────────────────────────────────────────────────────────
# Guard the backfill with a sentinel row in ``db.migrations`` so it
# runs exactly once per environment even across restarts. Legacy
# tenants that don't have any jobs yet cost < 5ms per tenant to
# check, so the guard cost is negligible.
_BACKFILL_KEY = "feb2026_job_titles_backfill_v1"


async def backfill_from_existing_jobs() -> Dict[str, Any]:
    """Seed ``db.job_titles`` from ``db.jobs.title`` distincts per
    tenant.  Idempotent via ``db.migrations`` sentinel — safe to
    call on every boot; second-and-later calls are ~10ms no-ops.
    """
    already = await db.migrations.find_one({"id": _BACKFILL_KEY})
    if already:
        return {"skipped": True, "reason": "already_ran"}
    tenants_touched = 0
    titles_seeded = 0
    async for tenant_row in db.tenants.find({}, {"_id": 0, "id": 1}):
        tid = tenant_row.get("id")
        if not tid:
            continue
        # Aggregate distinct titles + their counts within the tenant.
        pipeline = [
            {"$match": {
                "tenant_id": tid,
                "title": {"$exists": True, "$nin": [None, ""]},
            }},
            {"$group": {"_id": "$title", "n": {"$sum": 1}}},
        ]
        touched = 0
        async for row in db.jobs.aggregate(pipeline):
            title = _normalize(str(row.get("_id") or ""))
            if not title:
                continue
            count = int(row.get("n") or 0)
            lower = title.lower()
            now = _now_iso()
            # Upsert with the real count; $setOnInsert protects the
            # original id/title if a race created it first.
            await db.job_titles.update_one(
                {"tenant_id": tid, "title_lower": lower},
                {
                    "$setOnInsert": {
                        "id": str(uuid.uuid4()),
                        "tenant_id": tid,
                        "title": title,
                        "title_lower": lower,
                        "created_at": now,
                    },
                    "$set": {
                        "usage_count": count,
                        "updated_at": now,
                    },
                },
                upsert=True,
            )
            touched += 1
            titles_seeded += 1
        if touched:
            tenants_touched += 1
    # Sentinel — subsequent boots become no-ops.
    await db.migrations.insert_one({
        "id": _BACKFILL_KEY,
        "ran_at": _now_iso(),
        "tenants_touched": tenants_touched,
        "titles_seeded": titles_seeded,
    })
    logger.info(
        "[job_titles] backfill complete · tenants=%d titles=%d",
        tenants_touched, titles_seeded,
    )
    return {
        "skipped": False,
        "tenants_touched": tenants_touched,
        "titles_seeded": titles_seeded,
    }
