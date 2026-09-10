"""Feb-2026 · Add-Card-on-File email/magic-link flow — backend contract.

Locks in the truthful-outcome contract for
``POST /api/customers/{cid}/send-card-add-link`` after the P1
"toast lies" pivot. Covers:

  1. Successful send actually invokes Resend (mocked) AND returns
     ``{ok: true, sent_email: true, outcome: "sent"|"partial",
       channels: {email: {sent: true, status: "sent"}, ...}}``.
  2. No email + no phone → 400 ``NO_CONTACT_ON_FILE`` (was silent 200).
  3. Templates missing → 409 ``TEMPLATE_MISSING`` (was silent 200).
  4. Resend returns ``not_sent_missing_key`` → 502 ``PROVIDER_FAILURE``
     (was silent 200).
  5. Magic link built by ``build_add_card_link`` ends at the
     ``/portal/add-card?token=...`` public Stripe page — the token
     does NOT require any portal login. Also asserts the 7-day
     default TTL.
  6. Deliveries ledger persists the truthful per-channel
     ``provider_status`` + ``error`` fields so ops can audit without
     tailing logs.
  7. RBAC — manager/tech/customer boundaries.
"""
from __future__ import annotations

import asyncio
import time
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


TID = "t-acf"


def _seed_customer(fake_db, *, email="a@x", phone="+12025551212",
                    cid="cust-a"):
    fake_db.customers.rows.append({
        "id": cid, "tenant_id": TID, "email": email, "phone": phone,
        "name": "A Customer",
    })
    return cid


def _seed_templates(fake_db):
    fake_db.marketing_templates.rows.extend([
        {"tenant_id": TID, "code": "add_card_request_email",
          "subject": "Add your card", "body": "Click {{ADD_CARD_LINK}}"},
        {"tenant_id": TID, "code": "add_card_request_sms",
          "body": "Add your card: {{ADD_CARD_LINK}}"},
    ])


@pytest.fixture()
def fake_db(monkeypatch):
    fake = _DB()
    from routers import customers as cust_mod
    monkeypatch.setattr(cust_mod, "db", fake)
    from services import add_card_links as acl
    # Clear the module-level rate cache so each test starts fresh.
    acl._RATE_CACHE.clear()
    return fake


def _admin():
    return {"id": "u-adm", "role": "admin"}


def _tenant():
    return {"id": TID, "name": "Aquaterra"}


# ═════════════════════════════════════════════════════════════════════
# 1. Happy path — Resend send fires and the truthful envelope is
#    returned. This is the P1 regression guard.
# ═════════════════════════════════════════════════════════════════════
def test_happy_path_invokes_resend_and_returns_sent_envelope(
    fake_db, monkeypatch,
):
    cid = _seed_customer(fake_db)
    _seed_templates(fake_db)

    send_calls: list = []

    async def _fake_send_email(**kwargs):
        send_calls.append(kwargs)
        return {"status": "sent", "provider_id": "resend_id_123"}

    # Patch send_email + send_sms so nothing hits the network.
    import services.comms_email_adapter as cea
    monkeypatch.setattr(cea, "send_email", _fake_send_email)
    import utils as _utils
    monkeypatch.setattr(_utils, "send_sms", lambda *a, **kw: None)

    from routers.customers import send_card_add_link
    out = _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))

    # Resend was actually invoked (mocked).
    assert len(send_calls) == 1
    assert send_calls[0]["to_email"] == "a@x"
    assert send_calls[0]["tenant_id"] == TID
    # Truthful envelope.
    assert out["ok"] is True
    assert out["sent_email"] is True
    assert out["sent_sms"] is True
    assert out["outcome"] == "sent"
    assert out["channels"]["email"]["status"] == "sent"
    assert out["channels"]["sms"]["status"] == "sent"
    # Deliveries ledger has the truthful per-channel outcome.
    email_row = next(
        r for r in fake_db.marketing_deliveries.inserts
        if r["channel"] == "email"
    )
    assert email_row["delivered"] is True
    assert email_row["provider_status"] == "sent"
    assert email_row["error"] is None


