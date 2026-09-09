"""Feb-2026 · P43b — "Missing address" data-quality chip.

Pins the following behaviours on ``GET /api/customers``:

* ``missing_address=true`` matches customers whose top-level
  ``service_address`` is empty in every historical shape (null,
  missing, empty string, whitespace-only string, empty dict,
  all-blank dict) AND whose per-field breakdown
  (``service_street|street|service_city|city|service_state|state
  |service_zip|zip``) is also entirely empty.
* A customer with a real string ``service_address`` is NOT matched.
* A customer with a real dict ``service_address`` (any single
  non-blank field) is NOT matched.
* A customer with an empty ``service_address`` but a populated
  ``service_street`` per-field slot is NOT matched.
* Composes AND with the sibling ``missing_email`` / ``missing_phone``
  chips so combined chip selection narrows the result.
* ``count_only=true`` version returns the same predicate cardinality.
* The parameter is exposed on the OpenAPI schema so client-code
  gens can pick it up.
"""
import os
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient


API = "http://localhost:8001/api"
_ENV = dotenv_values("/app/backend/.env")
_MONGO_URL = _ENV.get("MONGO_URL") or os.environ.get("MONGO_URL")
_DB_NAME = _ENV.get("DB_NAME") or os.environ.get("DB_NAME")
_sync_db = MongoClient(_MONGO_URL)[_DB_NAME] if _MONGO_URL and _DB_NAME else None


def _login(email: str, password: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    r.raise_for_status()
    body = r.json()
    if body.get("multi_account_choice_required"):
        pick = requests.post(
            f"{API}/auth/login/select-account",
            json={"choice_token": body["choice_token"],
                  "record_id": body["accounts"][0]["id"]},
            timeout=15,
        )
        pick.raise_for_status()
        return pick.json()["access_token"]
    return body["access_token"]


@pytest.fixture
def admin_token():
    return _login("admin@aquaterra.com")


@pytest.fixture
def tenant_id():
    u = _sync_db.users.find_one({"email": "admin@aquaterra.com"})
    return u["tenant_id"]


@pytest.fixture
def seeded_customers(tenant_id):
    """Seed one customer per address shape so the filter can be
    exercised against a known truth set. Teardown removes all rows
    tagged with the fixture marker.
    """
    marker = f"p43b-{uuid.uuid4().hex[:8]}"
    now = "2026-02-14T12:00:00+00:00"
    rows = [
        # 1. string address — has address
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} A",
         "service_address": "13333 W Jesse Red Dr Peoria AZ 85383",
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 2. dict address, fully populated — has address
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} B",
         "service_address": {"street": "1 Main St", "city": "Peoria",
                              "state": "AZ", "postal_code": "85383"},
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 3. dict address, only street set — has address
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} C",
         "service_address": {"street": "9 Cactus Way",
                              "city": "", "state": "", "postal_code": ""},
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 4. per-field only (top-level empty) — has address
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} D",
         "service_address": None,
         "service_street": "42 Elm St", "service_city": "Phoenix",
         "service_state": "AZ", "service_zip": "85001",
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 5. null service_address — MISSING
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} E",
         "service_address": None,
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 6. empty string — MISSING
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} F",
         "service_address": "",
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 7. whitespace-only string — MISSING
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} G",
         "service_address": "   ",
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 8. empty dict — MISSING
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} H",
         "service_address": {},
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 9. all-blank dict — MISSING
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} I",
         "service_address": {"street": "  ", "city": "", "state": "",
                              "postal_code": ""},
         "is_active": True, "_p43b_marker": marker, "created_at": now},
        # 10. field-omitted entirely — MISSING
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": f"{marker} J",
         "is_active": True, "_p43b_marker": marker, "created_at": now},
    ]
    _sync_db.customers.insert_many(rows)
    yield marker, rows
    _sync_db.customers.delete_many({"_p43b_marker": marker})


