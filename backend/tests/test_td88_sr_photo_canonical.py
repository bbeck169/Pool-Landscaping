"""TD-88 · Feb-2026 — SR photo canonical shape · regression guard.

Context: ``GET /api/jobs/{jid}/service-report``,
``PATCH /api/jobs/{jid}/service-report`` and
``POST /api/jobs/{jid}/service-report/submit`` now stamp canonical
``thumb_url`` / ``full_url`` / legacy ``url`` on every
``photos[]`` subdoc of the response.

Before TD-88 the FE ``PhotoUploader.jsx`` composed the thumbnail
URL by hand against ``p.id``, which worked on fresh uploads
(ids originated from ``jobs.photos``) but was fragile under the
read-vs-write id-space drift (SR response can carry
``jobs.photos`` ids via the hydrated GET branch OR
``service_reports.photos`` ids via the raw PATCH find_one — see
TD-89 bookmark for the semantic cleanup).  BE SR fallback at
``routers/jobs.py::_find_sr_photo_by_job_and_id`` already
resolves either id against the jobs-route URL shape, so this
ship reuses the TD-76 Ph2f ``inject_photo_url_on_doc`` helper
rather than minting a sibling (per operator directive —
"don't let two helpers drift").

Pure in-memory contract tests here mirror the shape of each SR
response dict and assert the stamped fields.  No DB, no
FastAPI TestClient, no network — matches the test style of
``test_jobs_photo_url_injection.py`` (TD-76 Ph2f sibling, see
``services/jobs_slim_photos.py::inject_photo_url_on_doc``).

Related: ``test_jobs_photo_url_injection.py`` — the helper's
own regression suite.  This file adds the SR integration
regression guard on top.
"""
from __future__ import annotations

from services.jobs_slim_photos import inject_photo_url_on_doc


# ── GET /jobs/{jid}/service-report ──────────────────────────────────
# The GET endpoint hydrates ``existing["photos"] = job.get("photos")``,
# so photo ids on the response are ``jobs.photos`` ids.
def test_sr_get_response_stamps_canonical_fields_on_jobs_photos_shape():
    existing = {
        "id": "sr-1",
        "job_id": "job-1",
        "photos": [
            {"id": "p1", "label": "checklist-2026-02-19"},
            {"id": "p2", "label": "water-analysis-1"},
        ],
    }
    inject_photo_url_on_doc(existing, jid="job-1")
    for p in existing["photos"]:
        pid = p["id"]
        assert p["thumb_url"] == f"/api/public/job-photo/job-1/{pid}/thumb"
        assert p["full_url"] == f"/api/public/job-photo/job-1/{pid}"
        assert p["url"] == f"/api/public/job-photo/job-1/{pid}"


# ── PATCH /jobs/{jid}/service-report ────────────────────────────────
# PATCH returns the raw ``service_reports.find_one`` doc, so photo ids
# are ``service_reports.photos`` ids.  BE SR fallback resolves these
# against the same jobs-route URL shape — stamping is identical.
def test_sr_patch_response_stamps_canonical_fields_on_sr_photos_shape():
    resp = {
        "id": "sr-1",
        "job_id": "job-1",
        "tech_id": "tech-1",
        "photos": [
            {"id": "sr-pid-a", "storage_path": "svc/report/sr-1/a.jpg"},
            {"id": "sr-pid-b", "storage_path": "svc/report/sr-1/b.jpg"},
        ],
    }
    inject_photo_url_on_doc(resp, jid="job-1")
    for p in resp["photos"]:
        pid = p["id"]
        assert p["thumb_url"] == f"/api/public/job-photo/job-1/{pid}/thumb"
        assert p["full_url"] == f"/api/public/job-photo/job-1/{pid}"
        assert p["url"] == f"/api/public/job-photo/job-1/{pid}"


