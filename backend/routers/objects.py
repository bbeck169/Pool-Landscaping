"""Feb 2026 · Object-Storage streaming + legacy pod-local uploads router.

Two responsibilities:

1. ``GET /api/objects/{path:path}`` — resolves an Emergent Object Storage
   path (e.g. ``poolcrm/{tenant_id}/{entity_kind}/{entity_id}/{filename}``)
   and streams the bytes back to the browser with the stored content
   type. This is the single canonical retrieval endpoint every writer
   points at:

     ``services.media_provider._persist_image``   →  ``/api/objects/{path}``
     ``routers.before_after._upload_card``        →  ``/api/objects/{path}``

   URLs stored in the DB use the ``/api/objects/...`` prefix (routed
   through Kubernetes ingress → this backend → object-storage GET).

2. ``GET /api/uploads/{path:path}`` — backwards-compat handler that
   serves pod-local files still living under ``/app/backend/uploads/``.
   These are legacy artefacts predating the object-storage migration;
   the boot migration converts them to object storage AND updates the
   DB records, but this endpoint keeps any still-un-migrated URL
   resolvable during the transition window.

Neither endpoint requires authentication — media URLs are keyed on
opaque storage paths / share tokens / public UUIDs generated at
upload time. The upload endpoints themselves gate authentication.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from config import logger
from services import object_storage as _obj

router = APIRouter(tags=["Objects"])

_UPLOAD_ROOT = "/app/backend/uploads"


def _guess_content_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif":  "image/gif",
        "svg":  "image/svg+xml",
        "mp4":  "video/mp4",
        "mov":  "video/quicktime",
        "webm": "video/webm",
        "m4v":  "video/x-m4v",
        "mp3":  "audio/mpeg",
        "wav":  "audio/wav",
        "ogg":  "audio/ogg",
        "pdf":  "application/pdf",
    }.get(ext, "application/octet-stream")


@router.get("/objects/{path:path}")
async def get_object_by_path(path: str):
    """Fetch bytes stored at ``path`` in Emergent Object Storage and
    stream them back with the stored content type.

    ``path`` is the RAW object-storage path — starts with the app
    namespace prefix (``poolcrm/...`` or ``poolscape-crm/...`` per the
    two coexisting adapters). The FastAPI ``{path:path}`` converter
    captures forward slashes so callers don't have to URL-encode
    them.
    """
    # Path safety — refuse traversal attempts. Object storage doesn't
    # care about ``..`` but we still reject to keep audit logs clean.
    if not path or ".." in path.split("/"):
        raise HTTPException(400, "bad path")

    try:
        data, ctype = _obj.get_object(path)
    except RuntimeError as e:
        # Object storage not initialised OR upstream 4xx/5xx.
        msg = str(e)
        if "not initialised" in msg.lower():
            raise HTTPException(503, "Object storage not initialised")
        # Try to distinguish 404 from other errors by peeking at the
        # message. ``object_storage.get_object`` embeds the upstream
        # HTTP code in the RuntimeError string.
        if "[404]" in msg:
            raise HTTPException(404, "not found")
        logger.warning(f"[objects] get_object failed for {path}: {msg}")
        raise HTTPException(502, "Storage read failed")

    # Cache aggressively for immutable content — the storage path
    # already carries a UUID or hash so any change gets a new URL.
    return Response(
        content=data,
        media_type=ctype or _guess_content_type(path),
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@router.get("/uploads/{path:path}")
async def serve_legacy_upload(path: str):
    """Backwards-compat: stream a pod-local file still living under
    ``/app/backend/uploads/{path}``.

    The boot migration converts these to object storage AND rewrites
    the DB URLs. This endpoint remains so any URL that hasn't been
    migrated (e.g. an in-flight request against a stale DB record)
    still resolves — provided the pod-local file survives.

    Returns 404 when the file is missing (which is the expected
    steady state after migration).
    """
    if not path or ".." in path.split("/"):
        raise HTTPException(400, "bad path")

    fp = Path(_UPLOAD_ROOT) / path
    # Ensure the resolved path stays within the upload root — defence
    # against symlink / dotdot escapes even after the split guard.
    try:
        real = fp.resolve(strict=False)
        root = Path(_UPLOAD_ROOT).resolve(strict=False)
        if root not in real.parents and real != root:
            raise HTTPException(400, "bad path")
    except (OSError, RuntimeError):
        raise HTTPException(400, "bad path")

    if not fp.exists() or not fp.is_file():
        raise HTTPException(404, "not found")

    return FileResponse(
        path=str(fp),
        media_type=_guess_content_type(str(fp)),
        headers={"Cache-Control": "public, max-age=3600"},
    )
