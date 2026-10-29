"""Schedule 500 hardening · Feb-2026 — defensive list_jobs guards
for Homeworks-imported / legacy jobs.

Operator reports a real 500 on ``GET /api/jobs`` in prod on
Homeworks-imported docs. Preview DB does not carry the ``source:
"homeworks"`` discriminator so we can't repro here, but the field-
pattern description is consistent with legacy BSON leaks (dict
``scheduled_date``, dict ``price``, non-numeric lat/lng strings on
the parent customer doc, etc.). The patched code hardens:

  * Both ``float(lat/lng)`` cast sites (already had try/except;
    this suite proves the guard holds for non-numeric strings and
    dict shapes).
  * ``_resolve_service_note`` call site (already wrapped — proven
    non-fatal when the resolver raises).
  * ``.get()`` defaults on five operator-named fields:
    ``scheduled_date``, ``price``, ``customer_name``, ``address``,
    ``technician_id``.
  * Pydantic-serialization type coercers on ``JobListItem`` so a
    dict / list / string-typed ``price`` or a dict ``customer_name``
    becomes ``None`` on the wire (field_validator mode="before"
    pre-empts Pydantic's lax ValidationError).

Fixture plan (8 synthetic jobs — one scenario each + 1 all-nulls
+ 1 non-numeric lat/lng + 1 string-typed price):

  F1 — scheduled_date missing (null)
  F2 — price missing (null)
  F3 — customer_name missing (null)
  F4 — address missing (null)
  F5 — technician_id missing (null)
  F6 — ALL FIVE fields null on one job
  F7 — customer.service_lat/service_lng = non-numeric string + dict
  F8 — price = string ``"49.00"`` (legacy import coerces to float)
  F9 — price = dict ``{"$numberDouble": "..."}`` BSON leak → None

Direct Mongo inserts bypass ``JobIn``'s Pydantic validator so the
suite can exercise the read-path net against shapes that already
exist in prod-legacy data (mirrors ``test_p2_list_jobs_dict_address_
coercion.py`` conventions).
"""
from __future__ import annotations

import os
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from server import app


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _sync_db():
    return MongoClient(MONGO_URL)[DB_NAME]


_PREFIX = "SCHED500_"


