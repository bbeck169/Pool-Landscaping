"""Ticket 287998 — GET /api/jobs showed another customer's address.

Jobs whose ``property_id`` points at a DIFFERENT customer's property used to
return the stale stored ``job.address`` (and the coord ladder's ownership
guard never fired because the properties projection lacked ``customer_id``).
Data shapes below mirror the production rows from the ticket.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.address_resolver import correct_cross_customer_job_addresses  # noqa: E402
from services.geo_resolver import resolve_job_coordinates_with_property  # noqa: E402

JOLENE_PROP = {
    "id": "c066", "customer_id": "jolene", "label": "Main",
    "address": {"line1": "22442 N 80th Lane", "city": "Peoria",
                "state": "AZ", "postal_code": "85383"},
}
CARL_PROP = {
    "id": "carl-p", "customer_id": "carl", "label": "Main", "sort_order": 0,
    "address": {"line1": "27059 North 130th Drive", "city": "Peoria",
                "state": "AZ", "postal_code": "85383"},
}
CUSTS = {
    "carl": {"id": "carl", "address": "27059 North 130th Drive, Peoria, AZ, 85383",
             "service_lat": 33.728552, "service_lng": -112.340212},
    "jolene": {"id": "jolene", "address": "22442 N 80th Lane, Peoria, AZ, 85383"},
}


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, _n):
        return list(self._rows)


class _Props:
    def __init__(self, rows, boom=False):
        self.rows, self.boom, self.last_query = rows, boom, None

    def find(self, query, _proj=None):
        self.last_query = query
        if self.boom:
            raise RuntimeError("db down")
        ids = query["customer_id"]["$in"]
        return _Cursor([r for r in self.rows if r["customer_id"] in ids])


class _DB:
    def __init__(self, rows, boom=False):
        self.properties = _Props(rows, boom)


def _run(db, docs, pmap):
    return asyncio.run(correct_cross_customer_job_addresses(db, "t1", docs, CUSTS, pmap))


def test_foreign_property_job_gets_own_customers_address():
    job = {"id": "j1", "customer_id": "carl", "property_id": "c066",
           "address": "22442 N 80th Lane, Peoria, AZ 85383"}
    n = _run(_DB([CARL_PROP]), [job], {"c066": JOLENE_PROP})
    assert n == 1
    assert job["address"] == "27059 North 130th Drive, Peoria, AZ 85383"
    assert job["property_address"] == "27059 North 130th Drive, Peoria, AZ 85383"
    assert job["address_corrected"] is True


def test_own_property_job_untouched():
    job = {"id": "j2", "customer_id": "jolene", "property_id": "c066",
           "address": "22442 N 80th Lane, Peoria, AZ 85383"}
    db = _DB([])
    assert _run(db, [job], {"c066": JOLENE_PROP}) == 0
    assert job["address"] == "22442 N 80th Lane, Peoria, AZ 85383"
    assert "address_corrected" not in job
    assert db.properties.last_query is None  # no extra query on the happy path


def test_falls_back_to_customer_address_when_no_own_property():
    job = {"id": "j3", "customer_id": "carl", "property_id": "c066",
           "address": "22442 N 80th Lane, Peoria, AZ 85383"}
    _run(_DB([]), [job], {"c066": JOLENE_PROP})
    assert job["address"] == "27059 North 130th Drive, Peoria, AZ, 85383"


def test_db_failure_is_non_fatal():
    job = {"id": "j4", "customer_id": "carl", "property_id": "c066",
           "address": "22442 N 80th Lane, Peoria, AZ 85383"}
    _run(_DB([], boom=True), [job], {"c066": JOLENE_PROP})
    assert job["address"] == "27059 North 130th Drive, Peoria, AZ, 85383"


def test_legacy_property_without_owner_is_trusted():
    prop = {"id": "legacy", "label": "x", "address": {"line1": "1 Main St"}}
    job = {"id": "j5", "customer_id": "carl", "property_id": "legacy", "address": "1 Main St"}
    assert _run(_DB([]), [job], {"legacy": prop}) == 0


def test_coord_guard_fires_once_projection_carries_customer_id():
    job = {"id": "j6", "customer_id": "carl", "property_id": "c066"}
    foreign = dict(JOLENE_PROP, latitude=33.6874, longitude=-112.2327)
    lat, lng, src = resolve_job_coordinates_with_property(job, CUSTS, {"c066": foreign})
    assert (lat, lng, src) == (33.728552, -112.340212, "customer")
