"""Task L+P · Commit 4 — Workstream ``_media_summary`` SR merge.

Locks the merge contract for
``backend/routers/workstream.py::_media_summary`` and the sibling
batched enricher ``enrich_docs_with_sr_photos``:

  * ``_media_summary`` merges ``_sr_photos`` scratch key +
    ``job.photos[]`` into a single pool.
  * Dedupe by id; SR wins on collision.
  * Sort DESC by ``created_at`` / ``uploaded_at``; entries without
    a timestamp fall back to insertion order (SR first, jobs
    second) — mirrors ``_media_items`` Commit-1 semantics.
  * Return shape UNCHANGED (photos_count / videos_count /
    photo_thumbs / video_thumbs / extra_count) — no new fields.
  * SR photos surface their stored ``url`` verbatim when present
    (Phase-27 upload path); legacy jobs.photos entries emit the
    ``/api/public/job-photo/{jid}/{pid}`` shape which the Commit-3
    endpoint extension resolves against SR photos too.
  * ``enrich_docs_with_sr_photos``: single ``$in`` find per page,
    stamps ``_sr_photos`` scratch key on each doc, filters both
    tombstone shapes (SR-doc ``deleted_at`` at query time,
    per-photo ``is_deleted`` client-side).
  * Rows without ``_sr_photos`` scratch key behave EXACTLY as
    pre-Task-L+P (backward compat guard).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import MagicMock


# ─── _media_summary pure-Python tests ─────────────────────────────────
def test_media_summary_merges_job_and_sr_photos():
    """2 jobs.photos + 1 SR photo → photos_count=3, thumbs includes
    all 3 with SR entry's stored ``url``."""
    from routers.workstream import _media_summary
    job = {
        "id": "job-1",
        "photos": [
            {"id": "jp-1", "created_at": "2026-02-01T09:00:00Z"},
            {"id": "jp-2", "created_at": "2026-02-01T08:00:00Z"},
        ],
        "videos": [],
        "_sr_photos": [
            {"id": "sr-1", "url": "/api/public/service/u/photo/sr-1",
             "uploaded_at": "2026-02-01T10:00:00Z"},
        ],
    }
    out = _media_summary(job)
    assert out["photos_count"] == 3
    assert out["videos_count"] == 0
    ids = [t["id"] for t in out["photo_thumbs"]]
    assert ids == ["sr-1", "jp-1", "jp-2"]  # timestamp desc
    # SR photo's stored URL is used verbatim.
    sr_entry = next(t for t in out["photo_thumbs"] if t["id"] == "sr-1")
    assert sr_entry["url"] == "/api/public/service/u/photo/sr-1"
    # Legacy jobs.photos entries use the /api/public/job-photo URL shape.
    jp_entry = next(t for t in out["photo_thumbs"] if t["id"] == "jp-1")
    assert jp_entry["url"] == "/api/public/job-photo/job-1/jp-1"


def test_media_summary_dedupes_by_id_sr_wins():
    """Same id in both sources → single entry, SR-source URL
    preferred."""
    from routers.workstream import _media_summary
    job = {
        "id": "job-2",
        "photos": [{"id": "shared", "created_at": "2026-02-01T09:00:00Z"}],
        "_sr_photos": [
            {"id": "shared", "url": "/api/public/service/u/photo/shared",
             "uploaded_at": "2026-02-01T10:00:00Z"},
        ],
    }
    out = _media_summary(job)
    assert out["photos_count"] == 1
    assert len(out["photo_thumbs"]) == 1
    assert out["photo_thumbs"][0]["id"] == "shared"
    assert out["photo_thumbs"][0]["url"] == "/api/public/service/u/photo/shared"


