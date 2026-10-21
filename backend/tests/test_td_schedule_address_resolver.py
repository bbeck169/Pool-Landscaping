"""TD-schedule-address · Feb-2026 — FK-ladder resolver tests.

Pure unit tests for ``services.address_resolver.resolve_job_address_from_batches``
+ ``format_property_address``. The sync helper takes already-batched
maps (``cust_map`` / ``prop_map``) and returns the live address;
no DB round-trips, no asyncio.

Scope per operator dispatch:
  (a) FK ladder resolves to property address when present.
  (b) Falls back correctly when property missing / deleted / empty.
  (c) Final fallback to ``jobs.address`` snapshot when ladder yields
      nothing.
  (d) Does NOT regress coord resolution (coord path is unchanged;
      we smoke-test the extended projection by asserting
      ``build_property_coord_lookup`` returns the expected keys).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from services.address_resolver import (
    format_property_address,
    resolve_job_address_from_batches,
)


# ─── Helpers ─────────────────────────────────────────────────────
def _prop(line1="123 Live St", city="Phoenix", state="AZ",
            postal="85083", **extra) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "id": extra.pop("id", "p1"),
        "address": {
            "line1": line1, "city": city, "state": state,
            "postal_code": postal,
        },
    }
    doc.update(extra)
    return doc


def _cust(cid="c1", primary_property_id=None, service_address=None,
             address=None, billing_address=None) -> Dict[str, Any]:
    return {"id": cid, "primary_property_id": primary_property_id,
                "service_address": service_address, "address": address,
                "billing_address": billing_address}


def _job(jid="j1", cid="c1", property_id=None, address=None,
            site_address=None) -> Dict[str, Any]:
    return {"id": jid, "customer_id": cid, "property_id": property_id,
                "address": address, "site_address": site_address}


# ─── §1 · format_property_address compose ────────────────────────
def test_format_composes_full_address():
    out = format_property_address(_prop())
    assert out == "123 Live St, Phoenix, AZ 85083"


def test_format_returns_empty_for_non_dict_address():
    assert format_property_address({"address": "flat-string"}) == ""
    assert format_property_address({}) == ""


def test_format_handles_partial_fields():
    out = format_property_address({"address": {
        "line1": "", "line2": "Unit 7", "city": "Mesa",
        "state": "AZ", "postal_code": "",
    }})
    assert out == "Unit 7, Mesa, AZ"


# ─── §2 · (a) Rung 1 — job.property_id wins ──────────────────────
def test_rung1_job_property_id_resolves_live():
    prop_map = {"p-live": _prop(line1="1 CURRENT Way", id="p-live")}
    cust_map = {"c1": _cust(primary_property_id="p-stale",
                                   service_address="STALE service addr")}
    j = _job(property_id="p-live",
                address="STALE 5207 West Bajada Road, Phoenix, AZ 85083")
    assert resolve_job_address_from_batches(j, cust_map, prop_map) \
        == "1 CURRENT Way, Phoenix, AZ 85083"


# ─── §3 · Rung 2 — customer.primary_property_id ──────────────────
def test_rung2_customer_primary_property_id():
    prop_map = {"p-cust": _prop(line1="22 CUST-PROP Rd", id="p-cust")}
    cust_map = {"c1": _cust(primary_property_id="p-cust",
                                   service_address="noise addr")}
    j = _job(property_id=None, address="STALE addr")
    assert resolve_job_address_from_batches(j, cust_map, prop_map) \
        == "22 CUST-PROP Rd, Phoenix, AZ 85083"


# ─── §4 · (b) deleted property → skips rung, falls to rung 3 ─────
def test_deleted_property_falls_to_customer_text():
    prop_map = {"p-del": _prop(line1="Old", id="p-del",
                                       deleted_at="2026-01-01T00:00:00Z")}
    cust_map = {"c1": _cust(primary_property_id="p-del",
                                   service_address="47 Service Current Rd")}
    j = _job(property_id="p-del", address="snapshot")
    assert resolve_job_address_from_batches(j, cust_map, prop_map) \
        == "47 Service Current Rd"


def test_property_missing_from_batch_falls_through():
    prop_map: Dict[str, Any] = {}  # pid in job but not in batch
    cust_map = {"c1": _cust(service_address="47 Service Current Rd")}
    j = _job(property_id="p-missing", address="snapshot")
    assert resolve_job_address_from_batches(j, cust_map, prop_map) \
        == "47 Service Current Rd"


def test_property_with_empty_address_falls_through():
    prop_map = {"p-empty": {"id": "p-empty", "address": {}}}
    cust_map = {"c1": _cust(primary_property_id="p-empty",
                                   service_address="47 Current Rd")}
    j = _job(property_id="p-empty", address="snapshot")
    assert resolve_job_address_from_batches(j, cust_map, prop_map) \
        == "47 Current Rd"


# ─── §5 · Rung 3 — customer text ladder service → address → billing ─
def test_rung3_prefers_service_over_address_over_billing():
    cust_map = {"c1": _cust(service_address="SERVICE 1",
                                   address="ADDR 2",
                                   billing_address="BILLING 3")}
    j = _job(address=None)
    assert resolve_job_address_from_batches(j, cust_map, {}) == "SERVICE 1"

    cust_map2 = {"c1": _cust(service_address=None, address="ADDR 2",
                                     billing_address="BILLING 3")}
    assert resolve_job_address_from_batches(j, cust_map2, {}) == "ADDR 2"

    cust_map3 = {"c1": _cust(service_address=None, address=None,
                                     billing_address="BILLING 3")}
    assert resolve_job_address_from_batches(j, cust_map3, {}) == "BILLING 3"


# ─── §6 · (c) Rung 4 — job snapshot fallback ──────────────────────
def test_rung4_job_address_snapshot_final_fallback():
    # Property + customer both empty → job.address snapshot wins.
    j = _job(address="100 Snapshot Dr, Phoenix, AZ")
    assert resolve_job_address_from_batches(j, {}, {}) \
        == "100 Snapshot Dr, Phoenix, AZ"


def test_rung4_site_address_when_address_missing():
    j = _job(address=None, site_address="200 Site St")
    assert resolve_job_address_from_batches(j, {}, {}) == "200 Site St"


def test_everything_empty_returns_empty_string():
    j = _job(address=None, site_address=None)
    assert resolve_job_address_from_batches(j, {}, {}) == ""


# ─── §7 · The Michael Rauschenberger drift repro ────────────────
def test_rauschenberger_drift_repro_resolves_to_current_property():
    """Fixture-sourced repro from operator reality-check: when a
    customer with a stale ``jobs.address`` snapshot of
    ``5207 West Bajada Road`` is linked to a property with a new
    current address, the schedule endpoint now returns the CURRENT
    property address instead of the stale snapshot."""
    prop_map = {"p-rau-current": _prop(
        line1="9876 Current Dr", city="Phoenix", state="AZ",
        postal="85083", id="p-rau-current",
    )}
    cust_map = {"c-rau": _cust(cid="c-rau",
                                       primary_property_id="p-rau-current")}
    j = _job(jid="j-rau", cid="c-rau", property_id=None,
                address="5207 West Bajada Road, Phoenix, AZ 85083")
    out = resolve_job_address_from_batches(j, cust_map, prop_map)
    assert out == "9876 Current Dr, Phoenix, AZ 85083"
    assert "Bajada" not in out  # snapshot NEVER leaks when ladder resolves


# ─── §8 · (d) coord-resolution smoke — unchanged projection shape ─
def test_coord_lookup_projection_still_carries_coord_fields():
    """Ensures the TD-schedule-address projection extension kept the
    coord fields on ``build_property_coord_lookup``'s result shape
    (lat/lng/latitude/longitude). This is a shape-contract smoke —
    full coord-resolver tests already cover the resolve logic."""
    import inspect
    from services import geo_resolver as gr
    src = inspect.getsource(gr.build_property_coord_lookup)
    # Projection dict must still include all 4 coord field names.
    for field in ("latitude", "longitude", "lat", "lng"):
        assert f'"{field}": 1' in src, (
            f"coord field '{field}' dropped from projection — "
            f"TD-schedule-address regression"
        )
    # And must now include the new address/deleted_at fields.
    assert '"address": 1' in src
    assert '"deleted_at": 1' in src
