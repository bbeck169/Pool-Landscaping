"""Phase 9C · Feb 2026 — Marketing media library.

Backend for the Emergent Object Storage-backed asset library. Frontend
(TipTap ``<MediaLibraryPicker>``) consumes these endpoints in the next
session.

* Upload validates magic bytes, strips EXIF (JPEG/PNG/WebP), rejects
  SVG containing script/JS-URI content, caps size at 5 MB (200 KB for
  SVG).
* Every file is stored under
  ``pool-crm/tenants/{tenant_id}/marketing_media/{uuid}.{ext}`` in the
  shared bucket. Downloads proxy through this router so tenant
  isolation + auth are enforced.
* Soft-delete is guarded by a grep against
  ``marketing_templates.body`` — active templates that still reference
  the URL block the delete with **409**.
"""
from __future__ import annotations

import io
import os
import re
import uuid as _uuid
from typing import Dict, List, Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Response,
    UploadFile,
)

from config import db, logger
from routers.tenants import get_current_tenant
from services.marketing_media.storage_client import (
    StorageUnavailable, build_path, get_object, put_object,
)
from utils import get_current_user, new_id, now_iso, require_admin

router = APIRouter()

# ─────────── Constants
_MAX_SIZE = 5 * 1024 * 1024               # 5 MB
_MAX_SIZE_SVG = 200 * 1024                # 200 KB
_ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
_MIME_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
}
_MAGIC_HEADERS = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"], "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],  # + b"WEBP" at offset 8; checked separately
    "svg": [b"<?xml", b"<svg"],
}
_SVG_DANGER = re.compile(
    rb"(<script\b)|(\son\w+\s*=)|(href\s*=\s*[\"']?\s*javascript:)",
    re.IGNORECASE,
)
_FILENAME_SAFE = re.compile(r"[^a-zA-Z0-9._-]")
_MANAGERS = {"admin", "super_admin", "manager"}


def _require_managers(user: dict) -> None:
    if (user or {}).get("role") not in _MANAGERS:
        raise HTTPException(403, "Not allowed")


def _detect_ext(file_name: str, declared_mime: str) -> str:
    ext = ""
    if "." in file_name:
        ext = file_name.rsplit(".", 1)[-1].lower()
    if ext in _ALLOWED_EXT:
        return "jpg" if ext == "jpeg" else ext
    # Fall back to declared MIME.
    for e, m in _MIME_BY_EXT.items():
        if m == declared_mime.lower():
            return e
    raise HTTPException(415, f"Unsupported extension: {ext or declared_mime}")


def _magic_bytes_ok(ext: str, data: bytes) -> bool:
    hdrs = _MAGIC_HEADERS.get(ext) or []
    if not any(data.startswith(h) for h in hdrs):
        return False
    if ext == "webp" and data[8:12] != b"WEBP":
        return False
    return True


def _strip_exif(data: bytes, ext: str) -> bytes:
    """Best-effort EXIF strip for jpeg/png/webp. Returns data unchanged
    on failure so an unexpected Pillow issue never blocks an upload."""
    if ext not in ("jpg", "jpeg", "png", "webp"):
        return data
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        out = io.BytesIO()
        # ``save`` without ``exif`` argument strips it.
        save_fmt = {"jpg": "JPEG", "jpeg": "JPEG",
                     "png": "PNG", "webp": "WEBP"}[ext]
        img.save(out, format=save_fmt)
        return out.getvalue()
    except Exception as exc:
        logger.warning(f"[phase9c] EXIF strip failed ({exc}); using original bytes")
        return data


def _sanitize_filename(raw: str) -> str:
    name = os.path.basename(raw or "")
    name = _FILENAME_SAFE.sub("_", name)
    return (name[:120] if name else f"upload-{_uuid.uuid4().hex[:8]}")


def _download_url(mid: str) -> str:
    return f"/api/marketing/media/{mid}/download"