def _list_names(token: str, params: str) -> set[str]:
    r = requests.get(f"{API}/customers?{params}&limit=500",
                       headers={"Authorization": f"Bearer {token}"},
                       timeout=15)
    r.raise_for_status()
    body = r.json()
    rows = body if isinstance(body, list) else (body.get("items") or [])
    return {c["name"] for c in rows if c.get("name")}


def _count(token: str, params: str) -> int:
    r = requests.get(f"{API}/customers?{params}&count_only=true",
                       headers={"Authorization": f"Bearer {token}"},
                       timeout=15)
    r.raise_for_status()
    return r.json()["count"]


def test_openapi_registers_missing_address_param():
    r = requests.get(f"{API}/openapi.json", timeout=45)
    r.raise_for_status()
    ops = r.json()["paths"]["/api/customers"]["get"]["parameters"]
    names = {p["name"] for p in ops}
    assert "missing_address" in names, names


def test_missing_address_filter_returns_only_addressless(
        admin_token, seeded_customers):
    marker, rows = seeded_customers
    names = _list_names(admin_token, f"missing_address=true&search={marker}")
    assert names == {
        f"{marker} E", f"{marker} F", f"{marker} G", f"{marker} H",
        f"{marker} I", f"{marker} J",
    }, names


def test_no_filter_returns_all_seeded_rows(admin_token, seeded_customers):
    marker, _ = seeded_customers
    names = _list_names(admin_token, f"search={marker}")
    # All 10 seeded rows present when no chip is active.
    assert len({n for n in names if n.startswith(marker)}) == 10, names


def test_missing_address_false_disables_filter(
        admin_token, seeded_customers):
    """P43 convention — ``missing_*=false`` = chip off = no filter,
    NOT an inversion. Same behaviour as ``missing_email=false`` /
    ``missing_phone=false``.
    """
    marker, _ = seeded_customers
    names = _list_names(admin_token, f"missing_address=false&search={marker}")
    assert len({n for n in names if n.startswith(marker)}) == 10, names


def test_count_only_matches_list_length(admin_token, seeded_customers):
    marker, _ = seeded_customers
    # Add a unique marker to the search so we don't count unrelated
    # rows in the tenant. The ``search`` filter matches ``name``
    # substrings, so all 10 seeded rows share the prefix.
    count = _count(admin_token, f"missing_address=true&search={marker}")
    assert count == 6, count


def test_composes_and_with_missing_email(admin_token, seeded_customers,
                                            tenant_id):
    """When BOTH chips are on, only customers missing BOTH match.
    Seed row E has ``service_address=None`` and no email fields at
    all — so it should be included in ``missing_address AND missing_email``.
    """
    marker, _ = seeded_customers
    count_both = _count(admin_token,
                         f"missing_address=true&missing_email=true&search={marker}")
    count_addr = _count(admin_token,
                         f"missing_address=true&search={marker}")
    # AND-composition can never exceed the single-filter count.
    assert count_both <= count_addr, (count_both, count_addr)
    # At least one seed row lacks BOTH address AND email (rows E-J).
    assert count_both >= 6, count_both


def test_dict_with_only_zip_alias_is_not_missing(
        admin_token, seeded_customers, tenant_id):
    """The `_flatten_addr` helper accepts both ``postal_code`` and
    ``zip``. A dict with only ``zip`` populated must NOT be flagged
    as missing.
    """
    marker = f"p43b-zip-{uuid.uuid4().hex[:8]}"
    _sync_db.customers.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tenant_id,
        "name": f"{marker} Z", "is_active": True,
        "service_address": {"street": "", "city": "", "state": "",
                              "zip": "85383"},
        "_p43b_marker": marker,
        "created_at": "2026-02-14T12:00:00+00:00",
    })
    try:
        names = _list_names(admin_token,
                             f"missing_address=true&search={marker}")
        assert f"{marker} Z" not in names, names
    finally:
        _sync_db.customers.delete_many({"_p43b_marker": marker})
