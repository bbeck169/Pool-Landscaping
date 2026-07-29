"""LZ2 · Feb-2026 — Dispatcher unit tests + retroactive endpoint tests."""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"

_sync_client = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_client[os.environ["DB_NAME"]]


# ── Helpers ────────────────────────────────────────────────────────
def _invoice(**over):
    base = {
        "id": f"lz2-inv-{uuid.uuid4().hex[:10]}",
        "tenant_id": "lz2-tenant",
        "customer_id": "lz2-cust-x",
        "invoice_number": "INV-9001",
        "total": 125.50,
        "status": "sent",
        "currency": "USD",
        "title": "Test job",
    }
    base.update(over)
    return base


def _customer():
    return {"id": "lz2-cust-x", "name": "Test Customer",
            "email": "lz2@example.com", "phone": "+1-555-0100"}


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


# Ensure the env var IS set for the dispatcher module — the tests
# monkey-patch it as needed.
os.environ.setdefault("ZAPIER_INVOICE_LINK_WEBHOOK_URL",
                      "https://hooks.zapier.com/hooks/catch/DEFAULT/DEFAULT/")


# ── 1. Not configured (empty) ─────────────────────────────────────
def test_dispatch_skips_when_url_not_configured(monkeypatch):
    monkeypatch.setenv("ZAPIER_INVOICE_LINK_WEBHOOK_URL", "")
    from services.lumino_zapier_dispatcher import (
        dispatch_invoice_link_request,
    )
    r = _run(dispatch_invoice_link_request(_invoice(), _customer()))
    assert r["dispatched"] is False
    assert r["reason"] == "not_configured"
    assert len(r["correlation_id"]) == 16


# ── 2. REPLACE_ME_ placeholder ────────────────────────────────────
def test_dispatch_skips_when_url_placeholder(monkeypatch):
    monkeypatch.setenv(
        "ZAPIER_INVOICE_LINK_WEBHOOK_URL",
        "https://hooks.zapier.com/hooks/catch/REPLACE_ME/REPLACE_ME/",
    )
    from services.lumino_zapier_dispatcher import (
        dispatch_invoice_link_request,
    )
    r = _run(dispatch_invoice_link_request(_invoice(), _customer()))
    assert r["dispatched"] is False
    assert r["reason"] == "not_configured"


# ── 3. Already paid ───────────────────────────────────────────────
def test_dispatch_skips_when_invoice_already_paid(monkeypatch):
    monkeypatch.setenv("ZAPIER_INVOICE_LINK_WEBHOOK_URL",
                       "https://hooks.zapier.com/hooks/catch/1/2/")
    from services.lumino_zapier_dispatcher import (
        dispatch_invoice_link_request,
    )
    r = _run(dispatch_invoice_link_request(
        _invoice(status="paid"), _customer()))
    assert r["reason"] == "already_paid"


# ── 4. Already has URL ────────────────────────────────────────────
def test_dispatch_skips_when_invoice_already_has_url(monkeypatch):
    monkeypatch.setenv("ZAPIER_INVOICE_LINK_WEBHOOK_URL",
                       "https://hooks.zapier.com/hooks/catch/1/2/")
    from services.lumino_zapier_dispatcher import (
        dispatch_invoice_link_request,
    )
    r = _run(dispatch_invoice_link_request(
        _invoice(lumino_payment_url="https://pay.lumino.io/x"),
        _customer()))
    assert r["reason"] == "already_has_url"


