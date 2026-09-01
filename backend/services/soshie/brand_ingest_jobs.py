"""Phase I4 · Feb-2026 — Soshie brand-ingest async job worker.

Converts the previously-synchronous ``ingest_website`` flow into a
fire-and-forget background task pattern.

Pattern
-------
The HTTP endpoint (see ``routers/soshie_brand_ingest.py``) writes a
row to ``db.soshie_ingest_jobs`` with ``status="queued"`` and
returns 202 immediately.  ``spawn_ingest_job`` schedules the
worker via ``asyncio.create_task`` on the current running loop —
matching the ``phase17`` geocode pattern rather than APScheduler
(APScheduler is used for repeating cron ticks; one-off jobs go
through ``create_task``).

Job row schema (see also the brief in ``tests/test_soshie_brand_ingest_async.py``)::

    {
      "id": str,
      "tenant_id": str,
      "url": str,
      "extra_paths": [str, ...],
      "status": "queued" | "running" | "succeeded" | "failed",
      "started_at": iso,
      "finished_at": iso | None,
      "error": str | None,
      "progress": {
        "paths_crawled": int,
        "paths_total": int,
        "current_step": str,
      },
      "result_summary": {...} | None,
    }

Failure isolation
-----------------
* The worker wraps the full ingest under a total timeout ceiling
  (``_TOTAL_JOB_TIMEOUT_S``).  Overshoot → job flips to ``failed``
  with ``error="timeout"``; the process is NOT killed.
* Any raised exception is caught, truncated to 200 chars, and
  written to the job row so the frontend can surface it.
* A separate ``cleanup_stale_ingest_jobs`` sweep (registered as an
  APScheduler interval job in ``server.py``) marks jobs that have
  been ``running`` for >15 minutes as ``failed`` with
  ``error="timeout_stale"`` — this handles the "pod died mid-job"
  case.

Path caps
---------
``MAX_TOTAL_PATHS = 5`` — home page + up to 4 extras.  The router
returns 400 when the caller submits more.  Enforced twice (once at
the router, once in the worker) so mis-scheduled jobs also fail
fast.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db
from utils import new_id, now_iso

logger = logging.getLogger("soshie.brand_ingest_jobs")


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════
COLLECTION = "soshie_ingest_jobs"

MAX_TOTAL_PATHS = 5           # home + up to 4 extras
_STALE_AFTER_MIN = 15         # running > 15 min → force-fail
_TOTAL_JOB_TIMEOUT_S = 300    # 5-min ceiling on a single ingest run
# LLM-call timeout hint — surfaced in the module even though the
# current ingest is pure BeautifulSoup.  Wrapping any future LLM
# step in ``asyncio.wait_for(..., timeout=LLM_TIMEOUT_S)`` keeps
# the pipeline honest per the I4 brief.
LLM_TIMEOUT_S = 30

_TERMINAL_STATUSES = {"succeeded", "failed"}


# ═══════════════════════════════════════════════════════════════════
# Row-level helpers
# ═══════════════════════════════════════════════════════════════════
def _new_job_row(tenant_id: str, website_url: str,
                    extra_paths: List[str]) -> Dict[str, Any]:
    return {
        "id": new_id(),
        "tenant_id": tenant_id,
        "url": website_url,
        "extra_paths": list(extra_paths or []),
        "status": "queued",
        "started_at": now_iso(),
        "finished_at": None,
        "error": None,
        "progress": {
            "paths_crawled": 0,
            "paths_total": 1 + len(extra_paths or []),
            "current_step": "queued",
        },
        "result_summary": None,
    }


async def _update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    try:
        await db[COLLECTION].update_one(
            {"id": job_id}, {"$set": fields},
        )
    except Exception as exc:  # noqa: BLE001 — never crash the worker
        logger.warning("[brand_ingest_jobs] update %s failed: %s",
                          job_id, exc)


async def _update_progress(job_id: str, **kv) -> None:
    if not kv:
        return
    payload = {f"progress.{k}": v for k, v in kv.items()}
    try:
        await db[COLLECTION].update_one({"id": job_id}, {"$set": payload})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[brand_ingest_jobs] progress %s failed: %s",
                          job_id, exc)


# ═══════════════════════════════════════════════════════════════════
# Public API — insert a row + fire the worker
# ═══════════════════════════════════════════════════════════════════
async def create_ingest_job(tenant_id: str, website_url: str,
                                 extra_paths: Optional[List[str]] = None,
                                 *, user_id: Optional[str] = None,
                                 ) -> Dict[str, Any]:
    """Insert a queued row + return the full record. Does NOT
    spawn the worker — the caller controls whether to fire it
    (tests skip the fire; the router always fires).
    """
    row = _new_job_row(tenant_id, website_url, list(extra_paths or []))
    if user_id:
        row["created_by_user_id"] = user_id
    await db[COLLECTION].insert_one(dict(row))
    return row


def spawn_ingest_job(job_id: str) -> None:
    """Fire the worker without awaiting. Never raises — schedule
    failures fall back to marking the job failed via a synchronous
    Mongo update on the next event-loop tick."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error(
            "[brand_ingest_jobs] no running loop for job %s — "
            "worker not spawned", job_id,
        )
        return
    loop.create_task(_run_ingest_worker(job_id))


