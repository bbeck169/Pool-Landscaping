"""Phase P30 · Feb-2026 — Stripe Checkout Session (mode=setup)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests._f7_loop_fixture import run_test


class _StubStripe:
    """Stub Stripe SDK — swapped in via ``set_stripe_client``."""
    def __init__(self):
        self.checkout = MagicMock()
        self.checkout.Session = MagicMock()
        self.checkout.Session.create = MagicMock()
        self.Customer = MagicMock()
        self.Customer.create = MagicMock()
        # These are set by _init_api_key on the real SDK — noop here.
        self.api_key = None
        self.api_version = None


@pytest.fixture(autouse=True)
def _stripe_stub(monkeypatch):
    from services.payments import stripe_charge
    stub = _StubStripe()
    stripe_charge.set_stripe_client(stub)
    yield stub
    stripe_charge.set_stripe_client(None)


def test_p30_create_card_setup_checkout_session_returns_stripe_url(
    _stripe_stub,
):
    from services.payments.stripe_charge import (
        create_card_setup_checkout_session,
    )
    _stripe_stub.checkout.Session.create.return_value = {
        "id": "cs_test_setup_abc",
        "url": "https://checkout.stripe.com/c/pay/cs_test_setup_abc",
        "mode": "setup",
    }

    async def _go(db):
        url = await create_card_setup_checkout_session(
            customer_id="cust-1", tenant_id="tenant-A",
            stripe_customer_id="cus_stripe_xyz",
            success_url="https://app.plofv.com/portal/setup-success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://app.plofv.com/portal/setup-cancelled",
        )
        assert url == "https://checkout.stripe.com/c/pay/cs_test_setup_abc"

        # Assert call args.
        assert _stripe_stub.checkout.Session.create.call_count == 1
        kwargs = _stripe_stub.checkout.Session.create.call_args.kwargs
        assert kwargs["mode"] == "setup"
        assert kwargs["payment_method_types"] == ["card"]
        assert kwargs["customer"] == "cus_stripe_xyz"
        assert kwargs["success_url"].endswith(
            "?session_id={CHECKOUT_SESSION_ID}"
        )
        # ``{CHECKOUT_SESSION_ID}`` is a Stripe-side placeholder — must
        # be a LITERAL substring in the URL we send, not expanded.
        assert "{CHECKOUT_SESSION_ID}" in kwargs["success_url"]
        assert kwargs["cancel_url"] == (
            "https://app.plofv.com/portal/setup-cancelled"
        )

    run_test(_go)


def test_p30_metadata_carries_source_flow_tenant_and_customer(_stripe_stub):
    """Every P30 session MUST carry these four canonical metadata
    keys. ``source == "card_add_setup"`` is the webhook filter key —
    the checkout.session.completed branch in ``handle_webhook_event``
    gates on it."""
    from services.payments.stripe_charge import (
        create_card_setup_checkout_session,
    )
    _stripe_stub.checkout.Session.create.return_value = {
        "url": "https://checkout.stripe.com/c/ok", "id": "cs_ok",
    }

    async def _go(db):
        await create_card_setup_checkout_session(
            customer_id="cust-9", tenant_id="tenant-Q",
            stripe_customer_id="cus_stripe_q",
            success_url="https://x/success",
            metadata={"trigger_source": "unit_test",
                       "arbitrary_extra": "keep-me"},
        )
        kwargs = _stripe_stub.checkout.Session.create.call_args.kwargs
        m = kwargs["metadata"]
        # Canonical P30 keys.
        assert m["source"] == "card_add_setup"
        assert m["flow"] == "card_on_file_add"
        assert m["crm_tenant_id"] == "tenant-Q"
        assert m["crm_customer_id"] == "cust-9"
        # Caller-provided extras survive the merge.
        assert m["trigger_source"] == "unit_test"
        assert m["arbitrary_extra"] == "keep-me"

    run_test(_go)


def test_p30_caller_cannot_override_canonical_source_key(_stripe_stub):
    """A caller that passes ``metadata={"source": "spoofed"}`` MUST
    NOT be able to break the webhook filter. The helper overwrites
    the four canonical keys AFTER the merge."""
    from services.payments.stripe_charge import (
        create_card_setup_checkout_session,
    )
    _stripe_stub.checkout.Session.create.return_value = {
        "url": "https://x/ok", "id": "cs_ok",
    }

    async def _go(db):
        await create_card_setup_checkout_session(
            customer_id="c", tenant_id="t",
            stripe_customer_id="cus_x",
            success_url="https://x/success",
            metadata={"source": "spoofed",
                       "crm_tenant_id": "hijacked",
                       "flow": "spoofed"},
        )
        m = _stripe_stub.checkout.Session.create.call_args.kwargs["metadata"]
        assert m["source"] == "card_add_setup"
        assert m["crm_tenant_id"] == "t"
        assert m["flow"] == "card_on_file_add"

    run_test(_go)


def test_p30_missing_stripe_customer_id_raises_value_error(_stripe_stub):
    """No auto-create inside the checkout session helper — caller
    must have ensured the customer via ``ensure_stripe_customer``.
    Silently minting here would create untraceable orphans."""
    from services.payments.stripe_charge import (
        create_card_setup_checkout_session,
    )

    async def _go(db):
        with pytest.raises(ValueError) as exc_info:
            await create_card_setup_checkout_session(
                customer_id="c", tenant_id="t",
                stripe_customer_id="",   # empty
                success_url="https://x/success",
            )
        assert "stripe_customer_id required" in str(exc_info.value)
        # And no Stripe API call fired.
        assert _stripe_stub.checkout.Session.create.call_count == 0

    run_test(_go)


def test_p30_success_url_contains_stripe_placeholder(_stripe_stub):
    """A regression that URL-encoded or dropped ``{CHECKOUT_SESSION_ID}``
    would silently break the success-page confirmation. This test
    locks the literal-brace form."""
    from services.payments.stripe_charge import (
        create_card_setup_checkout_session,
    )
    _stripe_stub.checkout.Session.create.return_value = {
        "url": "https://x", "id": "cs",
    }

    async def _go(db):
        await create_card_setup_checkout_session(
            customer_id="c", tenant_id="t",
            stripe_customer_id="cus_x",
            success_url="https://app.plofv.com/portal/setup-success?session_id={CHECKOUT_SESSION_ID}",
        )
        kwargs = _stripe_stub.checkout.Session.create.call_args.kwargs
        assert "{CHECKOUT_SESSION_ID}" in kwargs["success_url"]
        # Not URL-encoded.
        assert "%7BCHECKOUT_SESSION_ID%7D" not in kwargs["success_url"]

    run_test(_go)


def test_p30_stripe_url_missing_raises_runtime_error(_stripe_stub):
    """A Stripe SDK bug that returns a session without a URL would
    silently ship a broken link. Assert we 500 instead."""
    from services.payments.stripe_charge import (
        create_card_setup_checkout_session,
    )
    _stripe_stub.checkout.Session.create.return_value = {"id": "cs_no_url"}

    async def _go(db):
        with pytest.raises(RuntimeError) as exc_info:
            await create_card_setup_checkout_session(
                customer_id="c", tenant_id="t",
                stripe_customer_id="cus_x",
                success_url="https://x/success",
            )
        assert "without a URL" in str(exc_info.value)

    run_test(_go)


def test_p30_legacy_alias_still_points_at_new_helper():
    """Guardrail — the legacy ``create_setup_checkout_session`` name
    remains as an alias for the migration window. A future refactor
    that removes it MUST update every caller first."""
    from services.payments import stripe_charge
    assert (stripe_charge.create_setup_checkout_session
             is stripe_charge.create_card_setup_checkout_session)


def test_p30_ensure_stripe_customer_returns_existing_id(_stripe_stub):
    """``ensure_stripe_customer`` short-circuits when the CRM row
    already has a ``stripe_customer_id``. Stripe API is NOT
    invoked."""
    from services.payments.stripe_charge import ensure_stripe_customer

    async def _go(db):
        tenant_id = "p30_ensure_t"
        cid = "p30_ensure_c"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tenant_id,
            "name": "Existing", "email": "existing@p30.test",
            "stripe_customer_id": "cus_existing_abc",
        })
        try:
            got = await ensure_stripe_customer(
                tenant_id=tenant_id, customer_id=cid,
            )
            assert got == "cus_existing_abc"
            assert _stripe_stub.Customer.create.call_count == 0
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)


def test_p30_ensure_stripe_customer_mints_and_persists_on_missing(
    _stripe_stub,
):
    """No existing id → ``Customer.create`` fires and the resulting
    id is persisted on ``customers.stripe_customer_id``."""
    from services.payments.stripe_charge import ensure_stripe_customer
    _stripe_stub.Customer.create.return_value = {"id": "cus_fresh_xyz"}

    async def _go(db):
        tenant_id = "p30_mint_t"
        cid = "p30_mint_c"
        await db.customers.insert_one({
            "id": cid, "tenant_id": tenant_id,
            "name": "Fresh", "email": "fresh@p30.test",
        })
        try:
            got = await ensure_stripe_customer(
                tenant_id=tenant_id, customer_id=cid,
            )
            assert got == "cus_fresh_xyz"
            assert _stripe_stub.Customer.create.call_count == 1
            row = await db.customers.find_one(
                {"id": cid, "tenant_id": tenant_id},
                {"_id": 0, "stripe_customer_id": 1},
            )
            assert row["stripe_customer_id"] == "cus_fresh_xyz"
        finally:
            await db.customers.delete_one({"id": cid})

    run_test(_go)
