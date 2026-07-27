"""Phase 27 · Feb 2026 — Service Report media upload + reorder.

Thin service-report-scoped wrapper over the shipped
``routers/media_uploads.py`` primitives. Endpoints:

* ``POST   /api/service-reports/{report_id}/media`` — upload a photo
  or video into the report's media pool. Caps: 10 photos, 3 videos,
  60s max per video, 100MB max per file.
* ``PATCH  /api/service-reports/{report_id}/media/reorder`` — accept
  ``photo_order`` + ``video_order`` (arrays of URLs) and persist the
  new order verbatim.
* ``GET    /api/public/service/{uuid}/video/{video_id}`` — public
  streaming endpoint (no auth) keyed on the report's ``public_uuid``.
  Only videos actually attached to THAT report are servable; every
  other id yields 404.

No ffmpeg / ffprobe dependency. Duration comes from the client
``X-Video-Duration`` header (mirrors the existing job videos flow);
posters are client-provided (form field ``poster_url``) — if absent,
the frontend renders a solid-color placeholder with a play icon.
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter, Depends, File, Form, Header, HTTPException, Request,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import BaseModel

from config import db
from routers.tenants import get_current_tenant
from services import object_storage as _storage
from utils import get_current_user, new_id, now_iso

logger = logging.getLogger(__name__)
router = APIRouter()

# ── policy constants ─────────────────────────────────────────────────
MAX_VIDEO_BYTES = 100 * 1024 * 1024      # 100 MB per file
MAX_VIDEO_DURATION_S = 60.0              # per Phase 27 spec — 60s cap
MAX_PHOTO_BYTES = 20 * 1024 * 1024       # 20 MB per photo
MAX_PHOTOS_PER_REPORT = 10
MAX_VIDEOS_PER_REPORT = 3

ALLOWED_VIDEO_MIMES = {
    "video/mp4", "video/quicktime", "video/webm", "video/x-m4v",
    "video/avi", "video/x-msvideo",
}
ALLOWED_PHOTO_MIMES = {
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
}
UPLOAD_ROLES = {"admin", "super_admin", "technician"}


def _role(u: dict) -> str:
    return (u.get("role") or "").lower()


def _forbid_customer(user: dict) -> None:
    if _role(user) == "customer":
        raise HTTPException(403, "Customers may not upload service media")


def _parse_duration(x_video_duration: Optional[str]) -> Optional[float]:
    if not x_video_duration:
        return None
    try:
        d = float(x_video_duration)
        return d if d > 0 else None
    except (TypeError, ValueError):
        return None


async def _get_report_or_404(report_id: str, tenant_id: str) -> dict:
    rep = await db.service_reports.find_one(
        {"id": report_id, "tenant_id": tenant_id}, {"_id": 0},
    )
    if not rep:
        raise HTTPException(404, "Service report not found")
    return rep


# ═══════════ Upload ═══════════════════════════════════════════════════
@router.post("/service-reports/{report_id}/media", status_code=201)
async def upload_service_report_media(
    report_id: str,
    request: Request,
    file: UploadFile = File(...),
    kind: Optional[str] = Form(None),            # "photo" | "video"
    poster_url: Optional[str] = Form(None),
    x_video_duration: Optional[str] = Header(
        None, alias="X-Video-Duration"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> dict:
    """Upload ONE media item (photo or video) into the report's pool."""
    _forbid_customer(user)
    if _role(user) not in UPLOAD_ROLES:
        raise HTTPException(403, "Not allowed to upload service media")

    rep = await _get_report_or_404(report_id, tenant["id"])
    if rep.get("deleted_at"):
        raise HTTPException(410, "Report has been deleted")

    mime = (file.content_type or "").lower()

    # Detect kind from mime if not explicitly declared.
    if not kind:
        if mime in ALLOWED_PHOTO_MIMES:
            kind = "photo"
        elif mime in ALLOWED_VIDEO_MIMES:
            kind = "video"
        else:
            raise HTTPException(
                400, f"Unsupported mime type {mime!r}. Provide `kind=photo|video`.")
    kind = kind.lower()
    if kind not in ("photo", "video"):
        raise HTTPException(400, "kind must be 'photo' or 'video'")

    # Mime allowlist enforcement.
    if kind == "photo" and mime not in ALLOWED_PHOTO_MIMES:
        raise HTTPException(
            400,
            f"Unsupported photo mime {mime!r}. "
            f"Allowed: {sorted(ALLOWED_PHOTO_MIMES)}",
        )
    if kind == "video" and mime not in ALLOWED_VIDEO_MIMES:
        raise HTTPException(
            400,
            f"Unsupported video mime {mime!r}. "
            f"Allowed: {sorted(ALLOWED_VIDEO_MIMES)}",
        )

    # Cap check BEFORE reading the body.
    existing_photos = [p for p in (rep.get("photos") or [])
                        if isinstance(p, dict) and not p.get("is_deleted")]
    existing_videos = [v for v in (rep.get("videos") or [])
                        if isinstance(v, dict) and not v.get("is_deleted")]
    if kind == "photo" and len(existing_photos) >= MAX_PHOTOS_PER_REPORT:
        raise HTTPException(
            409, f"Maximum {MAX_PHOTOS_PER_REPORT} photos per service report")
    if kind == "video" and len(existing_videos) >= MAX_VIDEOS_PER_REPORT:
        raise HTTPException(
            409, f"Maximum {MAX_VIDEOS_PER_REPORT} videos per service report")

    max_bytes = MAX_VIDEO_BYTES if kind == "video" else MAX_PHOTO_BYTES

    # Declared-size guard before draining the body.
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_i = int(declared)
        except ValueError:
            declared_i = 0
        if declared_i > max_bytes + 8192:
            raise HTTPException(413,
                                 f"File exceeds {max_bytes // (1024 * 1024)} MB limit")

    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(413,
                             f"File exceeds {max_bytes // (1024 * 1024)} MB limit")
    if not data:
        raise HTTPException(400, "Empty file")

    duration: Optional[float] = None
    if kind == "video":
        duration = _parse_duration(x_video_duration)
        if duration is not None and duration > MAX_VIDEO_DURATION_S:
            raise HTTPException(
                400,
                f"Video duration {duration:.1f}s exceeds "
                f"{int(MAX_VIDEO_DURATION_S)}-second cap",
            )

    # Storage.
    if not _storage.is_ready():
        _storage.init_storage()
    if not _storage.is_ready():
        raise HTTPException(503, "Object storage not initialised")

    ext = ""
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1]
    if not ext:
        ext = mime.split("/", 1)[-1].replace("x-m4v", "m4v").replace(
            "quicktime", "mov").replace("jpeg", "jpg")
    ext = "".join(c for c in ext.lower() if c.isalnum())[:8] or "bin"

    filename = f"{uuid.uuid4()}.{ext}"
    storage_path = _storage.build_path(
        tenant["id"], "service_report", report_id, filename)

    try:
        result = _storage.put_object(storage_path, data, mime)
    except Exception as e:
        logger.exception(
            f"[svc_report_media] put_object failed for {storage_path}: {e}")
        raise HTTPException(502, "Storage upload failed") from e

    canonical_path = result.get("path") or storage_path
    media_id = new_id()

    # Public streaming URL — no auth, keyed on the report's public_uuid.
    public_uuid = rep.get("public_uuid") or ""
    if kind == "video":
        stream_url = (f"/api/public/service/{public_uuid}/video/{media_id}"
                        if public_uuid else "")
    else:
        stream_url = (f"/api/public/service/{public_uuid}/photo/{media_id}"
                        if public_uuid else "")

    row = {
        "id": media_id,
        "storage_path": canonical_path,
        "url": stream_url,
        "mime": mime,
        "content_type": mime,
        "size_bytes": len(data),
        "uploaded_by_user_id": user.get("id"),
        "uploaded_at": now_iso(),
        "is_deleted": False,
    }
    if kind == "video":
        row["duration_seconds"] = duration
        if poster_url:
            row["poster_url"] = poster_url
            row["thumbnail_url"] = poster_url

    field = "photos" if kind == "photo" else "videos"
    await db.service_reports.update_one(
        {"id": report_id, "tenant_id": tenant["id"]},
        {"$push": {field: row}, "$set": {"updated_at": now_iso()}},
    )

    return {"kind": kind, "media": row}