def test_media_summary_backward_compat_no_sr_photos_key():
    """Rows without ``_sr_photos`` behave exactly as pre-Task-L+P:
    photos_count from jobs.photos alone; thumb URLs use the
    ``/api/public/job-photo/{jid}/{pid}`` shape."""
    from routers.workstream import _media_summary
    job = {
        "id": "job-3",
        "photos": [
            {"id": "jp-a"}, {"id": "jp-b"}, {"id": "jp-c"},
        ],
        "videos": [],
    }
    out = _media_summary(job)
    assert out["photos_count"] == 3
    ids = [t["id"] for t in out["photo_thumbs"]]
    assert set(ids) == {"jp-a", "jp-b", "jp-c"}
    for t in out["photo_thumbs"]:
        assert t["url"].startswith("/api/public/job-photo/job-3/")
        assert not t["url"].endswith("/thumb")  # backend emits full-size


def test_media_summary_return_shape_locked():
    """Response shape must NOT gain new top-level fields
    (backward-compat guard for downstream consumers)."""
    from routers.workstream import _media_summary
    out = _media_summary({"id": "job-x", "photos": []})
    assert set(out.keys()) == {
        "photos_count", "videos_count",
        "photo_thumbs", "video_thumbs", "extra_count",
    }


def test_media_summary_caps_thumb_list_at_max_photos():
    """``max_photos=4`` default — 6 photos → 4 thumbs + extra_count=2."""
    from routers.workstream import _media_summary
    job = {
        "id": "job-cap",
        "photos": [{"id": f"jp-{i}"} for i in range(6)],
    }
    out = _media_summary(job)
    assert out["photos_count"] == 6
    assert len(out["photo_thumbs"]) == 4
    assert out["extra_count"] == 2


def test_media_summary_overflow_counts_include_sr_photos():
    """extra_count reflects the merged pool size, not just
    jobs.photos length — so a job with 3 jobs.photos + 5 SR photos
    (8 total, 4 shown) reports extra_count=4."""
    from routers.workstream import _media_summary
    job = {
        "id": "job-overflow",
        "photos": [{"id": f"jp-{i}"} for i in range(3)],
        "_sr_photos": [
            {"id": f"sr-{i}", "url": f"/x/{i}"} for i in range(5)
        ],
    }
    out = _media_summary(job)
    assert out["photos_count"] == 8
    assert len(out["photo_thumbs"]) == 4
    assert out["extra_count"] == 4


def test_media_summary_insertion_order_fallback_when_no_ts():
    """Entries without a timestamp preserve their natural insertion
    order — SR first (rung 1), then jobs (rung 2)."""
    from routers.workstream import _media_summary
    job = {
        "id": "job-ins",
        "photos": [{"id": "jp-a"}, {"id": "jp-b"}],
        "_sr_photos": [
            {"id": "sr-1", "url": "/x/sr-1"},
            {"id": "sr-2", "url": "/x/sr-2"},
        ],
    }
    out = _media_summary(job)
    ids = [t["id"] for t in out["photo_thumbs"]]
    assert ids == ["sr-1", "sr-2", "jp-a", "jp-b"]


# ─── enrich_docs_with_sr_photos batched-fetch tests ──────────────────
class _AsyncCursor:
    def __init__(self, items: List[Dict[str, Any]]):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def test_enrich_sr_photos_issues_exactly_one_find_call():
    """N-doc page → 1 ``db.service_reports.find`` call."""
    from services.jobs_slim_photos import enrich_docs_with_sr_photos
    docs = [{"id": f"j-{i}"} for i in range(30)]
    tenant_id = "t-1"
    mock_srs = [
        {"job_id": "j-5", "photos": [{"id": "sr-p1"}]},
        {"job_id": "j-9", "photos": [{"id": "sr-p2"}, {"id": "sr-p3"}]},
    ]
    find_calls = []
    def _fake_find(query, projection):
        find_calls.append((query, projection))
        return _AsyncCursor(mock_srs)
    mock_db = MagicMock()
    mock_db.service_reports.find = _fake_find

    async def _go():
        await enrich_docs_with_sr_photos(mock_db, docs, tenant_id)
    asyncio.new_event_loop().run_until_complete(_go())

    assert len(find_calls) == 1
    q, proj = find_calls[0]
    assert q["tenant_id"] == tenant_id
    assert set(q["job_id"]["$in"]) == {f"j-{i}" for i in range(30)}
    assert q["deleted_at"] == {"$in": [None, ""]}
    assert proj == {
        "_id": 0, "job_id": 1, "photos": 1, "deleted_at": 1,
    }
    assert next(d for d in docs if d["id"] == "j-5")["_sr_photos"] == [
        {"id": "sr-p1"},
    ]
    assert next(d for d in docs if d["id"] == "j-9")["_sr_photos"] == [
        {"id": "sr-p2"}, {"id": "sr-p3"},
    ]
    assert next(d for d in docs if d["id"] == "j-0")["_sr_photos"] == []


