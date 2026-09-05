"""Phase K43 · Feb-2026 — ACH bank verification + admin verify tests.

Coverage matrix (K43 brief):
  · SetupIntent for ``us_bank_account`` now includes the FC + instant
    verification payment_method_options block (unit-level check).
  · ``charge_ach_on_file`` refuses to dispatch when the mirror row's
    ``verification_status`` is anything but ``verified`` and emits the
    ``autobilling_ach_skipped_unverified`` audit event (defence in
    depth for callers that bypass ``_ach_eligibility_and_pm``).
  · ``POST /customers/{cid}/bank-accounts/{pm_id}/verify-microdeposits``
    validates the body shape and rejects non-admins with 403.
  · ``POST /customers/{cid}/bank-accounts/{pm_id}/re-verify`` returns
    404 when the bank row is missing and 403 for non-admins.
  · Migration ``k43_sync_bank_verification_status`` runs idempotently
    (no-op on preview) and writes the sentinel.
  · Bulk-charge dry-run skip rows now carry ``customer_id`` so the K38
    modal can deep-link to the customer detail.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API = "http://localhost:8001/api"
_sync = MongoClient(os.environ["MONGO_URL"])
_db = _sync[os.environ["DB_NAME"]]

_CACHE: dict = {}


# ─────────────────────────────────────────────────────────────────────
# Shared event loop + motor client for the direct-helper tests.
# Motor's futures are tied to the loop that created them, so we
# bind ``services.payments.stripe_charge.db`` (and the ``config.db``
# it aliases) to a fresh motor client attached to the loop we own
# here, then execute helpers via ``_run(coro)``.
# ─────────────────────────────────────────────────────────────────────
_LOOP = asyncio.new_event_loop()


def _run(coro):
    """Run ``coro`` on the shared loop; ensures Motor sees a single
    loop across the whole test module."""
    return _LOOP.run_until_complete(coro)


def _install_async_db():
    import motor.motor_asyncio as _mm
    client = _mm.AsyncIOMotorClient(os.environ["MONGO_URL"],
                                       io_loop=_LOOP)
    adb = client[os.environ["DB_NAME"]]
    import config as _cfg
    _cfg.db = adb
    from services.payments import stripe_charge as _svc
    _svc.db = adb
    return adb


_ADB = _install_async_db()


def _login(email: str, password: str = "password123") -> str:
    key = f"tok:{email}"
    if _CACHE.get(key):
        return _CACHE[key]
    r = requests.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"login skipped for {email}: {r.status_code}")
    _CACHE[key] = r.json()["access_token"]
    return _CACHE[key]


def _me(token: str) -> dict:
    r = requests.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    return r.json() if r.status_code == 200 else {}


def _super_ctx() -> dict:
    if _CACHE.get("super_ctx"):
        return _CACHE["super_ctx"]
    tok = _login("super@aquaterra.com")
    me = _me(tok)
    _CACHE["super_ctx"] = {"token": tok, "tenant_id": me.get("tenant_id")}
    return _CACHE["super_ctx"]


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _seed_customer_and_pm(tenant_id: str, verification_status: str = "unverified"):
    """Seed a customer + a us_bank_account mirror row in the requested
    verification state.  Returns (customer_id, pm_id)."""
    cid = f"TEST-K43-CUST-{uuid.uuid4().hex[:8]}"
    pm_id = f"pm_TESTK43{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    _db.customers.insert_one({
        "id": cid, "tenant_id": tenant_id,
        "name": "K43 Test Customer", "email": "k43@example.com",
        "active": True, "created_at": now,
    })
    _db.payment_methods.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id, "customer_id": cid,
        "provider": "stripe", "provider_customer_id": f"cus_TESTK43{uuid.uuid4().hex[:6]}",
        "provider_payment_method_id": pm_id,
        "type": "us_bank_account",
        "brand": "us_bank_account",
        "last4": "3429", "bank_name": "Wells Fargo",
        "verification_status": verification_status,
        "created_at": now,
    })
    return cid, pm_id


# ═════════════════════════════════════════════════════════════════════
# 1) SetupIntent options — FC + instant verification for ACH
# ═════════════════════════════════════════════════════════════════════
def test_k43_setup_intent_forces_financial_connections_for_ach():
    """Unit-level introspection — ``_build_si_kwargs`` inside
    ``create_setup_intent`` must attach the FC + instant options when
    ``us_bank_account`` is in the requested types."""
    import inspect

    from services.payments import stripe_charge as svc
    src = inspect.getsource(svc.create_setup_intent)
    # The nested closure carries the FC options.
    assert 'verification_method": "instant"' in src, (
        "K43 SetupIntent must force verification_method=instant for ACH."
    )
    assert '"financial_connections"' in src, (
        "K43 SetupIntent must attach financial_connections permissions."
    )
    assert '"payment_method"' in src and '"balances"' in src, (
        "K43 FC permissions must include payment_method + balances."
    )


# ═════════════════════════════════════════════════════════════════════
# 2) charge_ach_on_file — refuses to fire when verification != verified
# ═════════════════════════════════════════════════════════════════════
def test_k43_charge_ach_on_file_skips_unverified_and_emits_audit():
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    cid, pm_id = _seed_customer_and_pm(tenant_id, verification_status="new")

    try:
        from services.payments.stripe_charge import charge_ach_on_file
        with pytest.raises(ValueError) as excinfo:
            _run(charge_ach_on_file(
                tenant_id=tenant_id,
                customer_id=cid,
                payment_method_id=pm_id,
                amount_cents=1500,
                currency="usd",
                invoice_id="TEST-K43-INV-x",
                description="K43 test",
                metadata={},
                actor_user_id="test-actor",
            ))
        assert str(excinfo.value) == "bank_unverified"

        # Audit landed.
        row = _db.audit_events.find_one({
            "event_type": "autobilling_ach_skipped_unverified",
            "customer_id": cid, "payment_method_id": pm_id,
        }, {"_id": 0})
        assert row is not None, "K43 audit event must be emitted."
        assert row["verification_status"] == "new"
        assert row["amount_cents"] == 1500
    finally:
        _db.customers.delete_one({"id": cid})
        _db.payment_methods.delete_many({"customer_id": cid})
        _db.audit_events.delete_many({"customer_id": cid})


def test_k43_charge_ach_on_file_passes_verified_bank_through():
    """A verified bank must clear the K43 guard and reach the Stripe
    call — we mock the Stripe layer so the test doesn't hit the network."""
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    cid, pm_id = _seed_customer_and_pm(tenant_id, verification_status="verified")

    # K45-companion test-hygiene fix (Feb-2026): the sparse-unique
    # ``stripe_charges_pi_unique`` index treats an explicit ``null``
    # PI as "present" for uniqueness purposes.  If a prior test run
    # crashed mid-flight it can leave both a ``pi_TESTK43`` row AND a
    # null-PI failure row in the collection, causing THIS test to
    # dup-key on both the happy-path insert and the exception-handler
    # fallback insert.  Purge any leaked K43 rows before we seed.
    _db.stripe_charges.delete_many({"customer_id": cid})
    _db.stripe_charges.delete_many({"stripe_payment_intent_id": "pi_TESTK43"})

    try:
        from services.payments import stripe_charge as svc
        # The guard passes when status=verified.  The next call is
        # `stripe.PaymentIntent.create` which needs a live Stripe key
        # to succeed — we monkeypatch to a stub that returns the shape
        # the helper expects.
        from types import SimpleNamespace
        stub = SimpleNamespace(
            id="pi_TESTK43", status="processing", client_secret="cs_x",
            charges=SimpleNamespace(data=[]),
            latest_charge=None,
        )

        async def _stub_thread(fn, *a, **kw):
            return stub

        monkey_before = svc._to_thread
        svc._to_thread = _stub_thread  # type: ignore
        try:
            res = _run(svc.charge_ach_on_file(
                tenant_id=tenant_id, customer_id=cid,
                payment_method_id=pm_id, amount_cents=1500,
                currency="usd", invoice_id="TEST-K43-INV-y",
                description="K43 test", metadata={},
                actor_user_id="test-actor",
            ))
            assert res["payment_intent_id"] == "pi_TESTK43"
        finally:
            svc._to_thread = monkey_before  # type: ignore
    finally:
        _db.customers.delete_one({"id": cid})
        _db.payment_methods.delete_many({"customer_id": cid})
        # K45-companion test-hygiene fix — always drain the
        # stripe_charges rows this test created (both the happy-path
        # ``pi_TESTK43`` row and any null-PI failure row the
        # exception handler may have persisted).
        _db.stripe_charges.delete_many({"customer_id": cid})
        _db.stripe_charges.delete_many({"stripe_payment_intent_id": "pi_TESTK43"})