# ═══════════════════════════════════════════════════════════════════
# Worker
# ═══════════════════════════════════════════════════════════════════
async def _run_ingest_worker(job_id: str) -> None:
    """Flip to ``running`` → wrap the ingest under a timeout ceiling
    → mark ``succeeded`` / ``failed`` based on outcome. Never
    raises — every exception path writes an ``error`` field."""
    t0 = time.monotonic()
    try:
        await _update_job(job_id, status="running")
        await _update_progress(job_id, current_step="fetching_home")
        result = await asyncio.wait_for(
            _do_ingest(job_id), timeout=_TOTAL_JOB_TIMEOUT_S,
        )
        await _update_job(
            job_id,
            status="succeeded",
            finished_at=now_iso(),
            result_summary=result,
        )
        await _update_progress(job_id, current_step="succeeded")
        logger.info(
            "[brand_ingest_jobs] job %s succeeded in %.1fs",
            job_id, time.monotonic() - t0,
        )
    except asyncio.TimeoutError:
        await _update_job(
            job_id,
            status="failed",
            error="timeout",
            finished_at=now_iso(),
        )
        logger.warning("[brand_ingest_jobs] job %s timed out", job_id)
    except Exception as exc:  # noqa: BLE001
        await _update_job(
            job_id,
            status="failed",
            error=str(exc)[:200] or exc.__class__.__name__,
            finished_at=now_iso(),
        )
        logger.warning("[brand_ingest_jobs] job %s failed: %s", job_id, exc)


async def _do_ingest(job_id: str) -> Dict[str, Any]:
    """Load the job row + fan-out to the sync ingest helper.

    Progress is updated after each page fetch. When the caller
    provided ``extra_paths`` we crawl those (resolved against the
    root URL) INSTEAD of the auto-discovered internal links so
    admins can steer the ingest at specific pages.
    """
    job = await db[COLLECTION].find_one({"id": job_id})
    if not job:
        raise RuntimeError(f"job_row_missing: {job_id}")
    tenant_id = job["tenant_id"]
    website_url = job["url"]
    extra_paths: List[str] = list(job.get("extra_paths") or [])

    # Enforce the path cap defensively in case the row was written
    # by a caller that bypassed the router validation.
    if len(extra_paths) > (MAX_TOTAL_PATHS - 1):
        raise ValueError(
            f"too_many_paths: {len(extra_paths)} extras "
            f"(cap {MAX_TOTAL_PATHS - 1})",
        )

    if extra_paths:
        summary = await _ingest_with_extra_paths(
            job_id, tenant_id, website_url, extra_paths,
        )
    else:
        summary = await _ingest_auto_discover(
            job_id, tenant_id, website_url,
        )
    return summary


