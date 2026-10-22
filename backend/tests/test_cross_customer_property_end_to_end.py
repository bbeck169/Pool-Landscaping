"""Ticket 287964 - end-to-end: batch lookup -> resolvers, plus generator + email paths."""
from __future__ import annotations

import asyncio

from services.address_resolver import resolve_job_address_from_batches
from services.geo_resolver import (
    build_property_coord_lookup,
    resolve_job_coordinates_with_property,
)

PROPS = [
    {"id": "p_howell", "tenant_id": "t1", "customer_id": "c_howell",
     "latitude": 33.8, "longitude": -112.2,
     "address": {"line1": "22442 N 80th Lane", "city": "Peoria",
                 "state": "AZ", "postal_code": "85383"}},
    {"id": "p_hess", "tenant_id": "t1", "customer_id": "c_hess",
     "latitude": 33.5, "longitude": -112.0,
     "address": {"line1": "1 Hess Way", "city": "Peoria",
                 "state": "AZ", "postal_code": "85383"}},
]


class _Cursor:
    def __init__(self, rows, projection):
        self.rows = [{k: v for k, v in r.items() if k in projection} for r in rows]

    async def to_list(self, n):
        return self.rows[:n]


class _Props:
    def find(self, flt, projection):
        ids = set(flt["id"]["$in"])
        return _Cursor([p for p in PROPS if p["id"] in ids], projection)


class _DB:
    properties = _Props()


def test_real_projection_carries_owner_and_guard_fires():
    prop_map = asyncio.run(build_property_coord_lookup(
        _DB(), "t1", ["p_howell", "p_hess"]))
    assert prop_map["p_howell"]["customer_id"] == "c_howell"
    custs = {"c_hess": {"id": "c_hess", "primary_property_id": "p_hess"}}
    job = {"id": "j", "customer_id": "c_hess", "property_id": "p_howell"}
    assert resolve_job_address_from_batches(job, custs, prop_map) == \
        "1 Hess Way, Peoria, AZ 85383"


def test_coord_rung_ignores_other_customers_property():
    prop_map = asyncio.run(build_property_coord_lookup(
        _DB(), "t1", ["p_howell"]))
    job = {"id": "j", "customer_id": "c_hess", "property_id": "p_howell"}
    cust = {"c_hess": {"id": "c_hess", "service_lat": 33.5, "service_lng": -112.0}}
    lat, lng, src = resolve_job_coordinates_with_property(job, cust, prop_map)
    assert src != "property" and (lat, lng) != (33.8, -112.2)


def test_sources_contain_owner_guards():
    import pathlib
    base = pathlib.Path(__file__).resolve().parents[1]
    rec = (base / "routers/recurring_jobs.py").read_text()
    assert "property_owner_mismatch" in rec
    mail = (base / "services/auto_visit_email.py").read_text()
    assert "property_owner_mismatch" in mail