# ═════════════════════════════════════════════════════════════════════
# 3) Admin verify-microdeposits endpoint — validation + auth
# ═════════════════════════════════════════════════════════════════════
def test_k43_verify_microdeposits_body_validation():
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    cid, pm_id = _seed_customer_and_pm(tenant_id, "pending_microdeposit")
    try:
        # Empty body → 422 (missing amounts + descriptor).
        r = requests.post(
            f"{API}/customers/{cid}/bank-accounts/{pm_id}/verify-microdeposits",
            headers=_headers(ctx["token"]), json={}, timeout=15,
        )
        assert r.status_code == 422, r.text
        assert "amounts_cents_or_descriptor_code_required" in r.json()["detail"]

        # Malformed amounts → 422.
        r = requests.post(
            f"{API}/customers/{cid}/bank-accounts/{pm_id}/verify-microdeposits",
            headers=_headers(ctx["token"]),
            json={"amounts_cents": [0, 250]}, timeout=15,
        )
        assert r.status_code == 422, r.text

        # Missing PM → 404.
        r = requests.post(
            f"{API}/customers/{cid}/bank-accounts/pm_MISSING/verify-microdeposits",
            headers=_headers(ctx["token"]),
            json={"amounts_cents": [32, 45]}, timeout=15,
        )
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "bank_account_not_found"
    finally:
        _db.customers.delete_one({"id": cid})
        _db.payment_methods.delete_many({"customer_id": cid})


