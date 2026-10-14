"""Feb-2026 · Skip-jobs postmortem — trace-log contract for
``services.google_maps.geocoding.geocode_and_persist_property``.

Classification (b) in the skip-jobs root-cause table: the backfill
endpoint had never fired live (audit log empty), the data path is
intact, and operators had no runtime visibility into whether their
dry-run → confirm flow actually landed writes. This commit adds a
structured ``[geocode-property]`` log line on every outcome branch
so operators can grep the backend log and post-verify.

This test locks the log-contract so future refactors can't quietly
drop one of the five outcome tags
(``google | cache | no_addr | missing | no_hit``).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch


def _run(coro):
    return asyncio.run(coro)


class _FakeProps:
    """Thin stand-in for the Motor ``db.properties`` collection.

    Each test instantiates its own with a canned ``find_one`` return.
    ``update_one`` is an AsyncMock so assertions can confirm (non-)
    writes.
    """
    def __init__(self, find_result):
        self._find_result = find_result
        self.update_one = AsyncMock()

    async def find_one(self, *_a, **_kw):
        return self._find_result


class _FakeDB:
    def __init__(self, properties):
        self.properties = properties


def test_geocode_property_logs_google_success(caplog):
    from services.google_maps import geocoding as _mod
    props = _FakeProps({
        "id": "pid-1", "tenant_id": "tenant-1",
        "latitude": None, "longitude": None,
        "address": {"address_line1": "123 Main St", "city": "Peoria",
                    "state": "AZ", "zip": "85383"},
    })
    with patch.object(_mod, "db", _FakeDB(props)):
        with patch.object(_mod, "geocode_address",
                            new=AsyncMock(return_value={
                                "lat": 33.5806, "lng": -112.2374,
                                "precision": "ROOFTOP"})):
            with caplog.at_level(logging.INFO,
                                   logger="pool_crm"):
                ok = _run(_mod.geocode_and_persist_property(
                    "pid-1", "tenant-1"))
    assert ok is True
    msgs = [r.getMessage() for r in caplog.records]
    hits = [m for m in msgs if "[geocode-property]" in m
             and "method=google" in m]
    assert len(hits) == 1, (
        f"expected exactly one method=google trace, got: {msgs}")
    assert "pid=pid-1" in hits[0]
    assert "new=(33.5806, -112.2374)" in hits[0]
    assert "old=(None, None)" in hits[0]


def test_geocode_property_logs_cache_hit(caplog):
    from services.google_maps import geocoding as _mod
    props = _FakeProps({
        "id": "pid-2", "tenant_id": "tenant-2",
        "latitude": 1.0, "longitude": 2.0,
        "geocoded_at": datetime.now(timezone.utc).isoformat(),
    })
    geo_mock = AsyncMock()
    with patch.object(_mod, "db", _FakeDB(props)):
        with patch.object(_mod, "geocode_address", geo_mock):
            with caplog.at_level(logging.INFO,
                                   logger="pool_crm"):
                ok = _run(_mod.geocode_and_persist_property(
                    "pid-2", "tenant-2"))
    assert ok is False
    assert any("[geocode-property]" in r.getMessage()
                and "method=cache" in r.getMessage()
                for r in caplog.records)
    geo_mock.assert_not_called()


def test_geocode_property_logs_no_addr(caplog):
    from services.google_maps import geocoding as _mod
    props = _FakeProps({
        "id": "pid-3", "tenant_id": "tenant-3",
        "latitude": None, "longitude": None, "address": {},
    })
    with patch.object(_mod, "db", _FakeDB(props)):
        with caplog.at_level(logging.INFO,
                               logger="pool_crm"):
            ok = _run(_mod.geocode_and_persist_property(
                "pid-3", "tenant-3"))
    assert ok is False
    assert any("[geocode-property]" in r.getMessage()
                and "method=no_addr" in r.getMessage()
                for r in caplog.records)


def test_geocode_property_logs_missing(caplog):
    from services.google_maps import geocoding as _mod
    props = _FakeProps(None)  # ``find_one`` returns None → missing path
    with patch.object(_mod, "db", _FakeDB(props)):
        with caplog.at_level(logging.INFO,
                               logger="pool_crm"):
            ok = _run(_mod.geocode_and_persist_property(
                "ghost-pid", "tenant-x"))
    assert ok is False
    assert any("[geocode-property]" in r.getMessage()
                and "method=missing" in r.getMessage()
                for r in caplog.records)


def test_geocode_property_logs_no_hit(caplog):
    from services.google_maps import geocoding as _mod
    props = _FakeProps({
        "id": "pid-nh", "tenant_id": "tenant-nh",
        "latitude": None, "longitude": None,
        "address": {"address_line1": "notarealstreet", "city": "X"},
    })
    with patch.object(_mod, "db", _FakeDB(props)):
        with patch.object(_mod, "geocode_address",
                            new=AsyncMock(return_value=None)):
            with caplog.at_level(logging.INFO,
                                   logger="pool_crm"):
                ok = _run(_mod.geocode_and_persist_property(
                    "pid-nh", "tenant-nh"))
    assert ok is False
    assert any("[geocode-property]" in r.getMessage()
                and "method=no_hit" in r.getMessage()
                for r in caplog.records)
