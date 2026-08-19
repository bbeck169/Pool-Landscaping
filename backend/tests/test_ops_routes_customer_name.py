"""Feb-2026 · Ops Routes customer-name bug fix — backend.

Verifies ``GET /api/routes/{tech_id}/stops`` now returns a real
customer name in ``customer_display_name`` even when the job doc is
missing ``customer_name`` (the tester's original scenario).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient

from tests.conftest import demo_pw

API = "http://localhost:8001/api"

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)
_MC = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=_LOOP)
_DB = _MC[_ENV["DB_NAME"]]


def _run(coro):
    asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _login(email: str) -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": demo_pw(email)}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tenant_of(email: str) -> str:
    return _run(_DB.users.find_one({"email": email}, {"_id": 0, "tenant_id": 1}))["tenant_id"]


DATE = "2026-04-11"
CUST_ID = f"TEST_opsroutes_cust_{uuid4().hex[:8]}"
CUST_NAME = f"TEST_opsroutes Susan Sample {uuid4().hex[:4]}"


async def _seed(tenant_id: str, tech_user_id: str):
    """Create one customer + two jobs; one job has denormalised
    customer_name, one does NOT (simulating the tester's scenario)."""
    await _DB.customers.insert_one({
        "id": CUST_ID, "tenant_id": tenant_id, "name": CUST_NAME,
        "billing_name": CUST_NAME, "service_address": "42 Test Ln, Peoria AZ",
    })
    j1 = f"TEST_opsroutes_job_denorm_{uuid4().hex[:8]}"
    j2 = f"TEST_opsroutes_job_missing_{uuid4().hex[:8]}"
    await _DB.jobs.insert_one({
        "id": j1, "tenant_id": tenant_id, "customer_id": CUST_ID,
        "customer_name": CUST_NAME,  # denormalised — good path.
        "title": "Weekly Pool Cleaning",
        "address": "42 Test Ln, Peoria AZ",
        "technician_id": tech_user_id, "scheduled_date": DATE,
        "status": "scheduled", "route_order": 0,
    })
    await _DB.jobs.insert_one({
        "id": j2, "tenant_id": tenant_id, "customer_id": CUST_ID,
        # customer_name intentionally MISSING — must fall back to
        # the customer doc lookup added by this fix.
        "title": "Weekly Pool Cleaning",
        "address": "42 Test Ln, Peoria AZ",
        "technician_id": tech_user_id, "scheduled_date": DATE,
        "status": "scheduled", "route_order": 1,
    })
    return j1, j2


async def _wipe():
    await _DB.customers.delete_many({"id": CUST_ID})
    await _DB.jobs.delete_many({"title": {"$regex": "TEST_opsroutes|Weekly Pool Cleaning"},
                                 "id": {"$regex": "^TEST_opsroutes"}})


@pytest.fixture(autouse=True)
def _clean():
    _run(_wipe())
    yield
    _run(_wipe())


def test_route_stops_projects_customer_display_name_from_job():
    """Case A · customer_name IS denormalised on the job — the
    endpoint echoes it back verbatim in customer_display_name."""
    admin_tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    tech = _run(_DB.users.find_one({"tenant_id": tenant_id, "role": "technician"},
                                    {"_id": 0, "id": 1}))
    assert tech, "seed technician missing"
    j1, _j2 = _run(_seed(tenant_id, tech["id"]))

    r = requests.get(f"{API}/routes/{tech['id']}/stops?date={DATE}",
                     headers={"Authorization": f"Bearer {admin_tok}"}, timeout=15)
    assert r.status_code == 200, r.text
    stops = r.json()["stops"]
    row = next((s for s in stops if s["job_id"] == j1), None)
    assert row is not None
    assert row["customer_display_name"] == CUST_NAME
    assert row["customer_name"] == CUST_NAME


def test_route_stops_falls_back_to_customer_doc_when_job_missing_name():
    """Case B · the tester's scenario. customer_name empty on the
    job → endpoint looks up the customer doc and returns its name
    via the batched map."""
    admin_tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    tech = _run(_DB.users.find_one({"tenant_id": tenant_id, "role": "technician"},
                                    {"_id": 0, "id": 1}))
    _j1, j2 = _run(_seed(tenant_id, tech["id"]))

    r = requests.get(f"{API}/routes/{tech['id']}/stops?date={DATE}",
                     headers={"Authorization": f"Bearer {admin_tok}"}, timeout=15)
    assert r.status_code == 200, r.text
    stops = r.json()["stops"]
    row = next((s for s in stops if s["job_id"] == j2), None)
    assert row is not None, "stop missing"
    # Bug fix: display_name walks name → billing_name → display_name
    # → service_address before falling back to "(no customer)". It
    # NEVER falls through to the job title.
    assert row["customer_display_name"] == CUST_NAME, \
        f"expected customer name from customer doc, got {row!r}"
    assert row["customer_name"] == CUST_NAME
    assert row.get("billing_name") == CUST_NAME
    assert row.get("service_address") == "42 Test Ln, Peoria AZ"
    assert row["customer_display_name"] != row["title"]


def test_route_stops_no_customer_fallback_string_when_all_missing():
    """Case C · orphan job (no customer doc, no customer_name) →
    display_name falls to the resolved address (last-resort chain),
    NOT the job title."""
    admin_tok = _login("super@aquaterra.com")
    tenant_id = _tenant_of("super@aquaterra.com")
    tech = _run(_DB.users.find_one({"tenant_id": tenant_id, "role": "technician"},
                                    {"_id": 0, "id": 1}))
    j_orphan = f"TEST_opsroutes_orphan_{uuid4().hex[:8]}"
    _run(_DB.jobs.insert_one({
        "id": j_orphan, "tenant_id": tenant_id,
        "customer_id": f"missing-{uuid4().hex[:8]}",
        "title": "Weekly Pool Cleaning",
        "address": "99 Orphan Blvd",
        "technician_id": tech["id"], "scheduled_date": DATE,
        "status": "scheduled", "route_order": 2,
    }))
    r = requests.get(f"{API}/routes/{tech['id']}/stops?date={DATE}",
                     headers={"Authorization": f"Bearer {admin_tok}"}, timeout=15)
    assert r.status_code == 200
    stops = r.json()["stops"]
    row = next((s for s in stops if s["job_id"] == j_orphan), None)
    assert row is not None
    # display_name must NOT be the job title (that's the bug we shipped
    # this fix for). Acceptable outcomes: address OR "(no customer)".
    assert row["customer_display_name"] != row["title"]
    assert row["customer_display_name"] in {"99 Orphan Blvd", "(no customer)"}
    _run(_DB.jobs.delete_many({"id": j_orphan}))