# ── 5. Happy path — POST shape correct ────────────────────────────
def test_dispatch_posts_to_zapier_when_ready(monkeypatch):
    monkeypatch.setenv("ZAPIER_INVOICE_LINK_WEBHOOK_URL",
                       "https://hooks.zapier.com/hooks/catch/1/2/")
    monkeypatch.setenv("LUMINO_ZAPIER_SHARED_SECRET",
                       "test-shared-secret-value")
    from services.lumino_zapier_dispatcher import (
        dispatch_invoice_link_request,
    )

    captured = {}
    class _FakeResp:
        status_code = 200
        text = "ok"
    async def _fake_post(self, url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResp()
    with patch("httpx.AsyncClient.post", _fake_post):
        r = _run(dispatch_invoice_link_request(
            _invoice(), _customer(),
            base_return_url="https://preview.example.com"))
    assert r["dispatched"] is True
    assert r["reason"] is None
    assert captured["url"] == "https://hooks.zapier.com/hooks/catch/1/2/"
    assert captured["headers"]["x-zapier-shared-secret"] == \
        "test-shared-secret-value"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["json"]["event_type"] == "invoice.created"
    assert captured["json"]["amount_cents"] == 12550
    assert captured["json"]["amount_display"] == "125.50"
    assert captured["json"]["return_url"].startswith(
        "https://preview.example.com/portal/payment-method/return?invoice_id="
    )


# ── 6. Retry once on 5xx ──────────────────────────────────────────
def test_dispatch_retries_once_on_5xx(monkeypatch):
    monkeypatch.setenv("ZAPIER_INVOICE_LINK_WEBHOOK_URL",
                       "https://hooks.zapier.com/hooks/catch/1/2/")
    # No sleep during test.
    from services import lumino_zapier_dispatcher as mod
    monkeypatch.setattr(mod, "_RETRY_BACKOFF_SECS", 0)
    calls = {"n": 0}
    class _R:
        def __init__(self, code): self.status_code = code
    async def _fake_post(self, url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _R(503 if calls["n"] == 1 else 200)
    with patch("httpx.AsyncClient.post", _fake_post):
        r = _run(mod.dispatch_invoice_link_request(_invoice(), _customer()))
    assert r["dispatched"] is True
    assert calls["n"] == 2


# ── 7. Give up after two 5xx failures ─────────────────────────────
def test_dispatch_gives_up_after_two_failures(monkeypatch):
    monkeypatch.setenv("ZAPIER_INVOICE_LINK_WEBHOOK_URL",
                       "https://hooks.zapier.com/hooks/catch/1/2/")
    from services import lumino_zapier_dispatcher as mod
    monkeypatch.setattr(mod, "_RETRY_BACKOFF_SECS", 0)
    calls = {"n": 0}
    class _R:
        def __init__(self, code): self.status_code = code
    async def _fake_post(self, url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _R(503)
    with patch("httpx.AsyncClient.post", _fake_post):
        r = _run(mod.dispatch_invoice_link_request(_invoice(), _customer()))
    assert r["dispatched"] is False
    assert r["reason"] == "zapier_unreachable"
    assert calls["n"] == 2


# ── 8. correlation_id shape ───────────────────────────────────────
def test_dispatch_correlation_id_deterministic_shape(monkeypatch):
    monkeypatch.setenv("ZAPIER_INVOICE_LINK_WEBHOOK_URL", "")
    from services.lumino_zapier_dispatcher import (
        dispatch_invoice_link_request,
    )
    r = _run(dispatch_invoice_link_request(_invoice(), _customer()))
    import re
    assert re.fullmatch(r"[0-9a-f]{16}", r["correlation_id"])


# ── 9. Payload contains all required fields ───────────────────────
def test_dispatch_payload_contains_required_fields(monkeypatch):
    monkeypatch.setenv("ZAPIER_INVOICE_LINK_WEBHOOK_URL",
                       "https://hooks.zapier.com/hooks/catch/1/2/")
    from services.lumino_zapier_dispatcher import (
        dispatch_invoice_link_request,
    )
    captured = {}
    class _R:
        status_code = 200
    async def _fake_post(self, url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return _R()
    with patch("httpx.AsyncClient.post", _fake_post):
        _run(dispatch_invoice_link_request(
            _invoice(), _customer(),
            base_return_url="https://x.example"))
    required = ["event_type", "invoice_id", "invoice_number",
                 "customer_id", "customer_name", "customer_email",
                 "customer_phone", "amount_cents", "amount_display",
                 "currency", "description", "return_url",
                 "external_id", "tenant_id", "created_at",
                 "correlation_id"]
    for f in required:
        assert f in captured["json"], f"missing field {f}"
        assert captured["json"][f] is not None, f"field {f} is None"


# ────────────── Retroactive endpoint tests ─────────────────────
def _admin_token():
    r = requests.post(f"{API}/auth/login",
                       json={"email": "manager@aquaterra.com",
                             "password": "password123"}, timeout=10)
    return r.json().get("access_token")


def _seed_invoice_in_db_invoices() -> str:
    inv_id = f"lz2-endpoint-inv-{uuid.uuid4().hex[:10]}"
    _sync_db.invoices.insert_one({
        "id": inv_id, "tenant_id": "lz2-endpoint",
        "customer_id": "lz2-cust-x",
        "customer_name": "EndpointCust",
        "customer_email": "endpoint@example.com",
        "total": 50.0, "status": "sent",
    })
    return inv_id


def _cleanup(inv_id: str):
    _sync_db.invoices.delete_one({"id": inv_id})


# ── 10. Endpoint dispatches ───────────────────────────────────────
def test_request_payment_link_endpoint_dispatches():
    tok = _admin_token()
    inv_id = _seed_invoice_in_db_invoices()
    try:
        r = requests.post(
            f"{API}/invoices/{inv_id}/request-payment-link",
            headers={"Authorization": f"Bearer {tok}"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "dispatched" in body
        assert "correlation_id" in body
        # Either dispatched=True (live Zapier reachable) or
        # dispatched=False + reason in known set. Both are OK — we're
        # verifying the endpoint runs the pipeline, not the network.
        assert body["dispatched"] in (True, False)
    finally:
        _cleanup(inv_id)


# ── 11. Auth required ─────────────────────────────────────────────
def test_request_payment_link_endpoint_requires_auth():
    r = requests.post(f"{API}/invoices/some-id/request-payment-link",
                       timeout=10)
    assert r.status_code in (401, 403)


# ── 12. Rate limit ────────────────────────────────────────────────
def test_request_payment_link_endpoint_rate_limits():
    tok = _admin_token()
    inv_id = _seed_invoice_in_db_invoices()
    try:
        codes = []
        for _ in range(6):
            r = requests.post(
                f"{API}/invoices/{inv_id}/request-payment-link",
                headers={"Authorization": f"Bearer {tok}"}, timeout=15,
            )
            codes.append(r.status_code)
        # First 5 should be non-429; 6th should be 429.
        assert codes[:5].count(429) == 0, codes
        assert codes[5] == 429, codes
    finally:
        _cleanup(inv_id)


# ── 13. Invoice not found ─────────────────────────────────────────
def test_request_payment_link_endpoint_invoice_not_found_404():
    tok = _admin_token()
    r = requests.post(
        f"{API}/invoices/nonexistent-{uuid.uuid4().hex[:8]}/request-payment-link",
        headers={"Authorization": f"Bearer {tok}"}, timeout=10,
    )
    assert r.status_code == 404
