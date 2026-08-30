"""Phase S1.5 · Feb-2026 — Soshie Autopilot config module.

Owns the ``soshie_autopilot_config`` collection: one row per
``(tenant_id, platform)`` carrying the target cadence + enable flag +
per-tenant timezone.  The autopilot scheduler reads these rows every
15min to decide which platforms are due for a fresh publish and
which are throttled by cadence or human-review gates.

Cadence semantics
-----------------
* ``posts_per_day``  — daily platforms (GBP). Once a
  ``social_publish_log`` row lands for this platform in the tenant's
  calendar day, no further posts fire until the next day.  Applies to
  GBP per user's AM1 amendment.
* ``posts_per_week`` — rolling 7-day window from now.  Used by
  WordPress + FB + IG + LinkedIn + YouTube.  Once the count is met,
  further posts defer until the window rolls forward enough to open
  a slot.
* ``manual_only`` — Reddit is hard-blocked from autopilot per user
  decision.  The scheduler MUST skip these platforms even if
  ``enabled=True`` (defence-in-depth).

Seed defaults
-------------
Seeded on tenant first-boot AND lazily on first read.  Values:

    gbp        posts_per_day=1                     enabled=False
    wordpress  posts_per_week=3                    enabled=False
    facebook   posts_per_week=3                    enabled=False
    instagram  posts_per_week=3                    enabled=False
    linkedin   posts_per_week=2                    enabled=False
    youtube    posts_per_week=1                    enabled=False
    tiktok     posts_per_week=0  (stubbed off)     enabled=False
    reddit     posts_per_week=0  manual_only=True  enabled=False

Default enabled=False is deliberate: turning on autopilot is an
explicit admin decision, never a boot-side default.  The scheduler
respects the per-platform flag.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso


# ─── Default cadence table (Phase S1.5 amendment 1) ───────────────
DEFAULT_CADENCE: Dict[str, Dict[str, Any]] = {
    "gbp":       {"posts_per_day": 1,  "posts_per_week": None},
    "wordpress": {"posts_per_day": None, "posts_per_week": 3},
    "facebook":  {"posts_per_day": None, "posts_per_week": 3},
    "instagram": {"posts_per_day": None, "posts_per_week": 3},
    "linkedin":  {"posts_per_day": None, "posts_per_week": 2},
    "youtube":   {"posts_per_day": None, "posts_per_week": 1},
    "tiktok":    {"posts_per_day": None, "posts_per_week": 0},
    "reddit":    {"posts_per_day": None, "posts_per_week": 0,
                    "manual_only": True},
}


PLATFORMS: List[str] = list(DEFAULT_CADENCE.keys())


DEFAULT_TIMEZONE = "America/Phoenix"


async def seed_defaults(tenant_id: str,
                          timezone: str = DEFAULT_TIMEZONE) -> int:
    """Idempotent per-tenant seed. Rows already present are left
    untouched so admin customisations survive re-seeding.  Returns
    the number of newly inserted rows."""
    n = 0
    for platform, cadence in DEFAULT_CADENCE.items():
        exists = await db.soshie_autopilot_config.find_one(
            {"tenant_id": tenant_id, "platform": platform},
            {"_id": 0, "id": 1},
        )
        if exists:
            continue
        doc = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "platform": platform,
            "posts_per_day": cadence.get("posts_per_day"),
            "posts_per_week": cadence.get("posts_per_week"),
            "manual_only": bool(cadence.get("manual_only", False)),
            "timezone": timezone,
            "enabled": False,
            "last_scheduled_at": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.soshie_autopilot_config.insert_one(doc)
        n += 1
    return n


async def list_for_tenant(tenant_id: str) -> List[Dict[str, Any]]:
    """Return every autopilot config row for the tenant, seeding
    the defaults first when the tenant has no rows at all."""
    rows = await db.soshie_autopilot_config.find(
        {"tenant_id": tenant_id}, {"_id": 0},
    ).sort("platform", 1).to_list(50)
    if not rows:
        await seed_defaults(tenant_id)
        rows = await db.soshie_autopilot_config.find(
            {"tenant_id": tenant_id}, {"_id": 0},
        ).sort("platform", 1).to_list(50)
    return rows


async def get_config(tenant_id: str, platform: str) -> Optional[Dict[str, Any]]:
    doc = await db.soshie_autopilot_config.find_one(
        {"tenant_id": tenant_id, "platform": platform},
        {"_id": 0},
    )
    return doc


async def update_config(tenant_id: str, platform: str,
                              patch: Dict[str, Any]) -> Dict[str, Any]:
    """Patch a subset of ``{enabled, posts_per_day, posts_per_week,
    timezone}``.  Unknown keys are silently dropped.  Row is
    upserted so a caller can turn on autopilot for a platform whose
    seed hasn't been written yet."""
    allowed = {"enabled", "posts_per_day", "posts_per_week",
                 "timezone"}
    upd: Dict[str, Any] = {}
    for k, v in (patch or {}).items():
        if k in allowed:
            upd[k] = v
    if not upd:
        # Nothing to change — return the current row (seed first if empty).
        existing = await get_config(tenant_id, platform)
        if existing:
            return existing
    upd["updated_at"] = now_iso()
    # Ensure the row exists before patching (upsert with seed defaults).
    default = DEFAULT_CADENCE.get(platform, {})
    setoninsert = {
        "id": new_id(),
        "tenant_id": tenant_id,
        "platform": platform,
        "posts_per_day": default.get("posts_per_day"),
        "posts_per_week": default.get("posts_per_week"),
        "manual_only": bool(default.get("manual_only", False)),
        "timezone": DEFAULT_TIMEZONE,
        "enabled": False,
        "last_scheduled_at": None,
        "created_at": now_iso(),
    }
    # $set MUST NOT clash with $setOnInsert — pull matching keys out.
    for k in upd.keys():
        setoninsert.pop(k, None)
    await db.soshie_autopilot_config.update_one(
        {"tenant_id": tenant_id, "platform": platform},
        {"$set": upd, "$setOnInsert": setoninsert},
        upsert=True,
    )
    return await get_config(tenant_id, platform)  # type: ignore[return-value]


async def seed_all_tenants() -> Dict[str, int]:
    """Startup migration hook — seeds every tenant once.  Returns
    ``{tenants, inserted}`` for the boot log."""
    total = 0
    tenants = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1, "timezone": 1}):
        tz = (t.get("timezone") or "").strip() or DEFAULT_TIMEZONE
        n = await seed_defaults(t["id"], timezone=tz)
        total += n
        tenants += 1
    if total:
        logger.info(
            "[s1.5.autopilot] seeded %d row(s) across %d tenant(s)",
            total, tenants,
        )
    return {"tenants": tenants, "inserted": total}