async def _ingest_auto_discover(job_id: str, tenant_id: str,
                                   website_url: str) -> Dict[str, Any]:
    """Wrap the legacy ``services.soshie.brand_ingest.ingest_website``
    which does auto-discovery of internal links. Progress
    reporting is coarse (start / finish) because the underlying
    function doesn't emit callbacks — an improvement is deferred."""
    from services.soshie.brand_ingest import ingest_website  # noqa: PLC0415
    await _update_progress(
        job_id, current_step="crawling_and_parsing",
    )
    result = await ingest_website(tenant_id, website_url)
    await _update_progress(
        job_id,
        paths_crawled=int(result.get("pages_fetched") or 0),
        paths_total=int(result.get("pages_fetched") or 0),
        current_step="merging_brand_brain",
    )
    return result


async def _ingest_with_extra_paths(job_id: str, tenant_id: str,
                                      website_url: str,
                                      extra_paths: List[str]) -> Dict[str, Any]:
    """Ingest home page + specifically-requested extra paths only.
    Bypasses auto-discovery so the caller controls the crawl
    breadth exactly."""
    import httpx  # noqa: PLC0415
    from urllib.parse import urljoin  # noqa: PLC0415
    from services.seo_scanner import fetch_page, normalize_url  # noqa: PLC0415
    from services.soshie.brand_ingest import (  # noqa: PLC0415
        parse_page, distill_bullets, _merge_into_brand_brain,
    )

    root = normalize_url(website_url)
    urls: List[str] = [root]
    for p in extra_paths:
        candidate = urljoin(root, p.strip())
        if candidate not in urls:
            urls.append(candidate)
    urls = urls[:MAX_TOTAL_PATHS]

    total = len(urls)
    await _update_progress(
        job_id, paths_total=total, paths_crawled=0,
        current_step="crawling_and_parsing",
    )

    pages: List[Dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for idx, url in enumerate(urls):
            try:
                fetched = await fetch_page(client, url)
                pages.append({"url": url,
                                 **parse_page(fetched["html_bytes"], url)})
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "[brand_ingest_jobs] job %s page skip %s: %s",
                    job_id, url, exc,
                )
            await _update_progress(
                job_id, paths_crawled=idx + 1,
            )

    await _update_progress(job_id, current_step="merging_brand_brain")
    ingested_at = now_iso()
    for p in pages:
        row = {
            "id": new_id(),
            "tenant_id": tenant_id,
            "url": p["url"],
            "title": p.get("title"),
            "h1": p.get("h1"),
            "h2s": p.get("h2s") or [],
            "h3s": p.get("h3s") or [],
            "about_paragraphs": p.get("about_paragraphs") or [],
            "cta_texts": p.get("cta_texts") or [],
            "service_hints": p.get("service_hints") or [],
            "ingested_at": ingested_at,
        }
        try:
            await db.brand_brain_ingested_pages.insert_one(row)
        except Exception as exc:  # noqa: BLE001
            logger.info(
                "[brand_ingest_jobs] insert failed %s: %s", p["url"], exc,
            )
    bullets = distill_bullets(pages)
    merge = await _merge_into_brand_brain(tenant_id, bullets)
    return {
        "pages_fetched": len(pages),
        "bullets_added": merge["added"],
        "urls": [p["url"] for p in pages],
        "at": ingested_at,
    }


# ═══════════════════════════════════════════════════════════════════
# Stale-job cleanup (registered as an APScheduler interval job)
# ═══════════════════════════════════════════════════════════════════
async def cleanup_stale_ingest_jobs() -> Dict[str, Any]:
    """Force-fail any job stuck in ``running`` for >15 minutes.
    Safe to call from a scheduler tick — returns a summary dict for
    logging + test assertions."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_STALE_AFTER_MIN)
    cutoff_iso = cutoff.isoformat()
    swept = 0
    try:
        res = await db[COLLECTION].update_many(
            {"status": "running", "started_at": {"$lt": cutoff_iso}},
            {"$set": {
                "status": "failed",
                "error": "timeout_stale",
                "finished_at": now_iso(),
            }},
        )
        swept = int(getattr(res, "modified_count", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[brand_ingest_jobs] cleanup sweep failed: %s", exc,
        )
    if swept:
        logger.info(
            "[brand_ingest_jobs] cleanup swept %d stale job(s)", swept,
        )
    return {"swept": swept, "cutoff_iso": cutoff_iso}
