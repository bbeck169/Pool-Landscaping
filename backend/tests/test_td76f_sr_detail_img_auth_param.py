"""TD-76f · Feb-2026 — portal SR Detail job-photos ``<img src>``
auth-param regression test.

Pre-TD-76f: ``_build_customer_job_photos`` emitted a raw URL
``/api/customers/me/jobs/<jid>/photos/<pid>`` with NO ``?auth=``
query param. TD-76d removed the FE-side ``withAuthToken`` wrapper
on the premise that the BE emission layer owned the full URL,
which left ``<img src>`` loads 401-ing in the browser (headers
can't be attached to image requests, and the TD-67 streaming
handler accepts a ``?auth=`` fallback).

Post-TD-76f: the emission site stamps ``?auth=<token>`` onto the
resolved URL for the portal_sr_detail context using the Bearer
token extracted from the inbound request's Authorization header.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


def test_build_customer_job_photos_stamps_auth_when_bearer_present():
    from routers.service_reports import _build_customer_job_photos
    job = {
        "id": "j-xyz",
        "photos": [{
            "id": "p-1", "visibility": "customer", "mime": "image/jpeg",
            "uploaded_at": "2026-02-01T10:00:00Z",
        }],
    }
    out = _build_customer_job_photos(
        job, base_url="https://api.example", bearer_token="jwt-abc",
    )
    assert len(out) == 1
    e = out[0]
    assert "auth=jwt-abc" in e["full_url"]
    assert "auth=jwt-abc" in e["thumb_url"]
    assert "auth=jwt-abc" in e["url"]
    # Base URL preserved.
    assert e["full_url"].startswith(
        "https://api.example/api/customers/me/jobs/j-xyz/photos/p-1",
    )


def test_build_customer_job_photos_no_auth_param_when_bearer_absent():
    from routers.service_reports import _build_customer_job_photos
    job = {
        "id": "j-xyz",
        "photos": [{
            "id": "p-1", "visibility": "customer", "mime": "image/jpeg",
            "uploaded_at": "2026-02-01T10:00:00Z",
        }],
    }
    out = _build_customer_job_photos(job, base_url="", bearer_token="")
    assert len(out) == 1
    e = out[0]
    assert "auth=" not in e["full_url"]
    assert e["full_url"] == "/api/customers/me/jobs/j-xyz/photos/p-1"


def test_build_customer_job_photos_url_encodes_token_special_chars():
    from routers.service_reports import _build_customer_job_photos
    job = {
        "id": "j-xyz",
        "photos": [{
            "id": "p-1", "visibility": "customer", "mime": "image/jpeg",
            "uploaded_at": "2026-02-01T10:00:00Z",
        }],
    }
    out = _build_customer_job_photos(
        job, base_url="", bearer_token="jwt/with+slash=and&amp",
    )
    # Special chars URL-encoded so the query param survives round-trip.
    url = out[0]["full_url"]
    # Decode and verify.
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse("http://x" + url).query)
    assert q["auth"] == ["jwt/with+slash=and&amp"]


def test_build_customer_job_photos_data_uri_thumb_overrides_thumb_url():
    """Embedded data-URI thumbs always paint inline and must NOT
    be token-stamped (they're pure base64, not an HTTP request)."""
    from routers.service_reports import _build_customer_job_photos
    data_uri = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/"
    job = {
        "id": "j-xyz",
        "photos": [{
            "id": "p-1", "visibility": "customer", "mime": "image/jpeg",
            "uploaded_at": "2026-02-01T10:00:00Z",
            "thumb": data_uri,
        }],
    }
    out = _build_customer_job_photos(
        job, base_url="", bearer_token="jwt-abc",
    )
    e = out[0]
    # ``thumb_url`` is the inline data URI — NEVER token-stamped.
    assert e["thumb_url"] == data_uri
    assert "auth=" not in e["thumb_url"]
    # ``full_url`` IS the authenticated streaming route (token-stamped).
    assert "auth=jwt-abc" in e["full_url"]
