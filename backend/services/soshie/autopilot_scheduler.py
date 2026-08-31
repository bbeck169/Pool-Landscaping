"""Phase S1.5 · Feb-2026 — Soshie Autopilot scheduler tick.

Runs every 15 minutes on the app's ``AsyncIOScheduler`` singleton
(registered by ``server.py``).  Per tick, per tenant with
``soshie_autopilot_enabled=True`` (any per-platform row):

    1. Acquire a per-tenant scheduler lease (55s TTL) so replicas
       never double-dispatch.
    2. Iterate autopilot-enabled platform configs for the tenant.
       Reddit is a HARD-BLOCK — always skipped regardless of
       ``enabled=True`` (defence-in-depth per user decision).
    3. For each platform, load the pending ``ai_employee_actions``
       rows matching:
          action == "soshie.publish_blog" or (soshie.draft_post
                    with the target platform in draft.platform),
          status == "pending",
          moderation_flags == [],
          requires_human_approval != True,
          created_at <= now - 24h.
    4. Check tenant AI credits.  Below the heavy-action floor
       (5 credits) → flip the action to ``deferred_no_credits``,
       skip.  Credit balance recovers → next tick picks up.
    5. Cadence check (Part B of the S1.5 brief):
          * ``posts_per_day``  — count today's
            ``social_publish_log`` rows in the tenant's TZ.  Hit? Skip.
          * ``posts_per_week`` — count last-7-day rows.  Hit? Skip.
    6. For image-bearing platforms (IG/TikTok/FB/GBP) that don't
       yet have media on the action row, run the media pipeline:
          a. ``select_media_for_post`` — hybrid job-photo → AI.
          b. If AI-generated, ``score_brand_consistency`` → if <
             threshold, flip ``requires_human_approval=True`` and
             skip.
          c. Persist ``media_url``, ``media_source``, ``brand_score``
             on the action row.
    7. Dispatch via
       :func:`routers.soshie_publishing.execute_publish_for_action`
       with ``idempotency_key=f"action-{aid}"``.  Success flips the
       row to ``status="published"``; failure to ``status="failed"``.

The lease + the action-row state machine give us two independent
guards against duplicate publishes.  ``social_publish_log`` has a
compound unique index on ``(tenant_id, action_id, platform)`` as
the final tripwire.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from config import db
from services.comms_hardening.scheduler_lease import (
    try_acquire_lease, release_lease,
)
from services.soshie.autopilot_config import (
    DEFAULT_CADENCE, PLATFORMS, seed_defaults,
)


logger = logging.getLogger("soshie.autopilot.scheduler")


# ─── Constants ────────────────────────────────────────────────────
AUTOPILOT_WINDOW_HOURS = 24
CREDIT_FLOOR = 5                # heavy-action cost floor
IMAGE_BEARING_PLATFORMS = {"instagram", "tiktok", "facebook", "gbp"}
REDDIT_HARDBLOCK = "reddit"    # never autopilot-dispatched


def _iso_hours_ago(hours: int) -> str:
    return (datetime.now(timezone.utc)
             - timedelta(hours=hours)).isoformat()


def _today_start_in_tz_iso(tz_name: str) -> str:
    """Midnight (start-of-day) in the tenant's timezone, expressed
    as an ISO string in UTC — matches the ISO strings written into
    ``social_publish_log.dispatched_at``."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:                                            # noqa: BLE001
        tz = ZoneInfo("America/Phoenix")
    now_local = datetime.now(tz)
    start_local = now_local.replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return start_local.astimezone(timezone.utc).isoformat()


async def _tenant_credit_balance(tenant_id: str) -> int:
    doc = await db.tenants.find_one(
        {"id": tenant_id}, {"_id": 0, "ai_credits_balance": 1},
    ) or {}
    try:
        return int(doc.get("ai_credits_balance") or 0)
    except (TypeError, ValueError):
        return 0


async def _count_publishes_since(tenant_id: str, platform: str,
                                      since_iso: str) -> int:
    return await db.social_publish_log.count_documents({
        "tenant_id": tenant_id,
        "platform": platform,
        "dispatched_at": {"$gte": since_iso},
    })


