"""Phase K63.polish · Feb-2026 — notification dispatch log read API.

Pins the ``GET /api/admin/notification-dispatch-log`` contract:

  1. Admin + super-admin can read; manager + tech → 403.
  2. Filters: lead_id, recipient (email lower-cased), channel,
     status, since, limit.
  3. limit clamps at 200; invalid channel / status → 400; invalid
     since → 400.
  4. Tenant isolation — the endpoint reads ``tenant_id`` from the
     acting user, never a query param. Rows for other tenants are
     invisible.
  5. Empty result → 200 with ``items=[]``, ``total=0``.
  6. Rows are newest-first.

Uses direct Mongo inserts (not the dispatcher) to seed audit rows
so the test never touches Resend / RingCentral adapters.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import requests

from config import db
from utils import new_id


API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> dict:
    r = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def admin_headers():
    return _login("admin@aquaterra.com")


@pytest.fixture(scope="module")
def super_headers():
    return _login("super@aquaterra.com")


@pytest.fixture(scope="module")
def manager_headers():
    return _login("manager@aquaterra.com")


@pytest.fixture(scope="module")
def tech_headers():
    return _login("mike@aquaterra.com")


@pytest.fixture(scope="module")
def tid(admin_headers) -> str:
    r = requests.get(f"{API}/tenants/current", headers=admin_headers, timeout=10)
    r.raise_for_status()
    return r.json()["id"]


_MARKER = "k63p-test-marker"


def _seed_rows(tenant_id: str, other_tenant_id: str, lead_id: str) -> list[dict]:
    """Insert a small deterministic set of ``audit_logs`` rows across
    two tenants + two channels + both statuses. Returns the ids so
    the teardown fixture can wipe them cleanly."""
    now = datetime.now(timezone.utc)
    rows = [
        # In-tenant · sent · email · newest
        {"id": new_id(), "tenant_id": tenant_id,
          "event": "lead_notification_sent",
          "channel": "email", "lead_id": lead_id,
          "target": "brian@plofv.com", "message_id": "resend-1",
          "marker": _MARKER,
          "created_at": (now - timedelta(minutes=1)).isoformat()},
        # In-tenant · sent · sms
        {"id": new_id(), "tenant_id": tenant_id,
          "event": "lead_notification_sent",
          "channel": "sms", "lead_id": lead_id,
          "target": "+16028874400", "message_id": "rc-1",
          "marker": _MARKER,
          "created_at": (now - timedelta(minutes=2)).isoformat()},
        # In-tenant · failed · email · older
        {"id": new_id(), "tenant_id": tenant_id,
          "event": "lead_notification_failed",
          "channel": "email", "lead_id": lead_id,
          "target": "brian@plofv.com", "error": "resend outage",
          "marker": _MARKER,
          "created_at": (now - timedelta(minutes=5)).isoformat()},
        # Cross-tenant row — must NOT be visible.
        {"id": new_id(), "tenant_id": other_tenant_id,
          "event": "lead_notification_sent",
          "channel": "sms", "lead_id": lead_id,
          "target": "+15550001111", "message_id": "rc-2",
          "marker": _MARKER,
          "created_at": now.isoformat()},
    ]
    async def _insert():
        await db.audit_logs.insert_many(rows)
    asyncio.get_event_loop().run_until_complete(_insert())
    return rows


@pytest.fixture(scope="module")
def seeded(tid):
    """Seed audit rows for this tenant + a synthetic other-tenant
    row so cross-tenant isolation is testable."""
    other_tid = "k63p-other-tenant"
    lead_id = "k63p-lead"
    rows = _seed_rows(tid, other_tid, lead_id)
    yield {"rows": rows, "other_tid": other_tid, "lead_id": lead_id}
    async def _wipe():
        await db.audit_logs.delete_many({"marker": _MARKER})
    asyncio.get_event_loop().run_until_complete(_wipe())


# ─── Role gate ──────────────────────────────────────────────────────

def test_admin_ok(admin_headers, seeded):
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["items"], list)
    assert body["limit"] > 0


def test_super_admin_ok(super_headers, seeded):
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=super_headers, timeout=10,
    )
    assert r.status_code == 200


def test_manager_forbidden(manager_headers, seeded):
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=manager_headers, timeout=10,
    )
    assert r.status_code == 403


def test_tech_forbidden(tech_headers, seeded):
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=tech_headers, timeout=10,
    )
    assert r.status_code == 403


# ─── Filters ────────────────────────────────────────────────────────

def _fetch(admin_headers, **params) -> list[dict]:
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=admin_headers, params=params, timeout=10,
    )
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_lead_id_filter(admin_headers, seeded):
    items = _fetch(admin_headers, lead_id=seeded["lead_id"])
    # 3 in-tenant rows for the seeded lead; cross-tenant NOT visible.
    assert len(items) == 3
    assert all(x["lead_id"] == seeded["lead_id"] for x in items)


def test_channel_filter(admin_headers, seeded):
    items = _fetch(admin_headers, lead_id=seeded["lead_id"], channel="sms")
    assert all(x["channel"] == "sms" for x in items)
    assert len(items) == 1


def test_status_filter(admin_headers, seeded):
    items = _fetch(admin_headers, lead_id=seeded["lead_id"], status="failed")
    assert all(x["status"] == "failed" for x in items)
    assert len(items) == 1
    assert items[0]["error"] == "resend outage"


def test_recipient_email_lowercased(admin_headers, seeded):
    items = _fetch(admin_headers,
                     lead_id=seeded["lead_id"],
                     recipient="Brian@Plofv.COM")
    assert len(items) == 2  # sent + failed for that email
    assert all(x["recipient"] == "brian@plofv.com" for x in items)


def test_recipient_phone_exact(admin_headers, seeded):
    items = _fetch(admin_headers,
                     lead_id=seeded["lead_id"],
                     recipient="+16028874400")
    assert len(items) == 1
    assert items[0]["channel"] == "sms"


def test_since_filter(admin_headers, seeded):
    # A 3-min-ago cutoff should keep only the two "newest" rows.
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    items = _fetch(admin_headers, lead_id=seeded["lead_id"], since=cutoff)
    assert len(items) == 2
    assert {x["status"] for x in items} == {"sent"}


def test_newest_first(admin_headers, seeded):
    items = _fetch(admin_headers, lead_id=seeded["lead_id"])
    ts = [x["created_at"] for x in items]
    assert ts == sorted(ts, reverse=True), (
        f"rows must be newest-first, got {ts}"
    )


def test_limit_clamp_to_200(admin_headers, seeded):
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=admin_headers, params={"limit": 9999}, timeout=10,
    )
    assert r.status_code == 200
    assert r.json()["limit"] == 200


def test_invalid_channel_400(admin_headers, seeded):
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=admin_headers, params={"channel": "carrier-pigeon"}, timeout=10,
    )
    assert r.status_code == 400


def test_invalid_status_400(admin_headers, seeded):
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=admin_headers, params={"status": "queued"}, timeout=10,
    )
    assert r.status_code == 400


def test_invalid_since_400(admin_headers, seeded):
    r = requests.get(
        f"{API}/admin/notification-dispatch-log",
        headers=admin_headers, params={"since": "not-a-date"}, timeout=10,
    )
    assert r.status_code == 400


def test_empty_result_200(admin_headers, seeded):
    items = _fetch(admin_headers, lead_id="lead-that-does-not-exist")
    assert items == []


# ─── Tenant isolation ──────────────────────────────────────────────

def test_cross_tenant_row_invisible(admin_headers, seeded):
    """The seeded ``k63p-other-tenant`` row must never surface to a
    caller whose token is minted against the AquaTerra tenant."""
    items = _fetch(admin_headers, lead_id=seeded["lead_id"])
    assert all("k63p-other" not in (x.get("lead_id") or "") for x in items)
    # And the specific target that only exists in the other tenant
    # should NOT be returned.
    targets = {x["recipient"] for x in items}
    assert "+15550001111" not in targets
