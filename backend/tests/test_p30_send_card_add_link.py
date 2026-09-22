"""Phase P30 · Feb-2026 — Router wiring for the direct Stripe Checkout
Session flow.

Locks in that ``POST /api/customers/{cid}/send-card-add-link`` now
mints a Stripe Checkout Session (mode="setup") via
``create_card_setup_checkout_session`` and drops the returned
``session.url`` straight into the merge context. Prior to P30 the
router built a self-hosted JWT magic link to ``/portal/add-card``.

Coverage:

1. Stripe helper is invoked with the correct kwargs — the four
   canonical identifiers plus a ``success_url`` carrying the literal
   ``{CHECKOUT_SESSION_ID}`` Stripe placeholder.
2. The stub helper's return URL flows into ``ADD_CARD_LINK`` so the
   rendered SMS + email bodies contain the Stripe-hosted URL (NOT
   the legacy ``/portal/add-card?token=…`` shape).
3. Stripe helper raising → 502 ``STRIPE_SESSION_ERROR`` (never
   silently 200s).
4. ``ensure_stripe_customer`` raising ValueError → 404 (missing
   customer / tenant edge — never 500s).
5. ``PUBLIC_FRONTEND_ORIGIN`` env var is honored — the success URL
   is built off that origin.

Uses the ``_DB`` fake pattern established in
``test_add_card_on_file_email_flow.py`` so the router is exercised
via a direct function call (no HTTP stack, no network I/O).
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.inserts: List[Dict[str, Any]] = []

    async def find_one(self, filt=None, projection=None, *a, **kw):
        for r in self.rows:
            if all(r.get(k) == v for k, v in (filt or {}).items()):
                return dict(r)
        return None

    async def insert_one(self, doc):
        self.inserts.append(doc)
        self.rows.append(doc)
        return SimpleNamespace(inserted_id=doc.get("id"))


class _DB:
    def __init__(self):
        self.customers = _Coll()
        self.tenants = _Coll()
        self.marketing_templates = _Coll()
        self.marketing_deliveries = _Coll()


TID = "t-p30"


def _seed(fake_db, *, cid="cust-p30", email="p30@example.com",
           phone="+14805551234"):
    fake_db.customers.rows.append({
        "id": cid, "tenant_id": TID, "email": email, "phone": phone,
        "name": "P30 Test", "stripe_customer_id": "cus_seeded",
    })
    fake_db.marketing_templates.rows.extend([
        {"tenant_id": TID, "code": "add_card_request_email",
          "subject": "Add your card",
          "body": "Click <a href=\"{{ADD_CARD_LINK}}\">here</a>"},
        {"tenant_id": TID, "code": "add_card_request_sms",
          "body": "Add card: {{ADD_CARD_LINK}}"},
    ])
    return cid


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _DB()
    from routers import customers as cust_mod
    monkeypatch.setattr(cust_mod, "db", fake)
    from services import add_card_links as acl
    acl._RATE_CACHE.clear()
    return fake


def _admin():
    return {"id": "u-adm", "role": "admin"}


def _tenant():
    return {"id": TID, "name": "P30 Tenant"}


def _patch_stripe(monkeypatch, *, url="https://checkout.stripe.com/c/pay/cs_test_abc",
                    stripe_cust_id="cus_ensured", raise_helper=False,
                    raise_ensure=None):
    """Patch ``ensure_stripe_customer`` + ``create_card_setup_checkout_session``.

    ``raise_helper`` — if True, ``create_card_setup_checkout_session``
    raises a RuntimeError (simulates Stripe outage).
    ``raise_ensure`` — if set, ``ensure_stripe_customer`` raises this
    exception instance.
    """
    call_captures = {"session_calls": []}

    async def _fake_ensure(**kwargs):
        if raise_ensure is not None:
            raise raise_ensure
        return stripe_cust_id

    async def _fake_session(**kwargs):
        call_captures["session_calls"].append(kwargs)
        if raise_helper:
            raise RuntimeError("stripe boom")
        return url

    from services.payments import stripe_charge as sc
    monkeypatch.setattr(sc, "ensure_stripe_customer", _fake_ensure)
    monkeypatch.setattr(sc, "create_card_setup_checkout_session", _fake_session)
    return call_captures


def _patch_comms(monkeypatch):
    """Patch email + RC SMS adapters to record calls without network."""
    email_calls: list = []
    sms_calls: list = []

    async def _fake_email(**kwargs):
        email_calls.append(kwargs)
        return {"status": "sent", "provider_id": "resend_p30"}

    async def _fake_sms(**kwargs):
        sms_calls.append(kwargs)
        return {"provider": "ringcentral", "provider_status": "sent",
                "provider_response_id": "rc_p30"}

    import services.comms_email_adapter as cea
    monkeypatch.setattr(cea, "send_email", _fake_email)
    import services.sms.rc_adapter as rc_ad
    monkeypatch.setattr(rc_ad, "send", _fake_sms)
    return email_calls, sms_calls


# ═════════════════════════════════════════════════════════════════════
# 1. Helper is invoked with the canonical P30 kwargs.
# ═════════════════════════════════════════════════════════════════════
def test_p30_router_invokes_helper_with_canonical_kwargs(
    fake_db, monkeypatch,
):
    cid = _seed(fake_db)
    captures = _patch_stripe(monkeypatch)
    _patch_comms(monkeypatch)
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://app.plofv.com")

    from routers.customers import send_card_add_link
    _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))

    assert len(captures["session_calls"]) == 1
    kw = captures["session_calls"][0]
    assert kw["customer_id"] == cid
    assert kw["tenant_id"] == TID
    assert kw["stripe_customer_id"] == "cus_ensured"
    # Success URL carries the LITERAL Stripe placeholder — Stripe
    # expands it at redirect time. Anything else would silently
    # ship a broken success page.
    assert kw["success_url"] == (
        "https://app.plofv.com/portal/setup-success"
        "?session_id={CHECKOUT_SESSION_ID}"
    )
    assert kw["cancel_url"] == "https://app.plofv.com/portal/setup-cancelled"
    # Router-side trigger metadata rides along so the webhook /
    # audit surfaces can trace the caller.
    assert kw["metadata"]["trigger_source"] == "send_card_add_link"


# ═════════════════════════════════════════════════════════════════════
# 2. Helper's return URL flows into ADD_CARD_LINK → shows up in
#    the rendered email + SMS bodies. Rules out a regression where
#    the router accidentally rendered the OLD magic-link URL.
# ═════════════════════════════════════════════════════════════════════
def test_p30_stripe_url_flows_into_email_and_sms_bodies(
    fake_db, monkeypatch,
):
    cid = _seed(fake_db)
    _patch_stripe(
        monkeypatch,
        url="https://checkout.stripe.com/c/pay/cs_flow_test_xyz",
    )
    email_calls, sms_calls = _patch_comms(monkeypatch)
    monkeypatch.setenv("PUBLIC_FRONTEND_ORIGIN", "https://app.plofv.com")

    from routers.customers import send_card_add_link
    _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))

    # Email body has the Stripe URL substituted for {{ADD_CARD_LINK}}.
    assert len(email_calls) == 1
    assert "https://checkout.stripe.com/c/pay/cs_flow_test_xyz" \
        in email_calls[0]["html"]
    # And crucially — NOT the legacy portal magic-link shape.
    assert "/portal/add-card?token=" not in email_calls[0]["html"]

    # SMS body ditto.
    assert len(sms_calls) == 1
    assert "https://checkout.stripe.com/c/pay/cs_flow_test_xyz" \
        in sms_calls[0]["body"]
    assert "/portal/add-card?token=" not in sms_calls[0]["body"]


# ═════════════════════════════════════════════════════════════════════
# 3. Stripe helper raises → 502 STRIPE_SESSION_ERROR (not silent 200).
# ═════════════════════════════════════════════════════════════════════
def test_p30_helper_failure_raises_502_stripe_session_error(
    fake_db, monkeypatch,
):
    cid = _seed(fake_db)
    _patch_stripe(monkeypatch, raise_helper=True)
    _patch_comms(monkeypatch)

    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException) as ei:
        _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))
    assert ei.value.status_code == 502
    detail = ei.value.detail
    assert detail["code"] == "STRIPE_SESSION_ERROR"
    assert "Stripe" in detail["message"]


# ═════════════════════════════════════════════════════════════════════
# 4. ensure_stripe_customer raising ValueError → 404.
# ═════════════════════════════════════════════════════════════════════
def test_p30_ensure_customer_missing_raises_404(fake_db, monkeypatch):
    cid = _seed(fake_db)
    _patch_stripe(
        monkeypatch,
        raise_ensure=ValueError("customer not found or missing email"),
    )
    _patch_comms(monkeypatch)

    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException) as ei:
        _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))
    assert ei.value.status_code == 404
    assert "missing" in str(ei.value.detail).lower() \
        or "not found" in str(ei.value.detail).lower()


# ═════════════════════════════════════════════════════════════════════
# 5. PUBLIC_FRONTEND_ORIGIN env var is honored — the success URL is
#    built off that origin (not the hardcoded production default).
# ═════════════════════════════════════════════════════════════════════
def test_p30_public_frontend_origin_env_var_is_honored(
    fake_db, monkeypatch,
):
    cid = _seed(fake_db)
    captures = _patch_stripe(monkeypatch)
    _patch_comms(monkeypatch)
    monkeypatch.setenv(
        "PUBLIC_FRONTEND_ORIGIN", "https://preview.example.dev",
    )

    from routers.customers import send_card_add_link
    _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))

    kw = captures["session_calls"][0]
    assert kw["success_url"].startswith("https://preview.example.dev/")
    assert kw["cancel_url"].startswith("https://preview.example.dev/")


# ═════════════════════════════════════════════════════════════════════
# 6. RBAC — technician role forbidden (unchanged from pre-P30).
# ═════════════════════════════════════════════════════════════════════
def test_p30_technician_role_is_forbidden(fake_db, monkeypatch):
    cid = _seed(fake_db)
    _patch_stripe(monkeypatch)
    _patch_comms(monkeypatch)

    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException) as ei:
        _run(send_card_add_link(
            cid,
            user={"id": "u-tech", "role": "technician"},
            tenant=_tenant(),
        ))
    assert ei.value.status_code == 403
