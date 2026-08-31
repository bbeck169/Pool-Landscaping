"""Feb-2026 · Widget-Embed extension · PII invariants.

Contract: neither ``map.html`` nor ``/pins`` may leak:
  * customer name
  * raw (unobfuscated) coordinates
  * exact completion date (finer than month-year)
  * job_id / customer_id / any internal id
  * raw address fields
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


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _fake_request():
    scope = {"type": "http", "method": "GET", "path": "/",
             "headers": [], "query_string": b"",
             "client": ("127.0.0.1", 0)}
    return Request(scope)


def _leaky_checkin(days_ago=5):
    """A public_checkin row seeded with LOADS of PII — the tests
    below assert none of it slips into the public response."""
    return {
        "id": "SECRET-INTERNAL-ID",
        "tenant_id": "t1",
        "source_job_id": "SECRET-JOB-ID-12345",
        "source_checkin_id": "SECRET-CHECKIN-ID",
        "source": "auto",
        "state": "approved",
        # Raw coords — MUST NEVER surface in the response body.
        "lat_raw": 33.572211,
        "lng_raw": -112.323712,
        # Obfuscated coords — the ONLY coords the response may show.
        "lat_public": 33.5730,
        "lng_public": -112.3240,
        "service_name": "Pool Cleaning",
        "service_category": "pools",
        "area_label": "Peoria, AZ",
        "completed_at": "2026-08-15T09:47:32.123456+00:00",
        "completed_at_month_year": "August 2026",
        "approved_at": _iso_days_ago(days_ago),
        # ── PII fields that MUST NOT leak ─────────────────────────
        "customer_name": "Alice Smith SECRETNAME",
        "customer_id": "cust-secret",
        "raw_address": {"street": "123 Real Street Ave",
                          "city": "Peoria", "state": "AZ",
                          "zip": "85383"},
        "masked_address": {"city": "Peoria", "state": "AZ"},
        "submitted_by_user_id": "user-secret",
        "approved_by_user_id": "user-secret-2",
    }


def test_pins_response_hides_all_pii(monkeypatch):
    if hasattr(pw, "_ip_buckets"):
        pw._ip_buckets.clear()
    fake = make_map_db(
        tenants=[{"id": "t1", "name": "T", "slug": "t"}],
        checkins=[_leaky_checkin()],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    class _RespShim:
        headers = {}
    payload = _run(pcm.public_pins("t", request=_fake_request(),
                                        response=_RespShim()))
    # ── Blob-level string checks.
    import json as _json
    body = _json.dumps(payload)
    for leak in (
        "SECRET-INTERNAL-ID", "SECRET-JOB-ID-12345",
        "SECRET-CHECKIN-ID", "SECRETNAME", "cust-secret",
        "user-secret", "123 Real Street",
        "33.572211", "-112.323712",   # raw coords
        "2026-08-15T09:47:32",         # exact timestamp
    ):
        assert leak not in body, (
            f"PII leaked into /pins response: {leak}"
        )
    # ── Structural check: only the whitelist keys are present.
    pin = payload["pins"][0]
    assert set(pin.keys()) == {"lat", "lng", "service_type",
                                 "completed_at_month_year",
                                 "area_label"}


def test_map_html_hides_all_pii(monkeypatch):
    if hasattr(pw, "_ip_buckets"):
        pw._ip_buckets.clear()
    fake = make_map_db(
        tenants=[{"id": "t1", "name": "T", "slug": "t"}],
        checkins=[_leaky_checkin()],
    )
    monkeypatch.setattr(pcm, "db", fake)
    monkeypatch.setattr(pw, "db", fake)

    resp = _run(pcm.public_map_html("t", request=_fake_request()))
    body = resp.body.decode("utf-8")

    for leak in (
        "SECRET-INTERNAL-ID", "SECRET-JOB-ID-12345",
        "SECRET-CHECKIN-ID", "SECRETNAME", "cust-secret",
        "user-secret", "123 Real Street",
        "33.572211", "-112.323712",
        "2026-08-15T09:47:32",
        "85383",   # zip
    ):
        assert leak not in body, (
            f"PII leaked into map.html: {leak}"
        )
