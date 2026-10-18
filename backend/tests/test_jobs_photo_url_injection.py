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


def test_canonical_thumb_and_full_url_stamped_on_every_photo():
    """TD-76 Ph2f — canonical ``{thumb_url, full_url}`` shape must
    land on every photo subdoc alongside the legacy ``url`` alias.
    Mirrors the shape every other TD-76 Phase B surface emits so
    the FE can read ``p.thumb_url`` / ``p.full_url`` directly."""
    doc = {
        "id": "job-1",
        "photos": [
            {"id": "p1", "label": "a"},
            {"id": "p2", "label": "b"},
        ],
    }
    inject_photo_url_on_doc(doc, jid="job-1")
    assert doc["photos"][0]["full_url"] == "/api/public/job-photo/job-1/p1"
    assert doc["photos"][0]["thumb_url"] == "/api/public/job-photo/job-1/p1/thumb"
    assert doc["photos"][0]["url"] == "/api/public/job-photo/job-1/p1"
    assert doc["photos"][1]["full_url"] == "/api/public/job-photo/job-1/p2"
    assert doc["photos"][1]["thumb_url"] == "/api/public/job-photo/job-1/p2/thumb"
    assert doc["photos"][1]["url"] == "/api/public/job-photo/job-1/p2"


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


def test_idempotent_preserves_prestamped_thumb_and_full_url_independently():
    """TD-76 Ph2f — each canonical field is independently idempotent
    so an operator-stamped absolute ``thumb_url`` (e.g., a CDN URL)
    is not clobbered when ``full_url`` is missing, and vice versa."""
    doc = {
        "id": "job-1",
        "photos": [
            {"id": "p1", "thumb_url": "https://cdn.example.com/thumb/p1.jpg"},
            {"id": "p2", "full_url": "https://cdn.example.com/full/p2.jpg"},
            {"id": "p3"},
        ],
    }
    inject_photo_url_on_doc(doc, jid="job-1")
    # p1: thumb_url preserved; full_url + url backfilled from canonical.
    assert doc["photos"][0]["thumb_url"] == "https://cdn.example.com/thumb/p1.jpg"
    assert doc["photos"][0]["full_url"] == "/api/public/job-photo/job-1/p1"
    assert doc["photos"][0]["url"] == "/api/public/job-photo/job-1/p1"
    # p2: full_url preserved; thumb_url + url backfilled from canonical.
    assert doc["photos"][1]["full_url"] == "https://cdn.example.com/full/p2.jpg"
    assert doc["photos"][1]["thumb_url"] == "/api/public/job-photo/job-1/p2/thumb"
    assert doc["photos"][1]["url"] == "/api/public/job-photo/job-1/p2"
    # p3: fully backfilled.
    assert doc["photos"][2]["thumb_url"] == "/api/public/job-photo/job-1/p3/thumb"
    assert doc["photos"][2]["full_url"] == "/api/public/job-photo/job-1/p3"
    assert doc["photos"][2]["url"] == "/api/public/job-photo/job-1/p3"


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
    assert "thumb_url" not in doc["photos"][0]
    assert "full_url" not in doc["photos"][0]
    assert "url" not in doc["photos"][1]
    assert "thumb_url" not in doc["photos"][1]
    assert "full_url" not in doc["photos"][1]
    assert doc["photos"][2]["url"] == "/api/public/job-photo/job-1/p3"
    assert doc["photos"][2]["thumb_url"] == "/api/public/job-photo/job-1/p3/thumb"
    assert doc["photos"][2]["full_url"] == "/api/public/job-photo/job-1/p3"


def test_missing_jid_is_noop_for_canonical_fields_too():
    """TD-76 Ph2f — missing ``jid`` must leave thumb_url/full_url alone
    on top of the legacy no-op guard."""
    doc = {"id": "job-1", "photos": [{"id": "p1"}]}
    inject_photo_url_on_doc(doc, jid=None)
    assert "thumb_url" not in doc["photos"][0]
    assert "full_url" not in doc["photos"][0]
    inject_photo_url_on_doc(doc, jid="")
    assert "thumb_url" not in doc["photos"][0]
    assert "full_url" not in doc["photos"][0]


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
