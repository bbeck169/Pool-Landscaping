"""DATA-PARITY-C3 · Feb-2026 — Unified customer-media reader.

Pre-fix state (ARCHITECTURAL AUDIT):

  * ``routers/portal_photos.py`` registered FIRST at
    ``GET /api/portal/photos``.  Walks ONLY
    ``service_reports.photos[]``.  Blind to tech-uploaded photos
    on ``jobs.photos[]`` + admin-uploaded images in ``files``.
  * ``routers/portal_media.py`` registered SECOND at the SAME
    paths.  Walks ``files`` + ``service_reports.photos[]`` but
    misses ``jobs.photos[]`` and ``estimates.photos[]``.
    DEAD CODE for photos+videos — FastAPI first-match wins.
  * ``routers/portal_videos.py`` registered FIRST at
    ``GET /api/portal/videos``.  Walks ONLY ``jobs.videos[]`` +
    ``estimates.videos[]`` with ``visibility=="customer"`` filter.
    Blind to ``service_reports.videos[]`` + admin ``files``.

Result: NONE of the three live endpoints returns the full media
set for a customer.  Preview DB has 13 jobs with embedded photos,
7 admin-uploaded images in ``files``, 1 service-report with embedded
photos — the live portal sees only the service-report row.

Post-fix contract:

  * **Four sources merged** by a single reader function —
    ``jobs.photos[]`` + ``jobs.videos[]`` (tech uploads, visibility
    filter), ``estimates.photos[]`` + ``estimates.videos[]`` (same),
    ``service_reports.photos[]`` + ``service_reports.videos[]``
    (submitted reports, is_deleted filter), ``files`` collection
    (admin-linked to job or customer, is_deleted filter + mime
    filter).
  * **Same reader on both surfaces** — portal + admin media
    endpoints call ``get_customer_media`` so a divergent query
    can't ship.
  * **Hidden-flag honoured** — ``hidden_from_portal`` on the top-
    level jobs/estimates/service_reports doc hides every embedded
    media item from the portal response.  Admin always sees
    everything.  Default visibility = visible to portal (matches
    the user's spec: "every photo/video attached to a customer's
    jobs appears on the portal unless explicitly flagged").
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional


logger = logging.getLogger("services.customer_media")

MediaKind = Literal["photo", "video", "all"]


def _is_image(mime: Optional[str]) -> bool:
    return bool(mime) and str(mime).lower().startswith("image/")


def _is_video(mime: Optional[str]) -> bool:
    return bool(mime) and str(mime).lower().startswith("video/")


def _kind_matches(mime: Optional[str], kind: MediaKind) -> bool:
    if kind == "all":
        return _is_image(mime) or _is_video(mime)
    if kind == "photo":
        return _is_image(mime)
    return _is_video(mime)


def _coerce_mime_item(item: Any, default_mime: str) -> str:
    """Embedded media sub-docs have inconsistent mime key names.
    Normalize to one string."""
    if not isinstance(item, dict):
        return default_mime
    return (item.get("mime")
            or item.get("content_type")
            or item.get("mime_type")
            or default_mime)


async def _customer_jobs(
    db, tenant_id: str, customer_id: str,
) -> List[Dict[str, Any]]:
    from utils import not_deleted_filter as _nd
    cur = db.jobs.find(
        {"tenant_id": tenant_id, "customer_id": customer_id, **_nd()},
        {"_id": 0, "id": 1, "title": 1, "service_type": 1,
         "scheduled_date": 1, "hidden_from_portal": 1,
         "photos": 1, "videos": 1},
    )
    return [j async for j in cur]


async def _customer_estimates(
    db, tenant_id: str, customer_id: str,
) -> List[Dict[str, Any]]:
    try:
        cur = db.estimates.find(
            {"tenant_id": tenant_id, "customer_id": customer_id},
            {"_id": 0, "id": 1, "title": 1, "service_type": 1,
             "hidden_from_portal": 1,
             "photos": 1, "videos": 1},
        )
        return [e async for e in cur]
    except Exception:                                                 # noqa: BLE001
        return []


async def _customer_service_reports(
    db, tenant_id: str, job_ids: List[str],
) -> List[Dict[str, Any]]:
    if not job_ids:
        return []
    cur = db.service_reports.find(
        {"tenant_id": tenant_id, "job_id": {"$in": job_ids},
         "submitted_at": {"$ne": None}},
        {"_id": 0, "id": 1, "job_id": 1, "public_uuid": 1,
         "hidden_from_portal": 1, "submitted_at": 1,
         "photos": 1, "videos": 1},
    )
    return [r async for r in cur]


async def _customer_files(
    db, tenant_id: str, customer_id: str, job_ids: List[str],
) -> List[Dict[str, Any]]:
    try:
        or_clauses = [{"linked_entity_type": "customer",
                        "linked_entity_id": customer_id}]
        if job_ids:
            or_clauses.append({"linked_entity_type": "job",
                                 "linked_entity_id": {"$in": job_ids}})
        cur = db.files.find(
            {"tenant_id": tenant_id, "is_deleted": False,
             "$or": or_clauses},
            {"_id": 0},
        )
        return [f async for f in cur]
    except Exception:                                                 # noqa: BLE001
        return []


async def get_customer_media(
    db,
    tenant_id: str,
    customer_id: str,
    *,
    kind: MediaKind = "all",
    for_portal: bool = True,
    limit: int = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """Merge every media item visible to the customer across all
    four source collections.

    When ``for_portal=True`` (portal callers), any top-level entity
    (job / estimate / service_report) carrying
    ``hidden_from_portal=True`` has every embedded media item
    omitted.  Individual sub-media items may ALSO carry
    ``is_deleted=True`` (service_reports) or
    ``visibility != "customer"`` (jobs/estimates tech uploads) —
    both are enforced.

    Admin callers (``for_portal=False``) bypass the portal gate
    but still honour per-item ``is_deleted`` so trashed media
    stays hidden.
    """
    jobs = await _customer_jobs(db, tenant_id, customer_id)
    estimates = await _customer_estimates(db, tenant_id, customer_id)
    job_ids = [j["id"] for j in jobs]
    service_reports = await _customer_service_reports(
        db, tenant_id, job_ids,
    )
    files = await _customer_files(
        db, tenant_id, customer_id, job_ids,
    )

    job_title_by_id = {j["id"]: (j.get("title")
                                   or j.get("service_type")
                                   or "Service Visit")
                        for j in jobs}

    items: List[Dict[str, Any]] = []

    # ── 1. jobs[].photos / jobs[].videos (tech upload) ─────────────
    for j in jobs:
        if for_portal and j.get("hidden_from_portal"):
            continue
        for p in (j.get("photos") or []):
            if not isinstance(p, dict):
                continue
            if p.get("is_deleted"):
                continue
            if for_portal and p.get("visibility") not in (
                    None, "customer", "public"):
                continue
            mime = _coerce_mime_item(p, "image/jpeg")
            if not _kind_matches(mime, kind):
                continue
            items.append({
                "source": "job",
                "kind": "photo",
                "job_id": j.get("id"),
                "job_title": job_title_by_id.get(j.get("id")),
                "media_id": p.get("id"),
                "url": p.get("url") or p.get("storage_path") or "",
                "mime": mime,
                "size_bytes": p.get("size_bytes") or 0,
                "caption": p.get("caption") or "",
                "uploaded_at": p.get("uploaded_at"),
            })
        for v in (j.get("videos") or []):
            if not isinstance(v, dict):
                continue
            if v.get("is_deleted"):
                continue
            if for_portal and v.get("visibility") not in (
                    None, "customer", "public"):
                continue
            mime = _coerce_mime_item(v, "video/mp4")
            if not _kind_matches(mime, kind):
                continue
            items.append({
                "source": "job",
                "kind": "video",
                "job_id": j.get("id"),
                "job_title": job_title_by_id.get(j.get("id")),
                "media_id": v.get("id"),
                "url": v.get("url") or v.get("storage_path") or "",
                "mime": mime,
                "size_bytes": v.get("size_bytes") or 0,
                "duration_seconds": v.get("duration_seconds"),
                "caption": v.get("caption") or "",
                "uploaded_at": v.get("uploaded_at"),
            })

    # ── 2. estimates[].photos / estimates[].videos ─────────────────
    for e in estimates:
        if for_portal and e.get("hidden_from_portal"):
            continue
        for p in (e.get("photos") or []):
            if not isinstance(p, dict):
                continue
            if p.get("is_deleted"):
                continue
            if for_portal and p.get("visibility") not in (
                    None, "customer", "public"):
                continue
            mime = _coerce_mime_item(p, "image/jpeg")
            if not _kind_matches(mime, kind):
                continue
            items.append({
                "source": "estimate",
                "kind": "photo",
                "estimate_id": e.get("id"),
                "estimate_title": (e.get("title")
                                    or e.get("service_type")
                                    or "Estimate"),
                "media_id": p.get("id"),
                "url": p.get("url") or p.get("storage_path") or "",
                "mime": mime,
                "uploaded_at": p.get("uploaded_at"),
            })
        for v in (e.get("videos") or []):
            if not isinstance(v, dict):
                continue
            if v.get("is_deleted"):
                continue
            if for_portal and v.get("visibility") not in (
                    None, "customer", "public"):
                continue
            mime = _coerce_mime_item(v, "video/mp4")
            if not _kind_matches(mime, kind):
                continue
            items.append({
                "source": "estimate",
                "kind": "video",
                "estimate_id": e.get("id"),
                "estimate_title": (e.get("title")
                                    or e.get("service_type")
                                    or "Estimate"),
                "media_id": v.get("id"),
                "url": v.get("url") or v.get("storage_path") or "",
                "mime": mime,
                "uploaded_at": v.get("uploaded_at"),
            })

    # ── 3. service_reports[].photos / videos ───────────────────────
    for r in service_reports:
        if for_portal and r.get("hidden_from_portal"):
            continue
        pub = r.get("public_uuid")
        for p in (r.get("photos") or []):
            if not isinstance(p, dict):
                continue
            if p.get("is_deleted"):
                continue
            mime = _coerce_mime_item(p, "image/jpeg")
            if not _kind_matches(mime, kind):
                continue
            items.append({
                "source": "service_report",
                "kind": "photo",
                "job_id": r.get("job_id"),
                "job_title": job_title_by_id.get(r.get("job_id")),
                "report_id": r.get("id"),
                "media_id": p.get("id"),
                "url": (f"/api/public/service/{pub}/photo/{p.get('id')}"
                         if pub else p.get("url") or ""),
                "mime": mime,
                "caption": p.get("caption") or "",
                "uploaded_at": p.get("uploaded_at") or r.get("submitted_at"),
            })
        for v in (r.get("videos") or []):
            if not isinstance(v, dict):
                continue
            if v.get("is_deleted"):
                continue
            mime = _coerce_mime_item(v, "video/mp4")
            if not _kind_matches(mime, kind):
                continue
            items.append({
                "source": "service_report",
                "kind": "video",
                "job_id": r.get("job_id"),
                "report_id": r.get("id"),
                "media_id": v.get("id"),
                "url": (f"/api/public/service/{pub}/video/{v.get('id')}"
                         if pub else v.get("url") or ""),
                "mime": mime,
                "uploaded_at": v.get("uploaded_at") or r.get("submitted_at"),
            })

    # ── 4. files collection (admin-linked uploads) ─────────────────
    for f in files:
        mime = f.get("content_type") or ""
        if not _kind_matches(mime, kind):
            continue
        items.append({
            "source": "file",
            "kind": "photo" if _is_image(mime) else "video",
            "job_id": (f.get("linked_entity_id")
                        if f.get("linked_entity_type") == "job"
                        else None),
            "job_title": (job_title_by_id.get(f.get("linked_entity_id"))
                           if f.get("linked_entity_type") == "job"
                           else None),
            "media_id": f.get("id"),
            "url": f"/api/files/{f.get('id')}/download",
            "mime": mime,
            "size_bytes": f.get("size") or 0,
            "uploaded_at": f.get("created_at"),
        })

    items.sort(key=lambda r: r.get("uploaded_at") or "",
                reverse=True)
    total = len(items)
    page = items[offset:offset + limit]

    return {
        "items":  page,
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


async def audit_tenant_customer_media(
    db, tenant_id: str, *, fix: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """For each non-deleted customer in the tenant, compare the
    media counts visible to admin vs. visible to portal.  Report
    mismatches with sample media_ids.

    ``fix=False`` (default) reports without writing.  ``fix=True``
    is reserved for a future repair pass — currently the only
    source of drift is the ``hidden_from_portal`` flag, which is an
    admin-authored decision we do NOT auto-flip.  When ``fix=True``
    the endpoint returns a report with ``fixed=0`` and a note
    stating no auto-repair action is taken.
    """
    from utils import not_deleted_filter as _nd

    scanned = 0
    matched = 0
    drifted = 0
    mismatches: List[Dict[str, Any]] = []
    _CAP = 50

    cursor = db.customers.find(
        {"tenant_id": tenant_id, **_nd()},
        {"_id": 0, "id": 1, "name": 1},
    )
    if limit:
        cursor = cursor.limit(int(limit))

    async for cust in cursor:
        scanned += 1
        cid = cust.get("id")
        if not cid:
            continue
        try:
            admin_bag = await get_customer_media(
                db, tenant_id, cid, kind="all",
                for_portal=False, limit=10_000,
            )
            portal_bag = await get_customer_media(
                db, tenant_id, cid, kind="all",
                for_portal=True, limit=10_000,
            )
        except Exception as _exc:                                     # noqa: BLE001
            logger.warning(
                "[media_audit] compute failed tenant=%s cust=%s: %s",
                tenant_id, cid, _exc,
            )
            continue

        admin_ids = {i.get("media_id") for i in admin_bag["items"]}
        portal_ids = {i.get("media_id") for i in portal_bag["items"]}
        hidden_from_portal = admin_ids - portal_ids

        if not hidden_from_portal:
            matched += 1
            continue

        drifted += 1
        if len(mismatches) < _CAP:
            mismatches.append({
                "customer_id":      cid,
                "customer_name":    cust.get("name"),
                "admin_count":      admin_bag["total"],
                "portal_count":     portal_bag["total"],
                "hidden_media_ids": sorted(
                    [m for m in hidden_from_portal if m])[:20],
            })

    return {
        "ok":                True,
        "fix":               fix,
        "tenant_id":         tenant_id,
        "customers_scanned": scanned,
        "customers_matched": matched,
        "customers_drifted": drifted,
        "customers_fixed":   0,
        "mismatches":        mismatches,
        "note": (
            "``fix=true`` is a no-op — hidden_from_portal is an "
            "admin-authored flag we don't auto-flip.  Report only."
            if fix else "Dry-run report."),
    }