def test_enrich_sr_photos_empty_docs_no_find_call():
    from services.jobs_slim_photos import enrich_docs_with_sr_photos
    find_calls = []
    def _fake_find(q, p):
        find_calls.append((q, p))
        return _AsyncCursor([])
    mock_db = MagicMock()
    mock_db.service_reports.find = _fake_find
    async def _go():
        await enrich_docs_with_sr_photos(mock_db, [], "t")
    asyncio.new_event_loop().run_until_complete(_go())
    assert find_calls == []


def test_enrich_sr_photos_filters_per_photo_is_deleted():
    """A SR doc with mixed live/dead photos → only live entries
    surface on ``_sr_photos``."""
    from services.jobs_slim_photos import enrich_docs_with_sr_photos
    docs = [{"id": "j-1"}]
    mock_srs = [
        {"job_id": "j-1", "photos": [
            {"id": "live-1", "is_deleted": False},
            {"id": "dead-1", "is_deleted": True},
            {"id": "live-2", "is_deleted": False},
        ]},
    ]
    def _fake_find(q, p):
        return _AsyncCursor(mock_srs)
    mock_db = MagicMock()
    mock_db.service_reports.find = _fake_find
    async def _go():
        await enrich_docs_with_sr_photos(mock_db, docs, "t")
    asyncio.new_event_loop().run_until_complete(_go())
    ids = [p["id"] for p in docs[0]["_sr_photos"]]
    assert ids == ["live-1", "live-2"]


def test_enrich_sr_photos_end_to_end_with_media_summary():
    """Full loop — enrich stamps ``_sr_photos``; ``_media_summary``
    merges into the summary shape.  Mirrors the live endpoint's
    two-call pattern (enricher → summary)."""
    from services.jobs_slim_photos import enrich_docs_with_sr_photos
    from routers.workstream import _media_summary
    docs = [{
        "id": "job-live",
        "photos": [
            {"id": "jp-1", "created_at": "2026-02-01T09:00:00Z"},
        ],
    }]
    mock_srs = [
        {"job_id": "job-live", "photos": [
            {"id": "sr-1", "url": "/x/sr-1", "is_deleted": False,
             "uploaded_at": "2026-02-01T11:00:00Z"},
        ]},
    ]
    def _fake_find(q, p):
        return _AsyncCursor(mock_srs)
    mock_db = MagicMock()
    mock_db.service_reports.find = _fake_find

    async def _go():
        await enrich_docs_with_sr_photos(mock_db, docs, "t")
    asyncio.new_event_loop().run_until_complete(_go())

    summary = _media_summary(docs[0])
    assert summary["photos_count"] == 2
    ids = [t["id"] for t in summary["photo_thumbs"]]
    assert ids == ["sr-1", "jp-1"]  # SR newer, comes first


def test_enrich_sr_photos_scratch_key_doesnt_leak_into_row_emit():
    """Sanity — the workstream endpoint's row-emit dict is
    hand-built; it does not spread the source doc, so
    ``_sr_photos`` scratch key stays on the source docs list and
    never reaches the wire.  This test asserts that the row keys
    documented in the endpoint spec do NOT include ``_sr_photos``.
    """
    from routers.workstream import _media_summary
    # Simulated row-emit shape (subset — the actual endpoint emits
    # more fields; the point is to prove ``_media_summary``'s
    # output doesn't leak the scratch key).
    summary = _media_summary({"id": "j", "photos": [], "_sr_photos": [
        {"id": "sr-x"},
    ]})
    # The summary dict only carries the shape-locked keys.
    assert "_sr_photos" not in summary
