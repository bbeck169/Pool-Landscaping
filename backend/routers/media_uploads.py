"""Phase 5A — Video uploads on jobs + estimates (Feb 2026).

First feature in the codebase to hit Emergent object storage. Follows the
Customer Equipment Photo Library RBAC pattern (see
``routers/customer_equipment_photos.py``): tenant-scoped everywhere,
``customer`` role uniformly rejected, admins can hard-delete metadata,
techs can upload.

Endpoints:

  POST   /api/jobs/{job_id}/videos
  DELETE /api/jobs/{job_id}/videos/{video_id}
  PATCH  /api/jobs/{job_id}/videos/{video_id}
  POST   /api/estimates/{estimate_id}/videos
  DELETE /api/estimates/{estimate_id}/videos/{video_id}
  PATCH  /api/estimates/{estimate_id}/videos/{video_id}
  GET    /api/media/videos/{path:path}    (auth-gated streaming)

Storage / cap decisions:
  * 100 MB per file, 10 videos per entity (mirrors the existing 10-photo
    cap on jobs).
  * Mime allow-list: mp4, quicktime, webm, x-m4v.
  * Duration parsed from ``X-Video-Duration`` client header (server has
    no ffprobe available); stored as null when absent or invalid.
  * Delete is soft — Emergent storage has no delete API. ``is_deleted``
    flags the row; the storage object persists.
  * Playback: HTML5 ``<video>`` fetches the whole body from
    ``/api/media/videos/{path}``. Range requests are honoured
    optimistically (slice the fetched bytes) so scrubbing feels
    responsive on small files. Emergent storage itself has no range
    API — repeated large seeks will therefore re-fetch. Documented in
    ``services/object_storage.py``.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, Form, Header, HTTPException, Query, Request,
    Response, UploadFile,
)

from config import db
from routers.tenants import get_current_tenant
from services import object_storage as _storage
from utils import get_current_user, new_id, now_iso

logger = logging.getLogger(__name__)
router = APIRouter()

# ── policy constants ────────────────────────────────────────────────────
MAX_VIDEO_BYTES = 100 * 1024 * 1024          # 100 MB per file
MAX_VIDEO_DURATION_S = 180.0                 # 3 min per file
# Slice K1 (Feb 2026): tightened from 10 → 3 per user brief. Photos
# still capped at 10 (see routers/jobs.py); this cap is video-only.
MAX_VIDEOS_PER_ENTITY = 3
ALLOWED_MIMES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
}
ENTITY_COLLECTIONS = {
    "job": "jobs",
    "estimate": "estimates",
}
UPLOAD_ROLES = {"admin", "super_admin", "technician"}
# Slice K1 (Feb 2026): admins can hard-delete anyone's video; techs
# can only hard-delete videos they themselves uploaded (enforced by
# comparing ``uploaded_by`` against the caller in the delete handler,
# NOT by role gate alone).
DELETE_ROLES = {"admin", "super_admin", "technician"}


def _role(u: dict) -> str:
    return (u.get("role") or "").lower()


def _forbid_customer(u: dict) -> None:
    if _role(u) == "customer":
        raise HTTPException(403, "Videos are not available to customers")


def _require_storage_ready() -> None:
    if not _storage.is_ready():
        # Try one lazy re-init in case startup happened before env was ready.
        _storage.init_storage()
        if not _storage.is_ready():
            raise HTTPException(503, "Object storage not configured")


async def _get_entity_or_404(kind: str, entity_id: str, tenant_id: str) -> dict:
    coll = ENTITY_COLLECTIONS[kind]
    doc = await db[coll].find_one(
        {"id": entity_id, "tenant_id": tenant_id},
        {"_id": 0, "id": 1, "videos": 1, "customer_id": 1, "title": 1},
    )
    if not doc:
        raise HTTPException(404, f"{kind.capitalize()} not found")
    return doc


def _visibility_or_400(value: Optional[str]) -> str:
    v = (value or "internal").strip().lower()
    if v not in ("internal", "customer"):
        raise HTTPException(400, "visibility must be 'internal' or 'customer'")
    return v


def _parse_duration(header_value: Optional[str]) -> Optional[float]:
    if not header_value:
        return None
    try:
        d = float(header_value)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    return d


async def _upload_video(
    kind: str,
    entity_id: str,
    request: Request,
    file: UploadFile,
    caption: Optional[str],
    visibility: Optional[str],
    x_video_duration: Optional[str],
    user: dict,
    tenant: dict,
) -> dict:
    _forbid_customer(user)
    if _role(user) not in UPLOAD_ROLES:
        raise HTTPException(403, "Not allowed to upload videos")

    _require_storage_ready()

    # Mobile Phase 2 · Feb-2026 — stricter caps when the caller
    # declares itself the mobile flush worker. Web / other clients
    # keep the pre-existing generous 100MB / 3-min / 4-mime policy.
    from services.mobile_offline_sync import (
        is_mobile_offline_sync,
        MOBILE_MAX_VIDEO_BYTES,
        MOBILE_MAX_VIDEO_DURATION_S,
        MOBILE_STRICT_MIMES,
    )
    is_mobile = is_mobile_offline_sync(request)
    _max_bytes = MOBILE_MAX_VIDEO_BYTES if is_mobile else MAX_VIDEO_BYTES
    _max_duration = (
        MOBILE_MAX_VIDEO_DURATION_S if is_mobile else MAX_VIDEO_DURATION_S
    )
    _allowed_mimes = MOBILE_STRICT_MIMES if is_mobile else ALLOWED_MIMES

    mime = (file.content_type or "").lower()
    if mime not in _allowed_mimes:
        raise HTTPException(
            400,
            f"Unsupported mimetype {mime!r}. "
            f"Allowed: {sorted(_allowed_mimes)}",
        )

    entity = await _get_entity_or_404(kind, entity_id, tenant["id"])
    existing = [v for v in (entity.get("videos") or []) if not v.get("is_deleted")]
    if len(existing) >= MAX_VIDEOS_PER_ENTITY:
        raise HTTPException(
            409,
            f"Maximum {MAX_VIDEOS_PER_ENTITY} videos per {kind}. "
            f"Delete an existing video before uploading another.",
        )

    # Declared-size guard — reject huge uploads before draining the body.
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_i = int(declared)
        except ValueError:
            declared_i = 0
        # Multipart framing adds a small overhead, allow 8KB slack.
        if declared_i > _max_bytes + 8192:
            _mb = _max_bytes // (1024 * 1024)
            raise HTTPException(413, f"Video exceeds {_mb} MB limit")

    data = await file.read()
    if len(data) > _max_bytes:
        _mb = _max_bytes // (1024 * 1024)
        raise HTTPException(413, f"Video exceeds {_mb} MB limit")
    if not data:
        raise HTTPException(400, "Empty video file")

    duration = _parse_duration(x_video_duration)
    if duration is not None and duration > _max_duration:
        raise HTTPException(
            400,
            f"Video duration {duration:.1f}s exceeds "
            f"{int(_max_duration)}s cap",
        )

    visibility_v = _visibility_or_400(visibility)

    caption_v = (caption or "").strip()
    if len(caption_v) > 240:
        raise HTTPException(400, "caption must be 240 characters or fewer")

    ext = (file.filename or "").rsplit(".", 1)[-1] if file.filename and "." in file.filename else ""
    if not ext:
        # Fall back on mimetype for the extension.
        ext = mime.split("/", 1)[-1].replace("x-m4v", "m4v").replace("quicktime", "mov")
    ext = "".join(c for c in ext.lower() if c.isalnum())[:8] or "bin"

    filename = f"{uuid.uuid4()}.{ext}"
    storage_path = _storage.build_path(tenant["id"], kind, entity_id, filename)

    try:
        result = _storage.put_object(storage_path, data, mime)
    except Exception as e:
        logger.exception(f"[media_uploads] put_object failed for {storage_path}: {e}")
        raise HTTPException(502, "Storage upload failed") from e

    canonical_path = result.get("path") or storage_path

    video = {
        "id": new_id(),
        "storage_path": canonical_path,
        "mime": mime,
        "size_bytes": len(data),
        "duration_seconds": duration,
        "original_filename": (file.filename or "")[:255] or None,
        "uploaded_by_user_id": user.get("id"),
        "uploaded_by_name": user.get("name") or user.get("email") or "Unknown",
        "uploaded_at": now_iso(),
        "visibility": visibility_v,
        "caption": caption_v or None,
        "is_deleted": False,
    }

    coll = ENTITY_COLLECTIONS[kind]
    await db[coll].update_one(
        {"id": entity_id, "tenant_id": tenant["id"]},
        {"$push": {"videos": video}, "$set": {"updated_at": now_iso()}},
    )

    return {
        "video": video,
        kind: {
            "id": entity.get("id"),
            "title": entity.get("title"),
            "customer_id": entity.get("customer_id"),
        },
    }


async def _patch_video(
    kind: str, entity_id: str, video_id: str,
    caption: Optional[str], visibility: Optional[str],
    user: dict, tenant: dict,
) -> dict:
    _forbid_customer(user)
    if _role(user) not in UPLOAD_ROLES:
        raise HTTPException(403, "Not allowed to edit videos")

    entity = await _get_entity_or_404(kind, entity_id, tenant["id"])
    videos = entity.get("videos") or []
    target = next((v for v in videos if v.get("id") == video_id), None)
    if not target:
        raise HTTPException(404, "Video not found")

    updates: dict = {}
    if caption is not None:
        cap = caption.strip()
        if len(cap) > 240:
            raise HTTPException(400, "caption must be 240 characters or fewer")
        updates["caption"] = cap or None
    if visibility is not None:
        updates["visibility"] = _visibility_or_400(visibility)

    if not updates:
        return {"video": target}

    coll = ENTITY_COLLECTIONS[kind]
    setops = {f"videos.$.{k}": v for k, v in updates.items()}
    setops["updated_at"] = now_iso()
    await db[coll].update_one(
        {"id": entity_id, "tenant_id": tenant["id"], "videos.id": video_id},
        {"$set": setops},
    )
    target = {**target, **updates}
    return {"video": target}


async def _delete_video(kind: str, entity_id: str, video_id: str,
                        user: dict, tenant: dict) -> dict:
    _forbid_customer(user)
    if _role(user) not in DELETE_ROLES:
        raise HTTPException(403, "Access denied")

    entity = await _get_entity_or_404(kind, entity_id, tenant["id"])
    videos = entity.get("videos") or []
    video = next((v for v in videos if v.get("id") == video_id), None)
    if not video:
        raise HTTPException(404, "Video not found")

    # Slice K1 RBAC — techs may hard-delete ONLY videos they themselves
    # uploaded. Admins can hard-delete anyone's video.
    if _role(user) == "technician":
        uploader = video.get("uploaded_by_user_id") or video.get("uploaded_by")
        if uploader != user.get("id"):
            raise HTTPException(403, "You can only delete your own uploads")

    coll = ENTITY_COLLECTIONS[kind]
    await db[coll].update_one(
        {"id": entity_id, "tenant_id": tenant["id"], "videos.id": video_id},
        {"$set": {"videos.$.is_deleted": True,
                  "videos.$.deleted_at": now_iso(),
                  "updated_at": now_iso()}},
    )
    return {"ok": True, "deleted": video_id, "hard_delete": False}


# ── job routes ──────────────────────────────────────────────────────────
@router.post("/jobs/{job_id}/videos", status_code=201)
async def upload_job_video(
    job_id: str,
    request: Request,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    visibility: Optional[str] = Form("internal"),
    x_video_duration: Optional[str] = Header(default=None, alias="X-Video-Duration"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    return await _upload_video(
        "job", job_id, request, file, caption, visibility,
        x_video_duration, user, tenant,
    )


@router.delete("/jobs/{job_id}/videos/{video_id}")
async def delete_job_video(job_id: str, video_id: str,
                            user: dict = Depends(get_current_user),
                            tenant: dict = Depends(get_current_tenant)):
    return await _delete_video("job", job_id, video_id, user, tenant)


@router.patch("/jobs/{job_id}/videos/{video_id}")
async def patch_job_video(
    job_id: str, video_id: str,
    caption: Optional[str] = Form(None),
    visibility: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    return await _patch_video("job", job_id, video_id,
                              caption, visibility, user, tenant)


# ── estimate routes ────────────────────────────────────────────────────
@router.post("/estimates/{estimate_id}/videos", status_code=201)
async def upload_estimate_video(
    estimate_id: str,
    request: Request,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    visibility: Optional[str] = Form("internal"),
    x_video_duration: Optional[str] = Header(default=None, alias="X-Video-Duration"),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    return await _upload_video(
        "estimate", estimate_id, request, file, caption, visibility,
        x_video_duration, user, tenant,
    )


@router.delete("/estimates/{estimate_id}/videos/{video_id}")
async def delete_estimate_video(estimate_id: str, video_id: str,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    return await _delete_video("estimate", estimate_id, video_id, user, tenant)


@router.patch("/estimates/{estimate_id}/videos/{video_id}")
async def patch_estimate_video(
    estimate_id: str, video_id: str,
    caption: Optional[str] = Form(None),
    visibility: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    return await _patch_video("estimate", estimate_id, video_id,
                              caption, visibility, user, tenant)


# ── streaming ──────────────────────────────────────────────────────────
async def _find_video_by_storage_path(tenant_id: str, path: str) -> Optional[dict]:
    """Locate a video doc by its storage_path across jobs + estimates in
    the given tenant. Returns ``{kind, entity_id, video}`` or None."""
    for kind, coll in ENTITY_COLLECTIONS.items():
        doc = await db[coll].find_one(
            {"tenant_id": tenant_id, "videos.storage_path": path},
            {"_id": 0, "id": 1, "customer_id": 1, "videos": 1},
        )
        if not doc:
            continue
        video = next(
            (v for v in (doc.get("videos") or [])
             if v.get("storage_path") == path and not v.get("is_deleted")),
            None,
        )
        if video:
            return {"kind": kind, "entity_id": doc["id"],
                    "customer_id": doc.get("customer_id"), "video": video}
    return None


def _resolve_bearer(auth_header: Optional[str], auth_query: Optional[str]) -> Optional[str]:
    """HTML5 ``<video src>`` cannot set headers, so we accept a token via
    a ``?auth=`` query param as well as the standard Authorization header.
    """
    if auth_header:
        return auth_header
    if auth_query:
        return f"Bearer {auth_query}"
    return None


@router.get("/media/videos/{path:path}")
async def stream_video(
    path: str,
    request: Request,
    auth: Optional[str] = Query(default=None),
):
    """Auth-gated proxy stream. Backend fetches the object from Emergent
    storage and returns the bytes with correct Content-Type + optional
    ``206 Partial Content`` when the client sends a ``Range`` header.

    Accepts token from either the ``Authorization: Bearer`` header
    (native fetch/axios path) or a ``?auth=`` query param (bare
    ``<video src>`` playback path — HTML5 media elements cannot set
    custom request headers).
    """
    import jwt as _jwt
    from config import JWT_SECRET, JWT_ALGO

    raw_auth = _resolve_bearer(request.headers.get("Authorization"), auth)
    if not raw_auth or not raw_auth.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    token = raw_auth.split(" ", 1)[1]

    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except _jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except _jwt.PyJWTError:
        raise HTTPException(401, "Invalid token")

    user = await db.users.find_one({"id": payload.get("sub")},
                                    {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(401, "User not found")
    if user.get("active") is False:
        raise HTTPException(401, "Account is deactivated")

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(403, "No tenant scope")

    hit = await _find_video_by_storage_path(tenant_id, path)
    if not hit:
        raise HTTPException(404, "Video not found")
    video = hit["video"]

    # Visibility gate — customers may only stream shareable videos AND
    # only for entities under their own ``customer_id``.
    if _role(user) == "customer":
        if video.get("visibility") != "customer":
            raise HTTPException(403, "This video is not shared with customers")
        if hit.get("customer_id") and user.get("customer_id") \
                and hit["customer_id"] != user["customer_id"]:
            raise HTTPException(403, "Not your video")

    try:
        data, ctype = _storage.get_object(path)
    except Exception as e:
        logger.exception(f"[media_uploads] get_object failed for {path}: {e}")
        raise HTTPException(502, "Storage read failed") from e

    ctype = video.get("mime") or ctype or "application/octet-stream"
    total = len(data)
    range_hdr = request.headers.get("range") or request.headers.get("Range")
    if range_hdr and range_hdr.lower().startswith("bytes="):
        try:
            start_end = range_hdr.split("=", 1)[1].split(",")[0]
            start_s, end_s = start_end.split("-", 1)
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else total - 1
            start = max(0, start); end = min(total - 1, end)
            if start > end:
                start, end = 0, total - 1
            chunk = data[start:end + 1]
            return Response(
                content=chunk,
                status_code=206,
                media_type=ctype,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(chunk)),
                },
            )
        except Exception:
            # Malformed Range → fall through to full response.
            pass

    return Response(
        content=data,
        media_type=ctype,
        headers={"Accept-Ranges": "bytes", "Content-Length": str(total)},
    )
