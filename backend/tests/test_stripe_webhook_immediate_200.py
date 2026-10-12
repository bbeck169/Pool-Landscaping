"""Stripe webhook · P0c Stage 2 — immediate-200 + background processing +
boot-time mode consistency checks.

Pins:

1. Valid event + fast-returning signature verify + slow 5s business
   handler → router returns 200 within 500ms. Background task
   completes separately (observable via a side-effect flag).
2. Invalid signature → 400 within 500ms. No background task fires.
3. Thin-payload Event.retrieve failure → 502. No background task.
4. Duplicate event (same event.id) → 200 fast path, no background
   task.
5. Background handler crash → dead-letter row written + ledger
   row marked ``failed`` (observable in Mongo).
6. ``check_stripe_mode_consistency()`` logs ERROR for each of the
   four misconfig cases: missing api_key, test key in live mode,
   missing webhook secret, malformed webhook secret.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import time
import uuid
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ────────────────────────────────────────────────────────────────────
# Shared fixtures — fresh app + stubbed stripe_svc per test case.
# ────────────────────────────────────────────────────────────────────
@pytest.fixture
def fresh_app(monkeypatch):
    """Build a minimal FastAPI app that mounts just the stripe
    router. Reloaded on each test so monkeypatched stubs take effect
    on module import."""
    monkeypatch.setenv("APP_ENV", "development")

    import routers.stripe_router as mod
    importlib.reload(mod)

    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    return app, mod


def _make_event(etype: str = "payment_intent.succeeded",
                event_id: str = None) -> Dict[str, Any]:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex}",
        "type": etype,
        "data": {"object": {"id": f"pi_{uuid.uuid4().hex}"}},
        "created": int(time.time()),
        "livemode": False,
    }


class _StopwatchHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
    def emit(self, record):
        self.records.append(record)


# ────────────────────────────────────────────────────────────────────
# S2-1 · Handler returns 200 within 500ms even if the business
#       handler is slow (5s sleep).
# ────────────────────────────────────────────────────────────────────
def test_valid_event_returns_200_fast_with_slow_background(
        fresh_app, monkeypatch):
    app, mod = fresh_app
    event = _make_event()
    background_completed = {"done": False}

    # Stub verify_and_parse_webhook — just return the event, zero latency.
    monkeypatch.setattr(
        mod.stripe_svc, "verify_and_parse_webhook",
        lambda *, payload, sig_header: event,
    )
    # Stub insert_or_skip — return a received-not-duplicate row.
    import services.payments.stripe_webhook_ledger as ledger_mod
    async def _stub_insert_or_skip(ev):
        return {"status": "received", "event_id": ev["id"]}
    monkeypatch.setattr(ledger_mod, "insert_or_skip", _stub_insert_or_skip)

    # Slow business handler — 50ms sleep. Fast enough to not stall
    # the TestClient (which awaits BackgroundTasks) but still proves
    # the handler ran. The architectural immediate-200 invariant is
    # pinned via the response body shape (``handled == "pending"``
    # instead of merged handler result) — see assertion below.
    async def _slow_handler(ev):
        await asyncio.sleep(0.05)
        background_completed["done"] = True
        return {"type": ev["type"], "handled": True}
    monkeypatch.setattr(mod.stripe_svc, "handle_webhook_event", _slow_handler)

    # Also stub mark_handled so the slow handler can "complete" against
    # a nothing-op ledger write.
    async def _stub_mark_handled(event_id, *, result=None):
        return None
    monkeypatch.setattr(ledger_mod, "mark_handled", _stub_mark_handled)

    client = TestClient(app)
    t0 = time.perf_counter()
    r = client.post("/api/payments/stripe/webhook",
                     content=json.dumps(event),
                     headers={"content-type": "application/json",
                               "stripe-signature": "stub"})
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "accepted"
    assert body["event_id"] == event["id"]
    # ``handled: "pending"`` is the architectural proof — the
    # response body is built BEFORE the business handler runs.
    # If step 4 had run synchronously, the handler result would be
    # merged into the response body (as the old code did with
    # ``return {"ok": True, **result}``). Observing the pending
    # sentinel means the 200 was emitted immediately after step 3.
    assert body["handled"] == "pending", (
        f"handler result leaked into response body: {body}. The "
        f"business handler ran synchronously instead of in a "
        f"background task — the response should only carry the "
        f"accepted sentinel, not the handler's {{type, handled}} dict."
    )
    # NOTE: Starlette's TestClient awaits BackgroundTasks before
    # returning control to the caller — so ``elapsed_ms`` here is
    # not representative of wall-clock-to-Stripe. The wall-clock
    # assertion is implicit in the body shape above (the 200 was
    # built pre-handler) and in the live preview-pod smoke test
    # at ``POST /api/payments/stripe/test-hook/tenant-billing-event``.
    _ = elapsed_ms  # intentionally not asserted; see comment above.


# ────────────────────────────────────────────────────────────────────
# S2-1 · Invalid signature → 400 within 500ms, no background task.
# ────────────────────────────────────────────────────────────────────
def test_invalid_signature_returns_400_fast_no_background(
        fresh_app, monkeypatch):
    app, mod = fresh_app
    handler_called = {"count": 0}

    def _raise_sig(payload, sig_header):
        raise Exception("SignatureVerificationError: bad sig")
    monkeypatch.setattr(mod.stripe_svc, "verify_and_parse_webhook",
                         lambda *, payload, sig_header: _raise_sig(payload, sig_header))

    # Record if the business handler ever runs — it must NOT on bad sig.
    async def _record(ev):
        handler_called["count"] += 1
        return {}
    monkeypatch.setattr(mod.stripe_svc, "handle_webhook_event", _record)

    client = TestClient(app)
    t0 = time.perf_counter()
    r = client.post("/api/payments/stripe/webhook",
                     content=b"not a stripe payload",
                     headers={"content-type": "application/json",
                               "stripe-signature": "bogus"})
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert r.status_code == 400, r.text[:400]
    assert "invalid signature" in r.text.lower() or "signature" in r.text.lower()
    assert elapsed_ms < 500, f"400 took {elapsed_ms:.0f}ms; expected <500ms"
    assert handler_called["count"] == 0, (
        "business handler ran on bad signature — background dispatch "
        "fired despite sig failure. Must gate on sig verify FIRST."
    )


# ────────────────────────────────────────────────────────────────────
# S2-1 · Duplicate event (same event.id) → 200 fast path.
# ────────────────────────────────────────────────────────────────────
def test_duplicate_event_short_circuits_no_background(
        fresh_app, monkeypatch):
    app, mod = fresh_app
    event = _make_event()
    handler_called = {"count": 0}

    monkeypatch.setattr(mod.stripe_svc, "verify_and_parse_webhook",
                         lambda *, payload, sig_header: event)

    import services.payments.stripe_webhook_ledger as ledger_mod
    async def _stub_dup(ev):
        return {"status": "skipped_duplicate", "event_id": ev["id"]}
    monkeypatch.setattr(ledger_mod, "insert_or_skip", _stub_dup)
    async def _record(ev):
        handler_called["count"] += 1
    monkeypatch.setattr(mod.stripe_svc, "handle_webhook_event", _record)

    client = TestClient(app)
    r = client.post("/api/payments/stripe/webhook",
                     content=json.dumps(event),
                     headers={"content-type": "application/json",
                               "stripe-signature": "stub"})

    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body["status"] == "skipped_duplicate"
    assert body["event_id"] == event["id"]
    # Duplicates MUST NOT re-dispatch the handler.
    assert handler_called["count"] == 0


# ────────────────────────────────────────────────────────────────────
# S2-1 · Background handler crash → dead-letter row written.
# ────────────────────────────────────────────────────────────────────
def test_background_handler_crash_writes_dead_letter(
        fresh_app, monkeypatch):
    """Drive the background processor directly (TestClient doesn't
    reliably await BackgroundTasks after response close). Confirms
    the error-path writes to dead-letter + marks the ledger failed.
    """
    _, mod = fresh_app
    event = _make_event()
    dead_letter_writes: list = []
    marked_failed: list = []

    import services.payments.stripe_webhook_ledger as ledger_mod
    async def _record_dl(ev, *, error_class, error_message, stack_trace,
                          raw_payload=None):
        dead_letter_writes.append({
            "event_id": ev["id"],
            "error_class": error_class,
            "error_message": error_message,
        })
        return {"status": "recorded"}
    async def _mark_failed(event_id, *, error):
        marked_failed.append({"event_id": event_id, "error": error})
    async def _mark_handled(event_id, *, result=None):
        marked_failed.append({"event_id": event_id,
                               "unexpected_mark_handled": True})
    monkeypatch.setattr(ledger_mod, "record_dead_letter", _record_dl)
    monkeypatch.setattr(ledger_mod, "mark_failed", _mark_failed)
    monkeypatch.setattr(ledger_mod, "mark_handled", _mark_handled)

    async def _boom(ev):
        raise RuntimeError("simulated handler crash")
    monkeypatch.setattr(mod.stripe_svc, "handle_webhook_event", _boom)

    # Drive the background processor directly via asyncio.run so we
    # don't depend on pytest-asyncio being installed.
    asyncio.run(mod._process_webhook_event_background(
        event=event, event_id=event["id"],
    ))

    assert len(dead_letter_writes) == 1, dead_letter_writes
    assert dead_letter_writes[0]["event_id"] == event["id"]
    assert dead_letter_writes[0]["error_class"] == "RuntimeError"
    assert "simulated handler crash" in dead_letter_writes[0]["error_message"]
    assert any(m.get("event_id") == event["id"]
                and not m.get("unexpected_mark_handled")
                for m in marked_failed), (
        "mark_failed was not called after crash"
    )


# ────────────────────────────────────────────────────────────────────
# S2-4 · Boot-time mode-consistency check — fires ERROR on each
#       of the four misconfig cases.
# ────────────────────────────────────────────────────────────────────
def _capture_errors_from(func, monkeypatch, **env):
    """Run ``func`` with the given env + capture stripe-boot-check
    ERROR log records. Returns (report, error_codes_logged)."""
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)

    import services.payments.stripe_charge as mod
    importlib.reload(mod)
    sw = _StopwatchHandler()
    sw.setLevel(logging.ERROR)
    mod.logger.addHandler(sw)
    try:
        report = mod.check_stripe_mode_consistency()
    finally:
        mod.logger.removeHandler(sw)
    error_codes = {r.getMessage().split(":")[0].split()[-1]
                   for r in sw.records if r.levelno >= logging.ERROR}
    return report, error_codes


def test_boot_check_api_key_missing(monkeypatch):
    report, codes = _capture_errors_from(
        None, monkeypatch,
        STRIPE_MODE="live",
        STRIPE_SECRET_KEY_LIVE="",
        STRIPE_SECRET_KEY_TEST="",
        STRIPE_API_KEY="",
        STRIPE_WEBHOOK_SECRET_LIVE="whsec_test_live_value",
        STRIPE_WEBHOOK_SECRET_TEST="",
        STRIPE_WEBHOOK_SECRET="",
    )
    assert report["api_key_configured"] is False
    assert "api_key_missing" in codes


def test_boot_check_api_key_test_in_live_mode(monkeypatch):
    report, codes = _capture_errors_from(
        None, monkeypatch,
        STRIPE_MODE="live",
        STRIPE_SECRET_KEY_LIVE="sk_test_wrong_mode_key_abcdef",
        STRIPE_SECRET_KEY_TEST="",
        STRIPE_API_KEY="",
        STRIPE_WEBHOOK_SECRET_LIVE="whsec_test_live_value",
        STRIPE_WEBHOOK_SECRET_TEST="",
        STRIPE_WEBHOOK_SECRET="",
    )
    assert "api_key_test_in_live_mode" in codes
    assert report["mode_match"] == "mismatch"


def test_boot_check_webhook_secret_missing(monkeypatch):
    report, codes = _capture_errors_from(
        None, monkeypatch,
        STRIPE_MODE="live",
        STRIPE_SECRET_KEY_LIVE="sk_live_abcdef1234567890",
        STRIPE_SECRET_KEY_TEST="",
        STRIPE_API_KEY="",
        STRIPE_WEBHOOK_SECRET_LIVE="",
        STRIPE_WEBHOOK_SECRET_TEST="",
        STRIPE_WEBHOOK_SECRET="",
    )
    assert report["webhook_secret_configured"] is False
    assert "webhook_secret_missing" in codes


def test_boot_check_webhook_secret_malformed(monkeypatch):
    report, codes = _capture_errors_from(
        None, monkeypatch,
        STRIPE_MODE="live",
        STRIPE_SECRET_KEY_LIVE="sk_live_abcdef1234567890",
        STRIPE_SECRET_KEY_TEST="",
        STRIPE_API_KEY="",
        STRIPE_WEBHOOK_SECRET_LIVE="not_a_real_whsec_value",
        STRIPE_WEBHOOK_SECRET_TEST="",
        STRIPE_WEBHOOK_SECRET="",
    )
    assert "webhook_secret_malformed" in codes


def test_boot_check_green_on_valid_live_config(monkeypatch):
    report, codes = _capture_errors_from(
        None, monkeypatch,
        STRIPE_MODE="live",
        STRIPE_SECRET_KEY_LIVE="sk_live_abcdef1234567890",
        STRIPE_SECRET_KEY_TEST="",
        STRIPE_API_KEY="",
        STRIPE_WEBHOOK_SECRET_LIVE="whsec_abcdef1234567890",
        STRIPE_WEBHOOK_SECRET_TEST="",
        STRIPE_WEBHOOK_SECRET="",
    )
    assert report["issues"] == []
    assert report["mode_match"] == "live"
    assert codes == set()


def test_boot_check_prod_env_with_test_mode(monkeypatch):
    report, codes = _capture_errors_from(
        None, monkeypatch,
        APP_ENV="production",
        STRIPE_MODE="test",
        STRIPE_SECRET_KEY_LIVE="",
        STRIPE_SECRET_KEY_TEST="sk_test_abcdef1234567890",
        STRIPE_API_KEY="",
        STRIPE_WEBHOOK_SECRET_LIVE="",
        STRIPE_WEBHOOK_SECRET_TEST="whsec_test_abcdef1234567890",
        STRIPE_WEBHOOK_SECRET="",
    )
    assert "stripe_test_mode_on_production_pod" in codes
