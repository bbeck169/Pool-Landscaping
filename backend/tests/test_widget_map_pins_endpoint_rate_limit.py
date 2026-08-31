"""Feb-2026 · Widget-Embed extension · rate-limit contract.

The pins + map.html endpoints share the same 60/min per-IP bucket
as the existing feed (``routers/public_widget._rate_ok``). This
test bombs the endpoint 61 times from the same IP within the
window and asserts the 61st request 429s.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from routers import public_checkins_map as pcm
from routers import public_widget as pw
from tests._map_endpoint_fakes import make_map_db


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _fake_request(ip="203.0.113.7"):
    scope = {"type": "http", "method": "GET", "path": "/",
             "headers": [], "query_string": b"", "client": (ip, 0)}
    return Request(scope)


class _RespShim:
    headers = {}


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_61st_request_from_same_ip_gets_429(monkeypatch):
    # Clear the process-wide bucket so we can count.
    if hasattr(pw, "_ip_buckets"):
        pw._ip_buckets.clear()

    fake = make_map_db(
        tenants=[{"id": "t1", "name": "T", "slug": "t"}],
        checkins=[{"id": "pc-1", "tenant_id": "t1", "state": "approved",
                    "lat_public": 33.0, "lng_public": -112.0,
                    "service_name": "Pool",
                    "approved_at": _iso_days_ago(5)}],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    for i in range(60):
        _run(pcm.public_pins("t", request=_fake_request(),
                                 response=_RespShim()))

    # 61st MUST 429.
    import pytest
    with pytest.raises(HTTPException) as exc:
        _run(pcm.public_pins("t", request=_fake_request(),
                                 response=_RespShim()))
    assert exc.value.status_code == 429


def test_different_ips_do_not_share_budget(monkeypatch):
    """Rate limiting is per-IP, not global. Two independent
    clients hitting concurrently must each get their own 60."""
    if hasattr(pw, "_ip_buckets"):
        pw._ip_buckets.clear()

    fake = make_map_db(
        tenants=[{"id": "t1", "name": "T", "slug": "t"}],
        checkins=[{"id": "pc-1", "tenant_id": "t1", "state": "approved",
                    "lat_public": 33.0, "lng_public": -112.0,
                    "service_name": "Pool",
                    "approved_at": _iso_days_ago(5)}],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    for _ in range(60):
        _run(pcm.public_pins("t", request=_fake_request("1.1.1.1"),
                                 response=_RespShim()))

    # Different IP — should still succeed.
    result = _run(pcm.public_pins(
        "t", request=_fake_request("2.2.2.2"),
        response=_RespShim(),
    ))
    assert result["count"] == 1
