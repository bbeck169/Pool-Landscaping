"""Feb 2026 · P0 hotfix regression — ``GET /api/customers`` must
return HTTP 200 even when the underlying Mongo docs have mixed /
missing / BSON-datetime shapes for ``created_at``.

Root cause (Aug-2026, prod-only): ``CustomerListItem.created_at`` is
declared ``Optional[str]``. When a legacy doc carries a BSON
``datetime`` (not an ISO string), Pydantic v2's response-model union
discriminator can't coerce it and returns a
``ResponseValidationError`` → HTTP 500. The count endpoint doesn't
sort/serialize the same shape and stayed green, which produced the
"466 badge, empty list" symptom on prod.

Fix: coerce every ``datetime`` value in every doc to ISO string
right after the Mongo fetch, before any downstream processing.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
             or "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": "password123"},
                       timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"],
                               io_loop=_LOOP)[os.environ["DB_NAME"]]


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


@pytest.fixture()
def drift_ids(admin_headers):
    """Inject 4 customers with the four ``created_at`` shapes we've
    observed in prod: BSON datetime, ISO string, ``null``, and
    missing-field. Yielded ids are cleaned up on teardown so the
    test is fully hermetic."""
    async def _setup():
        db = _db()
        u = await db.users.find_one({"email": "admin@aquaterra.com"},
                                       {"_id": 0, "tenant_id": 1})
        tid = u["tenant_id"]
        docs = [
            {"id": f"drift-dt-{uuid.uuid4().hex[:6]}", "tenant_id": tid,
             "name": "Drift Datetime",
             "created_at": datetime.now(timezone.utc)},
            {"id": f"drift-str-{uuid.uuid4().hex[:6]}", "tenant_id": tid,
             "name": "Drift String",
             "created_at": "2024-01-01T00:00:00Z"},
            {"id": f"drift-null-{uuid.uuid4().hex[:6]}", "tenant_id": tid,
             "name": "Drift Null", "created_at": None},
            {"id": f"drift-miss-{uuid.uuid4().hex[:6]}", "tenant_id": tid,
             "name": "Drift Missing"},  # no created_at at all
        ]
        await db.customers.insert_many(docs)
        return [d["id"] for d in docs]

    ids = _run(_setup())
    yield ids

    async def _teardown():
        db = _db()
        await db.customers.delete_many({"id": {"$in": ids}})
    _run(_teardown())


@pytest.mark.parametrize("sort", ["", "created_desc", "created_asc", "name_asc",
                                       "not_a_real_sort"])
def test_customers_list_returns_200_with_mixed_created_at_shapes(
    admin_headers, drift_ids, sort,
):
    """The core regression — all four sort variants must return 200
    when drift docs are present. Unknown values fall back to
    ``created_desc``; test that too."""
    params = {"paginated": "true", "page": 1, "page_size": 25}
    if sort:
        params["sort"] = sort
    r = requests.get(f"{API}/customers", headers=admin_headers,
                      params=params, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert isinstance(body["items"], list)
    assert body["total"] >= 4  # at minimum, our 4 drift docs count


def test_customers_list_serialises_bson_datetime_to_iso_string(
    admin_headers, drift_ids,
):
    """Every ``created_at`` in the response is either a string or
    ``None`` — never a raw ``datetime`` object. Guards the pydantic
    boundary."""
    r = requests.get(
        f"{API}/customers",
        headers=admin_headers,
        params={"paginated": "true", "page": 1, "page_size": 500,
                 "sort": "created_desc"},
        timeout=20,
    )
    assert r.status_code == 200
    for item in r.json()["items"]:
        val = item.get("created_at", None)
        assert val is None or isinstance(val, str), (
            f"created_at must be None or str, got {type(val).__name__}: {val!r}"
        )


def test_drift_docs_are_returned_and_visible(admin_headers, drift_ids):
    """Legacy docs (missing / null / datetime / string) all show up
    in the list — nothing gets silently dropped by the coercion."""
    r = requests.get(
        f"{API}/customers",
        headers=admin_headers,
        params={"paginated": "true", "page": 1, "page_size": 500,
                 "sort": "created_desc"},
        timeout=20,
    )
    assert r.status_code == 200
    returned = {i["id"] for i in r.json()["items"]}
    for did in drift_ids:
        assert did in returned, f"drift doc {did} missing from response"


def test_count_endpoint_still_matches_paginated_total(
    admin_headers, drift_ids,
):
    """The count endpoint was returning 466 while the list was
    500-ing. Post-fix, ``count_only=true`` and the paginated
    ``total`` should agree exactly."""
    r_count = requests.get(
        f"{API}/customers",
        headers=admin_headers,
        params={"count_only": "true"},
        timeout=15,
    )
    assert r_count.status_code == 200
    count = int(r_count.json()["count"])
    r_page = requests.get(
        f"{API}/customers",
        headers=admin_headers,
        params={"paginated": "true", "page": 1, "page_size": 1,
                 "sort": "created_desc"},
        timeout=15,
    )
    assert r_page.status_code == 200
    total = int(r_page.json()["total"])
    assert count == total, (count, total)