# ═══════════════════════════ Upload ══════════════════════════════════
@router.post("/marketing/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    alt_text: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # comma-separated
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_managers(user)
    raw = await file.read()
    size = len(raw)
    if size == 0:
        raise HTTPException(400, "Empty file")
    ext = _detect_ext(file.filename or "", file.content_type or "")
    limit = _MAX_SIZE_SVG if ext == "svg" else _MAX_SIZE
    if size > limit:
        raise HTTPException(413, f"File exceeds {limit // 1024} KB limit")
    if not _magic_bytes_ok(ext, raw):
        raise HTTPException(
            415,
            "File contents don't match declared type "
            "(magic-bytes check failed)",
        )
    if ext == "svg" and _SVG_DANGER.search(raw):
        raise HTTPException(
            415, "SVG contains script/inline-JS — refused",
        )
    stripped = _strip_exif(raw, ext)

    mime = _MIME_BY_EXT[ext]
    uid = f"{_uuid.uuid4().hex}.{ext}"
    storage_path = build_path(tenant["id"], uid)
    try:
        put_object(storage_path, stripped, mime)
    except StorageUnavailable as exc:
        logger.warning(f"[phase9c] storage unavailable: {exc}")
        raise HTTPException(503, f"Storage unavailable: {exc}")

    mid = new_id()
    now = now_iso()
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    row = {
        "id": mid, "tenant_id": tenant["id"],
        "uploaded_by": user.get("id"),
        "file_name": _sanitize_filename(file.filename or f"{uid}"),
        "mime_type": mime,
        "size_bytes": len(stripped),
        "storage_key": storage_path,
        "storage_url": storage_path,   # served via /download proxy
        "cdn_url": _download_url(mid),
        "alt_text": alt_text or None,
        "tags": tag_list,
        "deleted_at": None,
        "ref_count_cached": 0,
        "created_at": now, "updated_at": now,
    }
    await db.marketing_media.insert_one(row)
    row.pop("_id", None)
    return {
        "id": mid,
        "url": _download_url(mid),
        "cdn_url": _download_url(mid),
        "mime_type": mime,
        "size_bytes": len(stripped),
        "file_name": row["file_name"],
    }


# ═══════════════════════════ Download proxy ══════════════════════════
@router.get("/marketing/media/{mid}/download")
async def download_media(
    mid: str,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    row = await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"], "deleted_at": None},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Media not found")
    try:
        data, ctype = get_object(row["storage_key"])
    except StorageUnavailable as exc:
        raise HTTPException(503, f"Storage unavailable: {exc}")
    return Response(content=data, media_type=row.get("mime_type") or ctype)


# ═══════════════════════════ List / Detail / Patch ═══════════════════
@router.get("/marketing/media")
async def list_media(
    page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
    tag: Optional[str] = None, search: Optional[str] = None,
    include_deleted: int = 0,
    user: dict = Depends(get_current_user),
    tenant: dict = Depends(get_current_tenant),
):
    _require_managers(user)
    q: Dict = {"tenant_id": tenant["id"]}
    if not include_deleted:
        q["deleted_at"] = None
    if tag:
        q["tags"] = tag
    if search:
        s = search.strip()
        q["$or"] = [
            {"file_name": {"$regex": s, "$options": "i"}},
            {"alt_text": {"$regex": s, "$options": "i"}},
        ]
    total = await db.marketing_media.count_documents(q)
    rows = await db.marketing_media.find(q, {"_id": 0}) \
        .sort("created_at", -1) \
        .skip((page - 1) * page_size).limit(page_size) \
        .to_list(page_size)
    return {"rows": rows, "total": total, "page": page,
             "page_size": page_size}


@router.get("/marketing/media/{mid}")
async def get_media(mid: str,
                       user: dict = Depends(get_current_user),
                       tenant: dict = Depends(get_current_tenant)):
    _require_managers(user)
    row = await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Media not found")
    return row


@router.patch("/marketing/media/{mid}")
async def patch_media(mid: str, payload: Dict,
                        user: dict = Depends(get_current_user),
                        tenant: dict = Depends(get_current_tenant)):
    _require_managers(user)
    upd: Dict = {}
    if "alt_text" in payload:
        upd["alt_text"] = payload["alt_text"] or None
    if "tags" in payload:
        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        upd["tags"] = list(tags)
    if not upd:
        raise HTTPException(400, "Nothing to update")
    upd["updated_at"] = now_iso()
    res = await db.marketing_media.update_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"$set": upd},
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Media not found")
    return await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0},
    )


# ═══════════════════════════ Soft-delete with ref-count ══════════════
async def _referencing_templates(tenant_id: str, mid: str,
                                    url: str) -> List[str]:
    """Return the ids of active (non-system-only would be surprising to
    the user; include ALL active) templates whose body embeds the
    media's URL. Uses two search patterns: the ``/download`` URL and a
    fallback for legacy raw storage paths."""
    patterns = [
        f"/api/marketing/media/{mid}/download",
        url,
    ]
    or_clauses = [
        {"body": {"$regex": re.escape(p), "$options": "i"}}
        for p in patterns
    ]
    cursor = db.marketing_templates.find(
        {"tenant_id": tenant_id, "active": True,
         "$or": or_clauses},
        {"_id": 0, "id": 1},
    )
    return [r["id"] async for r in cursor]


@router.delete("/marketing/media/{mid}")
async def delete_media(mid: str,
                          user: dict = Depends(get_current_user),
                          tenant: dict = Depends(get_current_tenant)):
    _require_managers(user)
    row = await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"], "deleted_at": None},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Media not found")
    refs = await _referencing_templates(tenant["id"], mid,
                                            row.get("cdn_url") or _download_url(mid))
    if refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Media is referenced by active templates",
                "referencing_template_ids": refs,
            },
        )
    await db.marketing_media.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": now_iso(), "updated_at": now_iso()}},
    )
    return {"ok": True, "id": mid}


@router.post("/marketing/media/{mid}/restore")
async def restore_media(mid: str,
                           user: dict = Depends(require_admin),
                           tenant: dict = Depends(get_current_tenant)):
    row = await db.marketing_media.find_one(
        {"id": mid, "tenant_id": tenant["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Media not found")
    if row.get("deleted_at") is None:
        return {"ok": True, "already_active": True}
    await db.marketing_media.update_one(
        {"id": mid, "tenant_id": tenant["id"]},
        {"$set": {"deleted_at": None, "updated_at": now_iso()}},
    )
    return {"ok": True, "id": mid}
