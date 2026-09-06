"""Phase R1.b · Feb-2026 — audit event contract test for the
one-tap "Send reminder" action wired from the Unpaid Invoices
panel (``POST /api/quotes/{qid}/send-reminder``).

The R1.a backend already had this endpoint (require_admin, does
in-app + SMS + email notify), R1.b added an ``invoice_reminder_sent``
audit event write so downstream DSO / collections dashboards can
count the touch without re-scanning the quotes collection.

We exercise the endpoint against the live backend as the R1.a
suite does, and assert the audit collection has a matching row.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
API = "http://localhost:8001/api"


def _login(email: str, pw: str = "password123") -> str:
    r = requests.post(f"{API}/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def super_h():
    return {"Authorization": f"Bearer {_login('super@aquaterra.com')}"}


@pytest.fixture(scope="module")
def db():
    c = MongoClient(_ENV["MONGO_URL"])
    return c[_ENV["DB_NAME"]]


def _pick_unpaid_invoice(db, tenant_id: str) -> dict | None:
    """Grab any outstanding invoice with a linked customer so the
    reminder path can dispatch."""
    return db.quotes.find_one({
        "tenant_id": tenant_id,
        "customer_id": {"$ne": None},
        "payment_status": {"$ne": "paid"},
        "$or": [
            {"amount_paid": {"$lt": "$total"}},
            {"amount_paid": None},
        ],
    })


class TestReminderAuditEvent:
    def test_reminder_writes_audit_event(self, super_h, db):
        tenant = db.tenants.find_one({"slug": "aquaterra"}, {"id": 1})
        if not tenant:
            pytest.skip("no aquaterra tenant seeded")
        inv = _pick_unpaid_invoice(db, tenant["id"])
        if not inv:
            pytest.skip("no unpaid invoice with a customer to remind")

        before_ts = datetime.now(timezone.utc).isoformat()
        r = requests.post(f"{API}/quotes/{inv['id']}/send-reminder",
                          headers=super_h, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert isinstance(body.get("reminder_count"), int)

        # An audit row landed with the right shape for THIS invoice
        # AFTER our timestamp anchor. Not scoped to test-run only —
        # existing rows for the same invoice will pre-date the anchor.
        ev = db.audit_events.find_one({
            "event_type": "invoice_reminder_sent",
            "tenant_id": tenant["id"],
            "payload.invoice_id": inv["id"],
            "timestamp": {"$gte": before_ts},
        })
        assert ev is not None, "invoice_reminder_sent audit event was not written"
        assert ev["payload"].get("customer_id") == inv.get("customer_id")
        assert ev["payload"].get("channel") == "in_app+sms+email"
        assert isinstance(ev["payload"].get("balance"), (int, float))
        assert ev["payload"].get("reminder_count") == body["reminder_count"]

    def test_reminder_endpoint_still_admin_gated(self):
        # No token → 401/403 from the require_admin guard.
        r = requests.post(f"{API}/quotes/doesnotmatter/send-reminder", timeout=10)
        assert r.status_code in (401, 403)
