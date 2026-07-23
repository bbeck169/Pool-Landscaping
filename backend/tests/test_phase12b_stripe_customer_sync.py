"""Phase 12B · Feb 2026 — Stripe ↔ Customers cross-reference backfill.

Direct service-level tests — the sync helpers are called via
:func:`tests._shared_loop.run` with ``stripe.PaymentMethod.list`` +
``Customer.list`` + ``Customer.retrieve`` mocked in-process. This
avoids the round-trip to the live backend process (which the test
harness can't monkey-patch).

RBAC gates are exercised over HTTP since they don't need Stripe at all.

Verified invariants (matches spec):

  * Happy path: known stripe_customer_id + PMs → card flag + display
    fields populated.
  * Email backfill: no stripe_customer_id + exactly one Stripe match
    → linked + card synced.
  * Ambiguous email match: not auto-linked; recorded on the report.
  * No Stripe match: silently skipped.
  * Idempotency: second run is a full no-op (zero writes).
  * Manual link endpoint: bad stripe_customer_id → 400; mismatched
    email → 400; happy path → 200 + linkage stored.
  * RBAC gates on the three admin endpoints (via HTTP).
  * Detach webhook: last PM detached → has_card_on_file back to false.
  * Attached webhook: card flag + display fields updated + audit row.
  * Tech projection strips ``stripe_customer_id`` (via HTTP).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from dotenv import dotenv_values
from fastapi import HTTPException
from pymongo import MongoClient

from tests._shared_loop import run as _run

_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = MongoClient(_env["MONGO_URL"])[_env["DB_NAME"]]
_TENANT = _sync.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
_TENANT_ID = _TENANT["id"]

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
def tech_headers():
    return _login("mike@aquaterra.com")


def _mk_customer(*, stripe_customer_id=None, email=None):
    cid = f"pytest-p12b-{uuid.uuid4().hex[:8]}"
    doc = {
        "id": cid, "tenant_id": _TENANT_ID,
        "name": f"P12B Fixture {uuid.uuid4().hex[:4]}",
        "email": email, "phone": None,
    }
    if stripe_customer_id:
        doc["stripe_customer_id"] = stripe_customer_id
    _sync.customers.insert_one(doc)
    return cid


def _cleanup_customer(cid):
    _sync.customers.delete_many({"id": cid})
    _sync.payment_methods_events.delete_many({"customer_id": cid})


# ─── Fake Stripe factory ─────────────────────────────────────────────
def _mk_pm(*, pm_id="pm_test", brand="visa", last4="4242",
            exp_month=8, exp_year=2028):
    return SimpleNamespace(
        id=pm_id,
        card=SimpleNamespace(brand=brand, last4=last4,
                              exp_month=exp_month, exp_year=exp_year),
    )


def _mk_stripe_customer(*, sid, email=None, default_pm=None):
    return SimpleNamespace(
        id=sid, email=email or "",
        invoice_settings=SimpleNamespace(default_payment_method=default_pm),
    )


def _fake_stripe(*, pm_list=None, cust_list=None, cust_retrieve=None):
    return SimpleNamespace(
        PaymentMethod=SimpleNamespace(
            list=(pm_list if callable(pm_list)
                    else (lambda **kw: {"data": pm_list or []}))),
        Customer=SimpleNamespace(
            list=(cust_list if callable(cust_list)
                    else (lambda **kw: {"data": cust_list or []})),
            retrieve=(cust_retrieve if callable(cust_retrieve)
                        else (lambda sid, **kw: _mk_stripe_customer(sid=sid))),
        ),
        error=SimpleNamespace(
            RateLimitError=Exception,
            APIConnectionError=Exception,
        ),
    )


# ─── Backfill happy path (direct service call) ───────────────────────
def test_backfill_customer_with_stripe_id_and_pms_flips_card_flag():
    from services.stripe_customer_sync import run_stripe_customer_sync
    cid = _mk_customer(stripe_customer_id="cus_test_happy")
    try:
        pms = [
            _mk_pm(pm_id="pm_1", brand="visa", last4="4242",
                    exp_month=8, exp_year=2028),
            _mk_pm(pm_id="pm_2", brand="mastercard", last4="1111",
                    exp_month=1, exp_year=2027),
        ]
        fake = _fake_stripe(
            pm_list=pms,
            cust_retrieve=lambda sid, **kw: _mk_stripe_customer(
                sid=sid, default_pm="pm_1"),
        )
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            report = _run(run_stripe_customer_sync(_TENANT_ID))
        entry = next((x for x in report["updated_card_flag"]
                       if x["customer_id"] == cid), None)
        assert entry is not None
        assert entry["pm_count"] == 2
        assert entry["brand"] == "visa"
        assert entry["last4"] == "4242"
        doc = _sync.customers.find_one({"id": cid}, {"_id": 0})
        assert doc["saved_payment_methods_count"] == 2
        assert doc["card_brand"] == "visa"
        assert doc["card_last4"] == "4242"
        assert doc["stripe_default_payment_method_id"] == "pm_1"
    finally:
        _cleanup_customer(cid)


def test_backfill_email_match_links_and_syncs():
    from services.stripe_customer_sync import run_stripe_customer_sync
    unique_email = f"p12b-em-{uuid.uuid4().hex[:6]}@pytest.local"
    cid = _mk_customer(email=unique_email)
    try:
        fake = _fake_stripe(
            pm_list=[_mk_pm(pm_id="pm_x", brand="amex", last4="0005",
                              exp_month=6, exp_year=2029)],
            cust_list=[_mk_stripe_customer(sid="cus_linked",
                                             email=unique_email,
                                             default_pm="pm_x")],
            cust_retrieve=lambda sid, **kw: _mk_stripe_customer(
                sid=sid, email=unique_email, default_pm="pm_x"),
        )
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            report = _run(run_stripe_customer_sync(_TENANT_ID))
        linked = next((l for l in report["linked"]
                        if l["customer_id"] == cid), None)
        assert linked is not None
        assert linked["stripe_customer_id"] == "cus_linked"
        doc = _sync.customers.find_one({"id": cid}, {"_id": 0})
        assert doc["stripe_customer_id"] == "cus_linked"
        assert doc["card_brand"] == "amex"
    finally:
        _cleanup_customer(cid)


def test_backfill_ambiguous_email_match_not_linked():
    from services.stripe_customer_sync import run_stripe_customer_sync
    unique_email = f"p12b-amb-{uuid.uuid4().hex[:6]}@pytest.local"
    cid = _mk_customer(email=unique_email)
    try:
        fake = _fake_stripe(
            pm_list=[],
            cust_list=[
                _mk_stripe_customer(sid="cus_a", email=unique_email),
                _mk_stripe_customer(sid="cus_b", email=unique_email),
            ],
        )
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            report = _run(run_stripe_customer_sync(_TENANT_ID))
        row = next((a for a in report["ambiguous_matches"]
                     if a["customer_id"] == cid), None)
        assert row is not None
        assert set(row["stripe_ids"]) == {"cus_a", "cus_b"}
        doc = _sync.customers.find_one({"id": cid}, {"_id": 0})
        assert doc.get("stripe_customer_id") is None
    finally:
        _cleanup_customer(cid)


def test_backfill_zero_stripe_matches_skipped():
    from services.stripe_customer_sync import run_stripe_customer_sync
    cid = _mk_customer(email=f"p12b-none-{uuid.uuid4().hex[:6]}@pytest.local")
    try:
        fake = _fake_stripe(pm_list=[], cust_list=[])
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            report = _run(run_stripe_customer_sync(_TENANT_ID))
        assert all(a["customer_id"] != cid for a in report["ambiguous_matches"])
        assert all(l["customer_id"] != cid for l in report["linked"])
        doc = _sync.customers.find_one({"id": cid}, {"_id": 0})
        assert doc.get("stripe_customer_id") is None
    finally:
        _cleanup_customer(cid)


def test_backfill_second_run_is_full_noop():
    from services.stripe_customer_sync import run_stripe_customer_sync
    cid = _mk_customer(stripe_customer_id="cus_noop")
    _sync.customers.update_one({"id": cid}, {"$set": {
        "saved_payment_methods_count": 1,
        "stripe_default_payment_method_id": "pm_only",
        "card_brand": "visa", "card_last4": "9999",
        "card_exp_month": 12, "card_exp_year": 2030,
    }})
    try:
        fake = _fake_stripe(
            pm_list=[_mk_pm(pm_id="pm_only", brand="visa", last4="9999",
                              exp_month=12, exp_year=2030)],
            cust_retrieve=lambda sid, **kw: _mk_stripe_customer(
                sid=sid, default_pm="pm_only"),
        )
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            report = _run(run_stripe_customer_sync(_TENANT_ID))
        assert all(x["customer_id"] != cid
                    for x in report["updated_card_flag"])
    finally:
        _cleanup_customer(cid)


# ─── Manual link ─────────────────────────────────────────────────────
def test_manual_link_bad_stripe_id_400():
    from services.stripe_customer_sync import link_customer_to_stripe
    cid = _mk_customer(email="link-bad@pytest.local")
    try:
        def _retrieve_raises(sid, **kw):
            raise ValueError("no such customer on stripe")
        fake = _fake_stripe(cust_retrieve=_retrieve_raises)
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            with pytest.raises(HTTPException) as ei:
                _run(link_customer_to_stripe(
                    tenant_id=_TENANT_ID, customer_id=cid,
                    stripe_customer_id="cus_missing",
                ))
            assert ei.value.status_code == 400
            assert "not found on stripe" in str(ei.value.detail).lower()
    finally:
        _cleanup_customer(cid)


def test_manual_link_email_mismatch_400():
    from services.stripe_customer_sync import link_customer_to_stripe
    cid = _mk_customer(email="crm-mail@pytest.local")
    try:
        fake = _fake_stripe(
            cust_retrieve=lambda sid, **kw: _mk_stripe_customer(
                sid=sid, email="different@pytest.local"),
        )
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            with pytest.raises(HTTPException) as ei:
                _run(link_customer_to_stripe(
                    tenant_id=_TENANT_ID, customer_id=cid,
                    stripe_customer_id="cus_x",
                ))
            assert ei.value.status_code == 400
            assert "email mismatch" in str(ei.value.detail).lower()
    finally:
        _cleanup_customer(cid)


def test_manual_link_happy_path():
    from services.stripe_customer_sync import link_customer_to_stripe
    unique_email = f"link-ok-{uuid.uuid4().hex[:4]}@pytest.local"
    cid = _mk_customer(email=unique_email)
    try:
        fake = _fake_stripe(
            pm_list=[_mk_pm(pm_id="pm_ok", brand="discover", last4="0002",
                              exp_month=3, exp_year=2031)],
            cust_retrieve=lambda sid, **kw: _mk_stripe_customer(
                sid=sid, email=unique_email, default_pm="pm_ok"),
        )
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            body = _run(link_customer_to_stripe(
                tenant_id=_TENANT_ID, customer_id=cid,
                stripe_customer_id="cus_ok",
            ))
        assert body["stripe_customer_id"] == "cus_ok"
        doc = _sync.customers.find_one({"id": cid}, {"_id": 0})
        assert doc["stripe_customer_id"] == "cus_ok"
        assert doc["card_brand"] == "discover"
    finally:
        _cleanup_customer(cid)


# ─── RBAC gates (HTTP) ───────────────────────────────────────────────
def test_tech_cannot_call_sync_endpoints(tech_headers):
    for path in ("preview", "run", "link"):
        r = requests.post(
            f"{API}/admin/stripe-customer-sync/{path}",
            json={"customer_id": "x", "stripe_customer_id": "y"},
            headers=tech_headers, timeout=10,
        )
        assert r.status_code == 403, f"{path} → {r.status_code}"


# ─── Webhook handlers (direct call, mocked Stripe) ───────────────────
def test_pm_attached_webhook_writes_audit_and_syncs():
    from routers.stripe_webhooks_live import _handle_payment_method_attached
    stripe_sid = f"cus_attach_{uuid.uuid4().hex[:8]}"
    cid = _mk_customer(stripe_customer_id=stripe_sid)
    try:
        fake = _fake_stripe(
            pm_list=[_mk_pm(pm_id="pm_new", brand="visa", last4="4242",
                              exp_month=9, exp_year=2029)],
            cust_retrieve=lambda sid, **kw: _mk_stripe_customer(
                sid=sid, default_pm="pm_new"),
        )
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            event = {
                "id": f"evt_test_{uuid.uuid4().hex[:8]}",
                "type": "payment_method.attached",
                "data": {"object": {
                    "id": "pm_new", "customer": stripe_sid,
                    "card": {"brand": "visa", "last4": "4242"},
                }},
            }
            _run(_handle_payment_method_attached(event))
        doc = _sync.customers.find_one({"id": cid}, {"_id": 0})
        assert doc["saved_payment_methods_count"] == 1
        assert doc["card_last4"] == "4242"
        audit = _sync.payment_methods_events.find_one(
            {"customer_id": cid, "action": "attached"}, {"_id": 0})
        assert audit is not None
        assert audit["brand"] == "visa"
        assert audit["last4"] == "4242"
    finally:
        _cleanup_customer(cid)


def test_pm_detached_webhook_clears_last_card():
    from routers.stripe_webhooks_live import _handle_payment_method_detached
    from routers.customers import _compute_card_fields
    stripe_sid = f"cus_detach_{uuid.uuid4().hex[:8]}"
    cid = _mk_customer(stripe_customer_id=stripe_sid)
    _sync.customers.update_one({"id": cid}, {"$set": {
        "saved_payment_methods_count": 1,
        "card_brand": "visa", "card_last4": "4242",
        "card_exp_month": 8, "card_exp_year": 2028,
        "stripe_default_payment_method_id": "pm_only",
    }})
    try:
        fake = _fake_stripe(
            pm_list=[],
            cust_retrieve=lambda sid, **kw: _mk_stripe_customer(sid=sid),
        )
        with patch("services.stripe_customer_sync._stripe", return_value=fake):
            event = {
                "id": f"evt_test_{uuid.uuid4().hex[:8]}",
                "type": "payment_method.detached",
                "data": {"object": {
                    "id": "pm_only", "customer": stripe_sid,
                    "card": {"brand": "visa", "last4": "4242"},
                }},
            }
            _run(_handle_payment_method_detached(event))
        doc = _sync.customers.find_one({"id": cid}, {"_id": 0})
        assert doc["saved_payment_methods_count"] == 0
        assert doc["card_brand"] is None
        derived = _compute_card_fields(doc, True)
        assert derived["has_card_on_file"] is False
    finally:
        _cleanup_customer(cid)


# ─── Tech projection (HTTP) ──────────────────────────────────────────
def test_tech_projection_strips_stripe_customer_id(tech_headers, admin_headers):
    cid = _mk_customer(stripe_customer_id="cus_sensitive",
                        email="tech-strip@pytest.local")
    try:
        rA = requests.get(f"{API}/customers/{cid}", headers=admin_headers,
                            timeout=10)
        assert rA.status_code == 200
        assert rA.json()["stripe_customer_id"] == "cus_sensitive"
        rT = requests.get(f"{API}/customers/{cid}", headers=tech_headers,
                            timeout=10)
        assert rT.status_code == 200
        assert "stripe_customer_id" not in rT.json()
    finally:
        _cleanup_customer(cid)