async def _cadence_ok(tenant_id: str, platform: str,
                          cfg: Dict[str, Any]) -> bool:
    """True when the platform has an open slot right now.  Daily
    cadence (GBP) uses today-start in the tenant's TZ; weekly uses
    a rolling 7d window in UTC (accuracy > TZ minutiae for weekly)."""
    ppd = cfg.get("posts_per_day")
    if isinstance(ppd, int) and ppd > 0:
        start = _today_start_in_tz_iso(cfg.get("timezone")
                                             or "America/Phoenix")
        used = await _count_publishes_since(tenant_id, platform, start)
        return used < ppd
    ppw = cfg.get("posts_per_week")
    if isinstance(ppw, int) and ppw > 0:
        start = (datetime.now(timezone.utc)
                     - timedelta(days=7)).isoformat()
        used = await _count_publishes_since(tenant_id, platform, start)
        return used < ppw
    return False   # posts_per_week=0 or None → autopilot never fires


def _platform_from_action(doc: Dict[str, Any]) -> Optional[str]:
    """Resolve the target platform from a Soshie action row."""
    action = doc.get("action") or ""
    draft = doc.get("draft") or {}
    if action == "soshie.publish_blog":
        return "wordpress"
    if action == "soshie.draft_post":
        return (draft.get("platform") or "").strip().lower() or None
    if action == "soshie.schedule_post":
        return ((doc.get("params") or {}).get("platform") or "").strip().lower() or None
    return None


