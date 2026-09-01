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

    gbp        posts_per_day=1    manual_only=True   enabled=False
    wordpress  posts_per_week=3                      enabled=False
    facebook   posts_per_week=3   manual_only=True   enabled=False
    instagram  posts_per_week=3   manual_only=True   enabled=False
    linkedin   posts_per_week=2   manual_only=True   enabled=False
    youtube    posts_per_week=1   manual_only=True   enabled=False
    tiktok     posts_per_week=0   manual_only=True   enabled=False
    reddit     posts_per_week=0   manual_only=True   enabled=False

Phase H5.5 · Feb-2026 — six new platforms are flipped to
``manual_only=True`` (Facebook, Instagram, LinkedIn, YouTube,
TikTok, Google Business Profile). This is a product decision to
ship value NOW without waiting on Meta / TikTok / LinkedIn /
YouTube / GBP OAuth + App Review (weeks of turnaround). Autopilot
still generates drafts + runs moderation for these platforms;
approved drafts land in the review queue with a "Copy to
clipboard" + "Mark as posted" affordance so operators hand-paste.

Note on GBP: previously carried ``manual_only=False`` because a
real GBP OAuth wiring was in scope. H5.5 explicitly downgrades
GBP to manual-only. If GBP OAuth is later provisioned, a future
phase can promote it back to fully-automated mode by flipping
this flag back to False; the review-queue affordance code path
naturally becomes dormant when nothing is stamped
``awaiting_manual``.

Default enabled=False is deliberate: turning on autopilot is an
explicit admin decision, never a boot-side default.  The scheduler
respects the per-platform flag.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import db, logger
from utils import new_id, now_iso


# ─── Default cadence table (Phase S1.5 amendment 1 → H5.5 flip) ───
DEFAULT_CADENCE: Dict[str, Dict[str, Any]] = {
    # Phase H5.5 · GBP downgraded from "Not Connected / awaiting
    # OAuth" to "Manual Only" until real GBP API wiring is scoped.
    "gbp":       {"posts_per_day": 1,  "posts_per_week": None,
                    "manual_only": True},
    "wordpress": {"posts_per_day": None, "posts_per_week": 3},
    # Phase H5.5 · Meta App Review path deferred — ship manual mode now.
    "facebook":  {"posts_per_day": None, "posts_per_week": 3,
                    "manual_only": True},
    "instagram": {"posts_per_day": None, "posts_per_week": 3,
                    "manual_only": True},
    # Phase H5.5 · LinkedIn Marketing Developer Program deferred.
    "linkedin":  {"posts_per_day": None, "posts_per_week": 2,
                    "manual_only": True},
    # Phase H5.5 · GCP + YT Data API v3 setup deferred.
    "youtube":   {"posts_per_day": None, "posts_per_week": 1,
                    "manual_only": True},
    # Phase H5.5 · TikTok Content Posting API partner path deferred.
    "tiktok":    {"posts_per_day": None, "posts_per_week": 0,
                    "manual_only": True},
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
    the defaults first when the tenant has no rows at all.

    Phase H5.5 · Feb-2026 — overlay the canonical ``manual_only``
    flag from ``DEFAULT_CADENCE`` on top of persisted rows. This
    lets us flip a platform to manual-only in code without a
    per-tenant migration: existing rows that were seeded before
    the flip keep their persisted cadence + enabled state but
    surface the current ``manual_only`` truth to the API caller
    (frontend pill + scheduler both consume this).
    """
    rows = await db.soshie_autopilot_config.find(
        {"tenant_id": tenant_id}, {"_id": 0},
    ).sort("platform", 1).to_list(50)
    if not rows:
        await seed_defaults(tenant_id)
        rows = await db.soshie_autopilot_config.find(
            {"tenant_id": tenant_id}, {"_id": 0},
        ).sort("platform", 1).to_list(50)
    for r in rows:
        canonical = DEFAULT_CADENCE.get(r.get("platform") or "", {})
        if canonical.get("manual_only"):
            r["manual_only"] = True
    return rows


def is_manual_only(platform: str, cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Single source of truth used by both the scheduler and the
    review-queue endpoints. Prefers the persisted flag but falls
    back to ``DEFAULT_CADENCE`` so freshly-flipped platforms behave
    correctly on tenants whose rows predate the flip.
    """
    if cfg and cfg.get("manual_only"):
        return True
    return bool(DEFAULT_CADENCE.get((platform or "").lower(), {})
                    .get("manual_only", False))


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