@pytest.mark.parametrize("email", [
    "manager@aquaterra.com",
    "carlos@aquaterra.com",
    "customer@aquaterra.com",
])
def test_k43_verify_microdeposits_denies_non_admin(email):
    tok = _login(email)
    r = requests.post(
        f"{API}/customers/TEST-NA/bank-accounts/pm_x/verify-microdeposits",
        headers=_headers(tok),
        json={"amounts_cents": [32, 45]}, timeout=15,
    )
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════════
# 4) Admin re-verify endpoint — 404 + auth
# ═════════════════════════════════════════════════════════════════════
def test_k43_reverify_missing_bank_returns_404():
    ctx = _super_ctx()
    r = requests.post(
        f"{API}/customers/TEST-CID-MISSING/bank-accounts/pm_MISSING/re-verify",
        headers=_headers(ctx["token"]), timeout=15,
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "bank_account_not_found"


@pytest.mark.parametrize("email", [
    "manager@aquaterra.com",
    "carlos@aquaterra.com",
    "customer@aquaterra.com",
])
def test_k43_reverify_denies_non_admin(email):
    tok = _login(email)
    r = requests.post(
        f"{API}/customers/TEST-NA/bank-accounts/pm_x/re-verify",
        headers=_headers(tok), timeout=15,
    )
    assert r.status_code == 403, r.text


# ═════════════════════════════════════════════════════════════════════
# 5) Migration — idempotent + sentinel-written
# ═════════════════════════════════════════════════════════════════════
def test_k43_migration_idempotent_writes_sentinel():
    from migrations import k43_sync_bank_verification_status as mig
    # Rebind the migration module's db to our motor client so its
    # own ``async for`` loops don't fight the pytest event loop.
    mig.db = _ADB  # type: ignore
    _run(mig.run())
    sentinel = _db.migrations.find_one(
        {"key": mig._SENTINEL_KEY}, {"_id": 0},
    )
    assert sentinel is not None
    assert sentinel["mode"] == "apply"
    # Rerun — still safe.
    _run(mig.run())


# ═════════════════════════════════════════════════════════════════════
# 6) Bulk-charge skip response carries customer_id (K38 QoL contract)
# ═════════════════════════════════════════════════════════════════════
def test_k43_bulk_charge_skip_row_carries_customer_id():
    """The K38 bulk-charge dry-run must include ``customer_id`` on
    every skipped row so the K43 modal QoL link can render.  Seed a
    customer with an unverified bank + a draft invoice and hit the
    dry-run endpoint."""
    ctx = _super_ctx()
    tenant_id = ctx["tenant_id"]
    cid, pm_id = _seed_customer_and_pm(tenant_id, "pending_microdeposit")
    now = datetime.now(timezone.utc).isoformat()

    # Mark the bank as the default so bulk-charge picks it up.
    _db.customers.update_one(
        {"id": cid},
        {"$set": {"default_payment_method_id": pm_id,
                   "billing_settings.default_ach_pm_id": pm_id}},
    )
    inv_id = f"TEST-K43-INV-{uuid.uuid4().hex[:8]}"
    # K45-companion fix (Feb-2026): the bulk-charge endpoint reads
    # invoices from the ``quotes`` collection (``doc_type: "invoice"``),
    # not from a legacy ``invoices`` collection.  Inserting into the
    # wrong one made the router return ``skip_reason=not_found`` and
    # the K43 contract assertion never fired.
    #
    # The eligibility helper also reads dollar-denominated ``total``
    # + ``amount_paid`` fields (not the ``_cents`` variants), so we
    # seed both so the invoice is picked up AND has non-zero
    # outstanding balance — otherwise the skip reason short-circuits
    # to ``zero_balance`` before the K43 bank_unverified branch runs.
    _db.quotes.insert_one({
        "id": inv_id, "tenant_id": tenant_id, "customer_id": cid,
        "doc_type": "invoice",
        "invoice_number": "K43-1",
        "status": "sent", "currency": "usd",
        "total": 15.0, "amount_paid": 0.0,
        "total_cents": 1500, "amount_paid_cents": 0,
        "created_at": now, "issued_at": now,
    })

    try:
        r = requests.post(
            f"{API}/invoices/bulk-charge-ach-on-file",
            headers=_headers(ctx["token"]),
            json={"invoice_ids": [inv_id], "dry_run": True,
                   "idempotency_key": f"k43-test-{uuid.uuid4().hex[:8]}"},
            timeout=30,
        )
        if r.status_code == 404:
            pytest.skip("bulk-charge-ach endpoint not mounted here")
        assert r.status_code == 200, r.text
        results = r.json().get("results", [])
        assert len(results) == 1
        row = results[0]
        assert row["status"] == "skipped"
        assert row["skip_reason"] == "bank_unverified"
        # K43 contract additions — customer_id and pm hints must be on
        # the skip row so the modal can deep-link.
        assert row.get("customer_id") == cid, (
            "K43 contract: customer_id must be present on every skip row."
        )
    finally:
        _db.customers.delete_one({"id": cid})
        _db.payment_methods.delete_many({"customer_id": cid})
        _db.quotes.delete_many({"id": inv_id})
