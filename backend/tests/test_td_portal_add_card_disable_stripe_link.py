"""TD-portal-add-card-disable-stripe-link · Feb-2026 — BE regression.

Guards the single BE change in Phase 2 D4:

  ``services.payments.stripe_charge.create_invoice_checkout_session``
  must pass ``payment_method_types=["card"]`` into the
  ``stripe.checkout.Session.create`` kwargs so the hosted Checkout
  surface does NOT auto-advertise Stripe Link / Apple Pay / Google Pay
  on the invoice pay-now flow.

Rationale (full write-up in
``memory/td_portal_add_card_disable_stripe_link_phase0_recon.md``
section 4 Option C): hosted Checkout defaults to every payment method
enabled on the Stripe Dashboard. The admin-impersonation / shared-
browser Link cross-contamination risk documented on the FE Elements
surfaces also applies here — Link is detected via a Stripe-domain
cookie, not the application's authenticated user.

Source-inspection pattern (``inspect.getsource`` + string match)
matches the existing ``test_phase47_direct_stripe_payment_link.py``
guard shape; no Stripe mocks required.
"""
from __future__ import annotations

import inspect
import re


def _get_body() -> str:
    from services.payments import stripe_charge as sc
    src = inspect.getsource(sc.create_invoice_checkout_session)
    # Strip docstring so we only grep runtime body.
    return re.sub(r'"""[\s\S]*?"""', "", src, count=1)


def test_session_kwargs_set_payment_method_types_card_only() -> None:
    body = _get_body()
    # Must appear inside the session_kwargs dict literal — regex
    # tolerates whitespace / trailing comma variants.
    assert re.search(
        r'"payment_method_types"\s*:\s*\[\s*"card"\s*,?\s*\]',
        body,
    ), (
        "create_invoice_checkout_session must pass "
        'payment_method_types=["card"] into checkout.Session.create '
        "so hosted Checkout does not auto-enable Stripe Link / "
        "Apple Pay / Google Pay. See TD-portal-add-card-disable-"
        "stripe-link Phase 2 D4."
    )


def test_ticket_reference_present() -> None:
    body = _get_body()
    assert "TD-portal-add-card-disable-stripe-link" in body, (
        "Ticket reference missing — the TD-portal-add-card-disable-"
        "stripe-link comment that documents WHY payment_method_types "
        "is forced to card-only must stay next to the kwarg so a "
        "future refactor does not silently drop it."
    )


def test_payment_intent_data_still_present() -> None:
    """Regression: the Phase 2 D4 edit MUST NOT dislodge the
    payment_intent_data metadata that the webhook reconcile path
    depends on.  Belt-and-braces around a single-concern commit.
    """
    body = _get_body()
    assert '"payment_intent_data"' in body
    assert '"client_reference_id"' in body
    assert '"line_items"' in body
    assert '"success_url"' in body
    assert '"cancel_url"' in body


def test_return_contract_unchanged() -> None:
    """D4 is kwargs-only; the response shape must stay as the FE
    PaymentForm.jsx expects (``payment_url`` + ``checkout_session_id``).
    """
    from services.payments import stripe_charge as sc
    src = inspect.getsource(sc.create_invoice_checkout_session)
    assert '"payment_url"' in src
    assert '"checkout_session_id"' in src
