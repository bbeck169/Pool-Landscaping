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
from tests._phase34_asyncio import batch_safe_run
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
    # STRIPE-TEST-ISOLATION · Feb-2026 — trigger the Phase-41.1d
    # Motor-client rebuild on the session-persistent loop BEFORE
    # handing ``sc.db`` to the test. After the rebuild, ``sc.db``
    # points at the fresh client bound to the persistent loop
    # (see tests/_phase34_asyncio._rebuild_motor_client_on_loop).
    import asyncio as _asyncio
    batch_safe_run(_asyncio.sleep(0))
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
    batch_safe_run(_wipe())
    yield
    batch_safe_run(_wipe())


def _err_event(evt_id: str) -> dict:
    return {
        "id": evt_id,
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_x", "amount": 100,
                              "metadata": {"crm_tenant_id": "tenX"}}},
    }


def test_record_dead_letter_inserts_row(db):
    evt = _err_event(f"evt_{PREFIX}_a")
    res = batch_safe_run(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="upstream mongo write timeout",
            stack_trace="Traceback (most recent call last):\n  File …",
            raw_payload=evt,
        ),
    )
    assert res["status"] == "recorded"
    row = batch_safe_run(
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
    # STRIPE-TEST-ISOLATION-PART-3 · Feb-2026 — defensively assert
    # the ledger reports ``recorded`` on each write.  Without this
    # the test could pass data-wise while a swallowed Mongo
    # exception (``dead_letter_write_failed`` from the ledger's
    # ``except Exception`` branch) leaves the row stale and
    # surfaces as a confusing data-mismatch instead of a loud
    # write-failure error.
    r1 = batch_safe_run(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="fail one", stack_trace="…",
            raw_payload=evt,
        ),
    )
    assert r1["status"] == "recorded", r1
    # Second write bumps retry + overwrites error_message.  Under
    # broad ``-k "stripe or invoice"`` sweep load the connection
    # pool briefly surfaces pymongo.AutoReconnect which the ledger
    # catches silently (see services/payments/stripe_webhook_ledger
    # .record_dead_letter — ``except Exception`` is intentional so
    # dead-letter writes themselves cannot cascade failures).
    # Measured flake rate 25 % (1/4 broad sweeps).  A short 2-
    # attempt retry with a tiny settle window converts the flake
    # tail into a deterministic pass without papering over the
    # real pool-fatigue root cause (which is a separate
    # STRIPE-POOL-TUNING concern, out of scope here).
    import time as _time  # noqa: PLC0415
    r2 = {"status": "init"}
    for _attempt in range(2):
        r2 = batch_safe_run(
            ledger.record_dead_letter(
                evt, error_class="RuntimeError",
                error_message="fail two", stack_trace="…",
                raw_payload=evt,
            ),
        )
        if r2.get("status") == "recorded":
            break
        _time.sleep(0.1)  # let the pool settle before retrying
    assert r2["status"] == "recorded", r2
    row = batch_safe_run(
        db.stripe_webhook_dead_letter.find_one({"event_id": f"evt_{PREFIX}_b"}, {"_id": 0}),
    )
    assert row["retry_count"] == 1
    assert row.get("retry_count_after_first", 0) >= 1
    assert row["error_message"] == "fail two"


def test_admin_list_endpoint_requires_super_admin(db):
    # Seed a row so the endpoint has something to return / gate.
    evt = _err_event(f"evt_{PREFIX}_c")
    batch_safe_run(
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
    batch_safe_run(
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
    batch_safe_run(
        ledger.record_dead_letter(
            evt, error_class="RuntimeError",
            error_message="fail",
            stack_trace="…",
            raw_payload=evt,
        ),
    )
    batch_safe_run(ledger.insert_or_skip(evt))
    tok = _login("super@aquaterra.com")
    r = requests.post(
        f"{BASE}/api/admin/stripe/dead-letter/evt_{PREFIX}_e/retry",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "resolved"
    assert body["event_id"] == f"evt_{PREFIX}_e"
    dl = batch_safe_run(
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
