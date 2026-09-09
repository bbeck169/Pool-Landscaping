"""Feb-2026 · P44 — "No payment on file" filter.

Pins ``GET /api/customers?has_payment_method=true|false``:

* ``has_payment_method=false`` matches customers whose
  ``saved_payment_methods_count`` is missing / null / 0. This is
  the SAME source-of-truth the ``CardOnFileWarningBanner`` reads
  (denorm maintained by every Stripe attach/detach code path).
* ``has_payment_method=true`` matches customers whose
  ``saved_payment_methods_count`` is > 0 — whether the underlying
  ``payment_methods`` row is ``type=card`` or ``type=us_bank_account``
  (both count uniformly through the denorm).
* Omitted → no filter (all customers pass).
* ``count_only=true`` variants of both truth values return matching
  cardinality.
* Composes AND with the P43b/P43c chips.
* Parameter is exposed on the OpenAPI schema.
* **Filter and banner must agree** — a customer flagged as
  ``has_card_on_file=true`` in the row response must NOT appear in
  the ``has_payment_method=false`` result set (invariant test
  below).
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
    """One customer per relevant payment-method-count state."""
    marker = f"p44-{uuid.uuid4().hex[:8]}"
    now = "2026-02-14T12:00:00+00:00"
    rows = [
        # NO_PAYMENT variants — filter must MATCH these.
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} A_no_pm_field",
         "is_active": True,
         "_p44_marker": marker, "created_at": now},
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} B_pm_count_zero",
         "is_active": True,
         "saved_payment_methods_count": 0,
         "_p44_marker": marker, "created_at": now},
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} C_pm_count_null",
         "is_active": True,
         "saved_payment_methods_count": None,
         "_p44_marker": marker, "created_at": now},
        # HAS_PAYMENT variants — filter must EXCLUDE these when
        # ``has_payment_method=false``.
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} D_card_on_file",
         "is_active": True,
         "saved_payment_methods_count": 1,
         "_p44_marker": marker, "created_at": now},
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} E_ach_on_file",
         "is_active": True,
         # ACH-only customer — denorm treats card + us_bank_account
         # uniformly, so count 1 with no card row is still "has
         # payment method".
         "saved_payment_methods_count": 1,
         "_p44_marker": marker, "created_at": now},
        {"id": str(uuid.uuid4()), "tenant_id": tenant_id,
         "name": f"{marker} F_multiple_methods",
         "is_active": True,
         "saved_payment_methods_count": 3,
         "_p44_marker": marker, "created_at": now},
    ]
    _sync_db.customers.insert_many(rows)
    yield marker, rows
    _sync_db.customers.delete_many({"_p44_marker": marker})


def _list(token: str, params: str) -> list[dict]:
    r = requests.get(f"{API}/customers?{params}&limit=500",
                       headers={"Authorization": f"Bearer {token}"},
                       timeout=15)
    r.raise_for_status()
    body = r.json()
    return body if isinstance(body, list) else (body.get("items") or [])


def _list_names(token: str, params: str) -> set[str]:
    return {c["name"] for c in _list(token, params) if c.get("name")}


def _count(token: str, params: str) -> int:
    r = requests.get(f"{API}/customers?{params}&count_only=true",
                       headers={"Authorization": f"Bearer {token}"},
                       timeout=15)
    r.raise_for_status()
    return r.json()["count"]


def test_openapi_registers_has_payment_method_param():
    r = requests.get(f"{API}/openapi.json", timeout=45)
    r.raise_for_status()
    ops = r.json()["paths"]["/api/customers"]["get"]["parameters"]
    names = {p["name"] for p in ops}
    assert "has_payment_method" in names, names


def test_has_payment_method_false_matches_no_payment_variants(
        admin_token, seeded_customers):
    marker, _ = seeded_customers
    names = _list_names(admin_token,
                          f"has_payment_method=false&search={marker}")
    assert names == {
        f"{marker} A_no_pm_field",
        f"{marker} B_pm_count_zero",
        f"{marker} C_pm_count_null",
    }, names


def test_has_payment_method_true_matches_paying_customers(
        admin_token, seeded_customers):
    marker, _ = seeded_customers
    names = _list_names(admin_token,
                          f"has_payment_method=true&search={marker}")
    assert names == {
        f"{marker} D_card_on_file",
        f"{marker} E_ach_on_file",
        f"{marker} F_multiple_methods",
    }, names


def test_omitted_returns_all(admin_token, seeded_customers):
    marker, _ = seeded_customers
    names = _list_names(admin_token, f"search={marker}")
    assert len({n for n in names if n.startswith(marker)}) == 6, names


def test_counts_partition_the_seeded_set(admin_token, seeded_customers):
    marker, _ = seeded_customers
    total = _count(admin_token, f"search={marker}")
    no_pm = _count(admin_token,
                     f"has_payment_method=false&search={marker}")
    has_pm = _count(admin_token,
                      f"has_payment_method=true&search={marker}")
    # true + false = all rows — no overlap, no gaps.
    assert no_pm + has_pm == total, (no_pm, has_pm, total)
    assert no_pm == 3
    assert has_pm == 3


def test_filter_agrees_with_banner_signal(
        admin_token, seeded_customers):
    """Invariant: rows returned with ``has_card_on_file=true`` (the
    banner's derived flag) must NEVER appear in
    ``has_payment_method=false``. Prevents the filter and banner
    from ever drifting.
    """
    marker, _ = seeded_customers
    rows = _list(admin_token, f"has_payment_method=false&search={marker}")
    for r in rows:
        # ``has_card_on_file`` is derived at read time in
        # ``_compute_card_fields`` from the SAME denorm the filter
        # keys on, so the invariant is mechanical, but we still
        # assert it as a regression guard.
        assert not r.get("has_card_on_file"), r


def test_composes_and_with_missing_address(
        admin_token, seeded_customers, tenant_id):
    """A no-payment customer without an address matches both chips;
    a no-payment customer WITH an address is excluded when the
    missing_address chip is also on.
    """
    marker, _ = seeded_customers
    ctl_id = str(uuid.uuid4())
    _sync_db.customers.insert_one({
        "id": ctl_id, "tenant_id": tenant_id,
        "name": f"{marker} X_no_pm_with_address",
        "is_active": True,
        "service_address": "1 Main St Peoria AZ 85383",
        "_p44_marker": marker,
        "created_at": "2026-02-14T12:00:00+00:00",
    })
    try:
        names = _list_names(
            admin_token,
            f"has_payment_method=false&missing_address=true&search={marker}",
        )
        assert f"{marker} A_no_pm_field" in names
        assert f"{marker} X_no_pm_with_address" not in names
        assert f"{marker} D_card_on_file" not in names
    finally:
        _sync_db.customers.delete_one({"id": ctl_id})


def test_composes_and_with_portal_activated(
        admin_token, seeded_customers, tenant_id):
    """No-payment AND not-onboarded — the classic operator cohort:
    customers who never engaged AND have no way to auto-charge.
    """
    marker, _ = seeded_customers
    # Attach a portal-engaged, no-payment control that should be
    # excluded when both chips are active.
    ctl_id = str(uuid.uuid4())
    _sync_db.customers.insert_one({
        "id": ctl_id, "tenant_id": tenant_id,
        "name": f"{marker} Y_no_pm_signed_in",
        "is_active": True,
        "last_portal_login_at": "2026-02-01T12:00:00+00:00",
        "_p44_marker": marker,
        "created_at": "2026-02-14T12:00:00+00:00",
    })
    try:
        names = _list_names(
            admin_token,
            f"has_payment_method=false&portal_activated=false&search={marker}",
        )
        assert f"{marker} A_no_pm_field" in names
        assert f"{marker} Y_no_pm_signed_in" not in names
    finally:
        _sync_db.customers.delete_one({"id": ctl_id})
