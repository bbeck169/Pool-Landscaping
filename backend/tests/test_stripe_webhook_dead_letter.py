"""Phase B3 · Feb-2026 — Stripe webhook dead-letter tests.

Verifies:
  * Handler crash lands the event in ``stripe_webhook_dead_letter``
    with error class + retry_count semantics (via the ledger helper
    directly — no HTTP round-trip needed for this layer).
  * The super_admin admin endpoints (``GET /api/admin/stripe/dead-
    letter`` and ``POST .../retry``) are gated to super_admin and
    replay the shipped handler.

For the HTTP layer we hit the LIVE supervisor-hosted backend via
``requests`` because Motor's async client conflicts with FastAPI's
in-process ``TestClient`` (documented in
``test_stripe_webhook_thin_payload.py`` docstring).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

from services.payments import stripe_webhook_ledger as ledger
from services.payments import stripe_charge as sc


_FE_ENV = dotenv_values(Path(__file__).resolve().parents[2] / "frontend" / ".env")
# Prefer localhost to skip the kubernetes-ingress round-trip (bcrypt
# login already burns ~10s; the ingress adds another 30-40s and
# blows out the pytest wall time). Fall back to REACT_APP_BACKEND_URL
# if localhost:8001 is unreachable.
BASE = os.environ.get("STRIPE_TEST_BASE") or "http://localhost:8001"
if not BASE:
    BASE = (
        _FE_ENV.get("REACT_APP_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL", "")
    ).rstrip("/")
assert BASE, "backend base URL not resolvable"

PREFIX = f"b3dl-{uuid.uuid4().hex[:8]}"


def _demo_pw() -> str:
    md = Path("/app/memory/test_credentials.md").read_text()
    for line in md.splitlines():
        if "super@aquaterra.com" in line:
            # The password is the second backticked token on the line.
            toks = [t for t in line.split("`") if t and " " not in t]
            if len(toks) >= 2:
                return toks[1]
    return "password123"


def _login(email: str) -> str:
    r = requests.post(f"{BASE}/api/auth/login",
                       json={"email": email, "password": _demo_pw()},
                       timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture
def db():
    return sc.db


@pytest.fixture(autouse=True)
def _clean(db):
    async def _wipe():
        await db.stripe_webhook_dead_letter.delete_many(
            {"event_id": {"$regex": f"^evt_{PREFIX}"}},
        )
        await db.stripe_webhook_events.delete_many(
            {"event_id": {"$regex": f"^evt_{PREFIX}"}},
        )
    asyncio.get_event_loop().run_until_complete(_wipe())
    yield
    asyncio.get_event_loop().run_until_complete(_wipe())


def _err_event(evt_id: str) -> dict:
    return {
        "id": evt_id,
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_x", "amount": 100,
                              "metadata": {"crm_tenant_id": "tenX"}}},
    }


def test_record_dead_letter_inserts_row(db):
    evt = _err_event(f"evt_{PREFIX}_a")
    res = asyncio.get_event_loop().run_until_complete(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="upstream mongo write timeout",
            stack_trace="Traceback (most recent call last):\n  File …",
            raw_payload=evt,
        ),
    )
    assert res["status"] == "recorded"
    row = asyncio.get_event_loop().run_until_complete(
        db.stripe_webhook_dead_letter.find_one(
            {"event_id": f"evt_{PREFIX}_a"}, {"_id": 0},
        ),
    )
    assert row is not None
    assert row["error_class"] == "RuntimeError"
    assert "mongo" in row["error_message"]
    assert row["resolved"] is False
    assert row["retry_count"] == 1
    assert row.get("raw_payload")


def test_record_dead_letter_upsert_bumps_retry(db):
    evt = _err_event(f"evt_{PREFIX}_b")
    asyncio.get_event_loop().run_until_complete(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="fail one", stack_trace="…",
            raw_payload=evt,
        ),
    )
    asyncio.get_event_loop().run_until_complete(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="fail two", stack_trace="…",
            raw_payload=evt,
        ),
    )
    row = asyncio.get_event_loop().run_until_complete(
        db.stripe_webhook_dead_letter.find_one({"event_id": f"evt_{PREFIX}_b"}, {"_id": 0}),
    )
    assert row["retry_count"] == 1
    assert row.get("retry_count_after_first", 0) >= 1
    assert row["error_message"] == "fail two"


def test_admin_list_endpoint_requires_super_admin(db):
    # Seed a row so the endpoint has something to return / gate.
    evt = _err_event(f"evt_{PREFIX}_c")
    asyncio.get_event_loop().run_until_complete(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="fail", stack_trace="…",
            raw_payload=evt,
        ),
    )
    # No auth header → 401/403.
    r = requests.get(f"{BASE}/api/admin/stripe/dead-letter", timeout=10)
    assert r.status_code in (401, 403), r.text
    # Non-super_admin.
    tok = _login("admin@aquaterra.com")
    r2 = requests.get(f"{BASE}/api/admin/stripe/dead-letter",
                        headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r2.status_code == 403, r2.text


def test_admin_list_endpoint_super_admin_returns_rows(db):
    evt = _err_event(f"evt_{PREFIX}_d")
    asyncio.get_event_loop().run_until_complete(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="fail", stack_trace="…",
            raw_payload=evt,
        ),
    )
    tok = _login("super@aquaterra.com")
    r = requests.get(f"{BASE}/api/admin/stripe/dead-letter",
                       headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] >= 1
    assert any(row["event_id"] == f"evt_{PREFIX}_d" for row in body["rows"])


def test_admin_retry_endpoint_replays_handler_and_resolves(db):
    # Craft an event handle_webhook_event returns ``handled=False``
    # for (payment_intent.canceled is unhandled) — replaying should
    # succeed without raising, letting us assert the resolution
    # bookkeeping end-to-end.
    evt = {
        "id": f"evt_{PREFIX}_e",
        "type": "payment_intent.canceled",
        "data": {"object": {"id": "pi_x", "amount": 100}},
    }
    asyncio.get_event_loop().run_until_complete(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="fail",
            stack_trace="…",
            raw_payload=evt,
        ),
    )
    asyncio.get_event_loop().run_until_complete(ledger.insert_or_skip(evt))
    tok = _login("super@aquaterra.com")
    r = requests.post(
        f"{BASE}/api/admin/stripe/dead-letter/evt_{PREFIX}_e/retry",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "resolved"
    assert body["event_id"] == f"evt_{PREFIX}_e"
    dl = asyncio.get_event_loop().run_until_complete(
        db.stripe_webhook_dead_letter.find_one({"event_id": f"evt_{PREFIX}_e"}, {"_id": 0}),
    )
    assert dl["resolved"] is True
    assert dl.get("resolved_at")


def test_admin_retry_endpoint_returns_404_for_unknown_event(db):
    tok = _login("super@aquaterra.com")
    r = requests.post(
        f"{BASE}/api/admin/stripe/dead-letter/evt_does_not_exist/retry",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 404
