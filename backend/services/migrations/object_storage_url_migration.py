"""Feb 2026 · Object-Storage URL migration.

Rewrites DB records that still carry pod-local ``/uploads/*`` URLs
OR bare ``/objects/*`` URLs (no ``/api/`` prefix, which don't route
through Kubernetes ingress) to the canonical ``/api/objects/{path}``
shape served by ``routers/objects.py``.

Contract:
  * Runs once per environment — guarded by a sentinel doc in
    ``db.migrations`` (``id: 'feb2026_object_storage_url_v1'``).
    Second-and-later boots become a fast no-op.
  * For any ``/uploads/{sub}/{filename}`` URL, checks if the file
    still exists at ``/app/backend/uploads/{sub}/{filename}``. If
    yes → uploads bytes to Emergent Object Storage under
    ``poolcrm/{tenant_id}/legacy_uploads/{sub}/{filename}`` and
    rewrites the DB URL to ``/api/objects/{storage_path}``. If the
    file is missing (already lost to a redeploy) → leaves the DB
    URL UNTOUCHED and increments the ``missing_files`` counter so
    ops can see the collateral.
  * For any bare ``/objects/{path}`` URL, rewrites it in-place to
    ``/api/objects/{path}`` (no bytes touched — the object is
    already in storage, only the URL was mis-prefixed).
  * Scans:
      - ``service_reports.photos[].url``
      - ``service_reports.videos[].url``
      - ``before_after_pairs.generated_card_url``
      - ``marketing_media.storage_url`` / ``cdn_url``
      - ``media_library.url`` / ``image_url``
      - ``customer_equipment_photos.photo_url``
    (Union of every collection our audit found holds media URLs.)
  * Emits a summary log at INFO with per-collection counts.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import db


logger = logging.getLogger("object_storage_url_migration")


_SENTINEL_ID = "feb2026_object_storage_url_v1"
_UPLOAD_ROOT = Path("/app/backend/uploads")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _guess_content_type(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {
        "png":  "image/png",
        "jpg":  "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif",
        "svg":  "image/svg+xml",
        "mp4":  "video/mp4", "mov": "video/quicktime",
        "webm": "video/webm", "m4v": "video/x-m4v",
    }.get(ext, "application/octet-stream")


def _rewrite_bare_objects_url(url: str) -> Optional[str]:
    """If the URL is a bare ``/objects/{path}`` (missing the ``/api``
    ingress prefix), return the rewritten ``/api/objects/{path}``.
    Returns None when the URL doesn't need this specific rewrite."""
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("/api/objects/"):
        return None
    if url.startswith("/objects/"):
        return "/api" + url
    return None


