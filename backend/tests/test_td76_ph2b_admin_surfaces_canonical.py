"""TD-76 Phase B (ph2b) · Feb-2026 — admin surfaces canonical shape.

Workstream list + Worklog list + admin SR detail list endpoints
now emit the TD-76 Phase A canonical ``{thumb_url, full_url}``
fields alongside the legacy ``url`` alias (mobile parity).

Admin surfaces route through ``/api/public/job-photo/<jid>/<pid>``
which has the resilient S3+base64+SR fallback cascade — zero
dead rows possible on these paths — so Phase B migration is
purely additive and does NOT need the OMIT filter the portal
surfaces required.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


# ───────────────────────────────────────────────────────────────────
# Workstream list — ``_media_summary.photo_thumbs``
# ───────────────────────────────────────────────────────────────────
def test_workstream_media_summary_photo_thumbs_shape():
    from routers.workstream import _media_summary
    job = {
        "id": "j1", "tenant_id": "t1",
        "photos": [
            {"id": "p1", "label": "front yard",
              "created_at": "2026-02-01T10:00:00Z"},
        ],
        "videos": [],
        "_sr_photos": [],
    }
    out = _media_summary(job)
    assert out["photos_count"] == 1
    assert len(out["photo_thumbs"]) == 1
    t = out["photo_thumbs"][0]
    # Canonical fields present.
    assert "thumb_url" in t and t["thumb_url"]
    assert "full_url" in t and t["full_url"]
    # Legacy alias present for mobile parity.
    assert "url" in t and t["url"]
    # All three point at the same resolved URL in Phase B.
    assert t["thumb_url"] == t["full_url"] == t["url"]
    # Routes through the resilient /api/public/job-photo/ cascade.
    assert "/api/public/job-photo/j1/p1" in t["thumb_url"]


# ───────────────────────────────────────────────────────────────────
# Worklog list (ServiceLogPage) — ``_media_items_legacy_shape``
# ───────────────────────────────────────────────────────────────────
def test_worklog_serialize_job_embedded_media_photo_fields():
    from routers.workstream_service_log import _serialize_job_embedded_media
    job = {
        "id": "j1",
        "photos": [{"id": "p1", "label": "x",
                     "created_at": "2026-02-01T10:00:00Z"}],
        "videos": [],
    }
    out = _serialize_job_embedded_media(job)
    assert len(out) == 1
    item = out[0]
    assert item["kind"] == "image"
    assert "thumb_url" in item and item["thumb_url"]
    assert "full_url" in item and item["full_url"]
    assert "url" in item and item["url"]
    assert item["thumb_url"] == item["full_url"] == item["url"]
    assert "/api/public/job-photo/j1/p1" in item["thumb_url"]


# ───────────────────────────────────────────────────────────────────
# SR-media serializer — ``_serialize_service_report_media``
# ───────────────────────────────────────────────────────────────────
def test_serialize_service_report_media_canonical_fields():
    from routers.workstream_service_log import _serialize_service_report_media
    photos = [{
        "id": "p1", "url": "/api/public/service/abc/photo/p1",
        "label": "pool",
        "created_at": "2026-02-01T10:00:00Z",
    }]
    out = _serialize_service_report_media(photos, [])
    assert len(out) == 1
    item = out[0]
    assert item["kind"] == "image"
    assert item["thumb_url"] == "/api/public/service/abc/photo/p1"
    assert item["full_url"] == "/api/public/service/abc/photo/p1"
    assert item["url"] == "/api/public/service/abc/photo/p1"


def test_serialize_service_report_media_skips_rows_with_no_url():
    """Pre-TD-76 behavior preserved — SR photos with neither a
    stored ``url`` nor a legacy ``s3_key`` are skipped. This is
    the OMIT branch for SR-side rows."""
    from routers.workstream_service_log import _serialize_service_report_media
    photos = [{
        "id": "p1", "url": "", "label": "no bytes",
    }]
    out = _serialize_service_report_media(photos, [])
    assert out == []
