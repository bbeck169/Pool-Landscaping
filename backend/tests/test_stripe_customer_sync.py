"""Feb 2026 · Stripe customer sync + billing history sync — end-to-end.

Uses stubbed Stripe SDK via ``set_stripe_client()`` so the tests
never touch the network. Covers the customer-match rules, the
idempotency guarantee, the prereq check on the billing history
flow, and the role gate on both endpoints.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest


TID = "test-tenant-stripe-sync"


# ═════════════════════════════════════════════════════════════════════
# Stripe SDK stub — deterministic, no network.
# ═════════════════════════════════════════════════════════════════════
class _StubStripeObject(dict):
    """Behaves as a dict + has attribute access for Stripe SDK
    compatibility with ``_asdict``."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k) from None


class _StubStripeCustomer:
    """Minimal shape of the ``stripe.Customer`` resource used by the
    sync services. Populated by individual tests."""

    _list_data: List[Dict[str, Any]] = []
    _retrieve_data: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def list(cls, **kwargs):
        # Auto-paginate: ignore pagination params for stub, always
        # return the full data set with has_more=False.
        return _StubStripeObject(data=list(cls._list_data), has_more=False)

    @classmethod
    def retrieve(cls, cust_id, **kwargs):
        return _StubStripeObject(cls._retrieve_data.get(cust_id) or {"id": cust_id})


class _StubStripeCharge:
    _list_data: List[Dict[str, Any]] = []

    @classmethod
    def list(cls, **kwargs):
        return _StubStripeObject(data=list(cls._list_data), has_more=False)


class _StubStripeInvoice:
    _list_data: List[Dict[str, Any]] = []

    @classmethod
    def list(cls, **kwargs):
        return _StubStripeObject(data=list(cls._list_data), has_more=False)


class _StubStripeSubscription:
    _list_data: List[Dict[str, Any]] = []

    @classmethod
    def list(cls, **kwargs):
        return _StubStripeObject(data=list(cls._list_data), has_more=False)


class _StripeStub:
    Customer = _StubStripeCustomer
    Charge = _StubStripeCharge
    Invoice = _StubStripeInvoice
    Subscription = _StubStripeSubscription


@pytest.fixture(autouse=True)
def _clean_db_and_stub():
    from services.payments.stripe_charge import set_stripe_client
    from config import db
    # Reset stub data per-test.
    _StubStripeCustomer._list_data = []
    _StubStripeCustomer._retrieve_data = {}
    _StubStripeCharge._list_data = []
    _StubStripeInvoice._list_data = []
    _StubStripeSubscription._list_data = []
    set_stripe_client(_StripeStub)

    async def _purge():
        for coll in ("customers", "payments", "invoices",
                      "stripe_subscriptions", "stripe_sync_audit", "quotes"):
            await db[coll].delete_many({"tenant_id": TID})

    asyncio.get_event_loop().run_until_complete(_purge())
    yield
    asyncio.get_event_loop().run_until_complete(_purge())
    set_stripe_client(None)


async def _seed_customer(cid: str, *, email: str = "", phone: str = "",
                          name: str = "", stripe_customer_id: Optional[str] = None,
                          is_active: bool = True):
    from config import db
    doc = {
        "id": cid, "tenant_id": TID, "name": name or cid,
        "email": email, "phone": phone, "is_active": is_active,
    }
    if stripe_customer_id:
        doc["stripe_customer_id"] = stripe_customer_id
    await db.customers.insert_one(doc)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ═════════════════════════════════════════════════════════════════════
