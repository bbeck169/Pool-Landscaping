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

    Task L+P · Feb-2026 — SR-photo widening. When the caller
    pre-fetches service-report photo IDs (batched via
    ``$in`` on ``job_id`` — see
    ``routers/jobs.py::list_jobs`` and
    ``routers/customers.py::customer_detail_jobs``) and stamps
    them on each row as a private ``_sr_photo_ids`` scratch key,
    this helper UNIONs them into ``photo_ids[]`` (dedupe by id;
    SR wins on collision — matches
    ``routers/workstream_service_log._media_items`` merge
    semantics) and recomputes ``photo_count`` +
    ``photo_thumb_urls[]`` accordingly.  The scratch key is
    stripped before returning so it never crosses the wire.

    Rows without the scratch key behave exactly as pre-Task-L+P —
    ``photo_count``/``photo_ids``/``photo_thumb_urls`` populated
    from ``photos[]`` only.
    """
    out: List[Dict[str, Any]] = list(docs) if not isinstance(docs, list) else docs
    for d in out:
        plist = d.get("photos") or []
        if not isinstance(plist, list):
            plist = []
        # Base ids from ``jobs.photos``.
        base_ids: List[str] = [
            str(p.get("id")) for p in plist
            if isinstance(p, dict) and p.get("id") is not None
        ]
        # Task L+P — SR ids pre-stamped by the caller.  SR wins on
        # id collision: we prepend SR ids and skip duplicates from
        # base_ids.  Preserves insertion order (SR first, then
        # legacy) for consumers that iterate the list.
        sr_ids_raw = d.get("_sr_photo_ids") or []
        sr_ids: List[str] = [
            str(x) for x in sr_ids_raw
            if isinstance(x, (str, int)) and x is not None
        ]
        seen: set = set()
        merged_ids: List[str] = []
        for i in sr_ids + base_ids:
            if i in seen:
                continue
            seen.add(i)
            merged_ids.append(i)

        d["photo_count"] = len(merged_ids)
        d["photo_ids"] = merged_ids
        # Feb-2026 · Thumbnails ship — additive per-photo thumb URL
        # so list-view clients can lazy-load without knowing s3 keys.
        # The route resolves to a 302 signed URL (S3 path) OR an
        # embedded base64 blob (flag-off path) depending on the
        # write-time state of the doc.
        # Task L+P — the endpoint at ``/api/public/job-photo/{jid}/
        # {pid}/thumb`` also falls back to service_reports.photos
        # when a pid is missing from jobs.photos, so URLs generated
        # for SR ids resolve correctly.
        jid = d.get("id")
        d["photo_thumb_urls"] = [
            f"/api/public/job-photo/{jid}/{pid}/thumb"
            for pid in merged_ids
        ] if jid else []
        # Drop the scratch key so it never leaks into the wire
        # payload.  Safe on rows that never had it (``.pop`` no-op).
        d.pop("_sr_photo_ids", None)
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



# ─────────────────────────────────────────────────────────────────
# Task L+P · Feb-2026 — Batched SR-photo id enricher.
#
# Callers with a page of job docs (``list_jobs`` in
# ``routers/jobs.py``, ``customer_detail_jobs`` in
# ``routers/customers.py``) invoke this BEFORE ``slim_photos_on_rows``
# so a single ``$in`` query fetches every SR photo id for the whole
# page in one round-trip instead of the naive N+1 pattern (which
# would issue up to 5000 ``find_one`` calls per list load on the
# default ``limit`` cap).
#
# Wire pattern (canonical two-line adoption at each call site):
#   await enrich_docs_with_sr_photo_ids(db, docs, tenant_id)
#   slim_photos_on_rows(docs, include_photos=…)
#
# The enricher stamps a private ``_sr_photo_ids`` scratch key on
# each doc; ``slim_photos_on_rows`` reads it, unions into
# ``photo_ids[]`` / ``photo_thumb_urls[]``, and drops the scratch
# key before returning so it never crosses the wire.
# ─────────────────────────────────────────────────────────────────
async def enrich_docs_with_sr_photo_ids(
    db: Any, docs: Iterable[Dict[str, Any]], tenant_id: str,
) -> None:
    """Batched SR photo-id pre-fetch.  Mutates ``docs`` in place by
    stamping a private ``_sr_photo_ids: list[str]`` scratch key on
    every row (empty list when the job has no SR photos).

    * Single ``db.service_reports.find({...})`` per call — indexed
      on ``(tenant_id, job_id)`` which is the SR primary lookup
      pattern used everywhere else in the codebase.
    * Projection is minimal (``photos.id`` + ``photos.is_deleted``
      + ``deleted_at``) so the payload stays tiny even when a job
      has 10+ SR photos.
    * Filters both tombstone shapes: the SR doc's own
      ``deleted_at`` (SR-level soft delete) AND each photo's
      per-item ``is_deleted`` flag (photo-level soft delete).
    * ``job_ids`` empty → no-op, returns immediately (zero-row list
      loads never issue a round-trip).
    * Defensive batching: if a caller ever exceeds 5000 job ids in
      a single call, we split into chunks so the ``$in`` predicate
      never grows unbounded.  The default list-jobs cap is 5000
      today (see ``routers/jobs.py::list_jobs``), so this is a
      no-op guard in practice — kept as a code comment for future
      readers.
    """
    if not tenant_id:
        return
    job_ids: List[str] = [
        d.get("id") for d in docs
        if isinstance(d, dict) and d.get("id")
    ]
    if not job_ids:
        return

    # Chunk defensively at 5000 ids per query (matches the outer
    # list-jobs cap).  In practice this loop runs exactly once.
    _CHUNK = 5000
    sr_map: Dict[str, List[str]] = {}
    for start in range(0, len(job_ids), _CHUNK):
        chunk = job_ids[start:start + _CHUNK]
        cursor = db.service_reports.find(
            {
                "tenant_id": tenant_id,
                "job_id": {"$in": chunk},
                # Drop SR-level soft-deleted docs at query time.
                "deleted_at": {"$in": [None, ""]},
            },
            {
                "_id": 0, "job_id": 1,
                "photos.id": 1, "photos.is_deleted": 1,
            },
        )
        async for sr in cursor:
            jid = sr.get("job_id")
            if not jid:
                continue
            live_pids = [
                p.get("id") for p in (sr.get("photos") or [])
                if isinstance(p, dict)
                and p.get("id") is not None
                and not p.get("is_deleted")
            ]
            if not live_pids:
                continue
            sr_map.setdefault(jid, []).extend(live_pids)

    # Stamp scratch key on every doc — empty list when no SR
    # photos so ``slim_photos_on_rows`` doesn't have to double-
    # check for missing keys.
    for d in docs:
        if isinstance(d, dict) and d.get("id"):
            d["_sr_photo_ids"] = sr_map.get(d["id"], [])



async def enrich_docs_with_sr_photos(
    db: Any, docs: Iterable[Dict[str, Any]], tenant_id: str,
) -> None:
    """Batched SR **full-photo-subdoc** pre-fetch.  Sibling to
    :func:`enrich_docs_with_sr_photo_ids`; the wider variant is
    used by consumers that need per-photo metadata beyond just the
    id — e.g. ``routers/workstream.py::_media_summary`` which
    builds thumbnail entries with ``id`` + ``url`` + ``label`` +
    ``created_at`` per photo.

    Mutates ``docs`` in place by stamping a private
    ``_sr_photos: list[dict]`` scratch key on every row (empty
    list when the job has no SR photos).  Consumers strip the key
    themselves after use.

    Projection: ``{"_id": 0, "job_id": 1, "photos": 1, "deleted_at": 1}``
    — includes every SR photo subdoc field written by
    ``routers/service_report_media.py::upload_service_report_media``
    (``id``, ``storage_path``, ``url``, ``mime``, ``uploaded_at``,
    ``is_deleted``, etc.).  Per-photo ``data`` blob is normally
    absent in the Phase-27 write path so the payload stays small;
    legacy manually-seeded rows that do carry ``data`` pull it too
    but those are rare.

    Filters both tombstone shapes:
      * SR-doc ``deleted_at`` — dropped at query time via
        ``{"$in": [None, ""]}`` predicate.
      * Per-photo ``is_deleted`` — filtered client-side after
        fetch.

    Single Mongo round-trip per page (batched via ``$in`` on
    ``job_id``); same 5000-chunk defensive split as the id
    variant.  ``docs`` empty → no-op.
    """
    if not tenant_id:
        return
    job_ids: List[str] = [
        d.get("id") for d in docs
        if isinstance(d, dict) and d.get("id")
    ]
    if not job_ids:
        return

    _CHUNK = 5000
    sr_map: Dict[str, List[Dict[str, Any]]] = {}
    for start in range(0, len(job_ids), _CHUNK):
        chunk = job_ids[start:start + _CHUNK]
        cursor = db.service_reports.find(
            {
                "tenant_id": tenant_id,
                "job_id": {"$in": chunk},
                "deleted_at": {"$in": [None, ""]},
            },
            {"_id": 0, "job_id": 1, "photos": 1, "deleted_at": 1},
        )
        async for sr in cursor:
            jid = sr.get("job_id")
            if not jid:
                continue
            live_photos = [
                p for p in (sr.get("photos") or [])
                if isinstance(p, dict)
                and p.get("id") is not None
                and not p.get("is_deleted")
            ]
            if not live_photos:
                continue
            sr_map.setdefault(jid, []).extend(live_photos)

    for d in docs:
        if isinstance(d, dict) and d.get("id"):
            d["_sr_photos"] = sr_map.get(d["id"], [])