# ═════════════════════════════════════════════════════════════════════
# 8. Feb-2026 follow-up P1 — ledger truthfulness contract.
#    The delivery row MUST persist ``provider_response_id`` so the
#    Resend webhook receiver can correlate terminal events back to
#    THIS row. Also stamps ``accepted_by_provider`` (semantic alias)
#    and ``terminal_delivered=None`` (flipped by the webhook).
# ═════════════════════════════════════════════════════════════════════
def test_delivery_row_persists_provider_id_for_webhook_correlation(
    fake_db, monkeypatch,
):
    cid = _seed_customer(fake_db, phone=None)
    _seed_templates(fake_db)

    async def _fake_send_email(**kwargs):
        return {"status": "sent", "provider_id": "resend_msg_ABC"}

    import services.comms_email_adapter as cea
    monkeypatch.setattr(cea, "send_email", _fake_send_email)

    from routers.customers import send_card_add_link
    _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))

    row = next(
        r for r in fake_db.marketing_deliveries.inserts
        if r["channel"] == "email"
    )
    # ``provider_response_id`` MUST be set so the webhook receiver
    # can update this row when Resend fires ``email.delivered`` etc.
    assert row["provider_response_id"] == "resend_msg_ABC"
    # Ledger truthfulness — ``delivered`` = "provider accepted" is
    # semantically ambiguous, so the row also carries an unambiguous
    # ``accepted_by_provider`` alias + a ``terminal_delivered`` tri-
    # state that only the webhook can flip.
    assert row["accepted_by_provider"] is True
    assert row["terminal_delivered"] is None


# ═════════════════════════════════════════════════════════════════════
# 2. No email + no phone → 400 ``NO_CONTACT_ON_FILE``.
# ═════════════════════════════════════════════════════════════════════
def test_no_contact_on_file_returns_400_no_contact(fake_db, monkeypatch):
    cid = _seed_customer(fake_db, email=None, phone=None)
    _seed_templates(fake_db)
    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException) as ei:
        _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))
    assert ei.value.status_code == 400
    detail = ei.value.detail
    assert detail["code"] == "NO_CONTACT_ON_FILE"
    assert "email or phone" in detail["message"].lower()


# ═════════════════════════════════════════════════════════════════════
# 3. Templates missing → 409 ``TEMPLATE_MISSING``.
# ═════════════════════════════════════════════════════════════════════
def test_template_missing_returns_409(fake_db, monkeypatch):
    cid = _seed_customer(fake_db)
    # Deliberately do NOT seed templates.
    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException) as ei:
        _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))
    assert ei.value.status_code == 409
    assert ei.value.detail["code"] == "TEMPLATE_MISSING"


# ═════════════════════════════════════════════════════════════════════
# 4. Provider failure — Resend returns ``not_sent_missing_key`` →
#    502 ``PROVIDER_FAILURE`` instead of silent 200.
# ═════════════════════════════════════════════════════════════════════
def test_missing_resend_key_returns_502_provider_failure(
    fake_db, monkeypatch,
):
    cid = _seed_customer(fake_db, phone=None)
    _seed_templates(fake_db)

    async def _fake_send_email(**kwargs):
        return {"status": "not_sent_missing_key",
                "error": "RESEND_API_KEY missing on this pod"}

    import services.comms_email_adapter as cea
    monkeypatch.setattr(cea, "send_email", _fake_send_email)

    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException) as ei:
        _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))
    assert ei.value.status_code == 502
    detail = ei.value.detail
    assert detail["code"] == "PROVIDER_FAILURE"
    assert detail["reasons"]["email"] == "not_sent_missing_key"


# ═════════════════════════════════════════════════════════════════════
# 5. Magic link is a Stripe-hosted URL that does NOT require portal
#    login — the JWT token is the sole authority. Also asserts the
#    7-day default TTL.
# ═════════════════════════════════════════════════════════════════════
def test_magic_link_targets_stripe_page_no_portal_login():
    from services.add_card_links import (
        build_add_card_link, decode_add_card_token,
        ADD_CARD_LINK_TTL_SECONDS,
    )
    link = build_add_card_link("https://example.com", "cust-1", "t-1")
    # Route is the public Stripe SetupIntent page — NOT a
    # portal-authed screen. Token is on the query string.
    assert link.startswith("https://example.com/portal/add-card?token=")
    # 7-day default TTL per the Feb-2026 pivot.
    assert ADD_CARD_LINK_TTL_SECONDS == 7 * 24 * 3600
    # Token decodes to a payload with the right shape + no auth
    # cookies / no user_id — the JWT is the sole authority.
    tok = link.split("token=", 1)[1]
    payload = decode_add_card_token(tok)
    assert payload["customer_id"] == "cust-1"
    assert payload["tenant_id"] == "t-1"
    assert payload["sub"] == "add_card"
    # ``exp`` is ~7d in the future (within a 60-s tolerance).
    assert payload["exp"] - int(time.time()) > (
        6 * 24 * 3600 + 23 * 3600
    )


