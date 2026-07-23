"""Phase 16 · Item 5 · Feb-2026 — Mass Messaging end-to-end
sanity test with the Resend + RingCentral adapters stubbed.

Reproduces the "not sending / not showing in log" bug report and
proves the guardrails:

* Sending a broadcast to 2 seeded customers persists exactly 2
  ``marketing_deliveries`` rows (one per recipient) with
  ``trigger_entity.kind == "mass_broadcast"``.
* Those rows come back on ``GET /api/communications-log``.
* A raised adapter exception still writes a ``failed`` row with the
  error captured — no silent drops.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT_ID = _sync.tenants.find_one({"slug": "aquaterra"})["id"]
API = "http://localhost:8001/api"


def _login(email, pw="password123"):
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(autouse=True)
def _clean_slate():
    _sync.mass_messaging_batches.delete_many({"tenant_id": _TENANT_ID})
    _sync.mass_messaging_confirm_tokens.delete_many({"tenant_id": _TENANT_ID})
    _sync.marketing_deliveries.delete_many({
        "tenant_id": _TENANT_ID,
        "trigger_entity.kind": "mass_broadcast",
        "customer_id": {"$regex": "^bugfix-"},
    })
    yield
    _sync.marketing_deliveries.delete_many({
        "tenant_id": _TENANT_ID,
        "trigger_entity.kind": "mass_broadcast",
        "customer_id": {"$regex": "^bugfix-"},
    })


@pytest.fixture
def two_customers():
    marker = uuid.uuid4().hex[:6]
    docs = [
        {"id": f"bugfix-{marker}-a", "tenant_id": _TENANT_ID,
          "name": f"Bug A {marker}", "first_name": "Anne",
          "email": f"anne-{marker}@ex.local", "phone": "+15550001111",
          "is_active": True},
        {"id": f"bugfix-{marker}-b", "tenant_id": _TENANT_ID,
          "name": f"Bug B {marker}", "first_name": "Ben",
          "email": f"ben-{marker}@ex.local", "phone": "+15550002222",
          "is_active": True},
    ]
    _sync.customers.insert_many(docs)
    ids = [d["id"] for d in docs]
    try:
        yield ids
    finally:
        _sync.customers.delete_many({"id": {"$in": ids}})


def test_send_persists_one_row_per_recipient_and_shows_in_log(
        admin_headers, two_customers):
    """Fire a preview + send with the DB currently holding ONLY the two
    seeded scratch customers (autouse fixture wipes prior broadcasts,
    but *other* active customers on the tenant remain — that's fine,
    we assert on the specific customer_ids we control)."""
    body = {"channels": ["email"], "audience": "all_active_customers",
             "subject": "Hi {{customer.first_name}}",
             "body": "Body for {{customer.first_name}}"}
    prev = requests.post(f"{API}/mass-messaging/preview", json=body,
                          headers=admin_headers, timeout=15).json()
    assert prev["estimated_recipients"]["email"] >= 2

    send = requests.post(
        f"{API}/mass-messaging/send",
        json={**body, "confirm_token": prev["confirm_token"]},
        headers=admin_headers, timeout=15,
    ).json()
    batch_id = send["batch_id"]
    assert batch_id

    # Wait for the background fanout — completed status is written
    # once the loop finishes; 5s is plenty for 2 rows.
    deadline = time.time() + 10
    while time.time() < deadline:
        b = _sync.mass_messaging_batches.find_one({"id": batch_id})
        if b and b.get("status") == "completed":
            break
        time.sleep(0.5)
    assert b["status"] == "completed", f"batch stuck: {b}"

    # Assert our TWO scratch customers each got exactly one email row.
    for cid in two_customers:
        rows = list(_sync.marketing_deliveries.find({
            "customer_id": cid, "batch_id": batch_id, "channel": "email",
        }))
        assert len(rows) == 1, f"expected 1 email row for {cid}, got {len(rows)}"
        row = rows[0]
        assert row["trigger_entity"]["kind"] == "mass_broadcast"
        assert row["trigger_entity"]["id"] == batch_id
        assert row["tenant_id"] == _TENANT_ID

    # GET /api/communications-log must surface those rows too.
    log = requests.get(
        f"{API}/communications-log?page_size=200",
        headers=admin_headers, timeout=10,
    ).json()
    log_ids = {r.get("customer_id") for r in log["items"]}
    for cid in two_customers:
        assert cid in log_ids, f"communications-log missing customer {cid}"


def test_adapter_exception_still_writes_failed_row(two_customers):
    """If the email adapter raises inside the fanout loop, the code
    must catch, mark the row as ``failed``, and capture the error
    message onto the ledger row. This is the guardrail for the
    checklist's 'fire-and-forget swallowing exceptions' concern.

    We call ``_run_broadcast`` directly (in-process) so we can patch
    the adapter's ``send`` attribute. HTTP-driven mocking wouldn't
    work — the background task runs inside the uvicorn process, not
    the test process."""
    import asyncio
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from routers.mass_messaging import _run_broadcast
    from utils import new_id, now_iso

    batch_id = new_id()
    _sync.mass_messaging_batches.insert_one({
        "id": batch_id, "tenant_id": _TENANT_ID,
        "initiated_by_user_id": "test-user",
        "channels": ["email"], "template_id": None,
        "custom_subject": "Boom", "custom_body": "Boom {{customer.first_name}}",
        "audience": "all_active_customers",
        "filters_applied": {"audience": "all_active_customers"},
        "started_at": now_iso(), "completed_at": None,
        "stats": {"sent": 0, "failed": 0, "suppressed": 0, "no_contact": 0},
        "status": "running",
        "queued_email": 2, "queued_sms": 0,
    })
    try:
        with patch(
            "services.email.resend_adapter.send",
            new=AsyncMock(side_effect=RuntimeError("resend network down")),
        ):
            asyncio.run(_run_broadcast(
                tenant_id=_TENANT_ID, batch_id=batch_id,
                channels=["email"], template_id=None,
                subject="Boom", body="Boom {{customer.first_name}}",
                initiated_by="test-user",
            ))

        # Every attempted row for our seeded customers must be marked
        # failed with the error captured.
        rows = list(_sync.marketing_deliveries.find({
            "batch_id": batch_id,
            "customer_id": {"$in": two_customers},
        }))
        assert len(rows) == 2
        for row in rows:
            assert row["delivery_status"] == "failed"
            assert row.get("error") == "resend network down"

        # Batch stats show 2 failed, 0 sent.
        b = _sync.mass_messaging_batches.find_one({"id": batch_id})
        assert b["status"] == "completed"
        assert b["stats"]["failed"] >= 2
        assert b["stats"]["sent"] == 0
    finally:
        _sync.mass_messaging_batches.delete_one({"id": batch_id})
        _sync.marketing_deliveries.delete_many({"batch_id": batch_id})
