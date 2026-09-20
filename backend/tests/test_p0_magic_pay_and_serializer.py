"""Feb-2026 P0 · Regression tests for the invoice magic-pay flow.

Uses the sync ``requests`` + ``pymongo`` fixture pattern shared with
``test_line_item_decline_phase_c_signature_gate.py`` so it slots
into the standard ``pytest -q`` sweep without extra plugins.

Guards two failure modes reported in prod:

1. **``Pay $0.00`` in the pay modal.** The frontend PaymentForm was
   reading ``invoice.total`` — undefined on the magic-viewer payload
   shape. Backend guard: the ``request-payment-link-magic`` endpoint
   accepts a valid magic-link JWT and delegates to the Stripe
   session builder without dropping the amount.

2. **"Preparing your secure payment link…" freeze.** The standard
   ``/request-payment-link`` requires ``get_current_user`` — no
   magic-link customer can reach it. The new
   ``/request-payment-link-magic`` variant lets them mint a Session
   without a portal login.

3. **Cost-snapshot leak audit.** Pricebook × Profit-Reporting
   Phase 1 added ``wholesale_price_snapshot`` / ``labor_cost_snapshot``
   / ``retail_price_snapshot`` to line items. These MUST never
   surface on customer-facing payloads.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import requests
from dotenv import dotenv_values
from pymongo import MongoClient
from tests._shared_mongo import (
    shared_client as _shared_client,
    shared_db as _shared_db,
)


_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_sync = _shared_db()
API = "http://localhost:8001/api"

_JWT_SECRET = _ENV["JWT_SECRET"]
_JWT_ALGO = _ENV.get("JWT_ALGO") or "HS256"


def _mint_magic_token(iid: str, tid: str, exp_offset: int = 3600) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "invoice_pay",
            "invoice_id": iid,
            "tenant_id": tid,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=exp_offset)).timestamp()),
        },
        _JWT_SECRET, algorithm=_JWT_ALGO,
    )


def _seed_invoice() -> dict:
    """Insert a $205 open invoice + tenant + customer."""
    tid = f"p0mp-t-{uuid.uuid4().hex[:8]}"
    cid = f"p0mp-c-{uuid.uuid4().hex[:8]}"
    iid = f"p0mp-inv-{uuid.uuid4().hex[:8]}"
    _sync.tenants.update_one(
        {"id": tid},
        {"$set": {"id": tid, "name": "P0 Magic Pay",
                    "slug": f"p0mp-{tid[-6:]}"}},
        upsert=True,
    )
    _sync.customers.update_one(
        {"id": cid},
        {"$setOnInsert": {"id": cid, "tenant_id": tid,
                             "name": "Merril Lynn",
                             "email": "merril@example.com"}},
        upsert=True,
    )
    _sync.quotes.insert_one({
        "id": iid, "tenant_id": tid, "customer_id": cid,
        "customer_name": "Merril Lynn", "doc_type": "invoice",
        "status": "sent", "payment_status": "unpaid",
        "line_items": [{"description": "Pool service", "quantity": 1,
                            "unit_price": 205.0, "total": 205.0}],
        "amount_paid": 0.0, "subtotal": 205.0, "total": 205.0,
        "tax": 0.0, "tax_rate": 0.0,
    })
    return {"iid": iid, "tid": tid, "cid": cid,
             "token": _mint_magic_token(iid, tid)}


def _cleanup(ctx: dict) -> None:
    _sync.quotes.delete_many({"id": ctx["iid"]})
    _sync.tenants.delete_many({"id": ctx["tid"]})
    _sync.customers.delete_many({"id": ctx["cid"]})


# ── Tests ──────────────────────────────────────────────────────────

def test_magic_pay_rejects_missing_token():
    ctx = _seed_invoice()
    try:
        r = requests.post(
            f"{API}/invoices/{ctx['iid']}/request-payment-link-magic",
            timeout=10,
        )
        assert r.status_code == 401
        detail = (r.json().get("detail") or "").lower()
        assert "token" in detail
    finally:
        _cleanup(ctx)


def test_magic_pay_rejects_token_for_other_invoice():
    ctx = _seed_invoice()
    try:
        stray = _mint_magic_token("some-other-iid", ctx["tid"])
        r = requests.post(
            f"{API}/invoices/{ctx['iid']}/request-payment-link-magic",
            params={"token": stray}, timeout=10,
        )
        assert r.status_code == 401
        detail = (r.json().get("detail") or "").lower()
        assert "mismatch" in detail
    finally:
        _cleanup(ctx)


def test_magic_pay_rejects_expired_token():
    ctx = _seed_invoice()
    try:
        expired = _mint_magic_token(ctx["iid"], ctx["tid"], exp_offset=-60)
        r = requests.post(
            f"{API}/invoices/{ctx['iid']}/request-payment-link-magic",
            params={"token": expired}, timeout=10,
        )
        assert r.status_code == 401
    finally:
        _cleanup(ctx)


def test_magic_pay_reaches_stripe_layer():
    """Valid token → endpoint reaches the Stripe session builder.

    We can't monkeypatch across the pytest → uvicorn process boundary
    so this checks the *contract at the boundary*: with a valid token
    the endpoint MUST NOT return 401 / 404, MUST return either 200
    (Stripe test key configured) or 503 with
    ``payment_gateway_unavailable`` (Stripe key absent). Both prove
    the token verification + invoice lookup + delegation to the
    Stripe helper are wired end-to-end. The 4XX rejection tests
    above cover the negative cases.
    """
    ctx = _seed_invoice()
    try:
        r = requests.post(
            f"{API}/invoices/{ctx['iid']}/request-payment-link-magic",
            params={"token": ctx["token"]}, timeout=15,
        )
        assert r.status_code in (200, 503), r.text
        if r.status_code == 200:
            body = r.json()
            assert body["amount_cents"] == 20500, body
            # payment_url may be a Checkout Session or a hosted-payment
            # URL depending on the tenant's Stripe config — just
            # verify the shape.
            assert isinstance(body.get("payment_url"), str)
            assert body["save_for_future_billing"] is False
        else:
            # Env doesn't have a Stripe test key — verify the endpoint
            # surfaces a structured error rather than freezing.
            body = r.json().get("detail", {})
            if isinstance(body, dict):
                assert body.get("error") == "payment_gateway_unavailable"
    finally:
        _cleanup(ctx)


def test_customer_view_payload_strips_cost_snapshots():
    """The estimate viewer's ``_project_line_items_for_customer``
    MUST strip every PB1 cost snapshot + admin-only flag."""
    from routers.estimate_viewer import _project_line_items_for_customer

    admin_line = {
        "description": "Pool cleaning", "qty_hr": 1, "unit_price": 100,
        "wholesale_price_snapshot": 40.0,
        "labor_cost_snapshot": 15.0,
        "retail_price_snapshot": 100.0,
        "overridden_price": False,
        "pricebook_writeback": True,
        "wholesale_price": 40.0,
        "labor_cost": 15.0,
        "labor_cost_default": 15.0,
        "cost_rate": 40.0, "cost": 40.0, "margin_pct": 60,
    }
    out = _project_line_items_for_customer([admin_line])[0]
    forbidden = (
        "wholesale_price_snapshot", "labor_cost_snapshot",
        "retail_price_snapshot", "overridden_price",
        "pricebook_writeback", "wholesale_price", "labor_cost",
        "labor_cost_default", "cost_rate", "cost", "margin_pct",
    )
    for k in forbidden:
        assert k not in out, (
            f"Serializer regression: ``{k}`` leaked into customer payload."
        )
    assert out.get("description") == "Pool cleaning"
