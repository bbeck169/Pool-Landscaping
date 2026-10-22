"""Ticket 287964 - repair planner is pure and conservative."""
from scripts.repair_cross_customer_property_links import plan_repair

ADDR = lambda l1: {"line1": l1, "city": "Peoria", "state": "AZ", "postal_code": "85383"}
PROPS = {
    "p_a": {"id": "p_a", "customer_id": "c_a", "address": ADDR("1 A St")},
    "p_b": {"id": "p_b", "customer_id": "c_b", "address": ADDR("2 B St")},
}
CUSTS = {
    "c_a": {"id": "c_a", "primary_property_id": "p_a"},
    "c_b": {"id": "c_b", "primary_property_id": "p_b"},
    "c_c": {"id": "c_c", "service_address": "3 C Rd, Peoria, AZ 85383"},
}


def test_correct_link_untouched():
    assert plan_repair({"customer_id": "c_a", "property_id": "p_a"}, PROPS, CUSTS) is None


def test_legacy_property_without_owner_untouched():
    props = {"p_x": {"id": "p_x", "address": ADDR("9 X")}}
    assert plan_repair({"customer_id": "c_a", "property_id": "p_x"}, props, CUSTS) is None


def test_mismatch_repoints_to_own_primary_property():
    upd = plan_repair({"customer_id": "c_a", "property_id": "p_b"}, PROPS, CUSTS)
    assert upd == {"$set": {"property_id": "p_a", "address": "1 A St, Peoria, AZ 85383"}}


def test_mismatch_without_own_property_clears_link_and_uses_customer_address():
    upd = plan_repair({"customer_id": "c_c", "property_id": "p_b"}, PROPS, CUSTS)
    assert upd == {"$unset": {"property_id": ""},
                   "$set": {"address": "3 C Rd, Peoria, AZ 85383"}}
