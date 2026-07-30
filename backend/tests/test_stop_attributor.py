"""Phase G5b · Feb-2026 — Pure-function tests for stop_attributor.

DB-backed tests live in ``test_attribution_api.py`` — they hit the
live backend so we don't have to wrestle with per-test Motor event
loops.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from services.stop_attributor import (  # noqa: E402
    _parse_iso, _stop_day_yyyy_mm_dd,
    job_address_latlon_from_docs,
)


class TestAddressResolution:
    def test_job_lat_lon_wins(self):
        j = {"lat": 33.5, "lon": -112.0}
        assert job_address_latlon_from_docs(j) == (33.5, -112.0)

    def test_property_lat_lng_used_when_job_missing(self):
        j = {"lat": None, "lon": None, "property_id": "p1"}
        prop = {"lat": 33.5, "lng": -112.0}
        assert job_address_latlon_from_docs(j, prop=prop) == (33.5, -112.0)

    def test_customer_service_lat_lng_used_when_others_missing(self):
        j = {"customer_id": "c1"}
        cust = {"service_lat": 33.5, "service_lng": -112.0}
        assert job_address_latlon_from_docs(j, customer=cust) == (33.5, -112.0)

    def test_none_when_no_geo_anywhere(self):
        assert job_address_latlon_from_docs({}) is None
        assert job_address_latlon_from_docs({"lat": None, "lon": None}) is None

    def test_property_beats_customer(self):
        j = {"customer_id": "c1", "property_id": "p1"}
        prop = {"lat": 33.5, "lng": -112.0}
        cust = {"service_lat": 34.0, "service_lng": -111.0}
        # Property wins.
        assert job_address_latlon_from_docs(j, customer=cust,
                                              prop=prop) == (33.5, -112.0)

    def test_bad_type_falls_through(self):
        j = {"lat": "not-a-number", "lon": "nan"}
        cust = {"service_lat": 33.5, "service_lng": -112.0}
        assert job_address_latlon_from_docs(j, customer=cust) == (33.5, -112.0)


class TestDayHelper:
    def test_parses_z_suffix(self):
        assert _stop_day_yyyy_mm_dd("2026-02-14T10:00:00Z") == "2026-02-14"

    def test_parses_offset(self):
        assert _stop_day_yyyy_mm_dd("2026-02-14T10:00:00+00:00") == "2026-02-14"

    def test_none_for_junk(self):
        assert _stop_day_yyyy_mm_dd("garbage") is None
        assert _stop_day_yyyy_mm_dd(None) is None
        assert _stop_day_yyyy_mm_dd("") is None

    def test_parse_iso_returns_utc(self):
        dt = _parse_iso("2026-02-14T10:00:00")
        assert dt is not None
        # Naive → coerced to UTC.
        assert dt.tzinfo is not None
