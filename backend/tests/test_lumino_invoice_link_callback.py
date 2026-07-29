"""LZ1 · Feb-2026 — Invoice-link callback endpoint tests."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
URL = f"{API}/webhooks/lumino/invoice-link-created"

_sync_client = MongoClient(os.environ["MONGO_URL"])
_sync_db = _sync_client[os.environ["DB_NAME"]]


def _read_secret() -> str:
    v = os.environ.get("LUMINO_ZAPIER_SHARED_SECRET", "").strip()
    if v.startswith("REPLACE_ME_"):
        return ""
    return v


SECRET = _read_secret()
HDR_OK = {"x-zapier-shared-secret": SECRET, "Content-Type": "application/json"}
HDR_WRONG = {"x-zapier-shared-secret": "not-the-secret",
              "Content-Type": "application/json"}
HDR_NO_SECRET = {"Content-Type": "application/json"}

needs_secret = pytest.mark.skipif(not SECRET,
                                    reason="LUMINO_ZAPIER_SHARED_SECRET unset")


def _seed_invoice() -> str:
    inv_id = f"lz1-inv-{uuid.uuid4().hex[:12]}"
    _sync_db.invoices.insert_one({
        "id": inv_id,
        "tenant_id": "lz1-test-tenant",
        "customer_id": "lz1-cust-x",
        "total": 100.0,
        "status": "sent",
    })
    return inv_id


def _cleanup_invoice(inv_id: str):
    _sync_db.invoices.delete_one({"id": inv_id})
    # Clean up any audit row we may have created.
    _sync_db.payment_events.delete_many({"invoice_id": inv_id})


# ── 1/2/3. Auth failure modes ─────────────────────────────────────
def test_callback_missing_secret_401():
    r = requests.post(URL, headers=HDR_NO_SECRET,
                       data=json.dumps({"a": 1}), timeout=10)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_callback_wrong_secret_401():
    r = requests.post(URL, headers=HDR_WRONG,
                       data=json.dumps({"a": 1}), timeout=10)
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_callback_env_not_configured_503(monkeypatch):
    """Direct-call the handler with an empty env."""
    import asyncio
    monkeypatch.setenv("LUMINO_ZAPIER_SHARED_SECRET", "")
    from routers import lumino_invoice_link_callback as m

    class _Req:
        headers = {"x-zapier-shared-secret": "whatever"}
        async def body(self):
            return b"{}"

    result = asyncio.run(m.lumino_invoice_link_created(_Req()))
    assert result.status_code == 503
    assert json.loads(result.body.decode())["error"] == "not_configured"


# ── 4. Malformed JSON ─────────────────────────────────────────────
@needs_secret
def test_callback_malformed_json_400():
    r = requests.post(URL, headers=HDR_OK, data=b"{not json",
                       timeout=10)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_json"


# ── 5. Non-object body ────────────────────────────────────────────
@needs_secret
@pytest.mark.parametrize("bad", [b"[1,2,3]", b'"hi"', b"42"])
def test_callback_non_object_body_400(bad):
    r = requests.post(URL, headers=HDR_OK, data=bad, timeout=10)
    assert r.status_code == 400
    assert r.json()["error"] == "not_json_object"


# ── 6/7/8. Field validation ───────────────────────────────────────
@needs_secret
def test_callback_missing_invoice_id_400():
    payload = {"lumino_payment_url": "https://pay.lumino.io/abc"}
    r = requests.post(URL, headers=HDR_OK,
                       data=json.dumps(payload), timeout=10)
    assert r.status_code == 400
    assert r.json()["error"] == "missing_invoice_id"


@needs_secret
def test_callback_missing_payment_url_400():
    payload = {"invoice_id": "some-invoice-id"}
    r = requests.post(URL, headers=HDR_OK,
                       data=json.dumps(payload), timeout=10)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_payment_url"


@needs_secret
@pytest.mark.parametrize("bad_url", [
    "http://insecure.example.com/pay",
    "javascript:alert(1)",
    "ftp://old.example.com/pay",
    "",
    "not-a-url-at-all",
])
def test_callback_invalid_payment_url_scheme_400(bad_url):
    payload = {"invoice_id": "some-invoice-id",
                "lumino_payment_url": bad_url}
    r = requests.post(URL, headers=HDR_OK,
                       data=json.dumps(payload), timeout=10)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_payment_url"


# ── 9. Invoice not found ──────────────────────────────────────────
@needs_secret
def test_callback_invoice_not_found_404():
    payload = {"invoice_id": f"nonexistent-{uuid.uuid4().hex[:8]}",
                "lumino_payment_url":
                    "https://pay.lumino.io/checkout/xyz"}
    r = requests.post(URL, headers=HDR_OK,
                       data=json.dumps(payload), timeout=10)
    assert r.status_code == 404
    assert r.json()["error"] == "invoice_not_found"


# ── 10. Happy path — persists URL ─────────────────────────────────
@needs_secret
def test_callback_signed_valid_invoice_persists_url_200():
    inv_id = _seed_invoice()
    try:
        url = f"https://pay.lumino.io/checkout/{uuid.uuid4().hex[:12]}"
        payload = {"invoice_id": inv_id, "lumino_payment_url": url}
        r = requests.post(URL, headers=HDR_OK,
                           data=json.dumps(payload), timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["invoice_id"] == inv_id
        assert body["lumino_payment_url_set"] is True
        assert body["correlation_id"]
        # DB round-trip
        persisted = _sync_db.invoices.find_one({"id": inv_id})
        assert persisted["lumino_payment_url"] == url
        assert persisted["lumino_link_created_at"]
        assert persisted["updated_at"]
    finally:
        _cleanup_invoice(inv_id)


# ── 11. Optional refs persist ─────────────────────────────────────
@needs_secret
def test_callback_optional_refs_persist():
    inv_id = _seed_invoice()
    try:
        url = f"https://pay.lumino.io/checkout/{uuid.uuid4().hex[:12]}"
        payload = {
            "invoice_id": inv_id,
            "lumino_payment_url": url,
            "lumino_customer_ref": "cus_L_abc123",
            "lumino_payment_ref": "pay_L_xyz789",
        }
        r = requests.post(URL, headers=HDR_OK,
                           data=json.dumps(payload), timeout=10)
        assert r.status_code == 200
        persisted = _sync_db.invoices.find_one({"id": inv_id})
        assert persisted["lumino_customer_ref"] == "cus_L_abc123"
        assert persisted["lumino_payment_ref"] == "pay_L_xyz789"
    finally:
        _cleanup_invoice(inv_id)


# ── 12. Double-call idempotency ───────────────────────────────────
@needs_secret
def test_callback_double_call_idempotent():
    inv_id = _seed_invoice()
    try:
        url = f"https://pay.lumino.io/checkout/{uuid.uuid4().hex[:12]}"
        payload = {"invoice_id": inv_id, "lumino_payment_url": url}
        r1 = requests.post(URL, headers=HDR_OK,
                            data=json.dumps(payload), timeout=10)
        r2 = requests.post(URL, headers=HDR_OK,
                            data=json.dumps(payload), timeout=10)
        assert r1.status_code == 200 and r2.status_code == 200
        # Exactly ONE audit row for this (invoice_id, url) pair.
        events = list(_sync_db.payment_events.find(
            {"invoice_id": inv_id,
             "lumino_payment_url": url}))
        assert len(events) == 1, \
            f"Expected exactly 1 audit row, got {len(events)}"
    finally:
        _cleanup_invoice(inv_id)