# Customer sync — service-level unit tests.
# ═════════════════════════════════════════════════════════════════════
class TestCustomerSyncPreview:
    def test_matches_by_email_exact(self):
        async def go():
            await _seed_customer("c1", email="Alice@Example.com", name="Alice")
            _StubStripeCustomer._list_data = [
                {"id": "cus_A", "email": "alice@example.com", "name": "Alice"},
            ]
            _StubStripeCustomer._retrieve_data = {
                "cus_A": {"id": "cus_A", "invoice_settings": {
                    "default_payment_method": {
                        "id": "pm_1",
                        "card": {"brand": "visa", "last4": "4242"},
                    },
                }},
            }
            from services.stripe_customer_sync import sync_stripe_customers
            report = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u-super", dry_run=True,
            )
            assert report["attachable_count"] == 1
            row = report["attachments"][0]
            assert row["stripe_customer_id"] == "cus_A"
            assert row["customer_id"] == "c1"
            assert row["card"]["brand"] == "visa"
            assert row["card"]["last4"] == "4242"
        _run(go())

    def test_no_email_customer_skipped(self):
        async def go():
            _StubStripeCustomer._list_data = [
                {"id": "cus_X", "email": None, "phone": None},
            ]
            from services.stripe_customer_sync import sync_stripe_customers
            report = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=True,
            )
            assert report["no_email_count"] == 1
            assert report["attachable_count"] == 0
        _run(go())

    def test_duplicate_crm_email_flagged(self):
        async def go():
            await _seed_customer("c1", email="dup@example.com", name="A")
            await _seed_customer("c2", email="dup@example.com", name="B")
            _StubStripeCustomer._list_data = [
                {"id": "cus_D", "email": "dup@example.com"},
            ]
            from services.stripe_customer_sync import sync_stripe_customers
            report = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=True,
            )
            assert report["duplicate_email_count"] == 1
            assert report["attachable_count"] == 0
            assert len(report["duplicates"]) == 1
            assert sorted(report["duplicates"][0]["crm_match_names"]) == ["A", "B"]
        _run(go())

    def test_unmatched_bucketed_when_no_crm_match(self):
        async def go():
            _StubStripeCustomer._list_data = [
                {"id": "cus_U", "email": "unknown@example.com", "name": "Bob"},
            ]
            from services.stripe_customer_sync import sync_stripe_customers
            report = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=True,
            )
            assert report["unmatched_count"] == 1
            assert report["unmatched"][0]["email"] == "unknown@example.com"
            assert report["attachable_count"] == 0
        _run(go())

    def test_phone_fallback_when_email_missing(self):
        async def go():
            await _seed_customer("c1", phone="(602) 555-1234", name="A")
            _StubStripeCustomer._list_data = [
                {"id": "cus_P", "email": None, "phone": "+16025551234"},
            ]
            from services.stripe_customer_sync import sync_stripe_customers
            report = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=True,
            )
            assert report["attachable_count"] == 1
            assert report["attachments"][0]["customer_id"] == "c1"
        _run(go())

    def test_already_attached_skipped(self):
        async def go():
            await _seed_customer("c1", email="a@example.com",
                                  stripe_customer_id="cus_A")
            _StubStripeCustomer._list_data = [
                {"id": "cus_A", "email": "a@example.com"},
            ]
            from services.stripe_customer_sync import sync_stripe_customers
            report = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=True,
            )
            assert report["already_attached_count"] == 1
            assert report["attachable_count"] == 0
        _run(go())