# ═══════════ Reorder ══════════════════════════════════════════════════
class MediaReorderIn(BaseModel):
    photo_order: Optional[List[str]] = None
    video_order: Optional[List[str]] = None


@router.patch("/service-reports/{report_id}/media/reorder")
async def reorder_service_report_media(
    report_id: str,
    body: MediaReorderIn,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
) -> dict:
    _forbid_customer(user)
    if _role(user) not in UPLOAD_ROLES:
        raise HTTPException(403, "Not allowed to reorder service media")

    rep = await _get_report_or_404(report_id, tenant["id"])

    updates: dict = {}
    if body.photo_order is not None:
        by_url = {}
        for p in (rep.get("photos") or []):
            if isinstance(p, dict):
                url = p.get("url") or p.get("public_url") or ""
                if url:
                    by_url[url] = p
        new_list = [by_url[u] for u in body.photo_order if u in by_url]
        # Append any that weren't referenced so nothing is lost.
        remaining = [p for u, p in by_url.items() if u not in set(body.photo_order)]
        updates["photos"] = new_list + remaining

    if body.video_order is not None:
        by_url = {}
        for v in (rep.get("videos") or []):
            if isinstance(v, dict):
                url = v.get("url") or v.get("public_url") or ""
                if url:
                    by_url[url] = v
        new_list = [by_url[u] for u in body.video_order if u in by_url]
        remaining = [v for u, v in by_url.items() if u not in set(body.video_order)]
        updates["videos"] = new_list + remaining

    if not updates:
        raise HTTPException(400, "Provide photo_order and/or video_order")

    updates["updated_at"] = now_iso()
    await db.service_reports.update_one(
        {"id": report_id, "tenant_id": tenant["id"]},
        {"$set": updates},
    )
    fresh = await db.service_reports.find_one(
        {"id": report_id, "tenant_id": tenant["id"]},
        {"_id": 0, "photos": 1, "videos": 1},
    )
    return {"photos": fresh.get("photos") or [], "videos": fresh.get("videos") or []}


