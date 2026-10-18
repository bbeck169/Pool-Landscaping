"""TD-76a · Feb-2026 — URL emission contract for the service-report
photos branch of ``services/customer_media.get_customer_media``.

Pre-TD-76a the SR branch emitted
``/api/public/service/<public_uuid>/photo/<pid>`` which routes to
``routers/service_report_media.stream_public_service_photo`` — a
handler with NO fallback cascade that hard-404s on any subdoc missing
``storage_path``.  Operator's prod symptom: only the newest 2-3
thumbnails loaded on ``/portal/photos``; everything older rendered
as a broken ``<img>``.

Post-TD-76a the SR branch routes to
``/api/public/job-photo/<job_id>/<pid>`` which hits
``routers/jobs.public_job_photo`` — a handler with the full
``s3_key → base64 → SR-fallback`` cascade (Task L+P).  Legacy /
mirrored / Phase-27-upload photos all resolve through one resilient
path.

Fallback ladder preserved:
  * If ``r.job_id`` is set → emit job-photo URL (99%+ case).
  * Else if ``r.public_uuid`` is set → emit SR share-link URL
    (preserves genuine share-link flow — only used when the SR row
    somehow lacks a ``job_id``).
  * Else emit ``p.url`` or empty string (defensive).
"""
from __future__ import annotations

import pytest

from services.customer_media import get_customer_media


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


# ───────────────────────────────────────────────────────────────────
# Minimal in-memory async stub mirroring the Motor API surface used
# by ``get_customer_media``.
# ───────────────────────────────────────────────────────────────────
class _AsyncCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, _filter=None, _proj=None):
        return _AsyncCursor(self._docs)


class _DB:
    def __init__(self, *, jobs, estimates, service_reports, files=()):
        self.jobs = _Coll(jobs)
        self.estimates = _Coll(estimates)
        self.service_reports = _Coll(service_reports)
        self.files = _Coll(files)


def _job(jid, *, hidden=False):
    return {
        "id": jid, "tenant_id": "t1", "customer_id": "c1",
        "title": f"Visit {jid}",
        "service_type": "pool_service",
        "hidden_from_portal": hidden,
        "is_deleted": False,
        "photos": [], "videos": [],
    }


def _sr_photo(pid, *, uploaded_at="2026-02-01T10:00:00Z",
                storage_path="", caption=""):
    row = {
        "id": pid, "mime": "image/jpeg",
        "uploaded_at": uploaded_at, "caption": caption,
    }
    if storage_path:
        row["storage_path"] = storage_path
    return row


def _sr(jid, *, public_uuid="", photos=()):
    return {
        "id": f"sr-{jid}", "tenant_id": "t1", "job_id": jid,
        "public_uuid": public_uuid, "photos": list(photos),
        "videos": [], "hidden_from_portal": False,
        "submitted_at": "2026-02-01T10:00:00Z",
    }


# ───────────────────────────────────────────────────────────────────
# 1. Primary contract — SR photos emit the ``/api/public/job-photo/``
#    URL shape when ``job_id`` is set, regardless of
#    ``storage_path`` or ``public_uuid`` presence.
# ───────────────────────────────────────────────────────────────────
@pytest.mark.anyio
async def test_sr_photo_with_job_id_emits_job_photo_url_shape():
    db = _DB(
        jobs=[_job("j1")],
        estimates=[],
        service_reports=[_sr(
            "j1", public_uuid="pub-xyz",
            photos=[_sr_photo("p1", storage_path="t1/sr/x/f.jpg")],
        )],
    )
    bag = await get_customer_media(db, "t1", "c1", kind="photo")
    assert bag["total"] == 1
    item = bag["items"][0]
    assert item["source"] == "service_report"
    # TD-76a: route via jobs.py cascade, NOT service_report_media.py.
    assert item["url"] == "/api/public/job-photo/j1/p1"


@pytest.mark.anyio
async def test_sr_photo_without_storage_path_still_emits_job_photo_url():
    """The pre-TD-76a bug: storage_path missing → public SR handler
    returned 404 Storage path missing. Post-TD-76a the URL routes to
    the robust job-photo handler which has an S3+base64+SR fallback
    cascade, so the browser gets working bytes."""
    db = _DB(
        jobs=[_job("j1")],
        estimates=[],
        service_reports=[_sr(
            "j1", public_uuid="pub-xyz",
            photos=[_sr_photo("p1")],  # NO storage_path
        )],
    )
    bag = await get_customer_media(db, "t1", "c1", kind="photo")
    assert bag["items"][0]["url"] == "/api/public/job-photo/j1/p1"


