"""P0-GEOCODE-LEAK-C2 · TD-62 (Feb-2026).

Pytest coverage for the append-only ``db.geocode_call_log``
instrumentation + the ``/admin/diagnostics/geocode-usage``
diagnostics endpoint.

Scope boundaries honoured:
  * No change to the shipped C1 ``ENABLE_BOOT_GEOCODE_BACKFILL``
    gate — tests do NOT touch ``server.py``.
  * No boot-sweep sentinel (that's C3).
  * No TTL change on ``_CACHE_TTL_DAYS`` (also C3).
  * Pure instrumentation — the geocode behaviour is byte-identical
    to pre-C2 EXCEPT for the per-call log row insert, which is
    wrapped in a fail-safe try/except so a Mongo outage NEVER
    blocks the geocode result.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# 1. Enum shape + classifier helper
# ─────────────────────────────────────────────────────────────────
def test_geocode_trigger_enum_covers_all_required_reasons():
    from services.google_maps.geocode_trigger import GeocodeTrigger

    required = {
        "property_create", "property_patch_addr_change",
        "customer_create", "customer_patch_addr_change",
        "lead_create_public", "lead_create_sense_convert",
        "csv_import", "manual_regeocode", "admin_backfill",
        "boot_sweep", "operator_force",
        "tenant_hq_patch", "ai_measure_resolve", "unknown",
    }
    actual = {t.value for t in GeocodeTrigger}
    assert required.issubset(actual), (
        f"Missing trigger_reason values: {required - actual}"
    )


def test_geocode_outcome_enum_covers_all_required_outcomes():
    from services.google_maps.geocode_trigger import GeocodeOutcome

    required = {"hit", "skipped_cached", "skipped_unchanged",
                "no_addr", "error"}
    actual = {o.value for o in GeocodeOutcome}
    assert required == actual, f"Outcome enum drift: {actual}"


def test_is_backend_trigger_classifier():
    from services.google_maps.geocode_trigger import (
        GeocodeTrigger, is_backend_trigger,
    )

    # BACKEND side
    assert is_backend_trigger(GeocodeTrigger.BOOT_SWEEP.value)
    assert is_backend_trigger(GeocodeTrigger.ADMIN_BACKFILL.value)
    assert is_backend_trigger(GeocodeTrigger.CSV_IMPORT.value)
    assert is_backend_trigger(GeocodeTrigger.MANUAL_REGEOCODE.value)
    # Unknown classified as backend to avoid under-counting the leak.
    assert is_backend_trigger(GeocodeTrigger.UNKNOWN.value)

    # USER side
    assert not is_backend_trigger(GeocodeTrigger.PROPERTY_CREATE.value)
    assert not is_backend_trigger(
        GeocodeTrigger.CUSTOMER_PATCH_ADDR_CHANGE.value
    )
    assert not is_backend_trigger(GeocodeTrigger.LEAD_CREATE_PUBLIC.value)
    assert not is_backend_trigger(GeocodeTrigger.OPERATOR_FORCE.value)
    assert not is_backend_trigger(GeocodeTrigger.TENANT_HQ_PATCH.value)


def test_hash_address_is_stable_and_case_insensitive():
    from services.google_maps.geocode_trigger import hash_address

    h1 = hash_address("123 Main St, Phoenix AZ")
    h2 = hash_address("  123 Main St, Phoenix AZ  ")
    h3 = hash_address("123 MAIN ST, PHOENIX AZ")
    assert h1 == h2 == h3
    assert hash_address("") == ""
    assert len(h1) == 64        # sha256 hex


# ─────────────────────────────────────────────────────────────────
# 2. write_geocode_log — fail-safe behaviour
# ─────────────────────────────────────────────────────────────────
class _FakeCollection:
    def __init__(self, *, raise_on_insert: bool = False):
        self.inserted: List[Dict[str, Any]] = []
        self.raise_on_insert = raise_on_insert

    async def insert_one(self, row: Dict[str, Any]) -> None:
        if self.raise_on_insert:
            raise RuntimeError("Mongo transient failure")
        self.inserted.append(row)


class _FakeDb:
    def __init__(self, *, raise_on_insert: bool = False):
        self.geocode_call_log = _FakeCollection(
            raise_on_insert=raise_on_insert,
        )


class _FakeLogger:
    def __init__(self):
        self.warnings: List[str] = []

    def warning(self, msg: str, *args: Any) -> None:
        try:
            self.warnings.append(msg % args if args else msg)
        except Exception:
            self.warnings.append(str(msg))


def test_write_geocode_log_inserts_one_row_with_all_fields():
    from services.google_maps.geocode_trigger import (
        GeocodeOutcome, GeocodeTrigger, write_geocode_log,
    )

    db = _FakeDb()
    logger = _FakeLogger()
    started_at = datetime.now(timezone.utc) - timedelta(milliseconds=42)

    asyncio.run(write_geocode_log(
        db_conn=db, logger=logger,
        tenant_id="tenant-1", entity_type="customer",
        entity_id="cust-1", address="123 Main St, Phoenix AZ",
        trigger_reason=GeocodeTrigger.CUSTOMER_CREATE.value,
        outcome=GeocodeOutcome.HIT.value,
        lat=33.5, lng=-112.1, started_at=started_at,
        api_key="AIzaSyFOOBAR_abc1234",
    ))

    assert len(db.geocode_call_log.inserted) == 1
    row = db.geocode_call_log.inserted[0]
    assert row["tenant_id"] == "tenant-1"
    assert row["entity_type"] == "customer"
    assert row["entity_id"] == "cust-1"
    assert row["address"] == "123 Main St, Phoenix AZ"
    assert row["address_hash"] != ""
    assert row["trigger_reason"] == "customer_create"
    assert row["outcome"] == "hit"
    assert row["lat"] == 33.5
    assert row["lng"] == -112.1
    assert row["error"] is None
    assert isinstance(row["called_at"], datetime)
    assert row["duration_ms"] is not None and row["duration_ms"] >= 0
    assert row["api_key_fingerprint"] == "1234"


def test_write_geocode_log_fail_safe_on_mongo_error():
    """A Mongo insert failure MUST NOT raise — the geocode result
    comes first; telemetry is best-effort."""
    from services.google_maps.geocode_trigger import write_geocode_log

    db = _FakeDb(raise_on_insert=True)
    logger = _FakeLogger()
    # Must not raise.
    asyncio.run(write_geocode_log(
        db_conn=db, logger=logger,
        tenant_id="t", entity_type="lead", entity_id="l",
        address="", trigger_reason="unknown", outcome="error",
    ))
    # Warning logged, no exception.
    assert any("geocode-call-log" in w for w in logger.warnings), logger.warnings


def test_write_geocode_log_truncates_address_at_512_chars():
    from services.google_maps.geocode_trigger import write_geocode_log

    db = _FakeDb()
    big = "A" * 2000
    asyncio.run(write_geocode_log(
        db_conn=db, logger=_FakeLogger(),
        tenant_id="t", entity_type="x", entity_id=None,
        address=big, trigger_reason="unknown", outcome="hit",
    ))
    assert len(db.geocode_call_log.inserted[0]["address"]) == 512


def test_write_geocode_log_api_key_fingerprint_skipped_when_missing():
    from services.google_maps.geocode_trigger import write_geocode_log

    db = _FakeDb()
    asyncio.run(write_geocode_log(
        db_conn=db, logger=_FakeLogger(),
        tenant_id="t", entity_type="x", entity_id=None,
        address="x", trigger_reason="unknown", outcome="hit",
        api_key=None,
    ))
    assert db.geocode_call_log.inserted[0]["api_key_fingerprint"] is None

    db2 = _FakeDb()
    asyncio.run(write_geocode_log(
        db_conn=db2, logger=_FakeLogger(),
        tenant_id="t", entity_type="x", entity_id=None,
        address="x", trigger_reason="unknown", outcome="hit",
        api_key="abc",       # too short
    ))
    assert db2.geocode_call_log.inserted[0]["api_key_fingerprint"] is None


# ─────────────────────────────────────────────────────────────────
# 3. Source-level invariants on the live call-sites
# ─────────────────────────────────────────────────────────────────
def test_geocode_address_signature_accepts_trigger_reason():
    """``geocode_address`` must accept the new kwargs so legacy
    callers that don't pass ``trigger_reason`` still work."""
    import inspect
    from services.google_maps.geocoding import geocode_address

    sig = inspect.signature(geocode_address)
    assert "trigger_reason" in sig.parameters
    assert "entity_type" in sig.parameters
    assert "entity_id" in sig.parameters
    # Default must be UNKNOWN enum member — callers that forget to
    # pass get flagged as a telemetry gap.
    from services.google_maps.geocode_trigger import GeocodeTrigger
    assert sig.parameters["trigger_reason"].default == GeocodeTrigger.UNKNOWN