async def _actions_due_for_platform(
    *, tenant_id: str, platform: str, cutoff_iso: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Pending Soshie actions past the 24h window that target the
    given platform.  Filters out flagged / human-review rows."""
    action_names: List[str] = ["soshie.publish_blog"]
    # Non-blog platforms map to ``soshie.draft_post`` with a
    # matching ``draft.platform`` value.
    if platform != "wordpress":
        action_names.append("soshie.draft_post")
    query: Dict[str, Any] = {
        "tenant_id": tenant_id,
        "employee_key": "soshie",
        "action": {"$in": action_names},
        "status": "pending",
        "created_at": {"$lte": cutoff_iso},
        # Empty list OR missing → clean.
        "$or": [
            {"moderation_flags": {"$in": [None, []]}},
            {"moderation_flags": {"$exists": False}},
        ],
        "requires_human_approval": {"$ne": True},
    }
    rows: List[Dict[str, Any]] = []
    async for doc in db.ai_employee_actions.find(
        query, {"_id": 0},
    ).sort("created_at", 1).limit(limit):
        if _platform_from_action(doc) != platform:
            continue
        rows.append(doc)
    return rows


async def _mark_deferred_no_credits(action_id: str, tenant_id: str) -> None:
    """Flip a pending action to the ``deferred_no_credits`` audit
    state so admins can see why autopilot skipped it.  Idempotent —
    only flips rows that are still ``pending``."""
    from utils import now_iso
    await db.ai_employee_actions.update_one(
        {"id": action_id, "tenant_id": tenant_id, "status": "pending"},
        {"$set": {"status": "deferred_no_credits",
                    "updated_at": now_iso()}},
    )


async def _requeue_deferred(tenant_id: str) -> int:
    """Every tick, flip any ``deferred_no_credits`` rows for this
    tenant back to ``pending`` — credits may have topped up between
    ticks.  Returns the number of rows requeued."""
    from utils import now_iso
    r = await db.ai_employee_actions.update_many(
        {"tenant_id": tenant_id, "status": "deferred_no_credits"},
        {"$set": {"status": "pending", "updated_at": now_iso()}},
    )
    return int(getattr(r, "modified_count", 0) or 0)


async def _maybe_attach_media(
    *, tenant_id: str, action: Dict[str, Any], platform: str,
) -> Dict[str, Any]:
    """For image-bearing platforms, ensure the action row has a
    ``media_url``.  If the action already has media, no-op.  If
    we generate via AI, run the brand-score gate and — on a low
    score — mark ``requires_human_approval=True`` and short-circuit.

    Returns::

        {"ok": bool,             # False → skip dispatch this tick
         "media_url": Optional[str],
         "media_source": str,    # "job_photo" | "ai_generated"
         "brand_score": Optional[float],
         "requires_human_approval": bool}
    """
    if platform not in IMAGE_BEARING_PLATFORMS:
        return {"ok": True, "media_url": None,
                 "media_source": "none",
                 "brand_score": None,
                 "requires_human_approval": False}
    if action.get("media_url"):
        return {"ok": True, "media_url": action["media_url"],
                 "media_source": action.get("media_source") or "prior",
                 "brand_score": action.get("brand_score"),
                 "requires_human_approval": False}
    from services.soshie.media_selector import select_media_for_post
    from services.soshie.ai_image_gen import (
        generate_brand_image, score_brand_consistency,
        _fetch_brand_memory, BRAND_SCORE_THRESHOLD,
    )
    ctx = {
        "service_type":
            (action.get("params") or {}).get("service_type")
            or (action.get("draft") or {}).get("service_type"),
    }
    sel = await select_media_for_post(tenant_id=tenant_id,
                                             post_context=ctx)
    if sel.get("source") == "job_photo" and sel.get("url"):
        return {"ok": True, "media_url": sel["url"],
                 "media_source": "job_photo",
                 "brand_score": None,
                 "requires_human_approval": False}
    # No job photo — AI fallback.
    try:
        gen = await generate_brand_image(
            tenant_id=tenant_id, platform=platform,
            prompt_context={
                "service_type": ctx.get("service_type") or "",
            },
            action_id=action["id"],
        )
    except Exception as e:                                        # noqa: BLE001
        logger.warning(
            "[autopilot] AI image gen failed action=%s: %s",
            action.get("id"), e,
        )
        return {"ok": False, "media_url": None,
                 "media_source": "none",
                 "brand_score": None,
                 "requires_human_approval": True,
                 "error": str(e)}
    brand = await _fetch_brand_memory(tenant_id)
    score = await score_brand_consistency(
        image_url=gen["url"], brand_memory=brand,
        tenant_id=tenant_id,
    )
    if score < BRAND_SCORE_THRESHOLD:
        return {"ok": False, "media_url": gen["url"],
                 "media_source": "ai_generated",
                 "brand_score": score,
                 "requires_human_approval": True}
    return {"ok": True, "media_url": gen["url"],
             "media_source": "ai_generated",
             "brand_score": score,
             "requires_human_approval": False}


async def _persist_media_on_action(
    *, action_id: str, tenant_id: str, media: Dict[str, Any],
) -> None:
    from utils import now_iso
    upd: Dict[str, Any] = {"updated_at": now_iso()}
    if media.get("media_url"):
        upd["media_url"] = media["media_url"]
    if media.get("media_source") and media["media_source"] != "none":
        upd["media_source"] = media["media_source"]
    if media.get("brand_score") is not None:
        upd["brand_score"] = float(media["brand_score"])
    if media.get("requires_human_approval"):
        upd["requires_human_approval"] = True
    await db.ai_employee_actions.update_one(
        {"id": action_id, "tenant_id": tenant_id}, {"$set": upd},
    )


async def _run_moderation_gate(
    *, tenant_id: str, action: Dict[str, Any],
    media: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Phase F3 · Feb-2026 — LLM moderation gate.

    Returns ``None`` when the post is cleared for publish (caller
    proceeds).  Returns a small outcome dict when the post is diverted
    (``awaiting_review`` / ``blocked``) and persists the moderation
    fingerprint onto the action row.
    """
    from utils import now_iso
    from services.soshie.llm_moderation import moderate_post

    aid = action["id"]
    draft = action.get("draft") or {}
    text = draft.get("text") or ""
    media_urls = [u for u in [media.get("media_url")] if u]
    try:
        result = await moderate_post(
            post_id=aid, tenant_id=tenant_id,
            text=text, media_urls=media_urls,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[autopilot] moderation crashed action=%s: %s", aid, e,
        )
        result = {"decision": "flag",
                    "reasons": ["moderation_service_unavailable"],
                    "risk_level": "medium",
                    "model": "unknown",
                    "cost_estimate_usd": 0.0,
                    "error": str(e)}
    decision = result.get("decision") or "flag"
    upd = {
        "moderation_decision": decision,
        "moderation_reasons": list(result.get("reasons") or []),
        "moderation_risk_level": result.get("risk_level") or "medium",
        "moderation_model": result.get("model"),
        "moderation_hash": result.get("hash"),
        "moderation_cost_usd": float(result.get("cost_estimate_usd") or 0.0),
        "moderation_checked_at": now_iso(),
        "updated_at": now_iso(),
    }
    if decision == "approve":
        await db.ai_employee_actions.update_one(
            {"id": aid, "tenant_id": tenant_id}, {"$set": upd},
        )
        return None
    if decision == "flag":
        upd["status"] = "awaiting_review"
    else:  # "block"
        upd["status"] = "blocked"
    await db.ai_employee_actions.update_one(
        {"id": aid, "tenant_id": tenant_id}, {"$set": upd},
    )
    return {
        "action_id": aid,
        "outcome": f"moderation_{decision}",
        "reasons": upd["moderation_reasons"],
    }


async def _dispatch_one(
    *, tenant_id: str, action: Dict[str, Any], platform: str,
) -> Dict[str, Any]:
    """Fire the publish for one action row.  Returns a small dict
    with the outcome for the tick summary."""
    from utils import now_iso
    from routers.soshie_publishing import execute_publish_for_action

    aid = action["id"]
    draft = action.get("draft") or {}
    params = action.get("params") or {}
    text = draft.get("text") or ""
    title = draft.get("title") or params.get("title") or ""
    if not text:
        return {"action_id": aid, "outcome": "skipped_empty_draft"}
    try:
        result = await execute_publish_for_action(
            action_id=aid,
            tenant_id=tenant_id,
            user_id="soshie-autopilot",
            platforms=[platform],
            text=text,
            title=title,
            link=params.get("link"),
            status=params.get("wp_status") or "draft",
            idempotency_key=f"action-{aid}",
        )
    except Exception as e:                                        # noqa: BLE001
        logger.warning(
            "[autopilot] dispatch crashed action=%s platform=%s: %s",
            aid, platform, e,
        )
        await db.ai_employee_actions.update_one(
            {"id": aid, "tenant_id": tenant_id},
            {"$set": {"status": "failed",
                        "executed_at": now_iso(),
                        "result": {"kind": "autopilot_dispatch_crash",
                                     "error": str(e)},
                        "updated_at": now_iso()}},
        )
        return {"action_id": aid, "outcome": "crashed", "error": str(e)}
    # Interpret adapter response.
    row = next(
        (r for r in result.get("results", [])
          if r.get("platform") == platform),
        None,
    )
    ok = bool(
        row
        and row.get("platform_post_id")
        and not row.get("error")
        and row.get("status") not in ("failed", "not_configured")
    )
    upd = {
        "executed_at": now_iso(),
        "updated_at": now_iso(),
        "result": {
            "kind": "soshie_autopilot_published" if ok
                        else "soshie_autopilot_failed",
            "publish": result,
        },
    }
    if ok:
        upd["status"] = "published"
    else:
        upd["status"] = "failed"
        upd["result"]["error"] = (row or {}).get("error") \
            or "adapter did not publish"
    await db.ai_employee_actions.update_one(
        {"id": aid, "tenant_id": tenant_id}, {"$set": upd},
    )
    return {"action_id": aid, "platform": platform,
            "outcome": "published" if ok else "failed"}


async def _process_tenant(tenant_id: str) -> Dict[str, Any]:
    """Full per-tenant tick pipeline. Returns a summary the caller
    can log."""
    lease = await try_acquire_lease(
        job_id="soshie.autopilot.tick",
        tenant_id=tenant_id,
        ttl_seconds=55,
    )
    if not lease.get("acquired"):
        return {"tenant": tenant_id, "skipped": "lease_lost"}
    try:
        # Global kill switch — Phase S2 · Feb-2026.  Tenant-wide
        # off overrides per-platform ``enabled=True`` and short-
        # circuits the entire tick.
        t = await db.tenants.find_one(
            {"id": tenant_id},
            {"_id": 0, "soshie_autopilot_enabled": 1},
        ) or {}
        if t.get("soshie_autopilot_enabled") is False:
            return {"tenant": tenant_id,
                    "skipped": "global_kill_switch_off"}
        # Requeue any deferred_no_credits rows in case credits recovered.
        await _requeue_deferred(tenant_id)
        # Autopilot-enabled platforms (Reddit hardblocked below).
        configs = await db.soshie_autopilot_config.find(
            {"tenant_id": tenant_id, "enabled": True},
            {"_id": 0},
        ).to_list(50)
        results: List[Dict[str, Any]] = []
        credits = await _tenant_credit_balance(tenant_id)
        cutoff = _iso_hours_ago(AUTOPILOT_WINDOW_HOURS)
        for cfg in configs:
            platform = (cfg.get("platform") or "").strip().lower()
            if platform == REDDIT_HARDBLOCK:
                logger.warning(
                    "[autopilot] reddit is hard-blocked from autopilot "
                    "for tenant %s — skipping despite enabled=True",
                    tenant_id,
                )
                continue
            if cfg.get("manual_only"):
                continue
            if not await _cadence_ok(tenant_id, platform, cfg):
                results.append({"platform": platform,
                                  "outcome": "cadence_hit"})
                continue
            actions = await _actions_due_for_platform(
                tenant_id=tenant_id, platform=platform,
                cutoff_iso=cutoff,
            )
            for action in actions:
                if credits < CREDIT_FLOOR:
                    await _mark_deferred_no_credits(
                        action["id"], tenant_id)
                    results.append({
                        "action_id": action["id"],
                        "platform": platform,
                        "outcome": "deferred_no_credits",
                    })
                    continue
                media = await _maybe_attach_media(
                    tenant_id=tenant_id,
                    action=action, platform=platform,
                )
                await _persist_media_on_action(
                    action_id=action["id"], tenant_id=tenant_id,
                    media=media,
                )
                if not media.get("ok"):
                    results.append({
                        "action_id": action["id"],
                        "platform": platform,
                        "outcome": "blocked_human_review",
                        "brand_score": media.get("brand_score"),
                    })
                    continue
                # Phase F3 · Feb-2026 — LLM Moderation gate.  Runs
                # AFTER media resolution (so image URLs are part of
                # the moderation input) but BEFORE any adapter call.
                # decision "approve" → publish; "flag" → queue for
                # admin review; "block" → mark rejected.  Failures
                # of the moderation call ALWAYS fall through to
                # "flag" — we never auto-approve on error.
                mod_outcome = await _run_moderation_gate(
                    tenant_id=tenant_id, action=action,
                    media=media,
                )
                if mod_outcome:
                    results.append(mod_outcome)
                    continue
                # Merge media context onto the action for the dispatch.
                enriched = {**action, **{k: v for k, v in {
                    "media_url": media.get("media_url"),
                    "media_source": media.get("media_source"),
                    "brand_score": media.get("brand_score"),
                }.items() if v is not None}}
                results.append(await _dispatch_one(
                    tenant_id=tenant_id, action=enriched,
                    platform=platform,
                ))
                # One post per platform per tick to respect cadence
                # even if multiple actions are eligible.
                break
        return {"tenant": tenant_id, "results": results}
    finally:
        await release_lease(lease.get("lease_id"))


async def tick() -> Dict[str, Any]:
    """Global tick — iterates every tenant that has any
    autopilot-enabled platform row and processes them serially.
    Serial keeps the Motor pool light; volume is bounded by the
    tenant count (~500 today)."""
    tenant_ids: List[str] = []
    async for row in db.soshie_autopilot_config.find(
        {"enabled": True}, {"_id": 0, "tenant_id": 1},
    ):
        tid = row.get("tenant_id")
        if tid and tid not in tenant_ids:
            tenant_ids.append(tid)
    out: List[Dict[str, Any]] = []
    for tid in tenant_ids:
        try:
            out.append(await _process_tenant(tid))
        except Exception as e:                                    # noqa: BLE001
            logger.warning(
                "[autopilot.tick] tenant %s crashed: %s", tid, e,
            )
            out.append({"tenant": tid, "error": str(e)})
    if out:
        logger.info(
            "[autopilot.tick] processed %d tenant(s)", len(out),
        )
    return {"tenants": out, "count": len(out)}


def register_soshie_autopilot_cron(scheduler) -> None:
    """Attach the tick to the app's existing ``AsyncIOScheduler``.
    Every 15 minutes."""
    if scheduler is None:
        return
    from apscheduler.triggers.interval import IntervalTrigger
    try:
        scheduler.add_job(
            tick,
            IntervalTrigger(minutes=15),
            id="soshie.autopilot.tick",
            replace_existing=True,
        )
        logger.info(
            "[autopilot] 15-min autopilot tick registered",
        )
    except Exception as exc:                                    # noqa: BLE001
        logger.warning(
            "[autopilot] scheduler registration failed: %s", exc,
        )
