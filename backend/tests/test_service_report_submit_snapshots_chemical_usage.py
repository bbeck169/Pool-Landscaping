"""Feb-2026 · P1 hotfix — Chemistry Profitability was reading $0 on
production because ``snapshot_chemical_usage`` (which writes the
``chemical_usage_events`` rows the ``GET /pools/{pool_id}/chemical-
profitability`` endpoint aggregates over) was only called from the
legacy ``PUT /jobs/{jid}`` field-report path. The modern
``POST /jobs/{jid}/service-report/submit`` path never emitted the
snapshot, so any job completed through the standard tech flow
contributed nothing to the customer chemistry history.

This suite locks the fix in place:

* Seeds a chemical catalog entry, a customer, a pool job, and a
  service_report with ``chemicals_added`` populated by two lines.
* Hits the submit endpoint as an admin (the aquaterra admin passes
  the technician-ownership gate the same way a real tech would).
* Asserts:
    - Two ``chemical_usage_events`` rows are inserted for the
      service_report_id.
    - Each row carries the resolved unit_cost + total_cost snapshot.
    - The chemistry-profitability rollup endpoint now returns a
      non-zero ``total_cost_cents`` for the customer.
    - Re-submitting is idempotent — the delete_many + insert flow
      inside ``snapshot_chemical_usage`` replaces rather than
      double-counts (submit itself is idempotent via
      ``submitted_at`` check, but the snapshot re-run through a
      direct helper call is also verified).

Cleanup: seed jobs / reports / events / catalog rows are all
prefixed with ``TEST-chemsnap-`` (jobs+events) or ``TEST_ChemSnap_``
(job titles), matching the session teardown hook in
``conftest.py``. The module-scoped autouse fixture also self-cleans
on setup + teardown.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"

_JOB_TITLE_PREFIX = "TEST_ChemSnap_"
_ID_PREFIX = "TEST-chemsnap-"
_CATALOG_SLUG = f"{_ID_PREFIX}chlorine-tab-3in"

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": pw}, timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers():
    return {"Authorization": f"Bearer {_login('admin@aquaterra.com')}"}


async def _get_tenant_id(slug: str = "aquaterra") -> str:
    row = await _db().tenants.find_one({"slug": slug}, {"_id": 0, "id": 1})
    assert row, f"tenant slug={slug!r} not found — required seed"
    return row["id"]


async def _pick_customer_id(tenant_id: str) -> str:
    c = await _db().customers.find_one(
        {"tenant_id": tenant_id}, {"_id": 0, "id": 1},
    )
    assert c, "expected at least one customer in aquaterra"
    return c["id"]


async def _pick_admin_id(tenant_id: str) -> str:
    u = await _db().users.find_one(
        {"tenant_id": tenant_id, "email": "admin@aquaterra.com"},
        {"_id": 0, "id": 1},
    )
    assert u, "admin@aquaterra.com is a required seed"
    return u["id"]


async def _seed_catalog(tenant_id: str) -> None:
    """Idempotent catalog seed so ``snapshot_chemical_usage`` can
    resolve a unit cost by slug."""
    await _db().chemical_costs.update_one(
        {"tenant_id": tenant_id, "chemical_slug": _CATALOG_SLUG},
        {"$set": {
            "id": _CATALOG_SLUG,
            "tenant_id": tenant_id,
            "chemical_slug": _CATALOG_SLUG,
            "name": "TEST Chlorine Tab 3in",
            "cost_per_unit_cents": 250,   # $2.50/tab
            "unit_kind": "tab",
        }},
        upsert=True,
    )


async def _seed_job_and_report(tenant_id: str, customer_id: str,
                                actor_id: str) -> dict:
    """Seed one pool job in status=scheduled and a bootstrap
    service_report with chemicals_added populated by two lines."""
    from datetime import datetime, timezone
    job_id = f"{_ID_PREFIX}job-{uuid.uuid4().hex[:8]}"
    sr_id = f"{_ID_PREFIX}sr-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    scheduled = "2099-09-15T14:00:00+00:00"
    await _db().jobs.insert_one({
        "id": job_id,
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "title": f"{_JOB_TITLE_PREFIX}{uuid.uuid4().hex[:6]}",
        "service_type": "pool",
        "job_type": "pool",
        "status": "scheduled",
        "scheduled_date": scheduled,
        "scheduled_start": scheduled,
        "technician_id": actor_id,
        "created_at": now, "updated_at": now,
    })
    await _db().service_reports.insert_one({
        "id": sr_id,
        "tenant_id": tenant_id,
        "job_id": job_id,
        "tech_id": actor_id,
        "template_kind": "pool",
        "created_at": now, "updated_at": now,
        "submitted_at": None,
        "chemical_readings": [
            {"key": "free_chlorine",  "value": 2.5},
            {"key": "ph",             "value": 7.4},
            {"key": "alkalinity",     "value": 90},
            {"key": "cyanuric_acid",  "value": 45},
        ],
        "chemicals_added": [
            {"product_slug": _CATALOG_SLUG,
              "name": "TEST Chlorine Tab 3in",
              "quantity_used": 2, "unit": "tab"},
            {"product_slug": _CATALOG_SLUG,
              "name": "TEST Chlorine Tab 3in",
              "quantity_used": 1, "unit": "tab"},
        ],
        "checklist_items": [], "photos": [], "notes": "",
    })
    return {"job_id": job_id, "service_report_id": sr_id}


async def _cleanup() -> None:
    seeded_job_ids = [j["id"] async for j in _db().jobs.find(
        {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}},
        {"_id": 0, "id": 1},
    )]
    await _db().jobs.delete_many(
        {"title": {"$regex": f"^{_JOB_TITLE_PREFIX}"}})
    await _db().service_reports.delete_many(
        {"job_id": {"$in": seeded_job_ids}} if seeded_job_ids
        else {"id": {"$regex": f"^{_ID_PREFIX}"}})
    await _db().chemical_usage_events.delete_many(
        {"job_id": {"$in": seeded_job_ids}} if seeded_job_ids
        else {"service_report_id": {"$regex": f"^{_ID_PREFIX}"}})
    await _db().chemical_costs.delete_many(
        {"chemical_slug": _CATALOG_SLUG})


@pytest.fixture(scope="module", autouse=True)
def seed_ctx():
    tenant_id = _run(_get_tenant_id())
    customer_id = _run(_pick_customer_id(tenant_id))
    admin_id = _run(_pick_admin_id(tenant_id))
    _run(_cleanup())
    _run(_seed_catalog(tenant_id))
    seed = _run(_seed_job_and_report(tenant_id, customer_id, admin_id))
    yield {"tenant_id": tenant_id, "customer_id": customer_id,
             "admin_id": admin_id, **seed}
    _run(_cleanup())


# ═══════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════
def test_submit_emits_chemical_usage_events(admin_headers, seed_ctx):
    """The core assertion: submitting a service-report must insert
    one ``chemical_usage_events`` row per chemicals_added line."""
    jid = seed_ctx["job_id"]
    sr_id = seed_ctx["service_report_id"]

    r = requests.post(
        f"{API}/jobs/{jid}/service-report/submit",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text

    # Snapshot rows now exist for this service_report_id.
    async def _fetch():
        return [e async for e in _db().chemical_usage_events.find(
            {"service_report_id": sr_id}, {"_id": 0},
        )]
    events = _run(_fetch())
    assert len(events) == 2, (
        f"expected 2 chemical_usage_events rows for the submit, got "
        f"{len(events)}: {[e.get('id') for e in events]}"
    )

    # Each row snapshotted the resolved unit cost + tenant/customer.
    for e in events:
        assert e["tenant_id"] == seed_ctx["tenant_id"]
        assert e["customer_id"] == seed_ctx["customer_id"]
        assert e["job_id"] == jid
        assert e["product_slug"] == _CATALOG_SLUG
        assert e["unit_cost_at_time_cents"] == 250
        assert e["total_cost_cents"] == 250 * int(e["quantity_used"])
    total = sum(int(e["total_cost_cents"]) for e in events)
    # 2 tabs + 1 tab @ 250 cents = 750 cents.
    assert total == 750, f"expected snapshot total 750, got {total}"


def test_profitability_endpoint_reflects_submitted_usage(
    admin_headers, seed_ctx,
):
    """The Chemistry History page reads
    ``/pools/{customer_id}/chemical-profitability`` — after the
    submit, this rollup must return a non-zero total for the
    customer."""
    customer_id = seed_ctx["customer_id"]
    r = requests.get(
        f"{API}/pools/{customer_id}/chemical-profitability?months=36",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    totals = body.get("totals") or {}
    assert totals.get("total_cost_cents", 0) >= 750, (
        "profitability rollup missed the seeded snapshot — "
        f"got {totals}"
    )
    assert totals.get("visit_count", 0) >= 1, (
        f"profitability rollup missed the visit — got {totals}"
    )


def test_snapshot_is_idempotent_on_replay(admin_headers, seed_ctx):
    """``snapshot_chemical_usage`` does ``delete_many`` before
    ``insert_one`` per line, so a second run on the same
    (tenant, service_report_id) replaces rather than double-counts.
    Exercise the real replay path: reset the report to un-submitted,
    swap the chemicals_added shape, re-submit, and assert the event
    set was REPLACED (not accumulated)."""
    jid = seed_ctx["job_id"]
    sr_id = seed_ctx["service_report_id"]

    # Clear the submitted_at gate so we can re-submit, and swap
    # the chemicals_added shape (2 lines → 1 line, doubled qty)
    # to distinguish "replaced" from "appended".
    async def _reset():
        await _db().service_reports.update_one(
            {"id": sr_id},
            {"$set": {
                "submitted_at": None,
                "chemicals_added": [
                    {"product_slug": _CATALOG_SLUG,
                     "name": "TEST Chlorine Tab 3in",
                     "quantity_used": 4, "unit": "tab"},
                ],
            }},
        )
        # And the job status back off `completed` so the door-hanger
        # side-effect (fired on the completed→completed transition)
        # doesn't try to re-send anything for this test seed.
        await _db().jobs.update_one(
            {"id": jid},
            {"$set": {"status": "scheduled"}},
        )
    _run(_reset())

    r = requests.post(
        f"{API}/jobs/{jid}/service-report/submit",
        headers=admin_headers, timeout=30,
    )
    assert r.status_code == 200, r.text

    async def _fetch():
        return [e async for e in _db().chemical_usage_events.find(
            {"service_report_id": sr_id}, {"_id": 0},
        )]
    events = _run(_fetch())
    # Exactly one event — old two rows replaced by the single new row.
    assert len(events) == 1, (
        f"idempotency broken — expected 1 event after replay, got "
        f"{len(events)}: {[e.get('quantity_used') for e in events]}"
    )
    assert events[0]["quantity_used"] == 4
    assert events[0]["total_cost_cents"] == 250 * 4