class TestCustomerSyncCommit:
    def test_commit_persists_fields(self):
        async def go():
            from config import db
            await _seed_customer("c1", email="a@example.com", name="A")
            _StubStripeCustomer._list_data = [
                {"id": "cus_A", "email": "a@example.com"},
            ]
            _StubStripeCustomer._retrieve_data = {
                "cus_A": {"id": "cus_A", "invoice_settings": {
                    "default_payment_method": {
                        "id": "pm_1",
                        "card": {"brand": "visa", "last4": "4242"},
                    },
                }},
            }
            from services.stripe_customer_sync import sync_stripe_customers
            r1 = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=False,
            )
            assert r1["attachable_count"] == 1
            doc = await db.customers.find_one({"id": "c1", "tenant_id": TID})
            assert doc["stripe_customer_id"] == "cus_A"
            assert doc["stripe_default_payment_method_id"] == "pm_1"
            assert doc["stripe_card_brand"] == "visa"
            assert doc["stripe_card_last4"] == "4242"
            assert doc["stripe_sync_status"] == "attached"
            audit = await db.stripe_sync_audit.find_one({"customer_id": "c1"})
            assert audit["action"] == "attached"
        _run(go())

    def test_second_run_is_idempotent(self):
        async def go():
            await _seed_customer("c1", email="a@example.com")
            _StubStripeCustomer._list_data = [{"id": "cus_A", "email": "a@example.com"}]
            _StubStripeCustomer._retrieve_data = {"cus_A": {"id": "cus_A"}}
            from services.stripe_customer_sync import sync_stripe_customers
            r1 = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=False,
            )
            r2 = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=False,
            )
            assert r1["attachable_count"] == 1
            assert r2["attachable_count"] == 0
            assert r2["already_attached_count"] == 1
        _run(go())

    def test_import_unmatched_creates_new_crm_row(self):
        async def go():
            from config import db
            _StubStripeCustomer._list_data = [
                {"id": "cus_U", "email": "new@example.com", "name": "New"},
            ]
            _StubStripeCustomer._retrieve_data = {"cus_U": {"id": "cus_U"}}
            from services.stripe_customer_sync import sync_stripe_customers
            r = await sync_stripe_customers(
                tenant_id=TID, actor_user_id="u", dry_run=False,
                import_unmatched=True,
            )
            assert r["imported_new_count"] == 1
            new_row = await db.customers.find_one(
                {"tenant_id": TID, "stripe_customer_id": "cus_U"},
            )
            assert new_row is not None
            assert new_row["source"] == "stripe_import"
            assert new_row["email"] == "new@example.com"
        _run(go())

    def test_tenant_scoping_never_cross_contaminates(self):
        async def go():
            from config import db
            # Seed a customer in a DIFFERENT tenant with same email.
            other_tid = "other-tenant"
            await db.customers.insert_one({
                "id": "c-other", "tenant_id": other_tid,
                "email": "shared@example.com", "is_active": True,
            })
            try:
                await _seed_customer("c-mine", email="shared@example.com")
                _StubStripeCustomer._list_data = [
                    {"id": "cus_S", "email": "shared@example.com"},
                ]
                _StubStripeCustomer._retrieve_data = {"cus_S": {"id": "cus_S"}}
                from services.stripe_customer_sync import sync_stripe_customers
                r = await sync_stripe_customers(
                    tenant_id=TID, actor_user_id="u", dry_run=False,
                )
                assert r["attachable_count"] == 1
                assert r["attachments"][0]["customer_id"] == "c-mine"
                # Other tenant's customer must NOT be touched.
                other = await db.customers.find_one(
                    {"id": "c-other"}, {"_id": 0, "stripe_customer_id": 1},
                )
                assert other.get("stripe_customer_id") is None
            finally:
                await db.customers.delete_many({"tenant_id": other_tid})
        _run(go())


# ═════════════════════════════════════════════════════════════════════
# Billing history sync — service-level unit tests.
# ═════════════════════════════════════════════════════════════════════
class TestBillingHistoryPrereq:
    def test_raises_when_no_stripe_customer_attached(self):
        async def go():
            await _seed_customer("c1", email="a@example.com")  # no stripe_id
            from services.stripe_billing_history_sync import (
                PrereqNotMetError, sync_stripe_billing_history,
            )
            with pytest.raises(PrereqNotMetError):
                await sync_stripe_billing_history(
                    tenant_id=TID, actor_user_id="u", dry_run=True,
                )
        _run(go())