def test_wrappers_accept_trigger_reason():
    import inspect
    from services.google_maps.geocoding import (
        geocode_and_persist_customer,
        geocode_and_persist_job,
        geocode_and_persist_property,
    )

    for fn in (geocode_and_persist_customer,
                geocode_and_persist_job,
                geocode_and_persist_property):
        sig = inspect.signature(fn)
        assert "trigger_reason" in sig.parameters, fn.__name__


def test_critical_call_sites_pass_a_trigger_reason():
    """Grep-style source invariant: the 7 named call-sites in the
    C2 dispatch each pass a ``trigger_reason`` keyword to the
    helper.  Regression guard against a merge-conflict silently
    dropping the arg."""
    import pathlib

    cases = [
        ("backend/routers/customers.py", "CUSTOMER_CREATE"),
        ("backend/routers/customers.py", "CUSTOMER_PATCH_ADDR_CHANGE"),
        ("backend/routers/customers.py", "CSV_IMPORT"),
        ("backend/routers/customers.py", "OPERATOR_FORCE"),
        ("backend/routers/properties.py", "PROPERTY_CREATE"),
        ("backend/routers/properties.py", "PROPERTY_PATCH_ADDR_CHANGE"),
        ("backend/routers/dispatch_board.py", "BOOT_SWEEP"),
        ("backend/routers/dispatch_board.py", "MANUAL_REGEOCODE"),
        ("backend/routers/admin_customer_geocode_backfill.py", "ADMIN_BACKFILL"),
        ("backend/routers/admin_property_geocode_diagnostics.py", "ADMIN_BACKFILL"),
        ("backend/routers/leads.py", "LEAD_CREATE_PUBLIC"),
    ]
    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    for rel, needle in cases:
        src = (repo / rel).read_text(encoding="utf-8")
        assert needle in src, (
            f"Trigger_reason {needle} missing from {rel} — "
            "a merge may have dropped the kwarg."
        )


