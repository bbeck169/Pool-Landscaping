"""JOB-PHOTOS-FIX · Feb-2026 — regression guard for
``inject_photo_url_on_doc`` in ``services/jobs_slim_photos.py``.

Context: ``GET /api/jobs/{jid}`` + ``POST /api/jobs/{jid}/photos``
now stamp each ``photos[]`` element with a resolved ``url`` so the
FE grid at ``JobDetail.jsx`` renders ``<img src={p.url}>`` instead
of coercing the raw dict to ``[object Object]``.  Contract tested
here is URL shape, idempotency, and defensive branches (missing
id, non-dict rows, missing doc / jid).

These are pure in-memory tests of the helper — no DB, no FastAPI
TestClient, no network.  Keeps the test fast and fully isolated
from the rest of the suite.
"""
from __future__ import annotations

from services.jobs_slim_photos import inject_photo_url_on_doc


def test_url_populated_on_every_photo_with_an_id():
    doc = {
        "id": "job-1",
        "photos": [
            {"id": "p1", "data": "data:image/jpeg;base64,AAAA", "label": "a"},
            {"id": "p2", "data": "data:image/png;base64,BBBB",  "label": "b"},
        ],
    }
    inject_photo_url_on_doc(doc, jid="job-1")
    assert doc["photos"][0]["url"] == "/api/public/job-photo/job-1/p1"
    assert doc["photos"][1]["url"] == "/api/public/job-photo/job-1/p2"
    # The ``data`` fallback is preserved alongside the new ``url``.
    assert doc["photos"][0]["data"] == "data:image/jpeg;base64,AAAA"
    assert doc["photos"][1]["data"] == "data:image/png;base64,BBBB"


def test_idempotent_does_not_override_existing_url():
    pre_set = "/custom/url/for/p1"
    doc = {
        "id": "job-1",
        "photos": [
            {"id": "p1", "data": "...", "url": pre_set},
            {"id": "p2", "data": "..."},
        ],
    }
    inject_photo_url_on_doc(doc, jid="job-1")
    assert doc["photos"][0]["url"] == pre_set, \
        "pre-existing url MUST be preserved (idempotent)"
    assert doc["photos"][1]["url"] == "/api/public/job-photo/job-1/p2"


def test_photo_without_id_is_skipped():
    doc = {
        "id": "job-1",
        "photos": [
            {"data": "..."},            # no id
            {"id": "", "data": "..."},  # empty id
            {"id": "p3", "data": "..."},
        ],
    }
    inject_photo_url_on_doc(doc, jid="job-1")
    assert "url" not in doc["photos"][0]
    assert "url" not in doc["photos"][1]
    assert doc["photos"][2]["url"] == "/api/public/job-photo/job-1/p3"


def test_non_dict_photo_entries_are_ignored():
    doc = {"id": "job-1", "photos": ["not a dict", 42, None]}
    # Must not raise; helper is defensive against legacy shape.
    inject_photo_url_on_doc(doc, jid="job-1")
    assert doc["photos"] == ["not a dict", 42, None]


def test_none_doc_is_noop():
    assert inject_photo_url_on_doc(None, jid="job-1") is None


def test_missing_jid_is_noop():
    doc = {"id": "job-1", "photos": [{"id": "p1"}]}
    inject_photo_url_on_doc(doc, jid=None)
    assert "url" not in doc["photos"][0]
    inject_photo_url_on_doc(doc, jid="")
    assert "url" not in doc["photos"][0]


def test_doc_without_photos_is_noop():
    doc = {"id": "job-1"}
    inject_photo_url_on_doc(doc, jid="job-1")
    assert "photos" not in doc


def test_photos_non_list_is_noop():
    doc = {"id": "job-1", "photos": "not a list"}
    inject_photo_url_on_doc(doc, jid="job-1")
    assert doc["photos"] == "not a list"
