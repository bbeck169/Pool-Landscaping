"""Feb-2026 P0 restore · GET /api/invoices/{iid}/full-magic tests.

Covers the restored magic-token invoice viewer endpoint in
``backend/routers/invoice_magic_view.py``. The endpoint's raison
d'être is powering the customer email pay-link
(``/pay/invoice/:id?token=<jwt>``) — see the top-of-file docstring
for the full RCA of why it was restored.

Key contracts under test:
* Valid token (minted by the SAME
  ``services.pay_link_builder.issue_invoice_magic_token`` the
  emailers use) returns 200 + the viewer payload.
* Bad / expired / malformed tokens fail closed with 401.
* Cross-tenant tokens can't view invoices in a different tenant
  (token's ``tenant_id`` scopes the invoice lookup, not the URL).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient


API = "http://127.0.0.1:8001/api"
_ENV = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_JWT_SECRET = _ENV["JWT_SECRET"]


def _warm_backend() -> None:
    import time
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            r = requests.get(f"{API}/config/public", timeout=5)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)


_warm_backend()


def _fresh_db():
    loop = asyncio.get_event_loop()
    client = AsyncIOMotorClient(_ENV["MONGO_URL"], io_loop=loop)
    return client[_ENV["DB_NAME"]], client


def _mint_token(*, invoice_id: str, tenant_id: str,
                sub: str = "invoice_pay",
                expires_in_seconds: int = 300) -> str:
    """Local token mint that MATCHES ``services.pay_link_builder``
    byte-for-byte. Kept here so the test can exercise the verifier
    without touching the production issuer surface."""
    payload = {
        "sub": sub,
        "invoice_id": invoice_id,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc)
                 + timedelta(seconds=expires_in_seconds),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


TENANT_A_ID = f"TEST_imv_tenantA_{uuid.uuid4().hex[:6]}"
TENANT_B_ID = f"TEST_imv_tenantB_{uuid.uuid4().hex[:6]}"


async def _seed_full_invoice_stack(db, tenant_id: str, *, delete: bool = False):
    """Seed a tenant + customer + invoice all keyed to the same
    tenant so ``_build_viewer_payload`` returns a real 200."""
    await db.tenants.update_one(
        {"id": tenant_id},
        {"$set": {"id": tenant_id, "name": "TEST_imv tenant",
                    "settings": {}}},
        upsert=True,
    )
    cust_id = f"TEST_imv_cust_{uuid.uuid4().hex[:8]}"
    await db.customers.insert_one({
        "id": cust_id, "tenant_id": tenant_id,
        "name": "TEST_imv Customer",
        "email": f"{cust_id}@example.com",
        "address": "1 Test Way, Test AZ",
    })
    inv_id = f"TEST_imv_inv_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": inv_id, "tenant_id": tenant_id,
        "doc_type": "invoice",
        "customer_id": cust_id,
        "invoice_number": inv_id[-8:],
        "status": "sent",
        "payment_status": "unpaid",
        "total": 42.00,
        "amount_paid": 0.00,
        "line_items": [{"description": "Test",
                         "cost_rate": 42.00, "qty_hr": 1, "percent": 0}],
        "notes": "",
        "created_at": "2027-01-01T00:00:00+00:00",
    }
    if delete:
        doc["deleted_at"] = "2027-01-02T00:00:00+00:00"
    await db.quotes.insert_one(doc)
    return inv_id, cust_id


async def _cleanup(db):
    for tid in (TENANT_A_ID, TENANT_B_ID):
        await db.tenants.delete_many({"id": tid})
        await db.customers.delete_many({"tenant_id": tid})
        await db.quotes.delete_many({"tenant_id": tid})


def test_valid_token_returns_200_with_viewer_payload():
    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            return await _seed_full_invoice_stack(db, TENANT_A_ID)
        finally:
            client.close()
    inv_id, _ = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        token = _mint_token(invoice_id=inv_id, tenant_id=TENANT_A_ID)
        r = requests.get(
            f"{API}/invoices/{inv_id}/full-magic",
            params={"token": token}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Same shape as the authenticated /full endpoint.
        assert body["invoice_id"] == inv_id
        assert body["bill_to"]["name"] == "TEST_imv Customer"
        assert body["totals"]["total_due"] == pytest.approx(42.00)
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_expired_token_returns_401_with_detail():
    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            return await _seed_full_invoice_stack(db, TENANT_A_ID)
        finally:
            client.close()
    inv_id, _ = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        token = _mint_token(invoice_id=inv_id, tenant_id=TENANT_A_ID,
                              expires_in_seconds=-60)
        r = requests.get(
            f"{API}/invoices/{inv_id}/full-magic",
            params={"token": token}, timeout=15,
        )
        assert r.status_code == 401, r.text
        assert "token_invalid_or_expired" in r.text
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_malformed_token_returns_401():
    """Anything that isn't a valid JWT → 401 fail-closed."""
    r1 = requests.get(f"{API}/invoices/anything/full-magic",
                       params={"token": "faketoken"}, timeout=15)
    assert r1.status_code == 401, r1.text
    assert "token_invalid_or_expired" in r1.text

    # Missing token entirely → 401 with token_missing.
    r2 = requests.get(f"{API}/invoices/anything/full-magic", timeout=15)
    assert r2.status_code == 401, r2.text
    assert "token_missing" in r2.text

    # Valid JWT signature but wrong ``sub`` → 401.
    bad_sub = jwt.encode({
        "sub": "not_invoice_pay", "invoice_id": "x", "tenant_id": "x",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }, _JWT_SECRET, algorithm="HS256")
    r3 = requests.get(f"{API}/invoices/x/full-magic",
                       params={"token": bad_sub}, timeout=15)
    assert r3.status_code == 401, r3.text


