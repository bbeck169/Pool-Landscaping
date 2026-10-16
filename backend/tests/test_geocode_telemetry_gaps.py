"""P0-GEOCODE-LEAK-C2.5 · TD-62 (Feb-2026).

Closes the two telemetry gaps flagged in C2:

  * Gap 1 — ``routers/google.py::_geocode_one`` (used by
    ``POST /admin/geocode-addresses``, ``PATCH /tenants/mine/geocode``,
    and the ``services/stop_geo.py`` lazy-property backfill).
  * Gap 2 — ``routers/ai_measure.py::geocode_address`` (used by
    ``POST /api/tools/ai-measure/preview`` address resolution).

Both helpers now call ``write_geocode_log`` directly rather than
being refactored to the core ``services.google_maps.geocoding.
geocode_address`` — see the inline rationale in each helper.

Scope boundaries (preserved from C1 + C2):
  * No ``_CACHE_TTL_DAYS`` drift (stays 30d).
  * No boot-sweep sentinel.
  * No ``ENABLE_BOOT_GEOCODE_BACKFILL`` default flip.
  * No FE / mobile edits.
  * Return shape of both helpers byte-for-byte preserved for all
    existing callers.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# Shared fakes
# ─────────────────────────────────────────────────────────────────
class _FakeCollection:
    def __init__(self) -> None:
        self.inserted: List[Dict[str, Any]] = []

    async def insert_one(self, row: Dict[str, Any]) -> None:
        self.inserted.append(row)


class _FakeHttpResponse:
    def __init__(self, *, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeHttpClient:
    """A minimal stand-in for ``httpx.AsyncClient`` that returns the
    next scripted response for any ``get`` call."""

    def __init__(self, responses: List[_FakeHttpResponse]) -> None:
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    async def get(self, url: str, params: Optional[Dict[str, Any]] = None):
        self.calls.append({"url": url, "params": params or {}})
        if not self._responses:
            raise AssertionError("no scripted response remaining")
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def aclose(self):
        return None


# ─────────────────────────────────────────────────────────────────
# Gap 1a — _geocode_one (admin backfill / tenant HQ / stop_geo)
# ─────────────────────────────────────────────────────────────────
def _ok_geocode_payload() -> Dict[str, Any]:
    return {
        "status": "OK",
        "results": [{
            "geometry": {"location": {"lat": 33.5731, "lng": -112.0878}},
            "formatted_address": "123 Main St, Phoenix, AZ 85003, USA",
            "place_id": "ChIJTestPlaceId",
        }],
    }


def test__geocode_one_admin_backfill_writes_hit_row(monkeypatch):
    """Gap 1 — ``_geocode_one`` called with
    ``trigger_reason=ADMIN_BACKFILL`` writes a ``hit`` row.
    """
    from routers import google as g
    from services.google_maps.geocode_trigger import GeocodeTrigger

    fake = _FakeCollection()

    class _StubDb:
        geocode_call_log = fake

    monkeypatch.setattr(g, "db", _StubDb(), raising=True)
    monkeypatch.setattr(g, "GOOGLE_API_KEY", "AIzaSyFAKEKEY1234", raising=True)

    client = _FakeHttpClient([_FakeHttpResponse(
        status_code=200, payload=_ok_geocode_payload(),
    )])

    result = asyncio.run(g._geocode_one(
        client, "123 Main St, Phoenix, AZ",
        trigger_reason=GeocodeTrigger.ADMIN_BACKFILL,
        tenant_id="tenant-A",
        entity_type="customer",
        entity_id="cust-123",
    ))

    # Return shape preserved for existing callers.
    assert result == {
        "lat": 33.5731, "lng": -112.0878,
        "formatted": "123 Main St, Phoenix, AZ 85003, USA",
        "place_id": "ChIJTestPlaceId",
    }

    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["trigger_reason"] == GeocodeTrigger.ADMIN_BACKFILL.value
    assert row["outcome"] == "hit"
    assert row["tenant_id"] == "tenant-A"
    assert row["entity_type"] == "customer"
    assert row["entity_id"] == "cust-123"
    assert row["address"] == "123 Main St, Phoenix, AZ"
    assert row["lat"] == 33.5731
    assert row["lng"] == -112.0878
    assert row["error"] is None
    assert row["api_key_fingerprint"] == "1234"


def test__geocode_one_admin_backfill_writes_error_row_on_http_500(monkeypatch):
    """Gap 1 — HTTP non-200 path writes an ``error`` row and
    returns None (preserved behaviour)."""
    from routers import google as g
    from services.google_maps.geocode_trigger import GeocodeTrigger

    fake = _FakeCollection()

    class _StubDb:
        geocode_call_log = fake

    monkeypatch.setattr(g, "db", _StubDb(), raising=True)
    monkeypatch.setattr(g, "GOOGLE_API_KEY", "AIzaSyFAKEKEY1234", raising=True)

    client = _FakeHttpClient([_FakeHttpResponse(
        status_code=500, payload={"status": "UNKNOWN_ERROR"},
    )])

    result = asyncio.run(g._geocode_one(
        client, "500 St Rd",
        trigger_reason=GeocodeTrigger.ADMIN_BACKFILL,
        tenant_id="tenant-A",
        entity_type="customer",
        entity_id="cust-500",
    ))

    assert result is None
    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["trigger_reason"] == GeocodeTrigger.ADMIN_BACKFILL.value
    assert row["outcome"] == "error"
    assert row["error"] == "http_500"
    assert row["lat"] is None
    assert row["lng"] is None


def test__geocode_one_tenant_hq_patch_writes_hit_row(monkeypatch):
    """Gap 1 — ``_geocode_one`` called with ``TENANT_HQ_PATCH``
    (the ``PATCH /tenants/mine/geocode`` call-site) writes a
    properly-attributed row."""
    from routers import google as g
    from services.google_maps.geocode_trigger import GeocodeTrigger

    fake = _FakeCollection()

    class _StubDb:
        geocode_call_log = fake

    monkeypatch.setattr(g, "db", _StubDb(), raising=True)
    monkeypatch.setattr(g, "GOOGLE_API_KEY", "AIzaSyFAKEKEY1234", raising=True)

    client = _FakeHttpClient([_FakeHttpResponse(
        status_code=200, payload=_ok_geocode_payload(),
    )])

    result = asyncio.run(g._geocode_one(
        client, "HQ 1 Plaza",
        trigger_reason=GeocodeTrigger.TENANT_HQ_PATCH,
        tenant_id="tenant-HQ",
        entity_type="tenant",
        entity_id="tenant-HQ",
    ))

    assert result is not None
    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["trigger_reason"] == GeocodeTrigger.TENANT_HQ_PATCH.value
    assert row["outcome"] == "hit"
    assert row["tenant_id"] == "tenant-HQ"
    assert row["entity_type"] == "tenant"


def test__geocode_one_tenant_hq_patch_error_path_writes_error_row(monkeypatch):
    """Gap 1 — exception path (httpx raises) writes an ``error``
    row with the exception class."""
    from routers import google as g
    from services.google_maps.geocode_trigger import GeocodeTrigger

    fake = _FakeCollection()

    class _StubDb:
        geocode_call_log = fake

    monkeypatch.setattr(g, "db", _StubDb(), raising=True)
    monkeypatch.setattr(g, "GOOGLE_API_KEY", "AIzaSyFAKEKEY1234", raising=True)

    class _ExplodingClient:
        async def get(self, *_a, **_kw):
            raise RuntimeError("connection reset by peer")

    result = asyncio.run(g._geocode_one(
        _ExplodingClient(), "HQ 1 Plaza",
        trigger_reason=GeocodeTrigger.TENANT_HQ_PATCH,
        tenant_id="tenant-HQ",
        entity_type="tenant",
        entity_id="tenant-HQ",
    ))

    assert result is None
    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["trigger_reason"] == GeocodeTrigger.TENANT_HQ_PATCH.value
    assert row["outcome"] == "error"
    assert row["error"] is not None
    assert row["error"].startswith("RuntimeError:")


def test__geocode_one_backward_compat_unknown_default(monkeypatch):
    """Gap 1 regression — callers that haven't been updated (e.g.
    ``services/stop_geo.py``) continue to work via the UNKNOWN
    default so the telemetry gap is closed as a free side-effect."""
    from routers import google as g
    from services.google_maps.geocode_trigger import GeocodeTrigger

    fake = _FakeCollection()

    class _StubDb:
        geocode_call_log = fake

    monkeypatch.setattr(g, "db", _StubDb(), raising=True)
    monkeypatch.setattr(g, "GOOGLE_API_KEY", "AIzaSyFAKEKEY1234", raising=True)

    client = _FakeHttpClient([_FakeHttpResponse(
        status_code=200, payload=_ok_geocode_payload(),
    )])

    result = asyncio.run(g._geocode_one(client, "any addr"))
    assert result is not None
    assert len(fake.inserted) == 1
    assert fake.inserted[0]["trigger_reason"] == GeocodeTrigger.UNKNOWN.value
    assert fake.inserted[0]["entity_type"] == "unknown"


# ─────────────────────────────────────────────────────────────────
# Gap 2 — ai_measure.geocode_address
# ─────────────────────────────────────────────────────────────────
def test_ai_measure_geocode_address_writes_hit_row(monkeypatch):
    """Gap 2 — ``ai_measure.geocode_address`` happy path writes a
    ``hit`` row with ``trigger_reason=ai_measure_resolve``."""
    from routers import ai_measure as am
    from services.google_maps.geocode_trigger import GeocodeTrigger

    fake = _FakeCollection()

    class _StubDb:
        geocode_call_log = fake

    # Patch the config.db that ``geocode_address`` imports lazily.
    monkeypatch.setattr("config.db", _StubDb(), raising=True)
    monkeypatch.setattr(am, "_resolve_google_key", lambda: "AIzaMEASURE1234", raising=True)

    client = _FakeHttpClient([_FakeHttpResponse(
        status_code=200, payload=_ok_geocode_payload(),
    )])

    result = asyncio.run(am.geocode_address(
        "1 Measurement Rd", http_client=client,
        tenant_id="tenant-M",
    ))

    assert result is not None
    assert result["lat"] == 33.5731
    assert result["lng"] == -112.0878
    assert result["formatted"] == "123 Main St, Phoenix, AZ 85003, USA"

    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["trigger_reason"] == GeocodeTrigger.AI_MEASURE_RESOLVE.value
    assert row["outcome"] == "hit"
    assert row["tenant_id"] == "tenant-M"
    assert row["entity_type"] == "ai_measure"
    assert row["address"] == "1 Measurement Rd"
    assert row["api_key_fingerprint"] == "1234"


def test_ai_measure_geocode_address_writes_error_row_on_http_500(monkeypatch):
    """Gap 2 — HTTP non-200 writes an ``error`` row and returns
    None (preserved behaviour)."""
    from routers import ai_measure as am
    from services.google_maps.geocode_trigger import GeocodeTrigger

    fake = _FakeCollection()

    class _StubDb:
        geocode_call_log = fake

    monkeypatch.setattr("config.db", _StubDb(), raising=True)
    monkeypatch.setattr(am, "_resolve_google_key", lambda: "AIzaMEASURE1234", raising=True)

    client = _FakeHttpClient([_FakeHttpResponse(
        status_code=500, payload={"status": "SERVER_ERROR"},
    )])

    result = asyncio.run(am.geocode_address(
        "1 Measurement Rd", http_client=client,
        tenant_id="tenant-M",
    ))

    assert result is None
    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["trigger_reason"] == GeocodeTrigger.AI_MEASURE_RESOLVE.value
    assert row["outcome"] == "error"
    assert row["error"] == "http_500"


def test_ai_measure_geocode_address_writes_no_addr_row(monkeypatch):
    """Gap 2 — empty address path writes a ``no_addr`` row rather
    than silently dropping the call."""
    from routers import ai_measure as am
    from services.google_maps.geocode_trigger import GeocodeTrigger

    fake = _FakeCollection()

    class _StubDb:
        geocode_call_log = fake

    monkeypatch.setattr("config.db", _StubDb(), raising=True)
    monkeypatch.setattr(am, "_resolve_google_key", lambda: "AIzaMEASURE1234", raising=True)

    result = asyncio.run(am.geocode_address("", tenant_id="tenant-M"))
    assert result is None
    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["trigger_reason"] == GeocodeTrigger.AI_MEASURE_RESOLVE.value
    assert row["outcome"] == "no_addr"


# ─────────────────────────────────────────────────────────────────
# Source-level invariant — gap-closure anchors so merges can't
# silently drop the trigger_reason propagation on the live routes.
# ─────────────────────────────────────────────────────────────────
def test_source_level_trigger_propagation_at_the_three_call_sites():
    import pathlib

    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    g = (repo / "backend/routers/google.py").read_text(encoding="utf-8")
    t = (repo / "backend/routers/tenants.py").read_text(encoding="utf-8")
    a = (repo / "backend/routers/ai_measure.py").read_text(encoding="utf-8")

    # Gap 1a — admin backfill passes ADMIN_BACKFILL.
    assert "GeocodeTrigger.ADMIN_BACKFILL" in g, (
        "/admin/geocode-addresses no longer passes ADMIN_BACKFILL"
    )
    # Gap 1b — tenant HQ patch passes TENANT_HQ_PATCH.
    assert "GeocodeTrigger.TENANT_HQ_PATCH" in t, (
        "/tenants/mine/geocode PATCH no longer passes TENANT_HQ_PATCH"
    )
    # Gap 2 — ai_measure helper writes AI_MEASURE_RESOLVE.
    assert "GeocodeTrigger.AI_MEASURE_RESOLVE" in a, (
        "ai_measure.geocode_address no longer writes AI_MEASURE_RESOLVE"
    )
    # All three must import the fail-safe writer.
    assert "write_geocode_log" in g
    assert "write_geocode_log" in a
