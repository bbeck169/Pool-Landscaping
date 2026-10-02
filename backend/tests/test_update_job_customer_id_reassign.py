"""Jobs Overhaul Phase 3a · PUT /jobs/{jid} customer_id reassignment.

Pins the backend side of the inline Customer tile on JobDetail.
When ``PUT /api/jobs/{jid}`` carries a ``customer_id`` that differs
from the job's current one, the handler MUST:

  (a) re-resolve ``customer_name`` from the target customer row
      (mirrors ``POST /jobs``:1535-1540);
  (b) ``$unset`` the stale ``property_id`` + ``address`` snapshot
      (both belong to the OLD customer and must NOT follow the
      job onto its new owner);
  (c) reject with HTTP 400 when the new ``customer_id`` doesn't
      resolve to a customer in the caller's tenant.

Harness mirrors ``test_jobs_put_role_gate.py`` — live ``requests``
to the FastAPI pod, admin login, direct ``motor`` seeds via
``asyncio.get_event_loop().run_until_complete``, explicit teardown.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os as _os_local                                             # noqa: E402
_ENV_BASE = _os_local.environ.get("JOB_CUSTOMER_PATCH_TEST_BASE")
BASE = (_ENV_BASE or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"

from config import db                                              # noqa: E402


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def super_session() -> dict:
    s = _login("super@aquaterra.com")
    me = requests.get(f"{API}/auth/me",
                       headers={"Authorization": f"Bearer {s['access_token']}"},
                       timeout=15).json()
    return {
        "headers": {"Authorization": f"Bearer {s['access_token']}"},
        "tenant_id": me.get("tenant_id"),
    }


@pytest.fixture()
def two_customers_and_a_job(super_session) -> dict:
    """Seed:
    - old_customer: has one property (resolves address + property_id)
    - new_customer: standalone (no property wiring needed)
    - job: scheduled on old_customer with that property_id + address.
    """
    tenant_id = super_session["tenant_id"]
    old_cid = f"cust-old-{uuid.uuid4()}"
    new_cid = f"cust-new-{uuid.uuid4()}"
    old_pid = f"prop-old-{uuid.uuid4()}"
    jid = f"job-reassign-{uuid.uuid4()}"
    docs = {
        "old_customer": {
            "id": old_cid, "tenant_id": tenant_id,
            "name": "Old Customer Co.", "is_active": True,
            "address": "123 Old Street, Oldtown AZ 85000",
            "phone": "480-555-0001", "email": "old@example.test",
        },
        "new_customer": {
            "id": new_cid, "tenant_id": tenant_id,
            "name": "New Customer LLC", "is_active": True,
            "address": "999 New Avenue, Newtown AZ 85099",
            "phone": "480-555-0999", "email": "new@example.test",
        },
        "old_property": {
            "id": old_pid, "tenant_id": tenant_id,
            "customer_id": old_cid, "is_active": True,
            "address": "123 Old Street, Oldtown AZ 85000",
            "label": "Primary",
        },
        "job": {
            "id": jid, "tenant_id": tenant_id,
            "customer_id": old_cid, "customer_name": "Old Customer Co.",
            "property_id": old_pid,
            "address": "123 Old Street, Oldtown AZ 85000",
            "title": "ph3a-reassign seeded",
            "service_type": "Landscape Maintenance",
            "status": "scheduled",
            "scheduled_date": datetime.now(timezone.utc).date().isoformat(),
            "work_class": "service",
        },
    }

    async def _seed():
        await db.customers.insert_one(dict(docs["old_customer"]))
        await db.customers.insert_one(dict(docs["new_customer"]))
        await db.properties.insert_one(dict(docs["old_property"]))
        await db.jobs.insert_one(dict(docs["job"]))
    _run(_seed())

    yield {"old_cid": old_cid, "new_cid": new_cid,
             "old_pid": old_pid, "jid": jid}

    async def _teardown():
        await db.customers.delete_many({"id": {"$in": [old_cid, new_cid]}})
        await db.properties.delete_many({"id": old_pid})
        await db.jobs.delete_many({"id": jid})
    _run(_teardown())


# ─────────────────────────── tests ───────────────────────────────
def test_reassigning_customer_resolves_denorm_customer_name(
    super_session, two_customers_and_a_job,
):
    bag = two_customers_and_a_job
    r = requests.put(
        f"{API}/jobs/{bag['jid']}",
        headers=super_session["headers"],
        json={"customer_id": bag["new_cid"]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    stored = _run(db.jobs.find_one({"id": bag["jid"]}, {"_id": 0}))
    assert stored["customer_id"] == bag["new_cid"]
    assert stored["customer_name"] == "New Customer LLC", (
        f"customer_name not re-resolved; stored={stored.get('customer_name')!r}"
    )


def test_reassigning_customer_unsets_stale_property_and_address(
    super_session, two_customers_and_a_job,
):
    bag = two_customers_and_a_job
    # Precondition — baseline carries old property + address.
    pre = _run(db.jobs.find_one({"id": bag["jid"]}, {"_id": 0}))
    assert pre["property_id"] == bag["old_pid"]
    assert "Old Street" in pre["address"]

    r = requests.put(
        f"{API}/jobs/{bag['jid']}",
        headers=super_session["headers"],
        json={"customer_id": bag["new_cid"]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    post = _run(db.jobs.find_one({"id": bag["jid"]}, {"_id": 0}))
    assert "property_id" not in post, (
        f"stale property_id leaked onto reassigned job: {post.get('property_id')!r}"
    )
    assert "address" not in post, (
        f"stale address leaked onto reassigned job: {post.get('address')!r}"
    )


def test_reassigning_to_unknown_customer_rejects_with_400(
    super_session, two_customers_and_a_job,
):
    bag = two_customers_and_a_job
    r = requests.put(
        f"{API}/jobs/{bag['jid']}",
        headers=super_session["headers"],
        json={"customer_id": "customer-does-not-exist-" + uuid.uuid4().hex},
        timeout=15,
    )
    assert r.status_code == 400, r.text
    body = r.json()
    detail = (body.get("detail") or "").lower()
    assert "customer" in detail, f"400 detail missing 'customer': {body!r}"
    # Confirm the job doc was NOT mutated by the rejected request.
    post = _run(db.jobs.find_one({"id": bag["jid"]}, {"_id": 0}))
    assert post["customer_id"] == bag["old_cid"]
    assert post["customer_name"] == "Old Customer Co."
    assert post["property_id"] == bag["old_pid"]
