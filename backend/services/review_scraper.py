"""Review-scraper service · Reviews Phase 3 (Feb 2026).

Central dispatcher + persistence layer for pulling external review
platforms into the ``reviews`` collection. Each platform adapter lives
in ``review_scraper_adapters/`` and exposes a coroutine
``fetch_recent_reviews(tenant_id) -> list[dict]`` returning
``ReviewDoc``-shaped payloads (see ``_UPSERT_KEYS`` below for the
required fields).

Behaviour contracts:
- Missing env / disabled integration → adapter returns ``[]`` and marks
  the sweep as ``not_configured`` / ``disabled`` on the resulting
  ``review_sync_events`` row. Never crashes the sweep.
- Deduplication uses ``(tenant_id, platform, source_review_id)`` as the
  unique key; the collection carries an index enforced by
  ``_ensure_indexes``.
- ``admin_response`` and ``visible_on_widget`` are **never overwritten**
  on re-sync — they belong to the operator.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import db
from utils import new_id

logger = logging.getLogger(__name__)

# ─── Env flags ────────────────────────────────────────────────────────
_GBP_FLAG_ENV = "GOOGLE_GBP_INTEGRATION_ENABLED"
_FB_FLAG_ENV  = "FACEBOOK_INTEGRATION_ENABLED"
_YELP_KEY_ENV = "YELP_API_KEY"

# Platforms with no sanctioned automation. Kept in-code so
# ``/sync-now/{platform}`` can 404 fast without an ``if platform in ...``
# chain sprinkled around routers.
UNSUPPORTED_PLATFORMS = {"bbb", "custom"}
SUPPORTED_PLATFORMS  = {"google", "facebook", "yelp"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ensure_indexes() -> None:
    """Uniqueness on ``(tenant_id, platform, source_review_id)`` +
    a per-tenant/platform reverse-chronological index for the sync
    journal. Idempotent; safe to call every sweep."""
    try:
        # Sparse so the internal_capture rows (source_review_id=None)
        # don't collide with each other.
        await db.reviews.create_index(
            [("tenant_id", 1), ("platform", 1), ("source_review_id", 1)],
            name="reviews_scrape_dedup",
            partialFilterExpression={"source_review_id": {"$type": "string"}},
            unique=True,
        )
        await db.review_sync_events.create_index(
            [("tenant_id", 1), ("platform", 1), ("ran_at", -1)],
        )
    except Exception as e:
        logger.debug(f"[review_scraper] index bootstrap partial: {e}")


# ─── Upsert primitive ────────────────────────────────────────────────

_UPSERT_KEYS = (
    "star_rating", "review_text", "reviewer_name",
    "external_review_url", "partial_content",
)


async def _upsert_review(tenant_id: str, platform: str, doc: dict) -> str:
    """Insert or update one scraped review.

    Returns one of ``"new"`` (row inserted), ``"updated"`` (existing row
    had a mutable field change), or ``"unchanged"`` (already fully in
    sync — most common). ``admin_response`` and ``visible_on_widget`` are
    admin-owned and never touched by this path.
    """
    src_id = str(doc.get("source_review_id") or "").strip()
    if not src_id:
        # Adapter must provide a stable ID for dedup. Bail loudly in
        # tests, silently in prod.
        raise ValueError("source_review_id required for scraped reviews")

    existing = await db.reviews.find_one(
        {"tenant_id": tenant_id, "platform": platform, "source_review_id": src_id},
        {"_id": 0},
    )
    if not existing:
        row = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "source": f"{platform}_scraped",
            "source_review_id": src_id,
            "review_request_id": None,
            "customer_id": None,
            "technician_id": None,
            "platform": platform,
            "star_rating": int(doc.get("star_rating") or 0),
            "review_text": (doc.get("review_text") or "").strip(),
            "reviewer_name": (doc.get("reviewer_name") or "").strip() or None,
            "external_review_url": doc.get("external_review_url"),
            "partial_content": bool(doc.get("partial_content")),
            "is_public": True,
            "visible_on_widget": True,
            "admin_response": None,
            "admin_response_at": None,
            "created_at": doc.get("created_at") or _now_iso(),
            "scraped_at": _now_iso(),
        }
        await db.reviews.insert_one(row)
        return "new"

    changes: Dict[str, Any] = {}
    for k in _UPSERT_KEYS:
        new_val = doc.get(k)
        if new_val is None:
            continue
        old_val = existing.get(k)
        # Normalise types where the external API is loose (Yelp sends
        # star_rating as string sometimes).
        if k == "star_rating":
            new_val = int(new_val)
        if new_val != old_val:
            changes[k] = new_val
    if not changes:
        return "unchanged"

    changes["scraped_at"] = _now_iso()
    await db.reviews.update_one(
        {"tenant_id": tenant_id, "platform": platform, "source_review_id": src_id},
        {"$set": changes},
    )
    return "updated"


# ─── Adapter dispatch ────────────────────────────────────────────────

def _adapter_for(platform: str):
    """Import lazily so a missing SDK for one platform doesn't tank the
    whole engine at import time."""
    if platform == "google":
        from services.review_scraper_adapters import google_adapter as ga
        return ga.fetch_recent_reviews
    if platform == "facebook":
        from services.review_scraper_adapters import facebook_adapter as fa
        return fa.fetch_recent_reviews
    if platform == "yelp":
        from services.review_scraper_adapters import yelp_adapter as ya
        return ya.fetch_recent_reviews
    return None


async def sync_platform(tenant_id: str, platform: str) -> Dict[str, Any]:
    """Run one adapter sweep for one tenant + platform.

    Returns a summary dict:
      ``{platform, tenant_id, fetched_count, new_count, updated_count,
         status: "ok"|"disabled"|"not_configured"|"error",
         error: str|None, ran_at}``

    Always writes a ``review_sync_events`` row (best-effort; log-only on
    failure).
    """
    if platform in UNSUPPORTED_PLATFORMS:
        return {
            "platform": platform, "tenant_id": tenant_id,
            "status": "unsupported",
            "detail": ("BBB has no review API and HTML scraping is "
                        "brittle — enter BBB reviews manually via "
                        "POST /api/reviews/reviews.")
                       if platform == "bbb"
                       else "Custom platforms are managed manually.",
            "fetched_count": 0, "new_count": 0, "updated_count": 0,
            "ran_at": _now_iso(),
        }

    await _ensure_indexes()

    adapter = _adapter_for(platform)
    if adapter is None:
        summary = {
            "platform": platform, "tenant_id": tenant_id,
            "status": "unsupported", "detail": f"Unknown platform '{platform}'",
            "fetched_count": 0, "new_count": 0, "updated_count": 0,
            "ran_at": _now_iso(),
        }
        return summary

    fetched: List[dict] = []
    status = "ok"
    detail: Optional[str] = None
    err: Optional[str] = None
    try:
        result = await adapter(tenant_id)
        # Adapters can return either a list (successful fetch) or a
        # dict signalling ``disabled`` / ``not_configured``.
        if isinstance(result, dict) and result.get("status") in (
            "disabled", "not_configured", "not_connected",
        ):
            status = result["status"]
            detail = result.get("detail")
            fetched = []
        else:
            fetched = list(result or [])
    except Exception as e:
        logger.exception(f"[review_scraper.{platform}] adapter crash: {e}")
        status = "error"
        err = str(e)[:400]

    new_count = 0
    updated_count = 0
    if status == "ok":
        for doc in fetched:
            try:
                outcome = await _upsert_review(tenant_id, platform, doc)
                if outcome == "new":
                    new_count += 1
                elif outcome == "updated":
                    updated_count += 1
            except Exception as e:
                logger.warning(f"[review_scraper.{platform}] upsert failed: {e}")

    summary = {
        "id": new_id(),
        "platform": platform,
        "tenant_id": tenant_id,
        "fetched_count": len(fetched),
        "new_count": new_count,
        "updated_count": updated_count,
        "status": status,
        "detail": detail,
        "error": err,
        "ran_at": _now_iso(),
    }
    try:
        await db.review_sync_events.insert_one(dict(summary))
    except Exception as e:
        logger.warning(f"[review_scraper] event journal write failed: {e}")
    return summary


async def sync_all_tenants(platform: str) -> Dict[str, Any]:
    """Fan out a per-platform sweep across every tenant. Called by the
    APScheduler daily sweeps."""
    total_tenants = 0
    total_new = 0
    total_updated = 0
    async for t in db.tenants.find({}, {"_id": 0, "id": 1}):
        total_tenants += 1
        try:
            s = await sync_platform(t["id"], platform)
            total_new += int(s.get("new_count") or 0)
            total_updated += int(s.get("updated_count") or 0)
        except Exception as e:
            logger.warning(f"[review_scraper] {platform} tenant {t.get('id')} failed: {e}")
    return {
        "platform": platform,
        "tenants_visited": total_tenants,
        "new_count": total_new,
        "updated_count": total_updated,
        "ran_at": _now_iso(),
    }


# ─── Scheduler registration ──────────────────────────────────────────

# Feb-2026 · P1 asyncio-in-thread fix.
#
# APScheduler's ``AsyncIOScheduler`` awaits coroutine callables on its
# own event loop, so the preferred pattern is to hand it the coroutine
# functions directly (below). We ALSO keep an explicit ``_fire_async``
# helper for any legacy caller that must synchronously drive a
# coroutine from a bare worker thread (e.g. APScheduler's
# ``ThreadPoolExecutor`` when a job is misconfigured, or ad-hoc backfill
# scripts). The safe pattern spins up a *fresh* event loop for the
# fire so ``asyncio.get_event_loop()`` inside the coroutine can no
# longer raise ``RuntimeError: There is no current event loop in
# thread 'asyncio_N'``.


def _fire_async(coro_factory):
    """Safely drive an async coroutine from a synchronous context.

    ``coro_factory`` must be a zero-arg callable that returns a fresh
    coroutine (APScheduler-style — required so the coroutine is not
    reused across fires). Creates a fresh event loop, sets it as the
    current thread's loop, awaits the coroutine to completion, then
    closes the loop.

    Returns the coroutine's return value; propagates any exception the
    coroutine raises (the caller is expected to log/swallow as
    appropriate).
    """
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_factory())
    finally:
        try:
            loop.close()
        finally:
            # Detach the closed loop from the current thread so a
            # subsequent ``get_event_loop()`` call doesn't return a
            # closed reference (which would itself raise).
            asyncio.set_event_loop(None)


async def _sync_google() -> None:
    await sync_all_tenants("google")


async def _sync_facebook() -> None:
    await sync_all_tenants("facebook")


async def _sync_yelp() -> None:
    await sync_all_tenants("yelp")


def register_daily_sync(scheduler) -> None:
    """Add three daily-at-03:00-UTC cron sweeps to the existing
    APScheduler instance. Called from ``server.py`` on startup."""
    try:
        scheduler.add_job(
            _sync_google,
            "cron", hour=3, minute=0, id="reviews.sync.google",
            replace_existing=True,
        )
        scheduler.add_job(
            _sync_facebook,
            "cron", hour=3, minute=10, id="reviews.sync.facebook",
            replace_existing=True,
        )
        scheduler.add_job(
            _sync_yelp,
            "cron", hour=3, minute=20, id="reviews.sync.yelp",
            replace_existing=True,
        )
        logger.info("[review_scraper] daily sync registered "
                     "(google 03:00, facebook 03:10, yelp 03:20 UTC)")
    except Exception as e:
        logger.warning(f"[review_scraper] scheduler registration failed: {e}")
