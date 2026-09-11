"""Feb-2026 · Photos-in-S3 Phase 2 · backfill migration endpoint.

Admin-only. Iterates job documents in the DB where any ``photos[]``
element still has ``data`` populated AND lacks ``s3_key``, and dual-
writes each photo to S3 while stamping the S3 key + mime on the doc.

Contract summary (see ``/app/memory/FEATURE_PHOTOS_S3_PHASE2.md``):

  * ``POST /api/admin/migrations/migrate-photos-to-s3``
  * Query params:
      - ``dry_run``      : bool, default **true**.
      - ``limit``        : int, default 500, max 2000.
      - ``tenant_id``    : Optional[str] — scope to one tenant.
      - ``purge_base64`` : bool, default **false**.
      - ``resume_after_job_id`` : Optional[str] — cursor for
        resumable batches (jobs are sorted by ``id`` ascending).
      - ``rate_limit_qps`` : int, default 10 — semaphore-bounded
        concurrency for S3 uploads.
  * Returns the ``MigrationReport`` envelope defined below.

Never crashes on individual photo failure — failures are collected
in ``failed[]`` and returned. Never touches ``s3_key`` unless the
S3 upload verified (via ``head_object`` after ``put_object``).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from utils import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


_ADMIN_ROLES = {"admin", "super_admin", "owner"}


@router.post(
    "/admin/migrations/migrate-photos-to-s3",
    operation_id="admin.s3.migrate_photos",
)
async def migrate_photos_to_s3(
    dry_run: bool = Query(True),
    limit: int = Query(500, ge=1, le=2000),
    tenant_id: Optional[str] = Query(None),
    purge_base64: bool = Query(False),
    resume_after_job_id: Optional[str] = Query(None),
    rate_limit_qps: int = Query(10, ge=1, le=64),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """Backfill legacy base64 photos into S3 (Phase 2)."""
    role = (user.get("role") or "").lower()
    if role not in _ADMIN_ROLES:
        raise HTTPException(403, "Admin only")

    # Phase 1 primitives — must resolve at request time so tests
    # can monkeypatch the module.
    from services.aws_s3 import photos as s3mod
    if not s3mod._is_configured(s3mod._cfg()) or s3mod._client() is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "s3_disabled",
                     "message": "PHOTOS_S3_ENABLED off or S3 client unavailable"},
        )

    from server import db  # lazy import — matches sibling admin routers.

    t0 = time.time()
    query: Dict[str, Any] = {
        # candidate = at least one photo with data but no s3_key.
        "photos": {"$elemMatch": {"data": {"$exists": True, "$ne": None},
                                     "s3_key": {"$in": [None, "", False]}}}
    }
    if tenant_id:
        query["tenant_id"] = tenant_id
    if resume_after_job_id:
        # ``id`` is a string UUID — lexicographic sort is stable.
        query["id"] = {"$gt": resume_after_job_id}

    # Pull only what we need — id, tenant_id, and the full photos
    # subarray (we need ``data`` to upload). No other job fields.
    projection: Dict[str, int] = {"_id": 0, "id": 1, "tenant_id": 1, "photos": 1}
    cursor = (
        db.jobs.find(query, projection).sort("id", 1).limit(limit)
    )
    docs: List[Dict[str, Any]] = await cursor.to_list(length=limit)

    uploaded: List[Dict[str, Any]] = []
    already: List[Dict[str, Any]] = []
    failed:   List[Dict[str, Any]] = []
    would_upload_bytes = 0
    candidate_count = 0

    # Semaphore-bounded concurrency for S3 calls. Not a strict QPS
    # governor but keeps us well within default boto3 pool limits.
    sem = asyncio.Semaphore(max(1, rate_limit_qps))

    async def _process_photo(
        job_id: str, tid: str, photo: Dict[str, Any],
    ) -> None:
        nonlocal would_upload_bytes
        pid = photo.get("id")
        data = photo.get("data")
        if not pid or not data:
            return  # Not a candidate — skip silently.
        # Path-safety on ids — build_key validates. If ids are
        # malformed we surface it in ``failed`` and skip.
        try:
            s3_key = s3mod.build_key(tid, job_id, pid)
        except ValueError as exc:
            failed.append({"job_id": job_id, "photo_id": pid,
                             "error": f"unsafe_id: {exc}"})
            return
        # Decode base64 to size the payload for dry-run tally.
        try:
            blob, mime = s3mod.decode_data_url(data)
        except Exception as exc:
            failed.append({"job_id": job_id, "photo_id": pid,
                             "error": f"decode: {exc}"})
            return
        # Fast idempotency short-circuit — if the object already
        # exists in S3, treat this as previously-migrated and just
        # stamp ``s3_key`` on the doc (unless dry_run).
        exists = False
        async with sem:
            exists = await asyncio.to_thread(s3mod.check_object_exists, s3_key)
        if exists:
            if not dry_run:
                try:
                    updates = {"photos.$[p].s3_key": s3_key,
                               "photos.$[p].s3_mime": mime}
                    if purge_base64:
                        pass  # unset handled below
                    op = {"$set": updates}
                    if purge_base64:
                        op["$unset"] = {"photos.$[p].data": ""}
                    await db.jobs.update_one(
                        {"id": job_id, "tenant_id": tid},
                        op,
                        array_filters=[{"p.id": pid}],
                    )
                except Exception as exc:
                    failed.append({"job_id": job_id, "photo_id": pid,
                                     "error": f"stamp_after_head: {exc}"})
                    return
            already.append({"job_id": job_id, "photo_id": pid,
                             "s3_key": s3_key})
            return

        would_upload_bytes += len(blob)
        if dry_run:
            uploaded.append({"job_id": job_id, "photo_id": pid,
                              "s3_key": s3_key, "bytes": len(blob),
                              "dry_run": True})
            return
        # Wet-run — upload, verify, stamp.
        async with sem:
            put_key = await asyncio.to_thread(
                s3mod.upload_photo, tid, job_id, pid, blob, mime,
            )
        if not put_key:
            failed.append({"job_id": job_id, "photo_id": pid,
                             "error": "upload_returned_none"})
            return
        # Verify via HEAD — the object must actually exist before
        # we stamp the doc. Guards against silent upload failures.
        async with sem:
            verified = await asyncio.to_thread(
                s3mod.check_object_exists, put_key,
            )
        if not verified:
            failed.append({"job_id": job_id, "photo_id": pid,
                             "error": "head_verify_failed"})
            return
        try:
            op: Dict[str, Any] = {
                "$set": {"photos.$[p].s3_key": put_key,
                          "photos.$[p].s3_mime": mime},
            }
            if purge_base64:
                op["$unset"] = {"photos.$[p].data": ""}
            await db.jobs.update_one(
                {"id": job_id, "tenant_id": tid},
                op,
                array_filters=[{"p.id": pid}],
            )
        except Exception as exc:
            # S3 write succeeded but Mongo stamp failed — flag it,
            # but do NOT roll back the S3 object (re-run will
            # short-circuit via ``check_object_exists``).
            failed.append({"job_id": job_id, "photo_id": pid,
                             "error": f"db_stamp: {exc}",
                             "s3_key_uploaded": put_key})
            return
        uploaded.append({"job_id": job_id, "photo_id": pid,
                          "s3_key": put_key, "bytes": len(blob)})

    for doc in docs:
        job_id = doc.get("id")
        tid = doc.get("tenant_id")
        photos = doc.get("photos") or []
        if not job_id or not tid or not isinstance(photos, list):
            continue
        # Only the sub-photos that are candidates (data + no s3_key).
        candidates = [
            p for p in photos
            if isinstance(p, dict)
            and p.get("data")
            and not p.get("s3_key")
        ]
        candidate_count += len(candidates)
        # Serial per-job (so array-filter updates don't race the
        # same doc); parallelism is bounded across jobs via ``sem``.
        for photo in candidates:
            await _process_photo(job_id, tid, photo)

    next_resume: Optional[str] = None
    if len(docs) >= limit and docs:
        next_resume = docs[-1].get("id")

    elapsed_ms = int((time.time() - t0) * 1000)
    return {
        "dry_run": dry_run,
        "purge_base64": purge_base64,
        "scope": {"tenant_id": tenant_id, "limit": limit},
        "scanned_jobs": len(docs),
        "candidate_photos": candidate_count,
        "would_upload_bytes": would_upload_bytes,
        "uploaded": uploaded,
        "already_migrated": already,
        "failed": failed,
        "next_resume_after_job_id": next_resume,
        "elapsed_ms": elapsed_ms,
    }