@pytest.mark.anyio
async def test_sr_photo_no_public_uuid_uses_job_photo_url_when_job_id_set():
    """Pre-TD-76a: no public_uuid → fell back to raw p.get('url')
    which was often empty → broken <img>. Post-TD-76a: job_id wins
    first, public_uuid is only consulted when job_id is absent."""
    db = _DB(
        jobs=[_job("j1")],
        estimates=[],
        service_reports=[_sr(
            "j1", public_uuid="",  # no public_uuid
            photos=[_sr_photo("p1")],
        )],
    )
    bag = await get_customer_media(db, "t1", "c1", kind="photo")
    assert bag["items"][0]["url"] == "/api/public/job-photo/j1/p1"


# ───────────────────────────────────────────────────────────────────
# 2. Fallback ladder — only when ``job_id`` is absent on the SR row
#    do we fall back to the public_uuid share-link URL.  This is a
#    defensive branch for a shape that effectively never occurs in
#    prod (all SRs carry a ``job_id``) but is pinned for parity with
#    the pre-TD-76a public-link flow.
# ───────────────────────────────────────────────────────────────────
@pytest.mark.anyio
async def test_sr_photo_with_only_public_uuid_falls_back_to_share_link():
    sr = _sr("", public_uuid="pub-xyz",
                photos=[_sr_photo("p1", storage_path="t1/sr/x/f.jpg")])
    sr["job_id"] = ""  # force absence
    db = _DB(jobs=[_job("j1")], estimates=[], service_reports=[sr])
    bag = await get_customer_media(db, "t1", "c1", kind="photo")
    # Zero job_id + non-empty public_uuid → share-link shape.
    assert bag["items"][0]["url"] == "/api/public/service/pub-xyz/photo/p1"


@pytest.mark.anyio
async def test_sr_photo_without_job_id_or_public_uuid_falls_back_to_raw_url():
    sr = _sr("", public_uuid="",
                photos=[_sr_photo("p1")])
    sr["job_id"] = ""
    # Attach a raw stored url so the final defensive branch is
    # observable.
    sr["photos"][0]["url"] = "https://cdn.example/x.jpg"
    db = _DB(jobs=[_job("j1")], estimates=[], service_reports=[sr])
    bag = await get_customer_media(db, "t1", "c1", kind="photo")
    assert bag["items"][0]["url"] == "https://cdn.example/x.jpg"


# ───────────────────────────────────────────────────────────────────
# 3. Regression locks — adjacent branches untouched by TD-76a.
# ───────────────────────────────────────────────────────────────────
@pytest.mark.anyio
async def test_jobs_photos_branch_still_passes_raw_url_through():
    """jobs.photos[] branch is NOT part of the TD-76a swap. Its raw
    passthrough shape stays as-is pending a future TD-76b/c cycle."""
    j = _job("j1")
    j["photos"] = [{
        "id": "p1", "mime": "image/jpeg", "url": "https://cdn/x.jpg",
        "visibility": "customer", "uploaded_at": "2026-02-01T10:00:00Z",
    }]
    db = _DB(jobs=[j], estimates=[], service_reports=[])
    bag = await get_customer_media(db, "t1", "c1", kind="photo")
    assert bag["items"][0]["url"] == "https://cdn/x.jpg"


@pytest.mark.anyio
async def test_sr_videos_branch_unchanged_still_uses_public_service_uuid():
    """TD-76a scope is PHOTOS ONLY. The videos branch keeps its
    pre-TD-76a share-link shape — operator-reported symptom is on
    photos, and videos have their own content-type cascade that
    was out of scope for this swap."""
    sr = _sr("j1", public_uuid="pub-xyz")
    sr["videos"] = [{
        "id": "v1", "mime": "video/mp4",
        "uploaded_at": "2026-02-01T10:00:00Z",
    }]
    db = _DB(jobs=[_job("j1")], estimates=[], service_reports=[sr])
    bag = await get_customer_media(db, "t1", "c1", kind="video")
    assert bag["items"][0]["url"] == "/api/public/service/pub-xyz/video/v1"


@pytest.mark.anyio
async def test_multiple_srs_each_resolve_against_their_own_job_id():
    """Three SRs across two jobs — URL emission must bind each photo
    to its OWN ``r.job_id``, not leak across rows."""
    db = _DB(
        jobs=[_job("j1"), _job("j2")],
        estimates=[],
        service_reports=[
            _sr("j1", photos=[_sr_photo("p1a"), _sr_photo("p1b")]),
            _sr("j2", photos=[_sr_photo("p2")]),
        ],
    )
    bag = await get_customer_media(db, "t1", "c1", kind="photo")
    urls = sorted(i["url"] for i in bag["items"])
    assert urls == [
        "/api/public/job-photo/j1/p1a",
        "/api/public/job-photo/j1/p1b",
        "/api/public/job-photo/j2/p2",
    ]
