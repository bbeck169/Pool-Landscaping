"""Phase F0 · Feb 2026 — /api/files/* router.

Auth-gated upload / download / soft-delete / list for arbitrary
customer / job / persona / portal / chat attachments. Backed by
``services/file_storage.py`` (Emergent Object Storage session client).

Design invariants
-----------------
* ``tenant_id`` boundary is ALWAYS enforced — cross-tenant download
  attempts 404.
* Storage paths are namespaced ``poolscape-crm/{tenant_id}/{purpose}/{uuid}.{ext}``
  so migrations + tenant deletes stay surgical.
* Soft delete only — the ``files`` doc keeps ``is_deleted=True`` so
  audit trails survive.
* Uploader OR any admin can soft-delete.
* Download supports both ``Authorization: Bearer <token>`` header
  and ``?auth=<token>`` query param (for ``<img src>`` compatibility).
"""
from __future__ import annotations

import mimetypes
import os
import uuid
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query,
    Request, Response, UploadFile,
)
from fastapi.responses import JSONResponse

from config import db, logger
from services.file_storage import (
    APP_NAME,
    StorageError,
    get_object,
    is_storage_configured,
    put_object,
)
from utils import get_current_user, new_id, now_iso

router = APIRouter(prefix="/files", tags=["files"])

MAX_UPLOAD_SIZE = 25 * 1024 * 1024   # 25 MB
ALLOWED_MIME_PREFIXES = ("image/", "video/mp4", "application/pdf")


def _mime_allowed(ct: str) -> bool:
    ct = (ct or "").lower()
    if ct == "application/pdf":
        return True
    return any(ct.startswith(p) for p in ALLOWED_MIME_PREFIXES)


def _ext_from(content_type: str, filename: str) -> str:
    # Try extension from filename first; fall back to content-type mapping.
    _, ext = os.path.splitext(filename or "")
    if ext and 1 < len(ext) <= 6:
        return ext.lstrip(".").lower()
    guess = mimetypes.guess_extension(content_type or "") or ""
    return guess.lstrip(".").lower() or "bin"


def _sanitize_segment(seg: str) -> str:
    """Constrain path segments to a safe alphabet so the storage
    key never encodes a path-traversal attempt."""
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    return "".join(c if c in keep else "_" for c in (seg or ""))[:64] or "general"


async def _resolve_bearer_or_query_auth(
    request: Request, auth: Optional[str] = None,
) -> dict:
    """Download-only auth resolver: accept the standard Bearer header
    OR a ``?auth=<token>`` query param (needed for ``<img src>`` usage
    where headers can't be attached).
    """
    from fastapi.security import HTTPAuthorizationCredentials
    from utils import get_current_user as _get
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    token = None
    if header and header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1].strip()
    if not token and auth:
        token = auth.strip()
    if not token:
        raise HTTPException(401, detail="not_authenticated")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return await _get(creds)


# ═══════════════════════════════════════════════════════════════════
# POST /api/files/upload
# ═══════════════════════════════════════════════════════════════════
@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    purpose: Optional[str] = Form(None),
    linked_entity_type: Optional[str] = Form(None),
    linked_entity_id: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    if not is_storage_configured():
        raise HTTPException(503, detail={
            "code": "STORAGE_UNAVAILABLE",
            "message": "File storage is not configured on this server.",
        })

    content_type = file.content_type or "application/octet-stream"
    if not _mime_allowed(content_type):
        raise HTTPException(415, detail={
            "code": "UNSUPPORTED_MIME",
            "message": f"Content type {content_type!r} is not allowed.",
        })

    data = await file.read()
    size = len(data)
    if size > MAX_UPLOAD_SIZE:
        raise HTTPException(413, detail={
            "code": "FILE_TOO_LARGE",
            "message": f"Max upload size is {MAX_UPLOAD_SIZE} bytes ({MAX_UPLOAD_SIZE // (1024 * 1024)} MB).",
        })

    tenant_id = user.get("tenant_id") or ""
    if not tenant_id:
        raise HTTPException(403, detail="tenant_required")

    ext = _ext_from(content_type, file.filename or "")
    fname = f"{uuid.uuid4().hex}.{ext}"
    path = "/".join([
        APP_NAME,
        _sanitize_segment(tenant_id),
        _sanitize_segment(purpose or "general"),
        fname,
    ])

    try:
        meta = put_object(path, data, content_type)
    except StorageError as e:
        logger.warning("[FILES] put_object failed: %s", e)
        raise HTTPException(502, detail={
            "code": "STORAGE_WRITE_FAILED",
            "message": str(e),
        })

    file_id = new_id()
    doc = {
        "id": file_id,
        "tenant_id": tenant_id,
        "storage_path": meta["path"],
        "original_filename": file.filename or fname,
        "content_type": content_type,
        "size": int(meta["size"]),
        "uploaded_by_user_id": user.get("id"),
        "purpose": purpose,
        "linked_entity_type": linked_entity_type,
        "linked_entity_id": linked_entity_id,
        "created_at": now_iso(),
        "is_deleted": False,
        "deleted_at": None,
    }
    await db.files.insert_one(doc)

    return {
        "id": file_id,
        "url": f"/api/files/{file_id}/download",
        "original_filename": doc["original_filename"],
        "content_type": doc["content_type"],
        "size": doc["size"],
        "storage_path": doc["storage_path"],
    }


