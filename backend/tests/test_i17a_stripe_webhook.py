"""Phase I1.7.a · Feb-2026 — Stripe webhook signature + idempotency.

Uses ``requests`` against the live backend (localhost:8001) — same
technique as ``test_i15a_tenant_theme_endpoint.py``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Stripe-compatible signature header: v1=HMAC-SHA256(secret,
    ``t.payload``). Mirrors the format Stripe posts and that the
    Stripe SDK's ``construct_event`` verifies."""
    if timestamp is None:
        timestamp = int(time.time())
    signed = f"{timestamp}.".encode() + payload
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def _webhook_secret() -> str:
    """Pick the webhook secret the backend will actually validate against.

    Backend selects based on ``STRIPE_MODE`` — mirror that logic here.
    """
    mode = (os.environ.get("STRIPE_MODE") or "test").strip().lower()
    if mode == "live":
        s = os.environ.get("STRIPE_WEBHOOK_SECRET_LIVE")
    else:
        s = os.environ.get("STRIPE_WEBHOOK_SECRET_TEST")
    assert s, f"webhook secret for STRIPE_MODE={mode} must be set in .env"
    return s


@pytest.fixture(autouse=True)
def _clean():
    yield
    _sync.stripe_webhook_events.delete_many(
        {"event_type": {"$regex": "^i17a_test"}}
    )


def test_i17a_webhook_missing_signature_returns_400():
    r = requests.post(
        f"{API}/integrations/stripe/webhook",
        data=b'{"id":"evt_test","type":"i17a_test.miss","object":"event"}',
        headers={"content-type": "application/json"},
        timeout=15,
    )
    assert r.status_code == 400
    assert "verify_failed" in r.text


def test_i17a_webhook_bad_signature_returns_400():
    r = requests.post(
        f"{API}/integrations/stripe/webhook",
        data=b'{"id":"evt_test","type":"i17a_test.bad","object":"event"}',
        headers={
            "content-type": "application/json",
            "stripe-signature": "t=1,v1=abcdef",
        },
        timeout=15,
    )
    assert r.status_code == 400


def test_i17a_webhook_valid_signature_records_event():
    webhook_secret = _webhook_secret()
    event_id = f"evt_i17a_{uuid.uuid4().hex[:12]}"
    payload = json.dumps({
        "id": event_id,
        "type": "i17a_test.charge.succeeded",
        "object": "event",     # required by stripe.Webhook.construct_event
        "data": {"object": {"amount": 1500}},
    }).encode()
    sig = _sign(payload, webhook_secret)
    r = requests.post(
        f"{API}/integrations/stripe/webhook",
        data=payload,
        headers={"stripe-signature": sig,
                 "content-type": "application/json"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"received": True, "duplicate": False}
    row = _sync.stripe_webhook_events.find_one({"event_id": event_id})
    assert row is not None
    assert row["event_type"] == "i17a_test.charge.succeeded"


def test_i17a_webhook_duplicate_event_id_is_deduped():
    webhook_secret = _webhook_secret()
    event_id = f"evt_i17a_dup_{uuid.uuid4().hex[:12]}"
    payload = json.dumps({
        "id": event_id, "type": "i17a_test.dup_probe",
        "object": "event", "data": {"object": {}},
    }).encode()
    sig = _sign(payload, webhook_secret)
    first = requests.post(
        f"{API}/integrations/stripe/webhook", data=payload,
        headers={"stripe-signature": sig, "content-type": "application/json"},
        timeout=15,
    )
    second = requests.post(
        f"{API}/integrations/stripe/webhook", data=payload,
        headers={"stripe-signature": sig, "content-type": "application/json"},
        timeout=15,
    )
    assert first.status_code == 200
    assert first.json() == {"received": True, "duplicate": False}
    assert second.status_code == 200
    assert second.json() == {"received": True, "duplicate": True}
    rows = list(_sync.stripe_webhook_events.find({"event_id": event_id}))
    assert len(rows) == 1
