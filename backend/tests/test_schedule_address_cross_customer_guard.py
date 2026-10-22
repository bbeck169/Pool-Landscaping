"""Ticket 287964 - cross-customer property_id must never drive the schedule address.

Repro: a job / recurring-template-generated job carries a ``property_id``
owned by a DIFFERENT customer.  Before the guard the resolver's rung 1
trusted the FK blindly, so the other customer's street rendered on the card.
"""
from __future__ import annotations

from services.address_resolver import (
    property_belongs_to_customer,
    resolve_job_address_from_batches,
)


def _prop(pid, customer_id, line1):
    return {
        "id": pid, "customer_id": customer_id,
        "address": {"line1": line1, "city": "Peoria", "state": "AZ",
                    "postal_code": "85383"},
    }


PROPS = {
    "p_howell": _prop("p_howell", "c_howell", "22442 N 80th Lane"),
    "p_hess": _prop("p_hess", "c_hess", "1 Hess Way"),
}
CUSTS = {
    "c_howell": {"id": "c_howell", "primary_property_id": "p_howell"},
    "c_hess": {"id": "c_hess", "primary_property_id": "p_hess"},
    "c_nopp": {"id": "c_nopp", "service_address": "9 Own Street, Peoria, AZ 85383"},
}


def test_cross_customer_property_id_is_ignored_falls_to_own_primary_property():
    job = {"id": "j1", "customer_id": "c_hess", "property_id": "p_howell",
           "address": "stale snapshot"}
    out = resolve_job_address_from_batches(job, CUSTS, PROPS)
    assert out == "1 Hess Way, Peoria, AZ 85383"
    assert "80th" not in out


def test_cross_customer_falls_back_to_customer_address_when_no_primary():
    job = {"id": "j2", "customer_id": "c_nopp", "property_id": "p_howell"}
    assert resolve_job_address_from_batches(job, CUSTS, PROPS) == \
        "9 Own Street, Peoria, AZ 85383"


def test_cross_customer_falls_back_to_snapshot_as_last_resort():
    job = {"id": "j3", "customer_id": "c_unknown", "property_id": "p_howell",
           "address": "7 Snapshot Rd, Peoria, AZ 85383"}
    assert resolve_job_address_from_batches(job, CUSTS, PROPS) == \
        "7 Snapshot Rd, Peoria, AZ 85383"


def test_matching_owner_still_resolves_via_property():
    job = {"id": "j4", "customer_id": "c_howell", "property_id": "p_howell"}
    assert resolve_job_address_from_batches(job, CUSTS, PROPS) == \
        "22442 N 80th Lane, Peoria, AZ 85383"


def test_legacy_property_without_customer_id_is_still_trusted():
    props = {"p_old": {"id": "p_old", "address": {"line1": "5 Old Rd",
             "city": "Peoria", "state": "AZ", "postal_code": "85383"}}}
    job = {"id": "j5", "customer_id": "c_hess", "property_id": "p_old"}
    assert resolve_job_address_from_batches(job, CUSTS, props) == \
        "5 Old Rd, Peoria, AZ 85383"


def test_ownership_helper():
    assert property_belongs_to_customer(PROPS["p_howell"], "c_howell")
    assert not property_belongs_to_customer(PROPS["p_howell"], "c_hess")
    assert property_belongs_to_customer({"id": "x"}, "c_hess")      # legacy: no owner
    assert property_belongs_to_customer(PROPS["p_howell"], None)    # no customer to compare