# ═══════════ Public video streaming (no auth) ═════════════════════════
@router.get("/public/service/{public_uuid}/video/{video_id}")
async def stream_public_service_video(public_uuid: str, video_id: str,
                                        request: Request):
    """Stream a video attached to a service report identified by its
    ``public_uuid``. No auth — the uuid+id combination is the
    authorisation."""
    # Share the metadata endpoint's rate-limit bucket so a video-heavy
    # portal page can't bypass the 60/minute IP cap.
    from routers.public_service_images import _rate_limit_public_service
    ip = (request.client.host if request.client else "?") or "?"
    await _rate_limit_public_service(ip)

    rep = await db.service_reports.find_one(
        {"public_uuid": public_uuid}, {"_id": 0, "videos": 1, "deleted_at": 1},
    )
    if not rep or rep.get("deleted_at"):
        raise HTTPException(404, "Not found")
    match = next((v for v in (rep.get("videos") or [])
                    if isinstance(v, dict) and v.get("id") == video_id
                    and not v.get("is_deleted")), None)
    if not match:
        raise HTTPException(404, "Video not found on this report")
    storage_path = match.get("storage_path")
    if not storage_path:
        raise HTTPException(404, "Storage path missing")
    try:
        data, ctype = _storage.get_object(storage_path)
    except Exception as e:
        logger.warning(f"public video fetch failed {storage_path}: {e}")
        raise HTTPException(502, "Storage read failed") from e
    return Response(content=data,
                     media_type=(ctype or match.get("content_type") or "video/mp4"),
                     headers={"Cache-Control": "public, max-age=300"})


@router.get("/public/service/{public_uuid}/photo/{photo_id}")
async def stream_public_service_photo(public_uuid: str, photo_id: str,
                                         request: Request):
    """Same-shape endpoint for photos uploaded via the new media route.
    Legacy job-mirrored photos (with externally-hosted URLs) continue
    to serve from their original CDN — this endpoint is only used for
    photos uploaded through ``POST /service-reports/{id}/media``."""
    from routers.public_service_images import _rate_limit_public_service
    ip = (request.client.host if request.client else "?") or "?"
    await _rate_limit_public_service(ip)

    rep = await db.service_reports.find_one(
        {"public_uuid": public_uuid}, {"_id": 0, "photos": 1, "deleted_at": 1},
    )
    if not rep or rep.get("deleted_at"):
        raise HTTPException(404, "Not found")
    match = next((p for p in (rep.get("photos") or [])
                    if isinstance(p, dict) and p.get("id") == photo_id
                    and not p.get("is_deleted")), None)
    if not match:
        raise HTTPException(404, "Photo not found on this report")
    storage_path = match.get("storage_path")
    if not storage_path:
        raise HTTPException(404, "Storage path missing")
    try:
        data, ctype = _storage.get_object(storage_path)
    except Exception as e:
        logger.warning(f"public photo fetch failed {storage_path}: {e}")
        raise HTTPException(502, "Storage read failed") from e
    return Response(content=data,
                     media_type=(ctype or match.get("content_type") or "image/jpeg"),
                     headers={"Cache-Control": "public, max-age=3600"})