# ── POST /jobs/{jid}/service-report/submit (idempotent return) ──────
def test_sr_submit_idempotent_return_stamps_canonical_fields():
    rep = {
        "id": "sr-1",
        "job_id": "job-1",
        "submitted_at": "2026-02-19T18:00:00+00:00",
        "photos": [
            {"id": "p1", "label": "checklist-ok"},
        ],
    }
    inject_photo_url_on_doc(rep, jid="job-1")
    assert rep["photos"][0]["thumb_url"] == "/api/public/job-photo/job-1/p1/thumb"
    assert rep["photos"][0]["full_url"] == "/api/public/job-photo/job-1/p1"
    assert rep["photos"][0]["url"] == "/api/public/job-photo/job-1/p1"


# ── POST /jobs/{jid}/service-report/submit (final return path) ──────
def test_sr_submit_final_return_stamps_canonical_fields():
    out = {
        "id": "sr-1",
        "job_id": "job-1",
        "photos": [
            {"id": "p1"},
            {"id": "p2"},
        ],
        "warnings": [],
    }
    inject_photo_url_on_doc(out, jid="job-1")
    for p in out["photos"]:
        pid = p["id"]
        assert "thumb_url" in p and p["thumb_url"].endswith(f"/{pid}/thumb")
        assert "full_url" in p and p["full_url"].endswith(f"/{pid}")
        assert "url" in p and p["url"].endswith(f"/{pid}")


# ── Idempotency on re-stamp (matches TD-76 Ph2 contract) ────────────
def test_sr_stamp_is_idempotent_on_repeat_emissions():
    existing = {
        "id": "sr-1", "job_id": "job-1",
        "photos": [{"id": "p1"}],
    }
    inject_photo_url_on_doc(existing, jid="job-1")
    first = dict(existing["photos"][0])
    inject_photo_url_on_doc(existing, jid="job-1")
    second = existing["photos"][0]
    assert first == second, \
        "Re-stamp must produce identical output (idempotent contract)"


# ── Pre-stamped canonical fields are preserved (operator-override) ──
def test_sr_stamp_does_not_override_prestamped_canonical_fields():
    pre_full = "https://cdn.example.com/sr/p1.jpg"
    pre_thumb = "https://cdn.example.com/sr/p1-thumb.jpg"
    existing = {
        "id": "sr-1", "job_id": "job-1",
        "photos": [{"id": "p1",
                     "full_url": pre_full, "thumb_url": pre_thumb}],
    }
    inject_photo_url_on_doc(existing, jid="job-1")
    assert existing["photos"][0]["full_url"] == pre_full
    assert existing["photos"][0]["thumb_url"] == pre_thumb
    # Legacy ``url`` alias still populated (no pre-stamp present).
    assert existing["photos"][0]["url"] == "/api/public/job-photo/job-1/p1"


# ── Defensive branches ──────────────────────────────────────────────
def test_sr_stamp_noop_on_empty_photos_list():
    existing = {"id": "sr-1", "job_id": "job-1", "photos": []}
    out = inject_photo_url_on_doc(existing, jid="job-1")
    assert out is existing
    assert existing["photos"] == []


def test_sr_stamp_noop_on_missing_photos_key():
    existing = {"id": "sr-1", "job_id": "job-1"}
    out = inject_photo_url_on_doc(existing, jid="job-1")
    assert out is existing
    assert "photos" not in existing


def test_sr_stamp_skips_photo_entries_without_id():
    existing = {
        "id": "sr-1", "job_id": "job-1",
        "photos": [
            {"id": "p1"},
            {"label": "orphan-no-id"},  # must be skipped
            {"id": "p2"},
        ],
    }
    inject_photo_url_on_doc(existing, jid="job-1")
    assert "thumb_url" in existing["photos"][0]
    # Entry with no id gets no URL fields stamped.
    assert "thumb_url" not in existing["photos"][1]
    assert "full_url" not in existing["photos"][1]
    assert "url" not in existing["photos"][1]
    assert "thumb_url" in existing["photos"][2]
