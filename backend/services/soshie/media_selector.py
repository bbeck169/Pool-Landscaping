"""Phase S1.5 · Feb-2026 — Soshie hybrid media selector.

Given a Soshie autopilot post context, pick the best media asset
to attach.  Preference order:

    1. Real technician-uploaded photo from a recent ``service_reports``
       submission (last 60 days, matching service_type/tags, no
       ``private`` or missing-consent flag).
    2. Legacy inline ``jobs.photos[]`` photo from a job in the same
       window (some pods still write to the job doc directly).
    3. Nothing → AI fallback (caller invokes ``ai_image_gen``).

The function NEVER raises on empty inputs — an empty context or a
tenant with no service reports returns
``{"source": "none", "url": None}`` and the caller decides whether
to fall through to the AI path.

Returned shape
--------------

    {"source": "job_photo" | "ai_generated" | "none",
     "url":    Optional[str],
     "caption_hint": str,
     "metadata": {
         "service_report_id": Optional[str],
         "job_id": Optional[str],
         "photo_id": Optional[str],
         "service_type": Optional[str],
         "captured_at": Optional[str],  # ISO
     }}

Design notes
------------
* The user's brief called out a ``job_media`` collection.  It does
  NOT exist in this codebase — tech-uploaded photos live on
  ``service_reports.photos[]`` (the canonical write target, per
  ``routers/portal_media.py``'s comment) and legacy ``jobs.photos[]``.
  We resolve from both.
* Consent gating: a photo is skipped when the parent job's
  ``customer_id`` maps to a customer with ``media_consent=False``
  OR when the individual photo dict has ``private=True``.  Missing
  consent flag on legacy customers defaults to TRUE (opt-in) —
  matches the existing before/after share behavior.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import db, logger


LOOKBACK_DAYS = 60


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc)
             - timedelta(days=days)).isoformat()


async def _customer_consent_ok(tenant_id: str,
                                    customer_id: Optional[str]) -> bool:
    """A missing customer OR missing ``media_consent`` field defaults
    to True (opt-in). Only an explicit ``media_consent=False`` blocks."""
    if not customer_id:
        return True
    doc = await db.customers.find_one(
        {"tenant_id": tenant_id, "id": customer_id},
        {"_id": 0, "media_consent": 1},
    )
    if not doc:
        return True
    return bool(doc.get("media_consent", True))


def _photo_is_private(p: Dict[str, Any]) -> bool:
    return bool(p.get("private") or p.get("is_private"))


def _matches_service_type(job_service_type: Optional[str],
                              target: Optional[str]) -> bool:
    """Loose case-insensitive substring match; empty target matches all."""
    if not target:
        return True
    st = (job_service_type or "").strip().lower()
    tg = target.strip().lower()
    return tg in st or st in tg if st and tg else True


async def _pull_service_report_photos(
    tenant_id: str, service_type: Optional[str], since_iso: str,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """Fetch recent submitted service reports + join their parent
    jobs so we can filter by service_type + resolve consent.  Cap
    the scan at ``limit`` reports to keep the query light."""
    rows: List[Dict[str, Any]] = []
    async for rep in db.service_reports.find(
        {"tenant_id": tenant_id,
          "submitted_at": {"$gte": since_iso},
          "photos": {"$exists": True, "$ne": []}},
        {"_id": 0, "id": 1, "job_id": 1, "photos": 1, "submitted_at": 1},
    ).sort("submitted_at", -1).limit(limit):
        job_id = rep.get("job_id")
        if not job_id:
            continue
        job = await db.jobs.find_one(
            {"tenant_id": tenant_id, "id": job_id},
            {"_id": 0, "service_type": 1, "job_type": 1,
              "customer_id": 1, "tags": 1},
        )
        if not job:
            continue
        job_st = job.get("service_type") or job.get("job_type") or ""
        if not _matches_service_type(job_st, service_type):
            continue
        if not await _customer_consent_ok(
            tenant_id, job.get("customer_id"),
        ):
            continue
        for photo in (rep.get("photos") or []):
            if not isinstance(photo, dict):
                continue
            if _photo_is_private(photo):
                continue
            pid = photo.get("id")
            url = photo.get("url") or (
                f"/api/public/job-photo/{job_id}/{pid}" if pid else None
            )
            if not url:
                continue
            rows.append({
                "url": url,
                "photo_id": pid,
                "service_report_id": rep.get("id"),
                "job_id": job_id,
                "service_type": job_st,
                "captured_at": (photo.get("created_at")
                                    or rep.get("submitted_at")),
                # Larger resolutions (when set) rank first below.
                "_w": int(photo.get("width") or 0),
                "_h": int(photo.get("height") or 0),
            })
    return rows


async def _pull_legacy_job_photos(
    tenant_id: str, service_type: Optional[str], since_iso: str,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """Some pods still write photos inline on the ``jobs`` row."""
    rows: List[Dict[str, Any]] = []
    async for job in db.jobs.find(
        {"tenant_id": tenant_id,
          "photos": {"$exists": True, "$ne": []},
          "updated_at": {"$gte": since_iso}},
        {"_id": 0, "id": 1, "service_type": 1, "job_type": 1,
          "customer_id": 1, "photos": 1, "updated_at": 1},
    ).sort("updated_at", -1).limit(limit):
        job_st = job.get("service_type") or job.get("job_type") or ""
        if not _matches_service_type(job_st, service_type):
            continue
        if not await _customer_consent_ok(
            tenant_id, job.get("customer_id"),
        ):
            continue
        for photo in (job.get("photos") or []):
            if not isinstance(photo, dict):
                continue
            if _photo_is_private(photo):
                continue
            pid = photo.get("id")
            url = photo.get("url") or (
                f"/api/public/job-photo/{job['id']}/{pid}" if pid else None
            )
            if not url:
                continue
            rows.append({
                "url": url,
                "photo_id": pid,
                "service_report_id": None,
                "job_id": job["id"],
                "service_type": job_st,
                "captured_at": (photo.get("created_at")
                                    or job.get("updated_at")),
                "_w": int(photo.get("width") or 0),
                "_h": int(photo.get("height") or 0),
            })
    return rows


def _rank_candidates(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank: largest resolution first, then most-recent capture."""
    return sorted(
        rows,
        key=lambda r: (
            -(r.get("_w", 0) * r.get("_h", 0)),
            r.get("captured_at") or "",
        ),
        reverse=False,
    )


