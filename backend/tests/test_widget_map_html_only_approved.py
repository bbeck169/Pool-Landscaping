"""Feb-2026 · Widget-Embed extension · state gates.

Contract:
  * Only ``state='approved'`` rows appear on the map.
  * Rows older than 12 months are excluded.
  * Rows without obfuscated coords (older MR0 rows pre-Feb-2026) are
    silently filtered — no half-pin rendering.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import Request

from routers import public_checkins_map as pcm
from routers import public_widget as pw
from tests._map_endpoint_fakes import make_map_db


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _fake_request():
    scope = {"type": "http", "method": "GET", "path": "/",
             "headers": [], "query_string": b"", "client": ("127.0.0.1", 0)}
    return Request(scope)


def _fresh_bucket():
    if hasattr(pw, "_ip_buckets"):
        pw._ip_buckets.clear()


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


class _RespShim:
    headers = {}


def test_pending_and_rejected_rows_never_leak(monkeypatch):
    _fresh_bucket()
    fake = make_map_db(
        tenants=[{"id": "t1", "name": "T", "slug": "t"}],
        checkins=[
            {"id": "a", "tenant_id": "t1", "state": "approved",
             "lat_public": 33.0, "lng_public": -112.0,
             "service_name": "Pool", "approved_at": _iso_days_ago(3)},
            {"id": "b", "tenant_id": "t1", "state": "pending_review",
             "lat_public": 34.0, "lng_public": -113.0,
             "service_name": "Trim", "approved_at": _iso_days_ago(2)},
            {"id": "c", "tenant_id": "t1", "state": "rejected",
             "lat_public": 35.0, "lng_public": -114.0,
             "service_name": "Trim", "approved_at": _iso_days_ago(1)},
            {"id": "d", "tenant_id": "t1", "state": "unpublished",
             "lat_public": 36.0, "lng_public": -115.0,
             "service_name": "Trim", "approved_at": _iso_days_ago(1)},
        ],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    payload = _run(pcm.public_pins("t", request=_fake_request(),
                                        response=_RespShim()))
    assert payload["count"] == 1
    pin = payload["pins"][0]
    # Only the approved row (a) leaked its coords through.
    assert pin["lat"] == 33.0


def test_rows_older_than_12_months_excluded(monkeypatch):
    _fresh_bucket()
    fake = make_map_db(
        tenants=[{"id": "t1", "name": "T", "slug": "t"}],
        checkins=[
            {"id": "recent", "tenant_id": "t1", "state": "approved",
             "lat_public": 33.0, "lng_public": -112.0,
             "service_name": "Pool", "approved_at": _iso_days_ago(30)},
            {"id": "stale", "tenant_id": "t1", "state": "approved",
             "lat_public": 40.0, "lng_public": -100.0,
             "service_name": "Pool",
             "approved_at": _iso_days_ago(400)},   # >12 months
        ],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    payload = _run(pcm.public_pins("t", request=_fake_request(),
                                        response=_RespShim()))
    assert payload["count"] == 1
    assert payload["pins"][0]["lat"] == 33.0


def test_row_missing_public_coords_silently_filtered(monkeypatch):
    """MR0 rows (pre-Feb-2026) had no ``lat_public``/``lng_public``.
    They're valid moderation-queue rows, they just don't appear on
    the map. NEVER render a half-pin."""
    _fresh_bucket()
    fake = make_map_db(
        tenants=[{"id": "t1", "name": "T", "slug": "t"}],
        checkins=[
            {"id": "mr0", "tenant_id": "t1", "state": "approved",
             "service_name": "Pool", "approved_at": _iso_days_ago(5)},
            {"id": "new", "tenant_id": "t1", "state": "approved",
             "lat_public": 33.0, "lng_public": -112.0,
             "service_name": "Pool", "approved_at": _iso_days_ago(2)},
        ],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    payload = _run(pcm.public_pins("t", request=_fake_request(),
                                        response=_RespShim()))
    assert payload["count"] == 1
    assert payload["pins"][0]["lat"] == 33.0


def test_unknown_tenant_slug_returns_404(monkeypatch):
    _fresh_bucket()
    fake = make_map_db(tenants=[], checkins=[])
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    from fastapi import HTTPException
    import pytest
    with pytest.raises(HTTPException) as exc:
        _run(pcm.public_pins("nope", request=_fake_request(),
                                 response=_RespShim()))
    assert exc.value.status_code == 404, (
        "unknown slug must return 404 (not 403) to avoid "
        "tenant enumeration"
    )