# ─────────────────────────────────────────────────────────────────
# 4. Diagnostics endpoint — rollup logic
# ─────────────────────────────────────────────────────────────────
def test_diagnostics_router_mounted_in_server_py():
    """Lock the include_router registration so a merge can't
    accidentally drop the endpoint."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    src = (repo / "backend/server.py").read_text(encoding="utf-8")
    assert "admin_geocode_diagnostics" in src
    assert "_c2_geocode_diag.router" in src


def test_diagnostics_endpoint_requires_admin():
    """Route decorator must declare the ``require_admin``
    dependency — swap-in of a non-admin dep would leak the full
    cross-tenant rollup."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    src = (repo / "backend/routers/admin_geocode_diagnostics.py").read_text(
        encoding="utf-8"
    )
    assert "require_admin" in src
    assert "Depends(require_admin)" in src
    assert "/admin/diagnostics/geocode-usage" in src


def test_diagnostics_days_param_bounded_1_to_90():
    import pathlib
    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    src = (repo / "backend/routers/admin_geocode_diagnostics.py").read_text(
        encoding="utf-8"
    )
    # Default + bounds are declared via FastAPI Query(..., ge=1, le=90).
    assert "ge=1" in src and "le=_MAX_DAYS" in src
    assert "_MAX_DAYS = 90" in src
    assert "_DEFAULT_DAYS = 7" in src


# ─────────────────────────────────────────────────────────────────
# 5. Lifespan TTL index invariants
# ─────────────────────────────────────────────────────────────────
def test_server_py_provisions_geocode_call_log_indexes():
    """TTL index + 3 secondary indexes must be registered in the
    lifespan handler.  Index creation failures are swallowed; this
    test only locks that the creation CALLS are present."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parent.parent.parent
    src = (repo / "backend/server.py").read_text(encoding="utf-8")
    assert "db.geocode_call_log.create_index" in src
    assert "expireAfterSeconds=7_776_000" in src        # 90 days
    assert "geocode_call_log_ttl_90d" in src
    assert "geocode_call_log_by_tenant_recent" in src
    assert "geocode_call_log_by_trigger_recent" in src
    assert "geocode_call_log_by_addr_recent" in src