def _upload_local_file(tenant_id: str, upload_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Given a legacy ``/uploads/{sub}/{filename}`` URL, try to
    locate the file on pod-local disk, upload it to Emergent Object
    Storage, and return ``(new_url, error)``. On success, ``error``
    is ``None`` and ``new_url`` is the ``/api/objects/{path}``
    rewrite. On missing file, ``(None, "missing_file")``. On upload
    failure, ``(None, str(exc))``.
    """
    from services import object_storage as _obj

    # Extract the relative path from ``/uploads/{rest}``.
    prefix = "/uploads/"
    idx = upload_url.find(prefix)
    if idx == -1:
        return None, "not_uploads_url"
    rel = upload_url[idx + len(prefix):]
    if not rel or ".." in rel.split("/"):
        return None, "bad_relative_path"
    local_fp = _UPLOAD_ROOT / rel
    if not local_fp.exists() or not local_fp.is_file():
        return None, "missing_file"

    try:
        data = local_fp.read_bytes()
    except OSError as e:
        return None, f"read_failed:{e}"

    if not _obj.is_ready():
        try:
            _obj.init_storage()
        except Exception:  # noqa: BLE001
            pass
    if not _obj.is_ready():
        return None, "object_storage_not_ready"

    # Preserve the sub-path shape so ops can trace legacy assets.
    filename = local_fp.name
    entity_kind = "legacy_uploads"
    entity_id = rel.rsplit("/", 1)[0] or "root"
    # ``build_path`` sanitises the filename ext; we keep the full
    # basename verbatim so multiple legacy files under the same
    # entity_id don't clobber each other.
    storage_path = _obj.build_path(tenant_id or "unknown-tenant",
                                    entity_kind, entity_id, filename)

    try:
        _obj.put_object(storage_path, data,
                          _guess_content_type(filename))
    except Exception as e:  # noqa: BLE001
        return None, f"put_object_failed:{e}"

    return f"/api/objects/{storage_path}", None


async def _migrate_service_report_photos(counters: Dict[str, int]) -> None:
    """Scan and rewrite ``service_reports.photos[].url`` +
    ``.videos[].url``."""
    coll = db.service_reports
    async for rep in coll.find(
        {"$or": [
            {"photos.url": {"$regex": "/uploads/"}},
            {"photos.url": {"$regex": "^/objects/"}},
            {"videos.url": {"$regex": "/uploads/"}},
            {"videos.url": {"$regex": "^/objects/"}},
        ]},
        {"_id": 0, "id": 1, "tenant_id": 1, "photos": 1, "videos": 1},
    ):
        rid = rep.get("id")
        tid = rep.get("tenant_id")
        if not (rid and tid):
            continue

        touched = False
        for fld in ("photos", "videos"):
            rows = rep.get(fld) or []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = row.get("url")
                if not isinstance(url, str) or not url:
                    continue
                # Case 1: bare /objects/... → prefix rewrite only.
                rewritten = _rewrite_bare_objects_url(url)
                if rewritten:
                    row["url"] = rewritten
                    counters["objects_prefix_fixed"] += 1
                    touched = True
                    continue
                # Case 2: /uploads/... → try to upload local file.
                if "/uploads/" in url:
                    new_url, err = _upload_local_file(tid, url)
                    if new_url:
                        row["url"] = new_url
                        counters[f"migrated_service_report_{fld}"] += 1
                        touched = True
                    elif err == "missing_file":
                        counters["missing_files"] += 1
                    else:
                        counters["upload_errors"] += 1
                        logger.warning(
                            "[url_migration] service_report %s %s upload "
                            "failed: %s", rid, fld, err,
                        )

        if touched:
            await coll.update_one(
                {"id": rid, "tenant_id": tid},
                {"$set": {"photos": rep.get("photos") or [],
                          "videos": rep.get("videos") or []}},
            )


async def _migrate_simple_url_field(collection_name: str,
                                    field: str,
                                    counters: Dict[str, int],
                                    counter_key: str) -> None:
    """Generic single-field rewriter for collections whose media URL
    lives at a scalar top-level field (e.g. ``generated_card_url``,
    ``storage_url``, ``photo_url``)."""
    coll = db[collection_name]
    async for row in coll.find(
        {"$or": [
            {field: {"$regex": "/uploads/"}},
            {field: {"$regex": "^/objects/"}},
        ]},
        {"_id": 0, "id": 1, "tenant_id": 1, field: 1},
    ):
        rid = row.get("id")
        tid = row.get("tenant_id")
        url = row.get(field)
        if not (rid and isinstance(url, str) and url):
            continue

        rewritten = _rewrite_bare_objects_url(url)
        if rewritten:
            await coll.update_one({"id": rid}, {"$set": {field: rewritten}})
            counters["objects_prefix_fixed"] += 1
            continue

        if "/uploads/" in url:
            new_url, err = _upload_local_file(tid or "unknown-tenant", url)
            if new_url:
                await coll.update_one({"id": rid}, {"$set": {field: new_url}})
                counters[counter_key] += 1
            elif err == "missing_file":
                counters["missing_files"] += 1
            else:
                counters["upload_errors"] += 1
                logger.warning(
                    "[url_migration] %s.%s upload failed: %s",
                    collection_name, field, err,
                )


async def migrate_object_storage_urls() -> Dict[str, Any]:
    """Idempotent boot migration. Returns a summary dict."""
    sentinel = await db.migrations.find_one({"id": _SENTINEL_ID})
    if sentinel:
        return {
            "skipped": True, "reason": "already_ran",
            "ran_at": sentinel.get("ran_at"),
            "summary": sentinel.get("summary") or {},
        }

    counters: Dict[str, int] = {
        "objects_prefix_fixed": 0,
        "migrated_service_report_photos": 0,
        "migrated_service_report_videos": 0,
        "migrated_before_after": 0,
        "migrated_marketing_media": 0,
        "migrated_media_library": 0,
        "migrated_equipment_photos": 0,
        "missing_files": 0,
        "upload_errors": 0,
    }

    # 1. service_reports.photos + videos
    try:
        await _migrate_service_report_photos(counters)
    except Exception as e:  # noqa: BLE001
        logger.warning("[url_migration] service_reports scan failed: %s", e)

    # 2. before_after_pairs.generated_card_url
    try:
        await _migrate_simple_url_field(
            "before_after_pairs", "generated_card_url",
            counters, "migrated_before_after",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[url_migration] before_after scan failed: %s", e)

    # 3. marketing_media.storage_url + cdn_url
    for fld in ("storage_url", "cdn_url"):
        try:
            await _migrate_simple_url_field(
                "marketing_media", fld,
                counters, "migrated_marketing_media",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[url_migration] marketing_media.%s scan failed: %s", fld, e)

    # 4. media_library.url + image_url
    for fld in ("url", "image_url"):
        try:
            await _migrate_simple_url_field(
                "media_library", fld,
                counters, "migrated_media_library",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[url_migration] media_library.%s scan failed: %s", fld, e)

    # 5. customer_equipment_photos.photo_url + thumbnail_url
    for fld in ("photo_url", "thumbnail_url"):
        try:
            await _migrate_simple_url_field(
                "customer_equipment_photos", fld,
                counters, "migrated_equipment_photos",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[url_migration] equipment_photos.%s scan failed: %s", fld, e)

    # Stamp sentinel — makes this a no-op on subsequent boots.
    await db.migrations.insert_one({
        "id": _SENTINEL_ID,
        "ran_at": _now_iso(),
        "summary": counters,
    })

    logger.info(
        "[url_migration] object-storage URL rewrite complete: %s",
        counters,
    )
    return {"skipped": False, "summary": counters}
