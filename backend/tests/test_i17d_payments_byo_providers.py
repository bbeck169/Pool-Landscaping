"""Phase I1.7.d · Feb-2026 — Tenant Payments BYO Providers.

Uses ``PAYMENTS_TESTMODE_MOCK=true`` so adapters short-circuit
without outbound HTTP. Endpoint-level cases hit the live backend on
``localhost:8001``.

Covers (per phase brief):
    01  registry lists all 4 providers
    02  PUT pay_square encrypts + masks on GET
    03  DELETE clears secret + sidecar
    04  webhook signature verify (valid + invalid, one per provider)
    05  test-connection success + failure
    06  usage per-op counters (charge / refund)
    07  cap 0/80%/100% + no-fallback-when-capped
    08  preserve-secret uniformity (cap-only edit)
    09  OpenAPI declares the new endpoints
    10  /schemas includes payments[] with connection_type=api_key
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


_LOOP: asyncio.AbstractEventLoop | None = None
_MOTOR_DB = None


def _setup_loop():
    global _LOOP, _MOTOR_DB
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        _MOTOR_DB = _client[os.environ["DB_NAME"]]
        import services.secrets.store as _store
        _store._default_db = lambda: _MOTOR_DB   # type: ignore
        import services.payments_byo.usage as _usage_mod
        _usage_mod._default_db = lambda: _MOTOR_DB  # type: ignore
        import services.provider_health.store as _health_store
        _health_store._default_db = lambda: _MOTOR_DB  # type: ignore
    return _LOOP, _MOTOR_DB


def _drive(coro_factory):
    loop, _ = _setup_loop()
    return loop.run_until_complete(coro_factory())


def _login(email="super@aquaterra.com", password="password123") -> str:
    r = requests.post(f"{API}/auth/login",
                        json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _hdrs(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _tenant_id(tok: str) -> str:
    r = requests.get(f"{API}/tenants/current", headers=_hdrs(tok), timeout=15)
    r.raise_for_status()
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _clean_and_flag(monkeypatch):
    monkeypatch.setenv("PAYMENTS_TESTMODE_MOCK", "true")
    from services.payments_byo.registry import reset_cache_for_tests
    reset_cache_for_tests()
    yield


def _cleanup_tenant(tid: str) -> None:
    _sync.tenant_secrets.delete_many({"tenant_id": tid,
                                        "provider_key": {"$regex": r"^pay_"}})
    _sync.tenant_payments_provider.delete_many({"tenant_id": tid})
    _sync.tenant_payments_usage.delete_many({"tenant_id": tid})
    _sync.tenant_payments_webhook_events.delete_many({"tenant_id": tid})
    _sync.tenant_provider_health.delete_many({
        "tenant_id": tid, "provider_key": {"$regex": r"^pay_"},
    })


# ── Case 01 — Registry lists all 4 ──────────────────────────────
def test_registry_lists_all_four_providers():
    from services.payments_byo.registry import (
        list_registered_payments_byo_provider_keys, list_short_names,
    )
    assert set(list_registered_payments_byo_provider_keys()) == {
        "pay_square", "pay_paypal", "pay_authnet", "pay_lumino",
    }
    assert set(list_short_names()) == {"square", "paypal", "authnet", "lumino"}


# ── Case 02 — PUT encrypts + masks on GET (Square) ──────────────
def test_put_pay_square_stores_encrypted_and_masks_on_get():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"sq_at_{uuid.uuid4().hex}"[:32]
        r = requests.put(
            f"{API}/tenants/me/integrations/pay_square",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"access_token": marker, "location_id": "L001",
                                "environment": "sandbox",
                                "webhook_signing_key": "whsec_sq"},
                    "monthly_request_cap": 1000},
        )
        assert r.status_code == 200, r.text
        # Ciphertext at rest — marker must not appear.
        row = _sync.tenant_secrets.find_one({"tenant_id": tid,
                                                "provider_key": "pay_square"})
        assert row is not None
        for f in ("encrypted_blob", "iv", "auth_tag"):
            assert marker not in str(row.get(f, ""))
        # GET /integrations reveals last_4 but never plaintext.
        lst = requests.get(f"{API}/tenants/me/integrations",
                              headers=_hdrs(tok), timeout=15).json()
        entry = next(x for x in lst["integrations"]
                        if x["provider_key"] == "pay_square")
        assert entry["last_4"] == marker[-4:]
        assert marker not in json.dumps(lst)
    finally:
        _cleanup_tenant(tid)


# ── Case 03 — DELETE clears secret + sidecar ────────────────────
def test_delete_pay_paypal_clears_secret_and_sidecar():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"pp_secret_{uuid.uuid4().hex}"[:32]
        requests.put(
            f"{API}/tenants/me/integrations/pay_paypal",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"client_id": "AXXX", "client_secret": marker,
                                "environment": "sandbox", "webhook_id": "whi_1"},
                    "monthly_request_cap": 500},
        ).raise_for_status()
        assert _sync.tenant_secrets.find_one(
            {"tenant_id": tid, "provider_key": "pay_paypal"}) is not None
        assert _sync.tenant_payments_provider.find_one(
            {"tenant_id": tid, "provider": "paypal"}) is not None
        r = requests.delete(f"{API}/tenants/me/integrations/pay_paypal",
                                headers=_hdrs(tok), timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["removed"] is True
        assert _sync.tenant_secrets.find_one(
            {"tenant_id": tid, "provider_key": "pay_paypal"}) is None
        assert _sync.tenant_payments_provider.find_one(
            {"tenant_id": tid, "provider": "paypal"}) is None
    finally:
        _cleanup_tenant(tid)


# ── Case 04a — Square webhook signature valid ───────────────────
def test_square_webhook_signature_valid():
    import hmac, hashlib
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        signing_key = "whsec_sq_test_1"
        requests.put(
            f"{API}/tenants/me/integrations/pay_square",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"access_token": "sq_at", "location_id": "L001",
                                "environment": "sandbox",
                                "webhook_signing_key": signing_key}},
        ).raise_for_status()
        payload = json.dumps({"event_id": f"ev_{uuid.uuid4().hex}",
                                "type": "payment.updated"}).encode()
        sig = hmac.new(signing_key.encode(), payload, hashlib.sha256).hexdigest()
        r = requests.post(
            f"{API}/tenants/me/integrations/pay_square/webhook",
            params={"tenant_id": tid},
            data=payload,
            headers={"Content-Type": "application/json",
                     "X-Square-HmacSha256-Signature": sig},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["received"] is True
    finally:
        _cleanup_tenant(tid)


# ── Case 04b — PayPal webhook signature invalid → 400 ───────────
def test_paypal_webhook_signature_invalid_rejects():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        requests.put(
            f"{API}/tenants/me/integrations/pay_paypal",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"client_id": "AXXX", "client_secret": "pps",
                                "environment": "sandbox", "webhook_id": "whi_1"}},
        ).raise_for_status()
        payload = b'{"event_type":"CHECKOUT.ORDER.APPROVED","id":"pp_ev_1"}'
        r = requests.post(
            f"{API}/tenants/me/integrations/pay_paypal/webhook",
            params={"tenant_id": tid},
            data=payload,
            headers={"Content-Type": "application/json",
                     "PAYPAL-TRANSMISSION-SIG": "deadbeef"},
            timeout=15,
        )
        assert r.status_code == 400, r.text
    finally:
        _cleanup_tenant(tid)


# ── Case 04c — Authorize.Net HMAC-SHA512 valid ──────────────────
def test_authnet_webhook_signature_valid():
    import hmac, hashlib
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        sig_key = "signkey_an"
        requests.put(
            f"{API}/tenants/me/integrations/pay_authnet",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_login_id": "aid1", "transaction_key": "tk1",
                                "environment": "sandbox", "signature_key": sig_key}},
        ).raise_for_status()
        payload = json.dumps({"notificationId": f"n_{uuid.uuid4().hex}",
                                "eventType": "net.authorize.payment.authcapture.created"}).encode()
        sig = hmac.new(sig_key.encode(), payload, hashlib.sha512).hexdigest()
        r = requests.post(
            f"{API}/tenants/me/integrations/pay_authnet/webhook",
            params={"tenant_id": tid},
            data=payload,
            headers={"Content-Type": "application/json",
                     "X-ANET-Signature": f"sha512={sig.upper()}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup_tenant(tid)


# ── Case 04d — Lumino HMAC-SHA256 valid ─────────────────────────
def test_lumino_webhook_signature_valid():
    import hmac, hashlib
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        whsec = "lm_whsec_1"
        requests.put(
            f"{API}/tenants/me/integrations/pay_lumino",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "lm_ak", "account_id": "acc_1",
                                "environment": "sandbox", "webhook_secret": whsec}},
        ).raise_for_status()
        payload = json.dumps({"id": f"lm_ev_{uuid.uuid4().hex}",
                                "event_type": "charge.succeeded"}).encode()
        sig = hmac.new(whsec.encode(), payload, hashlib.sha256).hexdigest()
        r = requests.post(
            f"{API}/tenants/me/integrations/pay_lumino/webhook",
            params={"tenant_id": tid},
            data=payload,
            headers={"Content-Type": "application/json",
                     "X-Lumino-Signature": sig},
            timeout=15,
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup_tenant(tid)


# ── Case 05a — test-connection success (mock) ────────────────────
def test_test_connection_success_records_health():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        requests.put(
            f"{API}/tenants/me/integrations/pay_lumino",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "lm_ak", "account_id": "acc_1",
                                "environment": "sandbox", "webhook_secret": "whs"}},
        ).raise_for_status()
        r = requests.post(
            f"{API}/tenants/me/integrations/pay_lumino/test-connection",
            headers=_hdrs(tok), timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        # tenant_provider_health row exists.
        row = _sync.tenant_provider_health.find_one(
            {"tenant_id": tid, "provider_key": "pay_lumino"},
        )
        assert row and row["status"] == "ok"
    finally:
        _cleanup_tenant(tid)


# ── Case 05b — test-connection failure (no config) ──────────────
def test_test_connection_failure_records_health():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        r = requests.post(
            f"{API}/tenants/me/integrations/pay_lumino/test-connection",
            headers=_hdrs(tok), timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is False
        row = _sync.tenant_provider_health.find_one(
            {"tenant_id": tid, "provider_key": "pay_lumino"},
        )
        assert row and row["status"] == "failed"
        assert row["consecutive_failures"] == 1
    finally:
        _cleanup_tenant(tid)


# ── Case 06 — Usage per-op counters ─────────────────────────────
def test_usage_records_charge_and_refund_ops():
    from services.payments_byo.usage import record_op
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        _drive(lambda: record_op(tenant_id=tid, provider="square", op="charge"))
        _drive(lambda: record_op(tenant_id=tid, provider="square", op="charge"))
        _drive(lambda: record_op(tenant_id=tid, provider="square", op="refund"))
        r = requests.get(
            f"{API}/tenants/me/integrations/payments/usage",
            headers=_hdrs(tok), timeout=15,
        )
        body = r.json()
        by = {p["provider"]: p for p in body["providers"]}
        assert by["square"]["charge_count"] == 2
        assert by["square"]["refund_count"] == 1
        assert by["square"]["ops_total"] == 3
    finally:
        _cleanup_tenant(tid)


# ── Case 07 — Cap semantics (0 / 80 % / 100 % / no fallback) ────
def test_cap_semantics_0_80_100_and_no_fallback():
    from services.payments_byo.usage import (
        _compute_status, enforce_cap_or_raise, record_op, upsert_provider_meta,
    )
    from services.payments_byo.models import TenantPaymentsUsageCapExceeded

    # 07a — pure function correctness
    assert _compute_status(used=0, cap=None) == "ok"       # unlimited
    assert _compute_status(used=0, cap=0) == "blocked"      # kill-switch
    assert _compute_status(used=79, cap=100) == "ok"
    assert _compute_status(used=80, cap=100) == "warn"      # 80% soft warn
    assert _compute_status(used=100, cap=100) == "blocked"  # 100% hard
    assert _compute_status(used=150, cap=100) == "blocked"

    # 07b — enforce raises at cap; no fallback when capped
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        _drive(lambda: upsert_provider_meta(
            tenant_id=tid, provider="authnet", monthly_request_cap=2,
        ))
        # 2 ops = at cap
        _drive(lambda: record_op(tenant_id=tid, provider="authnet", op="charge"))
        _drive(lambda: record_op(tenant_id=tid, provider="authnet", op="charge"))
        with pytest.raises(TenantPaymentsUsageCapExceeded):
            _drive(lambda: enforce_cap_or_raise(tenant_id=tid, provider="authnet"))
        # cap=0 = kill-switch, blocked immediately
        _drive(lambda: upsert_provider_meta(
            tenant_id=tid, provider="paypal", monthly_request_cap=0,
        ))
        with pytest.raises(TenantPaymentsUsageCapExceeded):
            _drive(lambda: enforce_cap_or_raise(tenant_id=tid, provider="paypal"))
    finally:
        _cleanup_tenant(tid)


# ── Case 08 — Cap-only edit preserves stored secret (uniform) ────
def test_cap_only_edit_preserves_stored_pay_authnet_secret():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        marker = f"an_tk_{uuid.uuid4().hex}"[:32]
        put1 = requests.put(
            f"{API}/tenants/me/integrations/pay_authnet",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_login_id": "aid1", "transaction_key": marker,
                                "environment": "sandbox", "signature_key": "sk"},
                    "monthly_request_cap": 1000},
        )
        assert put1.status_code == 200
        before = next(r for r in requests.get(
            f"{API}/tenants/me/integrations", headers=_hdrs(tok), timeout=15,
        ).json()["integrations"] if r["provider_key"] == "pay_authnet")
        # Cap-only edit — no secret in payload.
        put2 = requests.put(
            f"{API}/tenants/me/integrations/pay_authnet",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_login_id": "aid1",
                                "environment": "sandbox"},
                    "monthly_request_cap": 2000},
        )
        assert put2.status_code == 200, put2.text
        after = next(r for r in requests.get(
            f"{API}/tenants/me/integrations", headers=_hdrs(tok), timeout=15,
        ).json()["integrations"] if r["provider_key"] == "pay_authnet")
        # last_4 unchanged = secret preserved.
        assert before["last_4"] == after["last_4"]
        assert before["last_4"] == marker[-4:]
    finally:
        _cleanup_tenant(tid)


# ── Case 09 — OpenAPI declares the new endpoints ────────────────
def test_openapi_declares_payments_byo_endpoints():
    r = requests.get(f"{API}/openapi.json", timeout=20)
    r.raise_for_status()
    paths = set(r.json().get("paths", {}).keys())
    # test-connection + webhook use ``{short}`` path template.
    assert "/api/tenants/me/integrations/pay_{short}/test-connection" in paths
    assert "/api/tenants/me/integrations/pay_{short}/webhook" in paths
    assert "/api/tenants/me/integrations/payments/usage" in paths


# ── Case 10 — /schemas exposes payments[] with connection_type ──
def test_schemas_includes_payments_array_with_connection_type():
    tok = _login()
    schemas = requests.get(
        f"{API}/tenants/me/integrations/schemas",
        headers=_hdrs(tok), timeout=15,
    ).json()
    assert "payments" in schemas
    keys = {p["provider_key"] for p in schemas["payments"]}
    assert keys == {"pay_square", "pay_paypal", "pay_authnet", "pay_lumino"}
    for entry in schemas["payments"]:
        assert entry["connection_type"] == "api_key", entry
        assert entry["kind"] == "payments"
        # Every payments provider must declare a webhook signing field.
        field_names = {f["name"] for f in entry["fields"]}
        assert field_names.intersection({
            "webhook_signing_key", "webhook_id",
            "signature_key", "webhook_secret",
        }), entry


# ── Case 11 — Health cron unified across all 4 families ─────────
def test_health_cron_covers_all_four_families():
    from services.provider_health.cron import provider_families
    fams = {name for name, _, _ in provider_families()}
    assert fams == {"ai", "maps", "calendars", "payments_byo"}


# ── Case 12 — Health cron healthy → failed → recovered ──────────
def test_health_cron_transitions_and_counter():
    from services.provider_health.store import record_probe, get_health
    tid = f"hct-{uuid.uuid4().hex[:8]}"
    try:
        # healthy
        _drive(lambda: record_probe(tenant_id=tid, provider_key="pay_square", ok=True))
        row = _drive(lambda: get_health(tenant_id=tid, provider_key="pay_square"))
        assert row["status"] == "ok"
        assert row["consecutive_failures"] == 0
        # 1st failure
        _drive(lambda: record_probe(tenant_id=tid, provider_key="pay_square",
                                       ok=False, message="probe HTTP 500"))
        row = _drive(lambda: get_health(tenant_id=tid, provider_key="pay_square"))
        assert row["status"] == "failed"
        assert row["consecutive_failures"] == 1
        # 2nd failure — counter increments
        _drive(lambda: record_probe(tenant_id=tid, provider_key="pay_square",
                                       ok=False, message="probe HTTP 500"))
        row = _drive(lambda: get_health(tenant_id=tid, provider_key="pay_square"))
        assert row["consecutive_failures"] == 2
        # recovered
        _drive(lambda: record_probe(tenant_id=tid, provider_key="pay_square", ok=True))
        row = _drive(lambda: get_health(tenant_id=tid, provider_key="pay_square"))
        assert row["status"] == "ok"
        assert row["consecutive_failures"] == 0
    finally:
        _sync.tenant_provider_health.delete_many({"tenant_id": tid})


# ── Case 13 — /integrations attaches health map ─────────────────
def test_integrations_list_attaches_health_map():
    tok = _login()
    tid = _tenant_id(tok)
    _cleanup_tenant(tid)
    try:
        # Save + probe once so a health row exists.
        requests.put(
            f"{API}/tenants/me/integrations/pay_lumino",
            headers=_hdrs(tok), timeout=15,
            json={"config": {"api_key": "lm", "account_id": "a",
                                "environment": "sandbox", "webhook_secret": "s"}},
        ).raise_for_status()
        requests.post(
            f"{API}/tenants/me/integrations/pay_lumino/test-connection",
            headers=_hdrs(tok), timeout=15,
        ).raise_for_status()
        lst = requests.get(
            f"{API}/tenants/me/integrations",
            headers=_hdrs(tok), timeout=15,
        ).json()
        assert "health" in lst
        assert "pay_lumino" in lst["health"]
        snap = lst["health"]["pay_lumino"]
        assert snap["status"] == "ok"
        assert snap["provider_key"] == "pay_lumino"
    finally:
        _cleanup_tenant(tid)
