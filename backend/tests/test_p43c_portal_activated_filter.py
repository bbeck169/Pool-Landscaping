"""Feb-2026 · P43c — "Portal status" tri-state filter.

Pins the following behaviours on ``GET /api/customers``:

* ``portal_activated=true`` matches customers with EITHER
  ``has_login=True`` OR ``last_portal_login_at`` set.
* ``portal_activated=false`` matches customers with NEITHER signal
  present (has_login is not truthy AND last_portal_login_at is
  null/missing/empty).
* Omitted → no filter (all customers pass).
* ``count_only=true`` variants of both truth values return matching
  cardinality.
* Composes AND with the P43b ``missing_address`` chip.
* Parameter is exposed on the OpenAPI schema.
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
    return _sync_db.users.find_one({"email": "admin@aquaterra.com"})["tenant_id"]


@pytest.fixture
def seeded_customers(tenant_id):
    """One customer per relevant portal-signal combination."""
    marker = f"p43c-{uuid.uuid4().hex[:8]}"
    now = "2026-02-14T12:00:00+00:00"
    rows = [
        # A. has_login True, no login yet — ACTIVATED
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} A_activated_login_set",
         "is_active": True, "has_login": True,
         "_p43c_marker": marker, "created_at": now},
        # B. last_portal_login_at set, has_login missing — ACTIVATED
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} B_activated_logged_in",
         "is_active": True,
         "last_portal_login_at": "2026-02-01T12:00:00+00:00",
         "_p43c_marker": marker, "created_at": now},
        # C. both signals set — ACTIVATED
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} C_activated_both",
         "is_active": True, "has_login": True,
         "last_portal_login_at": "2026-02-01T12:00:00+00:00",
         "_p43c_marker": marker, "created_at": now},
        # D. neither field present — NOT ACTIVATED
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} D_no_signals",
         "is_active": True,
         "_p43c_marker": marker, "created_at": now},
        # E. has_login=False + last_login=None — NOT ACTIVATED
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} E_explicit_false",
         "is_active": True, "has_login": False,
         "last_portal_login_at": None,
         "_p43c_marker": marker, "created_at": now},
        # F. last_login empty string — NOT ACTIVATED
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} F_empty_login",
         "is_active": True, "last_portal_login_at": "",
         "_p43c_marker": marker, "created_at": now},
    ]
    _sync_db.customers.insert_many(rows)
    yield marker, rows
    _sync_db.customers.delete_many({"_p43c_marker": marker})


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


def test_openapi_registers_portal_activated_param():
    r = requests.get(f"{API}/openapi.json", timeout=45)
    r.raise_for_status()
    ops = r.json()["paths"]["/api/customers"]["get"]["parameters"]
    names = {p["name"] for p in ops}
    assert "portal_activated" in names, names


def test_portal_activated_true_matches_positive_signals(
        admin_token, seeded_customers):
    marker, _ = seeded_customers
    names = _list_names(admin_token, f"portal_activated=true&search={marker}")
    assert names == {
        f"{marker} A_activated_login_set",
        f"{marker} B_activated_logged_in",
        f"{marker} C_activated_both",
    }, names


def test_portal_activated_false_matches_no_signals(
        admin_token, seeded_customers):
    marker, _ = seeded_customers
    names = _list_names(admin_token, f"portal_activated=false&search={marker}")
    assert names == {
        f"{marker} D_no_signals",
        f"{marker} E_explicit_false",
        f"{marker} F_empty_login",
    }, names


def test_omitted_returns_all(admin_token, seeded_customers):
    marker, _ = seeded_customers
    names = _list_names(admin_token, f"search={marker}")
    assert len({n for n in names if n.startswith(marker)}) == 6, names


def test_counts_partition_the_seeded_set(admin_token, seeded_customers):
    marker, _ = seeded_customers
    total = _count(admin_token, f"search={marker}")
    activated = _count(admin_token, f"portal_activated=true&search={marker}")
    not_activated = _count(admin_token,
                             f"portal_activated=false&search={marker}")
    # true + false = all rows — no overlap, no gaps.
    assert activated + not_activated == total, (
        activated, not_activated, total,
    )
    assert activated == 3
    assert not_activated == 3


def test_composes_and_with_missing_address(
        admin_token, seeded_customers, tenant_id):
    """A not-activated customer WITHOUT an address must appear when
    both chips are active; a not-activated customer WITH an address
    must NOT.
    """
    marker, _ = seeded_customers
    # Row D has no service_address AND no portal signals — both
    # chips should match. Seed a control row with an address to
    # confirm exclusion.
    ctl_id = str(uuid.uuid4())
    _sync_db.customers.insert_one({
        "id": ctl_id, "tenant_id": tenant_id,
        "name": f"{marker} X_not_activated_with_address",
        "is_active": True,
        "service_address": "1 Main St Peoria AZ 85383",
        "_p43c_marker": marker,
        "created_at": "2026-02-14T12:00:00+00:00",
    })
    try:
        names = _list_names(
            admin_token,
            f"portal_activated=false&missing_address=true&search={marker}",
        )
        # Rows D, E, F qualify (no signals + no address). The control
        # row X_not_activated_with_address has an address so is
        # excluded.
        assert f"{marker} D_no_signals" in names
        assert f"{marker} X_not_activated_with_address" not in names
        assert f"{marker} A_activated_login_set" not in names
    finally:
        _sync_db.customers.delete_one({"id": ctl_id})


def test_composes_and_with_active_search(
        admin_token, seeded_customers):
    """Search + portal_activated compose (AND). Search that matches
    a subset should shrink the count, not clear the filter.
    """
    marker, _ = seeded_customers
    # Search for the activated_logged_in row specifically.
    names = _list_names(
        admin_token,
        f"portal_activated=true&search={marker}%20B_activated",
    )
    # Only the B row survives the intersected filter.
    assert f"{marker} B_activated_logged_in" in names
    assert f"{marker} A_activated_login_set" not in names