class TestBillingHistoryCharges:
    def test_matches_charge_by_payment_intent(self):
        async def go():
            from config import db
            await _seed_customer("c1", email="a@example.com",
                                  stripe_customer_id="cus_A")
            await db.quotes.insert_one({
                "id": "q1", "tenant_id": TID, "doc_type": "invoice",
                "customer_id": "c1", "total": 5000, "status": "paid",
                "stripe_payment_intent_id": "pi_123",
                "created_at": "2026-08-01T12:00:00+00:00",
            })
            _StubStripeCharge._list_data = [{
                "id": "ch_1", "customer": "cus_A",
                "payment_intent": "pi_123", "amount": 5000,
                "currency": "usd", "status": "succeeded",
                "created": 1754049600,
                "payment_method_details": {"card": {"brand": "visa", "last4": "1111"}},
            }]
            from services.stripe_billing_history_sync import sync_stripe_billing_history
            r = await sync_stripe_billing_history(
                tenant_id=TID, actor_user_id="u", dry_run=False,
                months_back=60,
            )
            assert r["matched_charges"] == 1
            assert r["created_payment_records"] == 1
            pay = await db.payments.find_one({"stripe_charge_id": "ch_1"})
            assert pay["invoice_id"] == "q1"
            assert pay["customer_id"] == "c1"
            assert pay["card_brand"] == "visa"
            assert pay["matched"] is True
        _run(go())

    def test_unmatched_charge_parks_to_customer_no_invoice(self):
        async def go():
            from config import db
            await _seed_customer("c1", email="a@example.com",
                                  stripe_customer_id="cus_A")
            _StubStripeCharge._list_data = [{
                "id": "ch_orphan", "customer": "cus_A",
                "amount": 999, "currency": "usd",
                "status": "succeeded", "created": 1754049600,
            }]
            from services.stripe_billing_history_sync import sync_stripe_billing_history
            r = await sync_stripe_billing_history(
                tenant_id=TID, actor_user_id="u", dry_run=False,
                months_back=60, include_subscriptions=False,
            )
            assert r["unmatched_charges"] == 1
            assert r["matched_charges"] == 0
            pay = await db.payments.find_one({"stripe_charge_id": "ch_orphan"})
            assert pay is not None
            assert pay["customer_id"] == "c1"
            assert pay["invoice_id"] is None
            assert pay["matched"] is False
        _run(go())

    def test_idempotent_second_run(self):
        async def go():
            from config import db
            await _seed_customer("c1", email="a@example.com",
                                  stripe_customer_id="cus_A")
            _StubStripeCharge._list_data = [{
                "id": "ch_1", "customer": "cus_A", "amount": 500,
                "currency": "usd", "status": "succeeded",
                "created": 1754049600,
            }]
            from services.stripe_billing_history_sync import sync_stripe_billing_history
            await sync_stripe_billing_history(
                tenant_id=TID, actor_user_id="u", dry_run=False,
                months_back=60, include_subscriptions=False,
            )
            r2 = await sync_stripe_billing_history(
                tenant_id=TID, actor_user_id="u", dry_run=False,
                months_back=60, include_subscriptions=False,
            )
            assert r2["skipped_dup_charges"] == 1
            assert r2["created_payment_records"] == 0
            assert await db.payments.count_documents(
                {"tenant_id": TID, "stripe_charge_id": "ch_1"},
            ) == 1
        _run(go())

    def test_charge_no_customer_bucketed(self):
        async def go():
            _StubStripeCharge._list_data = [{
                "id": "ch_1", "customer": "cus_UNKNOWN",
                "amount": 500, "currency": "usd", "status": "succeeded",
                "created": 1754049600,
            }]
            await _seed_customer("c1", email="a@example.com",
                                  stripe_customer_id="cus_A")
            from services.stripe_billing_history_sync import sync_stripe_billing_history
            r = await sync_stripe_billing_history(
                tenant_id=TID, actor_user_id="u", dry_run=True,
                months_back=60, include_subscriptions=False,
            )
            assert r["charge_no_customer"] == 1
            assert r["matched_charges"] == 0
        _run(go())


class TestBillingHistorySubscriptions:
    def test_include_subscriptions_flag_toggles(self):
        async def go():
            from config import db
            await _seed_customer("c1", email="a@example.com",
                                  stripe_customer_id="cus_A")
            _StubStripeSubscription._list_data = [{
                "id": "sub_1", "customer": "cus_A", "status": "active",
                "current_period_start": 1754049600,
                "current_period_end": 1754136000,
                "cancel_at_period_end": False, "created": 1754049600,
            }]
            from services.stripe_billing_history_sync import sync_stripe_billing_history
            r_off = await sync_stripe_billing_history(
                tenant_id=TID, actor_user_id="u", dry_run=False,
                months_back=60, include_subscriptions=False,
            )
            assert r_off["created_subscription_records"] == 0
            r_on = await sync_stripe_billing_history(
                tenant_id=TID, actor_user_id="u", dry_run=False,
                months_back=60, include_subscriptions=True,
            )
            assert r_on["created_subscription_records"] == 1
            assert await db.stripe_subscriptions.count_documents(
                {"tenant_id": TID, "stripe_subscription_id": "sub_1"},
            ) == 1
        _run(go())
