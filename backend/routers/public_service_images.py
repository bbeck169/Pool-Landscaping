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

    # Phase 27 · Feb 2026 — Videos (max 3 per report). Same private-tag
    # filter as photos; deduped by URL. Each entry emits a poster
    # thumbnail (or empty) so the portal can render a play-icon
    # overlay.
    videos: List[Dict[str, Any]] = []
    v_seen: set = set()
    for v in (report.get("videos") or []):
        if not _is_public_photo(v):  # same tag-based filter shape
            continue
        vurl = str(v.get("url") or v.get("public_url") or "")
        if not vurl or vurl in v_seen:
            continue
        v_seen.add(vurl)
        videos.append({
            "url": vurl,
            "poster_url": v.get("poster_url") or v.get("thumbnail_url") or "",
            "duration_seconds": v.get("duration_seconds"),
            "content_type": v.get("content_type") or "video/mp4",
        })

    # Phase 27 · Feb 2026 — Service-report content sections. PII-safe:
    # chemicals + readings + completed checklist items are service
    # data, never identity fields. Redaction mirrors the existing
    # customer-portal helper so private/issue notes never leak.
    chemicals_added = _public_chemicals_added(report)
    chemical_readings = _public_chemical_readings(report)
    checklist = _public_checklist(report)

    return {
        "business_name": business_name,
        "logo_url": logo_url,
        "tech_first_name": tech_first,
        "service_date": service_date,
        "service_type": service_type,
        "images": images,
        "videos": videos,
        "chemicals_added": chemicals_added,
        "chemical_readings": chemical_readings,
        "checklist": checklist,
    }


# ─── Phase 27 · Feb 2026 — PII-safe extractors for the public portal.
def _public_chemicals_added(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in (report.get("chemicals_added") or []):
        if not isinstance(r, dict):
            continue
        name = str(r.get("chemical") or r.get("name") or "").strip()
        qty = r.get("quantity") if r.get("quantity") is not None else r.get("amount")
        unit = str(r.get("unit") or "").strip()
        raw_label = str(r.get("raw_label") or "").strip()
        if raw_label or name:
            out.append({"name": name or None,
                        "quantity": qty if qty not in (None, "") else None,
                        "unit": unit or None,
                        "raw_label": raw_label or None})
    return out


def _public_chemical_readings(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in (report.get("chemical_readings") or []):
        if not isinstance(r, dict):
            continue
        val = r.get("value")
        if val in (None, ""):
            continue
        name = str(r.get("name") or r.get("key") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "key": r.get("key"),
            "value": val,
            "unit": r.get("unit"),
        })
    return out


def _public_checklist(report: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for it in (report.get("checklist_items") or []):
        if not isinstance(it, dict):
            continue
        if not it.get("checked"):
            continue
        label = str(it.get("label") or "").strip()
        if not label:
            continue
        out.append({"label": label})
    return out