def test_cross_tenant_token_cannot_view_other_tenant_invoice():
    """Token minted for tenant A used against tenant B's invoice id
    must NOT return tenant B's data. Because the aggregator is
    called with the TOKEN'S tenant_id (not the URL's), the lookup
    misses and returns 404 — not the cross-tenant payload."""
    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            inv_a, _ = await _seed_full_invoice_stack(db, TENANT_A_ID)
            inv_b, _ = await _seed_full_invoice_stack(db, TENANT_B_ID)
            return inv_a, inv_b
        finally:
            client.close()
    inv_a, inv_b = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        # Token minted for tenant A used on tenant B's invoice URL.
        # Verifier's ``token.invoice_id != iid`` guard fires first
        # → 401 token_invoice_mismatch (defence-in-depth).
        token_a = _mint_token(invoice_id=inv_a, tenant_id=TENANT_A_ID)
        r = requests.get(
            f"{API}/invoices/{inv_b}/full-magic",
            params={"token": token_a}, timeout=15,
        )
        assert r.status_code == 401, r.text
        assert "token_invoice_mismatch" in r.text

        # More insidious: attacker forges a token with tenant_A but
        # invoice_id = tenant_B's invoice (matching the URL). The
        # aggregator's lookup is scoped to the token's tenant_id, so
        # tenant B's invoice does NOT exist in tenant A → 404.
        forged = _mint_token(invoice_id=inv_b, tenant_id=TENANT_A_ID)
        r = requests.get(
            f"{API}/invoices/{inv_b}/full-magic",
            params={"token": forged}, timeout=15,
        )
        assert r.status_code == 404, r.text
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_deleted_invoice_rejected_404_per_aggregator_contract():
    """TEST-DRIFT · Feb-2026 — the aggregator ``_load_invoice`` now
    filters by ``deleted_at`` and 404s soft-deleted docs.  Previous
    version of this test asserted 200 and documented that the
    aggregator intentionally did NOT filter; ops has since tightened
    the contract to fail-closed on soft-deleted invoices.

    This flip is paired with the sibling
    ``test_invoice_viewer_load_invariants::test_load_invoice_rejects_soft_deleted_invoice``
    which asserts the same 404 contract from the aggregator side.
    Dunning + audit flows that previously relied on soft-deleted
    payload access must now use the authenticated ``/full`` endpoint
    with an admin token rather than the magic-link viewer."""
    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            return await _seed_full_invoice_stack(
                db, TENANT_A_ID, delete=True)
        finally:
            client.close()
    inv_id, _ = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        token = _mint_token(invoice_id=inv_id, tenant_id=TENANT_A_ID)
        r = requests.get(
            f"{API}/invoices/{inv_id}/full-magic",
            params={"token": token}, timeout=15,
        )
        # Fail-closed: soft-deleted invoice should NOT be viewable via
        # magic token.  See docstring for the paired aggregator-side
        # invariant test.
        assert r.status_code == 404, r.text
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())


def test_pay_link_builder_and_verifier_form_a_valid_round_trip():
    """The token minted by ``services.pay_link_builder.issue_invoice_magic_token``
    MUST verify cleanly through the endpoint. Guarantees the two
    modules stay in sync (they were originally two halves of the
    same deleted file)."""
    from services.pay_link_builder import issue_invoice_magic_token

    async def _seed():
        db, client = _fresh_db()
        try:
            await _cleanup(db)
            return await _seed_full_invoice_stack(db, TENANT_A_ID)
        finally:
            client.close()
    inv_id, _ = asyncio.get_event_loop().run_until_complete(_seed())

    try:
        token = issue_invoice_magic_token(inv_id, TENANT_A_ID)
        r = requests.get(
            f"{API}/invoices/{inv_id}/full-magic",
            params={"token": token}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["invoice_id"] == inv_id
    finally:
        async def _clean():
            db, client = _fresh_db()
            try:
                await _cleanup(db)
            finally:
                client.close()
        asyncio.get_event_loop().run_until_complete(_clean())
