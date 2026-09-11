"""Feb-2026 · Shared slim-photos row decorator.

Moved out of ``routers/jobs.py`` in the Feb-2026 slim-photos follow-up
so ``routers/customers.py`` (customer-detail embedded-jobs list) and
any future consumer can apply the same shape without duplicating the
loop.

Contract (matches ``routers/jobs.py`` list ship, Feb-2026):

  * ``photo_count`` — int, ``len(photos)`` (0 when the doc has no
    ``photos`` field or it's non-list).
  * ``photo_ids``  — list[str], stable per-photo ``id`` strings for
    lazy-loading via the existing per-photo GET.
  * Full ``photos`` array is dropped by default. Callers pass
    ``include_photos=True`` to restore the pre-slim shape (superset:
    ``photo_count`` + ``photo_ids`` are ALWAYS emitted regardless).

Legacy rows where the underlying Mongo doc has no ``photos`` key
are normalized to ``photo_count=0`` + ``photo_ids=[]`` so the
response shape is uniform across every row.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


# ─────────────────────────────────────────────────────────────────
# Feb-2026 · PERF-MONGO-PROJECT-EXCLUDE-PHOTOS-ON-JOBS-READS ship.
#
# Every ``db.jobs.find(...)`` / ``db.jobs.find_one(...)`` /
# ``db.jobs.aggregate(...)`` in the backend that pulls the WHOLE
# job doc should use this projection to keep the base64 photo
# blobs off the Mongo→process wire. The blob lives at
# ``photos[].data`` (schema-confirmed at ``routers/jobs.py:3674-3676``
# and ``routers/maintenance.py:345`` — every photo attach path
# writes ``{"id", "data", "label", "created_at", ["client_uuid"]}``).
#
# Mongo dot-notation on an array of subdocuments drops the
# ``data`` subfield from EVERY element while preserving the rest —
# so ``photo_count`` and ``photo_ids`` still populate correctly
# via the shared row decorator below.
#
# Three call sites explicitly OPT OUT of this projection and keep
# emitting the full ``photos.data`` on the wire:
#   1. ``GET /api/jobs/{jid}``      — single-job detail contract.
#   2. ``POST /api/jobs/{jid}/photos``   — photo-upload response,
#      renders the freshly-updated strip client-side.
#   3. ``DELETE /api/jobs/{jid}/photos/{pid}`` — photo-delete
#      response, same rationale.
# Plus the ``?include_photos=true`` opt-in on the list endpoint
# (conditional in-place).
# Plus the public-token photo endpoint at ``GET /public/job-photo/
# {jid}/{pid}`` which uses inclusion projection ``{"photos": 1}``
# and legitimately reads ``photo["data"]``.
#
# Every other read applies the constant below.
# ─────────────────────────────────────────────────────────────────
JOBS_LIST_PROJECTION: Dict[str, int] = {"_id": 0, "photos.data": 0}
JOBS_LIST_PROJECT_STAGE: Dict[str, int] = {"_id": 0, "photos.data": 0}
JOBS_PHOTOS_ONLY_EXCLUDE: Dict[str, int] = {"photos.data": 0}


def jobs_projection(*, include_photos: bool = False) -> Dict[str, int]:
    """Convenience — return the correct projection for an
    ``include_photos``-aware endpoint. Callers with no opt-in
    surface should just reference ``JOBS_LIST_PROJECTION`` directly.
    """
    if include_photos:
        # Preserve the pre-sweep wire contract for the opt-in
        # branch — full ``photos`` including ``data`` still flow.
        return {"_id": 0}
    return dict(JOBS_LIST_PROJECTION)


def slim_photos_on_rows(docs: Iterable[Dict[str, Any]],
                          include_photos: bool = False) -> List[Dict[str, Any]]:
    """Mutate + return ``docs`` in place with the slim-photos shape.
    Safe to call multiple times (idempotent). Returns the same list
    for chained-call ergonomics.
    """
    out: List[Dict[str, Any]] = list(docs) if not isinstance(docs, list) else docs
    for d in out:
        plist = d.get("photos") or []
        if not isinstance(plist, list):
            plist = []
        d["photo_count"] = len(plist)
        d["photo_ids"] = [
            str(p.get("id")) for p in plist
            if isinstance(p, dict) and p.get("id") is not None
        ]
        # Feb-2026 · Thumbnails ship — additive per-photo thumb URL
        # so list-view clients can lazy-load without knowing s3 keys.
        # The route resolves to a 302 signed URL (S3 path) OR an
        # embedded base64 blob (flag-off path) depending on the
        # write-time state of the doc.
        jid = d.get("id")
        d["photo_thumb_urls"] = [
            f"/api/public/job-photo/{jid}/{p['id']}/thumb"
            for p in plist
            if isinstance(p, dict) and p.get("id") is not None
        ] if jid else []
        if include_photos:
            # Superset — keep the full ``photos`` array. Coerce
            # missing/null to ``[]`` so every row carries the key.
            # Feb-2026 · Photos-in-S3 Phase 1 — strip S3 metadata
            # (``s3_key`` / ``s3_mime``) so the storage backend
            # never leaks over the wire. Callers use the public
            # photo URL to fetch, not the raw key.
            # Feb-2026 · Thumbnails ship — also strip the derivative
            # storage keys and the embedded base64 derivative blobs
            # (``thumb`` / ``preview``) — clients use the public
            # ``/thumb`` and ``/preview`` routes to render.
            _stripped_fields = {
                "s3_key", "s3_mime",
                "s3_thumb_key", "s3_preview_key",
                "thumb", "preview",
            }
            d["photos"] = [
                {k: v for k, v in (p.items() if isinstance(p, dict) else [])
                 if k not in _stripped_fields}
                for p in plist
            ]
        else:
            d.pop("photos", None)
    return out


def strip_s3_metadata_from_photos(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Remove S3 metadata + derivative blobs from a single job doc
    that will be shipped over the wire. Used by endpoints that
    return the full doc (photo upload / detail) without going
    through ``slim_photos_on_rows``.

    Feb-2026 · Photos-in-S3 Phase 1 — the S3 key is a storage-
    backend implementation detail; the public read endpoint proxies
    via a presigned URL, so clients never need the key itself.
    Feb-2026 · Thumbnails ship — same rule applies to
    ``s3_thumb_key`` / ``s3_preview_key`` and the embedded base64
    derivative blobs (``thumb`` / ``preview``).

    Mutates + returns ``doc`` for ergonomic chaining. ``None`` in →
    ``None`` out.
    """
    if not doc:
        return doc
    plist = doc.get("photos")
    if isinstance(plist, list):
        _stripped_fields = {
            "s3_key", "s3_mime",
            "s3_thumb_key", "s3_preview_key",
            "thumb", "preview",
        }
        doc["photos"] = [
            {k: v for k, v in (p.items() if isinstance(p, dict) else [])
             if k not in _stripped_fields}
            for p in plist
        ]
    return doc