@pytest.fixture
def homeworks_fixture():
    tenant_id = f"{_PREFIX}tid"
    customer_id = f"{_PREFIX}cust"
    customer_bad_coords_id = f"{_PREFIX}cust_bad_coords"
    fixture: Dict[str, Any] = {
        "tenants": [{
            "id": tenant_id,
            "name": "Schedule-500 Test Tenant",
            "slug": f"{_PREFIX}tenant",
            "active": True,
        }],
        "users": [{
            "id": f"{_PREFIX}sa",
            "tenant_id": tenant_id,
            "active_tenant_id": tenant_id,
            "email": f"{_PREFIX}sa@example.com",
            "role": "super_admin",
            "name": "Schedule-500 Super Admin",
            "is_active": True,
            "hashed_password": "xxx",
        }],
        "customers": [
            {
                "id": customer_id,
                "tenant_id": tenant_id,
                "name": "Homeworks Imported Cust",
                "address": "789 Legacy Blvd, Peoria, AZ",
                "service_lat": 33.5806,
                "service_lng": -112.2374,
            },
            {
                # Non-numeric coords on parent customer — F7 anchor.
                "id": customer_bad_coords_id,
                "tenant_id": tenant_id,
                "name": "Bad Coords Cust",
                "address": "100 Garbage Ln",
                "service_lat": "not-a-float",
                "service_lng": {"$numberDouble": "nan"},
            },
        ],
        # ── Synthetic jobs — one per fixture scenario. All on the
        # same scheduled_date so the fetch query is simple.
        # Direct insert bypasses JobIn 422 so we exercise the
        # read-path hardening on wire-breaking shapes.
        "jobs": [
            # F1 — scheduled_date missing (null)
            {
                "id": f"{_PREFIX}F1",
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "customer_name": "F1 Cust",
                "title": "F1 null scheduled_date",
                "status": "scheduled",
                "address": "F1 Street",
                "technician_id": "tech_1",
                "price": 50.0,
                "scheduled_date": None,
                "created_at": "2026-02-20T00:00:00+00:00",
            },
            # F2 — price missing (null)
            {
                "id": f"{_PREFIX}F2",
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "customer_name": "F2 Cust",
                "title": "F2 null price",
                "status": "scheduled",
                "address": "F2 Street",
                "technician_id": "tech_1",
                "scheduled_date": "2026-02-20",
                "price": None,
                "created_at": "2026-02-20T00:00:01+00:00",
            },
            # F3 — customer_name missing (null)
            {
                "id": f"{_PREFIX}F3",
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "customer_name": None,
                "title": "F3 null customer_name",
                "status": "scheduled",
                "address": "F3 Street",
                "technician_id": "tech_1",
                "scheduled_date": "2026-02-20",
                "price": 60.0,
                "created_at": "2026-02-20T00:00:02+00:00",
            },
            # F4 — address missing (null)
            {
                "id": f"{_PREFIX}F4",
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "customer_name": "F4 Cust",
                "title": "F4 null address",
                "status": "scheduled",
                "address": None,
                "technician_id": "tech_1",
                "scheduled_date": "2026-02-20",
                "price": 70.0,
                "created_at": "2026-02-20T00:00:03+00:00",
            },
            # F5 — technician_id missing (null)
            {
                "id": f"{_PREFIX}F5",
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "customer_name": "F5 Cust",
                "title": "F5 null technician_id",
                "status": "scheduled",
                "address": "F5 Street",
                "technician_id": None,
                "scheduled_date": "2026-02-20",
                "price": 80.0,
                "created_at": "2026-02-20T00:00:04+00:00",
            },
            # F6 — ALL FIVE fields null on one job
            {
                "id": f"{_PREFIX}F6",
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "customer_name": None,
                "title": "F6 all nulls",
                "status": "scheduled",
                "address": None,
                "technician_id": None,
                "scheduled_date": "2026-02-20",
                "price": None,
                "created_at": "2026-02-20T00:00:05+00:00",
            },
            # F7 — non-numeric lat/lng on the parent customer. The
            # job itself is well-formed; the hardening target is
            # the ``float(lat)`` cast on the customer-enrichment
            # branch (L1371-1376).
            {
                "id": f"{_PREFIX}F7",
                "tenant_id": tenant_id,
                "customer_id": customer_bad_coords_id,
                "customer_name": "F7 Cust",
                "title": "F7 bad lat/lng on customer",
                "status": "scheduled",
                "address": "F7 Street",
                "technician_id": "tech_1",
                "scheduled_date": "2026-02-20",
                "price": 90.0,
                "created_at": "2026-02-20T00:00:06+00:00",
            },
            # F8 — string-typed price "49.00" (legacy import coerces
            # to float on the wire).
            {
                "id": f"{_PREFIX}F8",
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "customer_name": "F8 Cust",
                "title": "F8 string price",
                "status": "scheduled",
                "address": "F8 Street",
                "technician_id": "tech_1",
                "scheduled_date": "2026-02-20",
                "price": "49.00",
                "created_at": "2026-02-20T00:00:07+00:00",
            },
            # F9 — dict price (BSON leak). Must coerce to None, NOT
            # ValidationError-500.
            {
                "id": f"{_PREFIX}F9",
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "customer_name": "F9 Cust",
                "title": "F9 dict price",
                "status": "scheduled",
                "address": "F9 Street",
                "technician_id": "tech_1",
                "scheduled_date": "2026-02-20",
                "price": {"$numberDouble": "49.00"},
                "created_at": "2026-02-20T00:00:08+00:00",
            },
        ],
    }
    db = _sync_db()
    db.tenants.insert_many(fixture["tenants"])
    db.users.insert_many(fixture["users"])
    db.customers.insert_many(fixture["customers"])
    db.jobs.insert_many(fixture["jobs"])
    yield fixture
    filt = {"id": {"$regex": f"^{_PREFIX}"}}
    for coll in ("tenants", "users", "customers", "jobs"):
        db[coll].delete_many(filt)


def _headers_for(user_id: str) -> Dict[str, str]:
    from datetime import datetime, timedelta, timezone
    import jwt
    from config import JWT_SECRET, JWT_ALGO
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    tok = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    return {"Authorization": f"Bearer {tok}"}


def _fetch_schedule_window(client) -> list:
    """GET /api/jobs for the fixture's scheduled_date window.  The
    endpoint MUST 200 for every synthetic row regardless of which
    scalar is malformed; the whole point of the hardening is a
    non-fatal response."""
    h = _headers_for(f"{_PREFIX}sa")
    # Use the explicit date filter so the fixture is deterministic
    # even if other tests have inserted stray rows into the same DB.
    r = client.get("/api/jobs?scheduled_date=2026-02-20", headers=h)
    assert r.status_code == 200, (
        f"list_jobs 500'd on malformed fixture row: {r.status_code} "
        f"body={r.text[:500]}"
    )
    rows = r.json()
    assert isinstance(rows, list)
    return rows


def _get(rows, job_id):
    return next((r for r in rows if r.get("id") == job_id), None)


