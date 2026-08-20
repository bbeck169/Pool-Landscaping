"""Feb-2026 · Slice 4 — Chemical cost hide on customer-facing views.

Guards the customer-scoped service-report endpoint
``GET /customers/me/service-reports/{report_id}``:

* ``chemicals_added`` rows still render name + amount + unit
* ``chemicals_added`` rows MUST NOT expose pricing fields
  (``unit_cost``, ``line_total``, ``cost_cents``, ``price_cents``,
  etc.)
* Top-level cost totals (``chem_total_cents``,
  ``chemicals_total_cents``, …) are also stripped.

Tech / admin / super_admin surfaces are out of scope — those still
render the raw service_report doc and therefore still see costs. That
invariant is asserted separately in the internal Workstream tests.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict

import pytest


_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _bind_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    fresh = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=_LOOP)
    fresh_db = fresh[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = fresh_db
    import routers.service_reports as _mod
    _mod.db = fresh_db
    yield


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(
        os.environ["MONGO_URL"], io_loop=_LOOP,
    )[os.environ["DB_NAME"]]


async def _tenant_id() -> str:
    u = await _db().users.find_one(
        {"email": "admin@aquaterra.com"}, {"_id": 0, "tenant_id": 1},
    )
    return u["tenant_id"]


async def _seed(tenant_id: str) -> Dict[str, str]:
    from utils import now_iso
    cid = f"test-cust-{uuid.uuid4().hex[:12]}"
    jid = f"test-job-{uuid.uuid4().hex[:12]}"
    rid = f"test-rep-{uuid.uuid4().hex[:12]}"
    uid = f"test-user-{uuid.uuid4().hex[:12]}"
    await _db().customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "Priced Test", "first_name": "Priced", "last_name": "Test",
        "email": "priced.test@example.com",
    })
    await _db().jobs.insert_one({
        "id": jid, "tenant_id": tenant_id, "customer_id": cid,
        "customer_name": "Priced Test", "title": "Weekly Pool",
        "service_type": "Weekly Pool Service",
        "status": "completed", "completed_at": now_iso(),
        "scheduled_start": now_iso(),
    })
    await _db().service_reports.insert_one({
        "id": rid, "tenant_id": tenant_id, "job_id": jid,
        "status": "submitted", "submitted_at": now_iso(),
        "chemical_readings": [
            {"key": "free_chlorine", "value": 2.5, "unit": "ppm"},
            {"key": "ph",            "value": 7.4},
        ],
        # Priced chemical rows — every pricing-signal field the
        # code base is known to write must be stripped for the
        # customer-scoped response.
        "chemicals_added": [
            {
                "name": "Liquid Chlorine", "quantity": 1.0, "unit": "gallon",
                "unit_cost": 8.00, "line_total": 8.00,
                "cost_cents": 800, "price_cents": 800,
                "unit_cost_at_time_cents": 800, "total_cost_cents": 800,
            },
            {
                "name": "Muriatic Acid", "quantity": 0.25, "unit": "gallon",
                "unit_cost": 12.00, "line_total": 3.00,
                "cost_cents": 300,
            },
        ],
        "chem_total_cents": 1100,
        "chemicals_total_cents": 1100,
        "checklist_items": [
            {"key": "skimmed_pool", "label": "Skimmed Pool", "checked": True},
        ],
        "internal_notes": "MARGIN NOTE — do not leak",
        "notes": "Public notes.",
    })
    # Customer session user (role=customer).
    await _db().users.insert_one({
        "id": uid, "tenant_id": tenant_id,
        "email": "priced.test@example.com", "role": "customer",
        "customer_id": cid,
    })
    return {"cid": cid, "jid": jid, "rid": rid, "uid": uid}


async def _drain(tenant_id: str, seed: Dict[str, str]) -> None:
    await _db().customers.delete_many({"tenant_id": tenant_id, "id": seed["cid"]})
    await _db().jobs.delete_many({"tenant_id": tenant_id, "id": seed["jid"]})
    await _db().service_reports.delete_many({"tenant_id": tenant_id, "id": seed["rid"]})
    await _db().users.delete_many({"tenant_id": tenant_id, "id": seed["uid"]})


async def _fetch_report(rid: str, tenant_id: str, uid: str) -> Dict[str, Any]:
    """Direct in-process call to the route handler with a synthetic
    customer session. Avoids the JWT dance for a pure DTO test."""
    from routers.service_reports import get_my_service_report
    user = await _db().users.find_one({"id": uid}, {"_id": 0})
    tenant = await _db().tenants.find_one({"id": tenant_id}, {"_id": 0})
    return await get_my_service_report(rid, user=user, tenant=tenant)


_COST_FIELDS = (
    "unit_cost", "line_total", "cost_cents", "price_cents",
    "unit_cost_at_time_cents", "total_cost_cents",
    "unit_cost_cents", "line_total_cents",
)


def test_portal_service_report_strips_chemical_costs():
    async def _go():
        tid = await _tenant_id()
        seed = await _seed(tid)
        try:
            sr = await _fetch_report(seed["rid"], tid, seed["uid"])

            # Chemicals still visible with name + qty + unit.
            chems = sr.get("chemicals_added") or []
            assert len(chems) == 2, chems
            names = {c.get("name") for c in chems}
            assert names == {"Liquid Chlorine", "Muriatic Acid"}, names
            for c in chems:
                assert c.get("name")
                assert c.get("quantity") is not None
                assert c.get("unit")
                for f in _COST_FIELDS:
                    assert f not in c, (
                        f"cost field {f!r} leaked into customer chemical row: {c}"
                    )

            # Top-level cost totals must be gone as well.
            for f in (
                "chem_total_cents", "chemicals_total_cents",
                "chemicals_cost_cents",
            ):
                assert f not in sr, (
                    f"top-level cost field {f!r} leaked into customer response"
                )

            # Serialise the whole payload and eyeball for pricing
            # signals — regression net for future adds. We accept
            # numeric-looking substrings like "1.0" (qty) but reject
            # explicit money strings.
            blob = json.dumps(sr)
            for _needle in ("$", "unit_cost", "line_total", "cost_cents", "price_cents"):
                assert _needle not in blob, (
                    f"pricing signal {_needle!r} present in customer DTO"
                )

            # Existing redactions still hold.
            assert "internal_notes" not in sr
            assert sr.get("notes") == "Public notes."
        finally:
            await _drain(tid, seed)

    _run(_go())


def test_portal_service_report_preserves_amount_display_fields():
    """Regression guard — the strip is field-scoped, not row-wide.
    We must NOT accidentally drop ``amount`` / ``qty`` aliases some
    legacy rows use in place of ``quantity``.
    """
    async def _go():
        tid = await _tenant_id()
        seed = await _seed(tid)
        # Overwrite the seeded rows with alias-heavy versions.
        await _db().service_reports.update_one(
            {"id": seed["rid"]},
            {"$set": {"chemicals_added": [
                {"name": "Chlorine Tabs", "amount": 3, "unit": "tabs",
                 "unit_cost": 2.0, "line_total": 6.0},
                {"chemical": "Bleach", "qty": 2, "default_unit": "gallon",
                 "cost_cents": 500},
                {"raw_label": "1 scoop", "name": "Shock",
                 "line_total": 4.5},
            ]}},
        )
        try:
            sr = await _fetch_report(seed["rid"], tid, seed["uid"])
            chems = sr.get("chemicals_added") or []
            assert len(chems) == 3
            # Row 1 — amount preserved.
            assert chems[0].get("amount") == 3
            assert chems[0].get("unit") == "tabs"
            # Row 2 — qty + chemical alias preserved.
            assert chems[1].get("qty") == 2
            assert chems[1].get("chemical") == "Bleach"
            assert chems[1].get("default_unit") == "gallon"
            # Row 3 — raw_label preserved (used by "1 scoop" style logs).
            assert chems[2].get("raw_label") == "1 scoop"
            assert chems[2].get("name") == "Shock"
            # No cost fields on any row.
            for c in chems:
                for f in _COST_FIELDS:
                    assert f not in c, (f, c)
        finally:
            await _drain(tid, seed)

    _run(_go())
