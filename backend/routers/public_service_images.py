"""Feb 2026 · Public Service Images Portal — unauthenticated portal
endpoint that renders the images a technician uploaded during service
report checkout, keyed by an opaque per-report ``public_uuid``.

Mounted at ``/api/public/service/{uuid}``. Deliberately narrow surface:

* No customer PII (name / email / phone / address / balance) is ever
  emitted. The response contains only the business identity, technician
  first name, service date + type, and the image URLs.
* IP-scoped rate limit — max 60 req/min per remote address. Buckets are
  purged lazily on hit.
* Photos tagged ``internal`` / ``issue`` / ``private`` are stripped
  before the response is built.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from config import db

router = APIRouter()

# ─── Rate limit ────────────────────────────────────────────────────────
_PUBLIC_SERVICE_RATE = 60
_PUBLIC_SERVICE_WINDOW_S = 60.0
_public_service_hits: Dict[str, List[float]] = {}
_public_service_lock = asyncio.Lock()


async def _rate_limit_public_service(ip: str) -> None:
    """Sliding-window IP rate limit — max 60 requests / 60 seconds.

    Kept in-process (single supervisor worker) — this endpoint is not
    high-QPS enough to warrant Redis. Bucket is pruned to the current
    window before the length check so long-idle IPs never grow the
    dict unboundedly.
    """
    now = time.monotonic()
    async with _public_service_lock:
        bucket = _public_service_hits.setdefault(ip, [])
        cutoff = now - _PUBLIC_SERVICE_WINDOW_S
        # Drop stale entries.
        i = 0
        while i < len(bucket) and bucket[i] < cutoff:
            i += 1
        if i:
            del bucket[:i]
        if len(bucket) >= _PUBLIC_SERVICE_RATE:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit — max {_PUBLIC_SERVICE_RATE}/minute",
            )
        bucket.append(now)


def _reset_rate_limit_for_tests() -> None:
    """Test-only hook — clear the in-process bucket state."""
    _public_service_hits.clear()


# ─── Photo filtering ───────────────────────────────────────────────────
_PRIVATE_TAGS = {"internal", "issue", "private"}


def _is_public_photo(p: Any) -> bool:
    """A photo is public unless it carries an ``internal|issue|private``
    tag. Non-dict rows are dropped."""
    if not isinstance(p, dict):
        return False
    tags = p.get("tags") or []
    if not isinstance(tags, list):
        return True
    for t in tags:
        if str(t).lower() in _PRIVATE_TAGS:
            return False
    return True


def _photo_url(p: Dict[str, Any]) -> str:
    return str(p.get("url") or p.get("public_url") or p.get("uri") or "")


def _first_name(full: Any) -> str:
    """Trim any last-name portion so the portal only exposes the
    tech's first name (per spec — no full PII)."""
    s = (full or "")
    if not isinstance(s, str):
        return ""
    return s.strip().split(None, 1)[0] if s.strip() else ""


# ─── Endpoint ──────────────────────────────────────────────────────────
@router.get("/public/service/{uuid}")
async def get_public_service_images(uuid: str, request: Request):
    """Fetch a public view of a submitted service report's images.

    Response shape (JSON):

    ```
    {
      "business_name": <str>,
      "logo_url": <str | None>,
      "tech_first_name": <str>,
      "service_date": <YYYY-MM-DD | ISO>,
      "service_type": <str>,
      "images": [{"url": <str>, "thumbnail_url": <str | None>}, ...]
    }
    ```

    Returns 404 if the ``uuid`` is unknown, 429 on rate-limit, 410 if the
    parent report is soft-deleted. Never leaks customer PII.
    """
    ip = (request.client.host if request.client else "?") or "?"
    await _rate_limit_public_service(ip)

    if not uuid or len(uuid) < 8:
        # Bail fast on obviously malformed ids without hitting Mongo.
        raise HTTPException(404, "Service report not found")

    report = await db.service_reports.find_one(
        {"public_uuid": uuid}, {"_id": 0},
    )
    if not report:
        raise HTTPException(404, "Service report not found")
    if report.get("deleted_at"):
        raise HTTPException(410, "This service report is no longer available")

    # Resolve tenant + job. Never raise on either — they are used for
    # cosmetic fields only.
    tenant = await db.tenants.find_one(
        {"id": report.get("tenant_id")}, {"_id": 0},
    ) or {}
    job = await db.jobs.find_one(
        {"id": report.get("job_id"), "tenant_id": report.get("tenant_id")},
        {"_id": 0},
    ) or {}

    # Business identity — never any owner or customer detail.
    settings = (tenant.get("settings") or {})
    business_card = settings.get("business_card") or {}
    business_name = (
        business_card.get("company_name")
        or tenant.get("name")
        or "Service Report"
    )
    logo_url = (
        business_card.get("logo_url")
        or tenant.get("logo_url")
        or settings.get("logo_url")
        or None
    )

    # Tech first name — cascade tech user row → tech name field.
    tech_first = ""
    tech_id = report.get("tech_id")
    if tech_id:
        tech_user = (
            await db.users.find_one({"id": tech_id}, {"_id": 0, "name": 1,
                                                       "first_name": 1})
            or await db.users.find_one(
                {"technician_id": tech_id}, {"_id": 0, "name": 1,
                                              "first_name": 1})
            or {}
        )
        tech_first = (tech_user.get("first_name")
                        or _first_name(tech_user.get("name") or ""))
    if not tech_first:
        tech_first = _first_name(report.get("tech_name") or "")

    # Service date + type — pull from report → job.
    service_date = (
        report.get("submitted_at")
        or job.get("service_report_submitted_at")
        or job.get("scheduled_at")
        or job.get("scheduled_start")
        or report.get("started_at")
        or ""
    )
    service_date = str(service_date)[:10] if service_date else ""

    service_type = (
        job.get("service_type")
        or job.get("job_type")
        or job.get("title")
        or (report.get("template") or "").capitalize()
        or ""
    )

    # Images — pool photos from BOTH the report and the job (mirror);
    # dedupe by URL and drop internal/issue/private-tagged rows.
    raw = list(report.get("photos") or [])
    raw.extend(job.get("photos") or [])
    images: List[Dict[str, Any]] = []
    seen: set = set()
    for p in raw:
        if not _is_public_photo(p):
            continue
        url = _photo_url(p)
        if not url or url in seen:
            continue
        seen.add(url)
        images.append({
            "url": url,
            "thumbnail_url": p.get("thumbnail_url") or p.get("thumb_url"),
        })

    return {
        "business_name": business_name,
        "logo_url": logo_url,
        "tech_first_name": tech_first,
        "service_date": service_date,
        "service_type": service_type,
        "images": images,
    }