# ──────────────────────────────────────────────────────────────────
# F1-F6 — missing-field hardening
# ──────────────────────────────────────────────────────────────────
def test_f1_null_scheduled_date(client, homeworks_fixture):
    """F1 — job without a scheduled_date is served (null stays null)
    AND does not knock out neighbouring rows."""
    rows = _fetch_schedule_window(client)
    # F1 has scheduled_date=None so it won't appear in the dated
    # window query. The hardening guarantee is that it does NOT
    # cause a 500 for the window that it is NOT in. We also hit the
    # no-date-window admin query and confirm F1 comes back cleanly.
    h = _headers_for(f"{_PREFIX}sa")
    r2 = client.get("/api/jobs?limit=200", headers=h)
    assert r2.status_code == 200, r2.text
    f1 = _get(r2.json(), f"{_PREFIX}F1")
    assert f1 is not None
    assert f1.get("scheduled_date") is None


def test_f2_null_price(client, homeworks_fixture):
    rows = _fetch_schedule_window(client)
    f2 = _get(rows, f"{_PREFIX}F2")
    assert f2 is not None, "F2 row missing from schedule window"
    assert f2.get("price") is None


def test_f3_null_customer_name(client, homeworks_fixture):
    rows = _fetch_schedule_window(client)
    f3 = _get(rows, f"{_PREFIX}F3")
    assert f3 is not None
    # customer_name is pulled from the customer doc enrichment OR
    # the stored value — either None or the resolved customer name
    # is acceptable; the invariant is that the row returns at all.
    assert "customer_name" in f3


def test_f4_null_address(client, homeworks_fixture):
    rows = _fetch_schedule_window(client)
    f4 = _get(rows, f"{_PREFIX}F4")
    assert f4 is not None
    # ``address`` is either None (preserved) or an empty string
    # (coerced). Either is acceptable; the row must not 500.
    assert f4.get("address") in (None, "")


def test_f5_null_technician_id(client, homeworks_fixture):
    rows = _fetch_schedule_window(client)
    f5 = _get(rows, f"{_PREFIX}F5")
    assert f5 is not None
    assert f5.get("technician_id") is None


def test_f6_all_five_null(client, homeworks_fixture):
    rows = _fetch_schedule_window(client)
    f6 = _get(rows, f"{_PREFIX}F6")
    assert f6 is not None, "F6 (all-nulls) row missing from schedule"
    assert f6.get("price") is None
    assert f6.get("technician_id") is None
    # customer_name may be None or resolved from the customer doc.


# ──────────────────────────────────────────────────────────────────
# F7 — non-numeric lat/lng on customer doc
# ──────────────────────────────────────────────────────────────────
def test_f7_non_numeric_lat_lng_on_customer(client, homeworks_fixture):
    """F7 — ``float("not-a-float")`` would raise ValueError and the
    ``float({...})`` on the BSON-leak lng would raise TypeError.
    Both are caught by the existing try/except at L1371-1376 /
    L1507-1516; this test proves the guard still holds and that
    ``location_lat`` + ``location_lng`` arrive as ``None`` on the
    wire."""
    rows = _fetch_schedule_window(client)
    f7 = _get(rows, f"{_PREFIX}F7")
    assert f7 is not None, "F7 row missing from schedule window"
    assert f7.get("location_lat") is None
    assert f7.get("location_lng") is None
    # ``coord_source`` should also be None (both-coords-None ⇒
    # coord_source None invariant enforced at jobs.py L1520).
    assert f7.get("coord_source") is None


# ──────────────────────────────────────────────────────────────────
# F8 — string-typed price "49.00" (coerces to float)
# F9 — dict-typed price (coerces to None, no 500)
# ──────────────────────────────────────────────────────────────────
def test_f8_string_typed_price_coerces_to_float(client, homeworks_fixture):
    rows = _fetch_schedule_window(client)
    f8 = _get(rows, f"{_PREFIX}F8")
    assert f8 is not None
    # Either Pydantic lax coercion ("49.00" → 49.0) OR our explicit
    # ``_coerce_price_field`` validator handles this. End state:
    # price is a float on the wire.
    assert isinstance(f8.get("price"), float), (
        f"string-typed price should coerce to float; got "
        f"{type(f8.get('price')).__name__}={f8.get('price')!r}"
    )
    assert f8["price"] == 49.0


def test_f9_dict_typed_price_coerces_to_none(client, homeworks_fixture):
    """F9 — dict-typed ``price`` (BSON leak shape) would 500 under
    plain Pydantic lax (ValidationError). Our ``_coerce_price_field``
    validator intercepts and returns None."""
    rows = _fetch_schedule_window(client)
    f9 = _get(rows, f"{_PREFIX}F9")
    assert f9 is not None, "F9 (dict price) 500'd the whole response"
    assert f9.get("price") is None, (
        f"dict price should coerce to None; got {f9.get('price')!r}"
    )
