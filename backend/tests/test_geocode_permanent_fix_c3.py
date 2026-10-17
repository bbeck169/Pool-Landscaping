"""P0-GEOCODE-LEAK-C3 · TD-62 (Feb-2026) — permanent fix lock.

Covers:
  * :func:`should_geocode` — unified pre-geocode guard
      - returns ``(False, "no_addr")`` on empty address
      - returns ``(False, "skipped_unchanged")`` when the address
        fingerprint matches a persisted hash + lat/lng
      - returns ``(False, "skipped_cached")`` when ``geocoded_at``
        is within ``_CACHE_TTL_DAYS`` (180d — regression: 60d-stale
        entity still inside TTL)
      - returns ``(True, None)`` on legitimate new / changed address
      - ``OPERATOR_FORCE`` bypasses every guard
  * ``_CACHE_TTL_DAYS == 180`` module-level invariant.
  * Boot sweep ``migration_status`` sentinel — sentineled tenants
    skip entirely; un-sentineled tenants sweep AND upsert the
    sentinel on clean completion.
  * Lead-Sense ``_maybe_backfill_lead_geocode`` widget-autocomplete
    short-circuit writes exactly one ``skipped_cached`` log row and
    does NOT schedule a background task.
  * Regression — cosmetic customer PATCH (no address field change)
    skips the geocode via ``should_geocode``'s hash branch.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


# ─────────────────────────────────────────────────────────────────
# Shared fakes
# ─────────────────────────────────────────────────────────────────
class _FakeCollection:
    def __init__(self) -> None:
        self.inserted: List[Dict[str, Any]] = []

    async def insert_one(self, row: Dict[str, Any]) -> None:
        self.inserted.append(row)


# ─────────────────────────────────────────────────────────────────
# should_geocode — pure helper
# ─────────────────────────────────────────────────────────────────
class TestShouldGeocode:
    def test_empty_address_returns_no_addr(self):
        from services.google_maps.geocoding import should_geocode
        from services.google_maps.geocode_trigger import GeocodeTrigger
        ok, skip = should_geocode(
            {"id": "c1"}, "", GeocodeTrigger.CUSTOMER_PATCH_ADDR_CHANGE,
        )
        assert ok is False
        assert skip == "no_addr"
        # Whitespace-only too.
        ok, skip = should_geocode({"id": "c1"}, "   \t\n ",
                                    GeocodeTrigger.PROPERTY_PATCH_ADDR_CHANGE)
        assert ok is False
        assert skip == "no_addr"
        # None too.
        ok, skip = should_geocode({"id": "c1"}, None,
                                    GeocodeTrigger.LEAD_CREATE_PUBLIC)
        assert ok is False
        assert skip == "no_addr"

    def test_hash_match_short_circuits_skipped_unchanged(self):
        from services.google_maps.geocoding import (
            should_geocode, hash_address,
        )
        from services.google_maps.geocode_trigger import GeocodeTrigger
        addr = "123 Main St, Phoenix AZ 85003"
        entity = {
            "id": "c1",
            "latitude": 33.57,
            "longitude": -112.08,
            "geocode_address_hash": hash_address(addr),
            # No ``geocoded_at`` — hash branch wins over TTL branch
            # when both would short-circuit.
        }
        ok, skip = should_geocode(
            entity, addr, GeocodeTrigger.CUSTOMER_PATCH_ADDR_CHANGE,
        )
        assert ok is False
        assert skip == "skipped_unchanged"

    def test_hash_mismatch_does_NOT_short_circuit(self):
        """Entity has a stale hash — a real address change must
        fall through to the actual geocode."""
        from services.google_maps.geocoding import (
            should_geocode, hash_address,
        )
        from services.google_maps.geocode_trigger import GeocodeTrigger
        entity = {
            "id": "c1",
            "latitude": 33.57,
            "longitude": -112.08,
            "geocode_address_hash": hash_address("OLD 456 Oak St"),
        }
        ok, skip = should_geocode(
            entity, "NEW 999 Pine Ave",
            GeocodeTrigger.CUSTOMER_PATCH_ADDR_CHANGE,
        )
        assert ok is True
        assert skip is None

    def test_within_ttl_returns_skipped_cached(self):
        """60d stale entity is still inside the 180d TTL → cached."""
        from services.google_maps.geocoding import should_geocode
        from services.google_maps.geocode_trigger import GeocodeTrigger
        _60d_ago = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        entity = {
            "id": "p1",
            # No hash — exercise the TTL branch cleanly.
            "latitude": 33.57, "longitude": -112.08,
            "geocoded_at": _60d_ago,
        }
        ok, skip = should_geocode(
            entity, "any addr", GeocodeTrigger.PROPERTY_PATCH_ADDR_CHANGE,
        )
        assert ok is False
        assert skip == "skipped_cached"

    def test_outside_ttl_falls_through(self):
        """181d-old stamp is OUTSIDE the new 180d TTL → geocode."""
        from services.google_maps.geocoding import should_geocode
        from services.google_maps.geocode_trigger import GeocodeTrigger
        _181d_ago = (datetime.now(timezone.utc) - timedelta(days=181)).isoformat()
        entity = {"id": "p1", "latitude": 33.57, "longitude": -112.08,
                    "geocoded_at": _181d_ago}
        ok, skip = should_geocode(
            entity, "any addr", GeocodeTrigger.PROPERTY_PATCH_ADDR_CHANGE,
        )
        assert ok is True
        assert skip is None

    def test_fresh_entity_with_new_address_passes_through(self):
        from services.google_maps.geocoding import should_geocode
        from services.google_maps.geocode_trigger import GeocodeTrigger
        ok, skip = should_geocode(
            {"id": "c-new"}, "100 First St",
            GeocodeTrigger.CUSTOMER_CREATE,
        )
        assert ok is True
        assert skip is None

    def test_operator_force_bypasses_hash_match(self):
        """OPERATOR_FORCE must always fall through, even when the
        hash matches (operator "Re-geocode now" workflow)."""
        from services.google_maps.geocoding import (
            should_geocode, hash_address,
        )
        from services.google_maps.geocode_trigger import GeocodeTrigger
        addr = "SAME 1 Plaza"
        entity = {
            "latitude": 33.57, "longitude": -112.08,
            "geocode_address_hash": hash_address(addr),
            "geocoded_at": datetime.now(timezone.utc).isoformat(),
        }
        ok, skip = should_geocode(entity, addr, GeocodeTrigger.OPERATOR_FORCE)
        assert ok is True
        assert skip is None

    def test_operator_force_bypasses_ttl(self):
        from services.google_maps.geocoding import should_geocode
        from services.google_maps.geocode_trigger import GeocodeTrigger
        entity = {"latitude": 33.57, "longitude": -112.08,
                   "geocoded_at": datetime.now(timezone.utc).isoformat()}
        ok, _ = should_geocode(entity, "any",
                                 GeocodeTrigger.OPERATOR_FORCE)
        assert ok is True

    def test_ttl_module_constant_is_180_days(self):
        """Regression lock — operator-approved 6× extension."""
        from services.google_maps.geocoding import _CACHE_TTL_DAYS
        assert _CACHE_TTL_DAYS == 180

    def test_hash_address_is_stable_and_normalizes_whitespace(self):
        from services.google_maps.geocoding import hash_address
        h1 = hash_address("  123 MAIN  St  ")
        h2 = hash_address("123 main st")
        assert h1 == h2
        assert len(h1) == 16
        # Empty → empty sentinel so a stored hash can't collide.
        assert hash_address("") == ""
        assert hash_address(None) == ""


# ─────────────────────────────────────────────────────────────────
# Boot sweep ``migration_status`` sentinel
# ─────────────────────────────────────────────────────────────────
class _TenantsCursor:
    """Minimal async iterator over an in-memory tenant list."""
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = list(rows)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._rows:
            raise StopAsyncIteration
        return self._rows.pop(0)


class _TenantsColl:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows
    def find(self, *_a, **_kw):
        return _TenantsCursor(self._rows)


class _CustomersColl:
    def __init__(self, rows_by_tenant: Dict[str, List[Dict[str, Any]]]):
        self._by_tenant = rows_by_tenant
    def find(self, query, *_a, **_kw):
        tid = (query or {}).get("tenant_id")
        return _TenantsCursor(list(self._by_tenant.get(tid, [])))


class _MigrationStatusColl:
    def __init__(self, prefilled: List[Dict[str, Any]]):
        self._rows: List[Dict[str, Any]] = list(prefilled)
        self.upserts: List[Dict[str, Any]] = []
    async def find_one(self, query, *_a, **_kw):
        for r in self._rows:
            if all(r.get(k) == v for k, v in query.items()):
                return r
        return None
    async def update_one(self, filt, update, upsert=False):
        self.upserts.append({"filter": filt, "update": update,
                              "upsert": upsert})
        if upsert:
            # Simulate the sentinel being written.
            self._rows.append(update.get("$set") or {})


class _StubDb:
    def __init__(self, tenants, customers, migration_status):
        self.tenants = _TenantsColl(tenants)
        self.customers = _CustomersColl(customers)
        self.migration_status = _MigrationStatusColl(migration_status)


def test_boot_sweep_skips_sentineled_tenant_without_touching_geocode():
    from routers import dispatch_board as dmod

    sentinel_rows = [
        {"key": "geocode_backfill_v2", "tenant_id": "T-done",
         "completed_at": "2026-01-01T00:00:00+00:00",
         "run_version": "C3"},
    ]
    stub = _StubDb(
        tenants=[{"id": "T-done", "slug": "done-tenant"}],
        customers={"T-done": [{"id": "c1"}, {"id": "c2"}]},
        migration_status=sentinel_rows,
    )
    calls = []
    async def _fake_gp(cid, tid, *, trigger_reason=None):
        calls.append((cid, tid))
        return False
    import services.google_maps.geocoding as _gm
    with patch.object(dmod, "db", stub), \
         patch.object(_gm, "geocode_and_persist_customer", _fake_gp), \
         patch("routers.dispatch_board.asyncio.sleep", new=_noop_sleep):
        asyncio.run(dmod.geocode_backfill_all_tenants_boot())
    assert calls == []  # geocode_and_persist_customer never called
    # No new sentinel upserts — the existing one gated the sweep.
    assert stub.migration_status.upserts == []


def test_boot_sweep_sweeps_un_sentineled_tenant_and_writes_sentinel():
    from routers import dispatch_board as dmod

    stub = _StubDb(
        tenants=[{"id": "T-new", "slug": "new-tenant"}],
        customers={"T-new": [{"id": "c1"}, {"id": "c2"}]},
        migration_status=[],
    )
    calls = []
    async def _fake_gp(cid, tid, *, trigger_reason=None):
        calls.append((cid, tid, getattr(trigger_reason, "value", None)))
        return True
    import services.google_maps.geocoding as _gm
    with patch.object(dmod, "db", stub), \
         patch.object(_gm, "geocode_and_persist_customer", _fake_gp), \
         patch("routers.dispatch_board.asyncio.sleep", new=_noop_sleep):
        asyncio.run(dmod.geocode_backfill_all_tenants_boot())
    assert [c[0] for c in calls] == ["c1", "c2"]
    # Sentinel upsert fired with the right shape.
    assert len(stub.migration_status.upserts) == 1
    _u = stub.migration_status.upserts[0]
    assert _u["filter"] == {"key": "geocode_backfill_v2",
                              "tenant_id": "T-new"}
    assert _u["upsert"] is True
    _set = _u["update"]["$set"]
    assert _set["key"] == "geocode_backfill_v2"
    assert _set["tenant_id"] == "T-new"
    assert _set["run_version"] == "C3"
    assert "completed_at" in _set


def test_boot_sweep_does_NOT_write_sentinel_when_a_customer_errors():
    """Belt-and-suspenders — only upsert on CLEAN sweep."""
    from routers import dispatch_board as dmod

    stub = _StubDb(
        tenants=[{"id": "T-partial", "slug": "partial-tenant"}],
        customers={"T-partial": [{"id": "c1"}, {"id": "c2"}]},
        migration_status=[],
    )
    async def _bad_gp(cid, tid, *, trigger_reason=None):
        if cid == "c2":
            raise RuntimeError("boom")
        return True
    import services.google_maps.geocoding as _gm
    with patch.object(dmod, "db", stub), \
         patch.object(_gm, "geocode_and_persist_customer", _bad_gp), \
         patch("routers.dispatch_board.asyncio.sleep", new=_noop_sleep):
        asyncio.run(dmod.geocode_backfill_all_tenants_boot())
    assert stub.migration_status.upserts == []


async def _noop_sleep(_s):
    return None


# ─────────────────────────────────────────────────────────────────
# Lead-Sense widget-autocomplete short-circuit
# ─────────────────────────────────────────────────────────────────
class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []
    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def test_lead_sense_widget_place_id_short_circuits_background_geocode(monkeypatch):
    from routers import leads as lmod
    from services.google_maps.geocode_trigger import GeocodeTrigger

    log = _FakeCollection()
    class _StubDbLeads:
        geocode_call_log = log
        leads = _FakeCollection()

    monkeypatch.setattr(lmod, "db", _StubDbLeads(), raising=True)

    bg = _FakeBackgroundTasks()
    lead = {
        "id": "L-1", "tenant_id": "T-1",
        "service_address": "123 Widget Ave",
        "latitude": 33.57, "longitude": -112.08,
        "custom_fields": {"autocomplete_place_id": "ChIJ-WIDGET-123"},
    }
    lmod._maybe_backfill_lead_geocode(
        bg, lead, trigger_reason=GeocodeTrigger.LEAD_CREATE_PUBLIC,
    )
    # No background GEOCODE scheduled — widget guard engaged.
    # Instead ONE telemetry task is queued on the request's
    # background_tasks so the log row writes after response-send.
    assert len(bg.tasks) == 1
    _fn, _args, _kwargs = bg.tasks[0]
    assert _fn is lmod._run_lead_widget_log
    # Run the queued task to materialize the log row.
    asyncio.run(_fn(*_args, **_kwargs))
    assert len(log.inserted) == 1
    row = log.inserted[0]
    assert row["trigger_reason"] == GeocodeTrigger.LEAD_CREATE_PUBLIC.value
    assert row["outcome"] == "skipped_cached"
    assert row["entity_type"] == "lead"
    assert row["entity_id"] == "L-1"
    assert row["tenant_id"] == "T-1"
    assert row["error"] == "widget_autocomplete_resolved"


def test_lead_without_place_id_still_short_circuits_on_latlng_but_no_log(monkeypatch):
    """Legacy behavior preservation — a lead with lat/lng but no
    widget place_id simply skips the background task (no log row).
    This keeps the broader widget-savings telemetry attributable."""
    from routers import leads as lmod
    from services.google_maps.geocode_trigger import GeocodeTrigger

    log = _FakeCollection()
    class _StubDbLeads:
        geocode_call_log = log
        leads = _FakeCollection()

    monkeypatch.setattr(lmod, "db", _StubDbLeads(), raising=True)

    bg = _FakeBackgroundTasks()
    lead = {
        "id": "L-2", "tenant_id": "T-1",
        "service_address": "123 Legacy Rd",
        "latitude": 33.57, "longitude": -112.08,
        # No custom_fields.autocomplete_place_id
    }
    lmod._maybe_backfill_lead_geocode(
        bg, lead, trigger_reason=GeocodeTrigger.LEAD_CREATE_PUBLIC,
    )
    assert bg.tasks == []
    assert log.inserted == []


# ─────────────────────────────────────────────────────────────────
# Regression — cosmetic PATCH on an unchanged address
# ─────────────────────────────────────────────────────────────────
def test_cosmetic_customer_patch_hash_match_skips_geocode_api_call(monkeypatch):
    """A customer PATCH that doesn't touch the address must NOT hit
    Google. Previously, every PATCH that passed ``trigger_reason=
    CUSTOMER_PATCH_ADDR_CHANGE`` would re-cache the result for 30d
    without consulting the fingerprint; C3 adds the hash short-
    circuit so a cosmetic rename / phone update / VIP flag flip is
    free."""
    from services.google_maps.geocoding import (
        geocode_and_persist_customer, hash_address,
    )
    from services.google_maps.geocode_trigger import GeocodeTrigger

    addr = "500 Unchanged Blvd"
    cust_doc = {
        "id": "C-x", "tenant_id": "T-x",
        "service_address": addr,
        "latitude": 33.57, "longitude": -112.08,
        "service_lat": 33.57, "service_lng": -112.08,
        "geocode_address_hash": hash_address(addr),
        # Fresh enough stamp — but hash match wins first anyway.
        "geocoded_at": datetime.now(timezone.utc).isoformat(),
    }

    class _StubDbC:
        geocode_call_log = _FakeCollection()
        class _CustomersStub:
            async def find_one(self_inner, query, *_a, **_kw):
                if query.get("id") == "C-x":
                    return dict(cust_doc)
                return None
            async def update_one(self_inner, *_a, **_kw):
                raise AssertionError("should not update — unchanged addr")
        customers = _CustomersStub()

    # Patch ``geocode_address`` so a leaked API call explodes the test.
    import services.google_maps.geocoding as _gm
    monkeypatch.setattr(_gm, "db", _StubDbC(), raising=True)
    async def _bomb(*_a, **_kw):
        raise AssertionError("geocode_address must NOT be called "
                              "when hash matches")
    monkeypatch.setattr(_gm, "geocode_address", _bomb, raising=True)

    did = asyncio.run(geocode_and_persist_customer(
        "C-x", "T-x",
        trigger_reason=GeocodeTrigger.CUSTOMER_PATCH_ADDR_CHANGE,
    ))
    assert did is False
    # Telemetry row with the right outcome.
    assert len(_StubDbC.geocode_call_log.inserted) == 1
    row = _StubDbC.geocode_call_log.inserted[0]
    assert row["outcome"] == "skipped_unchanged"
    assert row["trigger_reason"] == \
        GeocodeTrigger.CUSTOMER_PATCH_ADDR_CHANGE.value


def test_source_level_wiring_anchors():
    """Belt-and-suspenders — every call path visibly imports and
    uses ``should_geocode`` so a future merge can't silently drop
    the guard."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parent.parent
    for rel, needle in [
        ("services/google_maps/geocoding.py", "def should_geocode"),
        ("services/google_maps/geocoding.py", "_CACHE_TTL_DAYS = 180"),
        ("services/google_maps/geocoding.py", "hash_address"),
        ("routers/leads.py", "should_geocode"),
        ("routers/leads.py", "autocomplete_place_id"),
        ("routers/leads.py", "widget_autocomplete_resolved"),
        ("routers/dispatch_board.py", "geocode_backfill_v2"),
    ]:
        src = (repo / rel).read_text(encoding="utf-8")
        assert needle in src, f"missing anchor {needle!r} in {rel}"