async def select_media_for_post(
    *,
    tenant_id: str,
    post_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Pick the best real photo for the Soshie post context.

    ``post_context`` keys read:
        - ``service_type`` (optional) — filter photos to matching
          job type (loose substring match).
        - ``tags``         (optional) — reserved for future ranking.
        - ``lookback_days`` (optional int) — override default 60.

    Returns the standard :class:`MediaSelection` shape (see module
    docstring).  Callers get ``source="none"`` when no eligible
    real photo exists — that's the AI-fallback trigger.
    """
    try:
        ctx = post_context or {}
        service_type = ctx.get("service_type")
        lookback = int(ctx.get("lookback_days") or LOOKBACK_DAYS)
        since_iso = _iso_days_ago(lookback)

        primary = await _pull_service_report_photos(
            tenant_id, service_type, since_iso,
        )
        secondary = []
        if not primary:
            secondary = await _pull_legacy_job_photos(
                tenant_id, service_type, since_iso,
            )
        pool = _rank_candidates(primary or secondary)
        if not pool:
            return {"source": "none", "url": None,
                    "caption_hint": "",
                    "metadata": {}}
        best = pool[0]
        return {
            "source": "job_photo",
            "url": best["url"],
            "caption_hint": (best.get("service_type") or "").title(),
            "metadata": {
                "service_report_id": best.get("service_report_id"),
                "job_id": best.get("job_id"),
                "photo_id": best.get("photo_id"),
                "service_type": best.get("service_type"),
                "captured_at": best.get("captured_at"),
            },
        }
    except Exception as e:                                        # noqa: BLE001
        logger.warning(
            "[soshie.media_selector] crashed — returning none: %s", e,
        )
        return {"source": "none", "url": None,
                "caption_hint": "", "metadata": {"error": str(e)}}
