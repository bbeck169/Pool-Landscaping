"""Feb-2026 · Routing Traffic-Aware phase — Routes API integration.

Patches the low-level Google Routes API HTTP path and asserts that
the outbound request body carries the correct ``routingPreference``
based on the per-tenant ``routing_traffic_aware`` Business Settings
flag.

Test cases (both drive the same public entrypoint —
:func:`services.google_maps.directions.optimize_route` — via the
in-process helper, patching the async ``_post`` layer):

  1. Tenant with ``routing_traffic_aware=True`` → outbound body
     contains ``"routingPreference": "TRAFFIC_AWARE"``.
  2. Tenant with ``routing_traffic_aware=False`` (default) →
     outbound body contains ``"routingPreference": "TRAFFIC_UNAWARE"``.

See /app/memory/FEATURE_ROUTING_TRAFFIC_AWARE.md.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest


class _FakeDB:
    """Minimal async Mongo shim — implements only ``tenants.find_one``.

    ``get_effective_business_settings`` calls
    ``db.tenants.find_one({"id": tenant_id}, {"_id": 0})``; we return
    the pre-seeded doc without spinning up Mongo. Everything else
    on the collection namespace raises so accidental extra queries
    are caught in test.
    """

    def __init__(self, tenant_doc: Dict[str, Any]):
        self._doc = tenant_doc

        class _Tenants:
            async def find_one(_self, query, projection=None):
                if query.get("id") == tenant_doc.get("id"):
                    return {k: v for k, v in tenant_doc.items()}
                return None

        self.tenants = _Tenants()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sniff_body_and_return_fake_route():
    """Return a ``(sniffed, fake_post)`` pair. ``sniffed`` is a
    mutable dict that will contain the outbound body after the
    optimize call. ``fake_post`` is the async coroutine to patch
    ``services.google_maps.directions._post`` with.
    """
    sniffed: Dict[str, Any] = {}

    async def fake_post(body: Dict[str, Any]):
        # Capture the outbound Routes API v2 body.
        sniffed.clear()
        sniffed.update(body or {})
        # Return a route shaped so ``_parse_route`` yields ordered
        # indices back to the caller.
        return {
            "routes": [
                {
                    "distanceMeters": 12345,
                    "duration": "600s",
                    "polyline": {"encodedPolyline": "abc"},
                    "optimizedIntermediateWaypointIndex": [1, 0],
                    "legs": [
                        {"distanceMeters": 5000, "duration": "300s"},
                        {"distanceMeters": 7000, "duration": "300s"},
                    ],
                }
            ]
        }

    return sniffed, fake_post


# ═════════════════════════════════════════════════════════════════════
# Case 1 · Traffic-aware ON → body contains TRAFFIC_AWARE.
# ═════════════════════════════════════════════════════════════════════
def test_traffic_aware_flag_flips_routing_preference_to_aware():
    from services.google_maps import directions as d

    fake_db = _FakeDB({"id": "t-aware", "routing_traffic_aware": True})
    sniffed, fake_post = _sniff_body_and_return_fake_route()

    async def _drive():
        with patch.object(d, "_post", side_effect=fake_post):
            with patch.object(d, "_API_KEY", "test-key"):
                return await d.optimize_route(
                    origin=(37.0, -122.0),
                    waypoints=[(37.1, -122.1), (37.2, -122.2)],
                    tenant_id="t-aware",
                    db_conn=fake_db,
                )

    result = _run(_drive())
    assert result is not None
    assert sniffed.get("routingPreference") == "TRAFFIC_AWARE"
    assert sniffed.get("optimizeWaypointOrder") is True


# ═════════════════════════════════════════════════════════════════════
# Case 2 · Traffic-aware OFF (default) → body contains TRAFFIC_UNAWARE.
# ═════════════════════════════════════════════════════════════════════
def test_traffic_aware_flag_off_keeps_routing_preference_unaware():
    from services.google_maps import directions as d

    fake_db = _FakeDB({"id": "t-plain", "routing_traffic_aware": False})
    sniffed, fake_post = _sniff_body_and_return_fake_route()

    async def _drive():
        with patch.object(d, "_post", side_effect=fake_post):
            with patch.object(d, "_API_KEY", "test-key"):
                return await d.optimize_route(
                    origin=(37.0, -122.0),
                    waypoints=[(37.1, -122.1), (37.2, -122.2)],
                    tenant_id="t-plain",
                    db_conn=fake_db,
                )

    result = _run(_drive())
    assert result is not None
    assert sniffed.get("routingPreference") == "TRAFFIC_UNAWARE"


# ═════════════════════════════════════════════════════════════════════
# Case 3 · No tenant_id → defaults to TRAFFIC_UNAWARE (byte-for-byte
# back-compat with pre-Feb-2026 call sites).
# ═════════════════════════════════════════════════════════════════════
def test_no_tenant_id_defaults_to_unaware():
    from services.google_maps import directions as d

    sniffed, fake_post = _sniff_body_and_return_fake_route()

    async def _drive():
        with patch.object(d, "_post", side_effect=fake_post):
            with patch.object(d, "_API_KEY", "test-key"):
                return await d.optimize_route(
                    origin=(37.0, -122.0),
                    waypoints=[(37.1, -122.1), (37.2, -122.2)],
                )

    result = _run(_drive())
    assert result is not None
    assert sniffed.get("routingPreference") == "TRAFFIC_UNAWARE"