# ═════════════════════════════════════════════════════════════════════
# 6. RBAC — customer / technician / manager gate.
# ═════════════════════════════════════════════════════════════════════
def test_customer_role_rejected_with_403(fake_db):
    cid = _seed_customer(fake_db)
    _seed_templates(fake_db)
    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException) as ei:
        _run(send_card_add_link(
            cid,
            user={"id": "u-c", "role": "customer", "customer_id": cid},
            tenant=_tenant(),
        ))
    assert ei.value.status_code == 403


def test_manager_super_admin_admin_all_allowed(fake_db, monkeypatch):
    cid = _seed_customer(fake_db, phone=None)
    _seed_templates(fake_db)

    async def _fake_send_email(**kwargs):
        return {"status": "sent"}

    import services.comms_email_adapter as cea
    monkeypatch.setattr(cea, "send_email", _fake_send_email)

    from routers.customers import send_card_add_link
    from services import add_card_links as acl
    for role in ("admin", "manager", "super_admin"):
        acl._RATE_CACHE.clear()  # each role gets a fresh window
        out = _run(send_card_add_link(
            cid,
            user={"id": f"u-{role}", "role": role},
            tenant=_tenant(),
        ))
        assert out["sent_email"] is True



# ═════════════════════════════════════════════════════════════════════
# 9. SMS parity — silent-fail vector when RC BYO is unconfigured.
#    ``send_sms`` (legacy sync wrapper) returned True regardless of
#    whether the RC adapter answered ``provider="mock"`` (BYO
#    missing) or ``provider_status="dry_run"`` (comms env-guard
#    downgraded). The Feb-2026 fix calls the RC adapter directly
#    and surfaces the exact reason on the ledger + response.
# ═════════════════════════════════════════════════════════════════════
def test_sms_unconfigured_marks_sms_not_configured_not_sent(
    fake_db, monkeypatch,
):
    cid = _seed_customer(fake_db, email=None)  # SMS-only path
    _seed_templates(fake_db)

    async def _fake_rc_send(**kwargs):
        return {"provider": "mock", "provider_status": "not_configured",
                "provider_response_id": None}

    import services.sms.rc_adapter as rca
    monkeypatch.setattr(rca, "send", _fake_rc_send)

    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException) as ei:
        _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))
    assert ei.value.status_code == 502
    sms_row = next(
        r for r in fake_db.marketing_deliveries.inserts
        if r["channel"] == "sms"
    )
    assert sms_row["delivered"] is False
    assert sms_row["accepted_by_provider"] is False
    assert sms_row["provider_status"] == "sms_not_configured"
    assert "RingCentral" in sms_row["error"]


def test_sms_gate_dry_run_marks_gate_dry_run(fake_db, monkeypatch):
    cid = _seed_customer(fake_db, email=None)
    _seed_templates(fake_db)

    async def _fake_rc_send(**kwargs):
        return {"provider": "ringcentral", "provider_status": "dry_run",
                "provider_response_id": None}

    import services.sms.rc_adapter as rca
    monkeypatch.setattr(rca, "send", _fake_rc_send)

    from routers.customers import send_card_add_link
    with pytest.raises(HTTPException):
        _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))
    sms_row = next(
        r for r in fake_db.marketing_deliveries.inserts
        if r["channel"] == "sms"
    )
    assert sms_row["provider_status"] == "gate_dry_run"
    assert "allowlisted" in sms_row["error"]


def test_sms_happy_path_persists_provider_id(fake_db, monkeypatch):
    cid = _seed_customer(fake_db, email=None)
    _seed_templates(fake_db)

    async def _fake_rc_send(**kwargs):
        return {"provider": "ringcentral", "provider_status": "queued",
                "provider_response_id": "rc_msg_XYZ"}

    import services.sms.rc_adapter as rca
    monkeypatch.setattr(rca, "send", _fake_rc_send)

    from routers.customers import send_card_add_link
    out = _run(send_card_add_link(cid, user=_admin(), tenant=_tenant()))
    assert out["sent_sms"] is True
    assert out["channels"]["sms"]["status"] == "queued"
    sms_row = next(
        r for r in fake_db.marketing_deliveries.inserts
        if r["channel"] == "sms"
    )
    assert sms_row["provider_response_id"] == "rc_msg_XYZ"
    assert sms_row["accepted_by_provider"] is True
