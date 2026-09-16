"""Phase 5A · Daily service-line checklists — tenant-editable source of truth.

``GET /api/checklists/daily?service_line=pool|landscape`` returns the
ordered list of items for the requested service line. When the query
param is omitted, the service line is resolved from the current user's
department (technician role → ``pool`` for department=pool /
department=both, ``landscape`` for department=landscaping).

Storage
-------
Collection ``service_checklists`` keyed by ``{tenant_id, service_line}``
with an ordered ``items`` array of ``{key, label}`` dicts. Tenants can
edit their own copy without a code change — the boot-time seed only
inserts DEFAULTS when a tenant has no doc for the given service line.

Canonical defaults (as of Phase 5A · Feb 2026)
==============================================
Pool (7 core + 3 optional emptied items — Phase CHK1 · Feb-2026)
    1. Skimmed Pool
    2. Brush Pool
    3. Checked Skimmer Basket
    4. Checked Pump Basket
    5. Tested Chemicals
    6. Checked Equipment
    7. Secured all Gates
    8. Emptied skimmer basket        (optional)
    9. Emptied leaf canister         (optional)
    10. Emptied Betta Skimmer         (optional)

Landscape (10 items)
    1. Sprayed or Pulled Weeds
    2. Checked Irrigation
    3. Trimmed Bushes
    4. Mowed Grass
    5. Edged Grass
    6. Blow Property
    7. Raked Rocks
    8. Locked Gate
    9. Trimmed Trees
    10. Irrigation Repair

The Chemical Readings + Chemicals Added forms remain intact and are
rendered separately — this checklist is the completion checkbox list
only.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db, logger
from routers.tenants import get_current_tenant
from utils import get_current_user, now_iso

router = APIRouter()


# ─── Canonical seed data ─────────────────────────────────────────────
DEFAULT_POOL_ITEMS: List[dict] = [
    {"key": "skimmed_pool",           "label": "Skimmed Pool"},
    {"key": "brush_pool",             "label": "Brush Pool"},
    {"key": "checked_skimmer_basket", "label": "Checked Skimmer Basket"},
    {"key": "checked_pump_basket",    "label": "Checked Pump Basket"},
    {"key": "tested_chemicals",       "label": "Tested Chemicals"},
    {"key": "checked_equipment",      "label": "Checked Equipment"},
    {"key": "secured_all_gates",      "label": "Secured all Gates"},
    # Phase CHK1 · Feb-2026 — three optional "emptied" items appended.
    # These are OPTIONAL by design and must NEVER be added to the
    # chemistry gate / required-fields list — techs must be able to
    # close a job with these unchecked. Casing/spacing verbatim.
    {"key": "emptied_skimmer_basket", "label": "Emptied skimmer basket"},
    {"key": "emptied_leaf_canister",  "label": "Emptied leaf canister"},
    {"key": "emptied_betta_skimmer",  "label": "Emptied Betta Skimmer"},
]

DEFAULT_LANDSCAPE_ITEMS: List[dict] = [
    {"key": "sprayed_or_pulled_weeds", "label": "Sprayed or Pulled Weeds"},
    {"key": "checked_irrigation",      "label": "Checked Irrigation"},
    {"key": "trimmed_bushes",          "label": "Trimmed Bushes"},
    {"key": "mowed_grass",             "label": "Mowed Grass"},
    {"key": "edged_grass",             "label": "Edged Grass"},
    {"key": "blow_property",           "label": "Blow Property"},
    {"key": "raked_rocks",             "label": "Raked Rocks"},
    {"key": "locked_gate",             "label": "Locked Gate"},
    {"key": "trimmed_trees",           "label": "Trimmed Trees"},
    {"key": "irrigation_repair",       "label": "Irrigation Repair"},
]

_DEFAULTS = {
    "pool":      DEFAULT_POOL_ITEMS,
    "landscape": DEFAULT_LANDSCAPE_ITEMS,
}


def _normalize_service_line(v: Optional[str]) -> Optional[str]:
    """Accept a few common aliases so callers don't have to memorise the
    exact enum value. ``landscaping`` (matches user department) →
    ``landscape``. Anything else surfaces as-is for validation upstream."""
    if not v:
        return None
    v = v.strip().lower()
    if v in ("landscaping", "land", "landscape_tech"):
        return "landscape"
    if v in ("pool_tech",):
        return "pool"
    return v


def _resolve_from_user(user: dict) -> str:
    """Pool/landscape from user department. Non-tech callers must pass
    the explicit query param."""
    dept = (user.get("department") or "").lower()
    if dept == "landscaping":
        return "landscape"
    # pool + both + unassigned → pool (safe default; matches the tech nav
    # default used elsewhere in the codebase, see roleNav.js).
    return "pool"


@router.get("/checklists/daily")
async def get_daily_checklist(
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
    service_line: Optional[str] = Query(
        None, description="pool | landscape (defaults to caller's department)",
    ),
):
    """Return the ordered checklist for the given service line.

    Techs can only fetch their own line unless they explicitly pass the
    query param (a landscape tech may briefly look at the pool list if
    covering for a teammate, and vice versa — that's fine). Admins /
    managers must pass the query param OR they'll get the pool list."""
    sl = _normalize_service_line(service_line) or _resolve_from_user(user)
    if sl not in _DEFAULTS:
        raise HTTPException(400, f"service_line must be 'pool' or 'landscape' (got {sl})")

    doc = await db.service_checklists.find_one(
        {"tenant_id": tenant["id"], "service_line": sl},
        {"_id": 0},
    )
    if doc and doc.get("items"):
        items = doc["items"]
        source = "tenant"
    else:
        items = _DEFAULTS[sl]
        source = "default"
    return {
        "service_line": sl,
        "items": items,
        "source": source,
        "count": len(items),
    }


# ─── Boot-time seed (idempotent, non-destructive) ─────────────────────
async def seed_service_checklists_for_all_tenants() -> None:
    """For every active tenant, ensure both service_line entries exist.
    Never overwrites tenants that have already customised their copy.
    Emits an INFO log with the counts."""
    inserted = 0
    kept = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        tid = t.get("id")
        if not tid:
            continue
        for sl, items in _DEFAULTS.items():
            existing = await db.service_checklists.find_one(
                {"tenant_id": tid, "service_line": sl},
                {"_id": 0, "id": 1},
            )
            if existing:
                kept += 1
                continue
            doc = {
                "tenant_id": tid,
                "service_line": sl,
                "items": items,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "seeded_from_default": True,
            }
            try:
                await db.service_checklists.insert_one(doc)
                inserted += 1
            except Exception as e:  # pragma: no cover
                logger.warning(f"[phase5a] service_checklists seed failed for {tid}/{sl}: {e}")
    logger.info(f"[phase5a] service_checklists seed: inserted={inserted} kept={kept}")
