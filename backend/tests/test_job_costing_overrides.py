"""Jobs Overhaul Phase 3b · editable Job Costing overrides.

Pins the backend side of the inline Budgeted/Actual edits on
``JobCostingPanel``:

  * ``GET /api/jobs/{jid}/costing`` merges ``costing_overrides``
    on top of computed baseline/actual before deriving progress
    + net-profit + margin. Raw ``costing_overrides`` dict is
    echoed at the top level so the FE can hydrate state and
    PUT the full merged shape on each cell commit.
  * ``PUT /api/jobs/{jid}`` with ``costing_overrides`` is
    (a) admin-equivalent only (403 for techs/customers), and
    (b) shape-validated (400 on unknown buckets / inner keys /
    non-non-negative-int values).
  * The write is atomic — the backend ``$set``s the field
    verbatim. Confirmed indirectly by the "overrides reflect in
    next GET" assertion.

Harness mirrors ``test_update_job_customer_id_reassign.py`` —
live ``requests`` to the FastAPI pod + direct ``motor`` seeds via
``asyncio.get_event_loop().run_until_complete``.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_ENV_BASE = os.environ.get("JOB_COSTING_OVERRIDES_TEST_BASE")
BASE = (_ENV_BASE or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db  # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(
        f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15,
    )
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def super_session() -> dict:
    s = _login("super@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {s['access_token']}"}, timeout=15,
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {s['access_token']}"},
        "tenant_id": me.get("tenant_id"),
        "user_id": me.get("id"),
    }


@pytest.fixture(scope="module")
def tech_session() -> dict:
    s = _login("mike@aquaterra.com")
    me = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {s['access_token']}"}, timeout=15,
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {s['access_token']}"},
        "tenant_id": me.get("tenant_id"),
        "user_id": me.get("id"),
        "technician_id": me.get("technician_id"),
    }


@pytest.fixture()
def seeded_job(super_session):
    """A job owned by the super_admin's tenant.  Price = $500 so
    the costing panel has a real revenue baseline to drive the
    net-profit assertions."""
    tenant_id = super_session["tenant_id"]
    cid = f"cust-ph3b-{uuid.uuid4()}"
    jid = f"job-ph3b-{uuid.uuid4()}"
    docs = {
        "customer": {
            "id": cid, "tenant_id": tenant_id,
            "name": "Phase 3b Customer", "is_active": True,
            "address": "500 Dollar Ln", "phone": "555-0001",
        },
        "job": {
            "id": jid, "tenant_id": tenant_id,
            "customer_id": cid, "customer_name": "Phase 3b Customer",
            "address": "500 Dollar Ln",
            "title": "ph3b-costing seeded",
            "service_type": "Pool Cleaning",
            "status": "scheduled",
            "scheduled_date": datetime.now(timezone.utc).date().isoformat(),
            "work_class": "service",
            "price": 500.0,
        },
    }

    async def _seed():
        await db.customers.insert_one(dict(docs["customer"]))
        await db.jobs.insert_one(dict(docs["job"]))
    _run(_seed())

    yield {"cid": cid, "jid": jid}

    async def _teardown():
        await db.customers.delete_many({"id": cid})
        await db.jobs.delete_many({"id": jid})
    _run(_teardown())


# ─────────────────────── GET /costing ────────────────────────────
def test_costing_no_overrides_returns_raw_baseline_and_echoes_empty_dict(
    super_session, seeded_job,
):
    r = requests.get(
        f"{API}/jobs/{seeded_job['jid']}/costing",
        headers=super_session["headers"], timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Price=500 ⇒ revenue_cents=50000. All computed costs = 0 (no
    # time entries, no chemicals, no inventory reservations).
    assert body["baseline"]["revenue_cents"] == 50000, body
    assert body["baseline"]["labor_cents"] == 0
    assert body["baseline"]["materials_cents"] == 0
    assert body["baseline"]["equipment_cents"] == 0
    assert body["actual"]["labor_cents"] == 0
    # No overrides written yet ⇒ echoed as empty dict.
    assert body.get("costing_overrides") == {}, body
    # Net profit = revenue - 0 = 50000.
    assert body["estimated_net_profit_cents"] == 50000
    assert body["actual_net_profit_cents"] == 50000


def test_costing_merges_overrides_and_recomputes_profit(
    super_session, seeded_job,
):
    # Write baseline+actual overrides on labor and materials
    # directly to the DB so this test exercises the GET-side
    # merge alone (PUT-side merge is covered separately below).
    async def _seed_overrides():
        await db.jobs.update_one(
            {"id": seeded_job["jid"]},
            {"$set": {"costing_overrides": {
                "labor":     {"budgeted_cents": 10000, "actual_cents": 15000},
                "materials": {"budgeted_cents":  5000, "actual_cents":  3000},
            }}},
        )
    _run(_seed_overrides())
    try:
        r = requests.get(
            f"{API}/jobs/{seeded_job['jid']}/costing",
            headers=super_session["headers"], timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Merged baseline + actual.
        assert body["baseline"]["labor_cents"] == 10000
        assert body["baseline"]["materials_cents"] == 5000
        assert body["baseline"]["equipment_cents"] == 0  # not overridden
        assert body["actual"]["labor_cents"] == 15000
        assert body["actual"]["materials_cents"] == 3000
        # Progress uses merged values. labor: 15000/10000 ⇒ 150%,
        # materials: 3000/5000 ⇒ 60%.
        assert body["progress"]["labor_pct"] == 150.0
        assert body["progress"]["materials_pct"] == 60.0
        # Profit recomputed from merged costs:
        # estimated: 50000 - (10000 + 5000 + 0) = 35000
        # actual:    50000 - (15000 + 3000 + 0) = 32000
        assert body["estimated_net_profit_cents"] == 35000
        assert body["actual_net_profit_cents"] == 32000
        # Overrides echoed verbatim.
        assert body["costing_overrides"] == {
            "labor":     {"budgeted_cents": 10000, "actual_cents": 15000},
            "materials": {"budgeted_cents":  5000, "actual_cents":  3000},
        }
    finally:
        _run(db.jobs.update_one(
            {"id": seeded_job["jid"]},
            {"$unset": {"costing_overrides": ""}},
        ))


# ─────────────────────── PUT /jobs {overrides} ───────────────────
def test_put_persists_overrides_and_next_get_reflects_merge(
    super_session, seeded_job,
):
    try:
        r = requests.put(
            f"{API}/jobs/{seeded_job['jid']}",
            headers=super_session["headers"],
            json={"costing_overrides": {
                "labor":     {"budgeted_cents": 20000},
                "equipment": {"actual_cents": 7500},
            }},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # Confirm persisted via DB read.
        stored = _run(db.jobs.find_one(
            {"id": seeded_job["jid"]}, {"_id": 0, "costing_overrides": 1},
        ))
        assert stored["costing_overrides"] == {
            "labor":     {"budgeted_cents": 20000},
            "equipment": {"actual_cents": 7500},
        }
        # Next GET /costing reflects the merged view.
        g = requests.get(
            f"{API}/jobs/{seeded_job['jid']}/costing",
            headers=super_session["headers"], timeout=15,
        ).json()
        assert g["baseline"]["labor_cents"] == 20000
        assert g["actual"]["equipment_cents"] == 7500
        # Non-overridden fields fall back to computed (0).
        assert g["baseline"]["materials_cents"] == 0
        assert g["actual"]["labor_cents"] == 0
    finally:
        _run(db.jobs.update_one(
            {"id": seeded_job["jid"]},
            {"$unset": {"costing_overrides": ""}},
        ))


def test_put_with_unknown_bucket_rejected_400(super_session, seeded_job):
    r = requests.put(
        f"{API}/jobs/{seeded_job['jid']}",
        headers=super_session["headers"],
        json={"costing_overrides": {"bogus": {"budgeted_cents": 1}}},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    assert "bogus" in r.text.lower() or "unknown bucket" in r.text.lower(), r.text


def test_put_with_unknown_inner_field_rejected_400(super_session, seeded_job):
    r = requests.put(
        f"{API}/jobs/{seeded_job['jid']}",
        headers=super_session["headers"],
        json={"costing_overrides": {"labor": {"foo_cents": 1}}},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    assert "foo_cents" in r.text.lower() or "unknown field" in r.text.lower(), r.text


def test_put_with_negative_value_rejected_400(super_session, seeded_job):
    r = requests.put(
        f"{API}/jobs/{seeded_job['jid']}",
        headers=super_session["headers"],
        json={"costing_overrides": {"labor": {"budgeted_cents": -1}}},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    assert "non-negative" in r.text.lower(), r.text


def test_put_with_bool_value_rejected_400(super_session, seeded_job):
    # ``isinstance(True, int) is True`` in Python — the handler
    # must reject booleans so ``{"budgeted_cents": True}``
    # doesn't sneak through as 1.
    r = requests.put(
        f"{API}/jobs/{seeded_job['jid']}",
        headers=super_session["headers"],
        json={"costing_overrides": {"labor": {"budgeted_cents": True}}},
        timeout=15,
    )
    assert r.status_code == 400, r.text


def test_put_with_overrides_as_non_admin_rejected_403(
    tech_session, super_session, seeded_job,
):
    # Assign the job to the tech so the ownership guard doesn't
    # 403-pre-empt our actual costing-overrides 403 — otherwise
    # we can't distinguish "wrong role" from "not your job".
    tech_id = tech_session.get("technician_id") or tech_session.get("user_id")
    _run(db.jobs.update_one(
        {"id": seeded_job["jid"]}, {"$set": {"technician_id": tech_id}},
    ))
    try:
        r = requests.put(
            f"{API}/jobs/{seeded_job['jid']}",
            headers=tech_session["headers"],
            json={"costing_overrides": {"labor": {"budgeted_cents": 1000}}},
            timeout=15,
        )
        # Expect 403 either from the ownership guard (if F1 crew
        # gate rejects first) or from the costing_overrides gate.
        # The locked contract is "costing_overrides-scoped 403"
        # — we assert both status and message so the message
        # pins the scoping.
        assert r.status_code == 403, r.text
        assert "costing_overrides" in r.text or "admin-equivalent" in r.text, r.text
    finally:
        _run(db.jobs.update_one(
            {"id": seeded_job["jid"]}, {"$unset": {"technician_id": ""}},
        ))


def test_put_clearing_overrides_with_empty_dict_persists_200(
    super_session, seeded_job,
):
    # Seed first.
    _run(db.jobs.update_one(
        {"id": seeded_job["jid"]},
        {"$set": {"costing_overrides": {"labor": {"budgeted_cents": 5000}}}},
    ))
    try:
        r = requests.put(
            f"{API}/jobs/{seeded_job['jid']}",
            headers=super_session["headers"],
            json={"costing_overrides": {}},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        stored = _run(db.jobs.find_one(
            {"id": seeded_job["jid"]}, {"_id": 0, "costing_overrides": 1},
        ))
        assert stored.get("costing_overrides") == {}
    finally:
        _run(db.jobs.update_one(
            {"id": seeded_job["jid"]},
            {"$unset": {"costing_overrides": ""}},
        ))
