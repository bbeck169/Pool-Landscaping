"""Phase 47d · Feb-2026 — Mobile quote pay + ACH restoration.

Covers:
    * Mobile `POST /payments/admin/generate-link/{id}` (which never
      existed) → replaced by direct call to Phase-47's
      `POST /invoices/{id}/request-payment-link`. Backend contract
      unchanged; this file audits that the reused endpoint returns the
      `payment_url` key mobile expects.
    * `POST /quotes/{qid}/pay` audit — confirm it's still a manual /
      offline recording endpoint with zero Stripe interaction.
    * ACH endpoints restored to Stripe direct: link-session returns a
      SetupIntent client_secret; attach persists the PM.
"""
from __future__ import annotations
from unittest.mock import AsyncMock, patch


# ── /quotes/{qid}/pay audit — no Stripe / Lumino / Zapier ────────────
def test_quotes_pay_endpoint_is_manual_offline_only():
    import inspect
    from routers import quotes as router_mod
    src = inspect.getsource(router_mod.pay_quote).lower()
    # Must not call Stripe.
    assert "stripe" not in src, "quotes.pay must remain manual/offline only"
    assert "checkout" not in src
    assert "zapier" not in src
    assert "lumino" not in src
    assert "dispatch_invoice_link_request" not in src
    # Must set payment_method="manual".
    assert '"manual"' in src or "'manual'" in src


# ── Mobile quote-pay uses the Phase-47 direct-Stripe route ──────────
def test_mobile_quote_pay_calls_phase47_endpoint_not_stale_route():
    from pathlib import Path
    import re as _re
    p = Path(__file__).resolve().parents[2] / "mobile" / "app" / "quote" / "[id].tsx"
    src = p.read_text()
    # Strip comments before scanning — the migration comment names the
    # mythical endpoint on purpose so future maintainers understand the
    # swap. We only care about RUNTIME code references.
    code_only = _re.sub(r'//.*$', '', src, flags=_re.MULTILINE)
    code_only = _re.sub(r'/\*[\s\S]*?\*/', '', code_only)
    # Regression guard against the 404-returning mythical endpoint.
    assert "/payments/admin/generate-link/" not in code_only, \
        "mobile must not call the mythical generate-link endpoint at runtime"
    # Must instead call the Phase-47 direct-Stripe route.
    assert "/invoices/${id}/request-payment-link" in code_only or \
           "/invoices/{id}/request-payment-link" in code_only
    # No Lumino / Zapier references in the mobile pay path.
    for pat in ("lumino", "zapier", "dispatch_invoice_link_request"):
        assert pat not in code_only.lower(), \
            f"mobile quote pay must not reference {pat!r}"


# ── ACH restoration ──────────────────────────────────────────────────
def test_stripe_configured_reads_env(monkeypatch):
    from routers import customer_portal as cp
    for k in ("STRIPE_SECRET_KEY_LIVE", "STRIPE_SECRET_KEY_TEST", "STRIPE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert cp._stripe_configured() is False
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_x")
    assert cp._stripe_configured() is True


def test_ach_link_session_returns_stripe_not_configured_when_key_missing(monkeypatch):
    """When no Stripe key is set, the endpoint must short-circuit with
    ``ok=False, reason="stripe_not_configured"`` so the frontend
    renders its disabled-state UX rather than a hard 5xx."""
    for k in ("STRIPE_SECRET_KEY_LIVE", "STRIPE_SECRET_KEY_TEST", "STRIPE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    from routers import customer_portal as cp
    import inspect
    # Static guard — the endpoint body must reference _stripe_configured
    # and the "stripe_not_configured" short-circuit.
    src = inspect.getsource(cp.start_ach_link_session)
    assert "_stripe_configured" in src
    assert "stripe_not_configured" in src
    # And when configured, must delegate to create_setup_intent with
    # payment_method_types=["us_bank_account"].
    assert 'payment_method_types=["us_bank_account"]' in src


def test_ach_attach_delegates_to_shared_helper():
    """The attach endpoint must route through
    services.payments.stripe_charge.attach_payment_method (same helper
    the card-attach flow uses) so /payment-methods lists a unified
    view."""
    import inspect
    from routers import customer_portal as cp
    src = inspect.getsource(cp.attach_ach_result)
    assert "stripe_svc.attach_payment_method" in src
    assert 'raise HTTPException(422, "payment_method_id required")' in src
    # Set_default stays False for ACH (admin-controlled).
    assert "set_default=False" in src


def test_ach_attach_payload_shape_updated_for_phase47d():
    """The `AchAttachIn` model must require ``payment_method_id`` (Phase
    47d Stripe-direct shape) but keep the LZ4 fields as optional
    back-compat aliases."""
    from routers.customer_portal import AchAttachIn
    m = AchAttachIn(payment_method_id="pm_1234")
    assert m.payment_method_id == "pm_1234"
    assert m.stripe_bank_account_id is None
    assert m.session_id is None


# ── Regression: request-payment-link still returns payment_url ──────
def test_phase47_endpoint_response_key_unchanged():
    """Mobile (Phase 47d) and web (Phase 47) both destructure
    ``payment_url`` off the response. Guard against a rename."""
    import inspect
    from services.payments import stripe_charge as sc
    src = inspect.getsource(sc.create_invoice_checkout_session)
    assert '"payment_url"' in src


# ── Lumino / Zapier stay dark on the pay path ───────────────────────
def test_no_lumino_dispatcher_reference_in_pay_router():
    import inspect
    from routers import lumino_link_request as router_mod
    src = inspect.getsource(router_mod.request_payment_link)
    # Strip the docstring first — it explains the migration.
    import re
    body = re.sub(r'"""[\s\S]*?"""', "", src, count=1).lower()
    assert "dispatch_invoice_link_request" not in body
    assert "zapier" not in body