# ═══════════════════════════════════════════════════════════════════
# GET /api/files/{file_id}/download
# ═══════════════════════════════════════════════════════════════════
@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    request: Request,
    auth: Optional[str] = Query(None, description="Bearer token for <img> src usage"),
):
    user = await _resolve_bearer_or_query_auth(request, auth)
    tenant_id = user.get("tenant_id")

    doc = await db.files.find_one({"id": file_id})
    if not doc or doc.get("is_deleted") or doc.get("tenant_id") != tenant_id:
        raise HTTPException(404, detail="not_found")

    if not is_storage_configured():
        raise HTTPException(503, detail={
            "code": "STORAGE_UNAVAILABLE",
            "message": "File storage is not configured on this server.",
        })

    try:
        data, ct = get_object(doc["storage_path"])
    except StorageError as e:
        logger.warning("[FILES] get_object failed: %s", e)
        raise HTTPException(502, detail={
            "code": "STORAGE_READ_FAILED",
            "message": str(e),
        })

    filename = doc.get("original_filename") or file_id
    return Response(
        content=data,
        media_type=doc.get("content_type") or ct or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════════
# POST /api/files/{file_id}/delete    (soft-delete)
# ═══════════════════════════════════════════════════════════════════
@router.post("/{file_id}/delete")
async def delete_file(
    file_id: str,
    user: dict = Depends(get_current_user),
):
    doc = await db.files.find_one({"id": file_id})
    if not doc or doc.get("tenant_id") != user.get("tenant_id"):
        raise HTTPException(404, detail="not_found")
    if doc.get("is_deleted"):
        return Response(status_code=204)      # already soft-deleted; idempotent

    role = (user.get("role") or "").lower()
    is_admin = role in ("admin", "super_admin", "manager")
    if not is_admin and doc.get("uploaded_by_user_id") != user.get("id"):
        raise HTTPException(403, detail={
            "code": "NOT_UPLOADER",
            "message": "Only the uploader or an admin can delete this file.",
        })

    await db.files.update_one(
        {"id": file_id},
        {"$set": {"is_deleted": True, "deleted_at": now_iso()}},
    )
    return Response(status_code=204)


# ═══════════════════════════════════════════════════════════════════
# GET /api/files?linked_entity_type=X&linked_entity_id=Y
# ═══════════════════════════════════════════════════════════════════
@router.get("")
async def list_files(
    linked_entity_type: Optional[str] = Query(None),
    linked_entity_id: Optional[str] = Query(None),
    purpose: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    q: dict = {"tenant_id": user.get("tenant_id"), "is_deleted": False}
    if linked_entity_type:
        q["linked_entity_type"] = linked_entity_type
    if linked_entity_id:
        q["linked_entity_id"] = linked_entity_id
    if purpose:
        q["purpose"] = purpose
    rows = await db.files.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    for r in rows:
        r["url"] = f"/api/files/{r['id']}/download"
    return {"items": rows, "count": len(rows)}
