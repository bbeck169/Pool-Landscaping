"""TD-sms-reminder-use-balance-not-total · Feb-2026.

Pins the ``invoice_past_due_7d`` reminder bodies on both channels
(email + SMS) to render the OUTSTANDING BALANCE rather than the
stale invoice total, and the merge-tag registry to resolve
``INVOICE_BALANCE`` as ``total − amount_paid``.

Scope (deliberately narrow — see the sibling TECH_DEBT follow-up
candidates for the other reminder surfaces):

* ``services/marketing/merge_tags.py`` — new ``_invoice_balance``
  resolver + ``INVOICE_BALANCE`` ``TOKEN_REGISTRY`` row.
* ``services/migrations/seed_system_templates.py`` — ``email_template``
  and ``sms_template`` bodies for ``invoice_past_due_7d`` swap
  ``{{INVOICE_TOTAL}}`` → ``{{INVOICE_BALANCE}}``.

The existing ``INVOICE_TOTAL`` resolver + token entry are
preserved verbatim — other templates still rely on it.
"""
from __future__ import annotations

from services.marketing.merge_tags import (
    _invoice_balance,
    _invoice_total,
    MERGE_TAGS,
    render_context,
    render_template,
)
from services.migrations.seed_system_templates import _build_templates


# ═══════════════════════════════════════════════════════════════════
# 1 · ``_invoice_balance`` resolver semantics
# ═══════════════════════════════════════════════════════════════════

def test_invoice_balance_subtracts_amount_paid_from_total():
    """Operator-brief fixture: total=100, applied=30 → '$70.00'."""
    ctx = render_context(invoice={"total": 100, "amount_paid": 30})
    assert _invoice_balance(ctx) == "$70.00"


def test_invoice_balance_unpaid_renders_same_as_total():
    """No ``amount_paid`` on the doc → balance == total (parity with
    the legacy ``INVOICE_TOTAL`` resolver for fresh unpaid rows)."""
    ctx = render_context(invoice={"total": 250})
    assert _invoice_balance(ctx) == "$250.00"
    assert _invoice_total(ctx) == "$250.00"


def test_invoice_balance_fully_paid_renders_zero():
    """Benign no-stale-render outcome when the invoice flips to
    ``paid`` between enqueue and render — reminder body shows
    ``$0.00`` rather than the stale pre-payment total."""
    ctx = render_context(invoice={"total": 100, "amount_paid": 100})
    assert _invoice_balance(ctx) == "$0.00"


def test_invoice_balance_formats_thousands_separator_and_two_decimals():
    ctx = render_context(invoice={"total": 1234.5, "amount_paid": 0})
    assert _invoice_balance(ctx) == "$1,234.50"


def test_invoice_balance_handles_missing_invoice_gracefully():
    """No ``invoice`` key in ctx → ``$0.00`` (defensive default)."""
    assert _invoice_balance({}) == "$0.00"


def test_invoice_balance_handles_bad_numeric_input_gracefully():
    """Non-numeric ``total`` / ``amount_paid`` → ``$0.00``."""
    ctx = render_context(invoice={"total": "oops", "amount_paid": 5})
    assert _invoice_balance(ctx) == "$0.00"


# ═══════════════════════════════════════════════════════════════════
# 2 · Merge-tag registry entry + end-to-end rendering
# ═══════════════════════════════════════════════════════════════════

def test_invoice_balance_token_registered_in_merge_tags():
    tokens = {t["token"] for t in MERGE_TAGS}
    assert "INVOICE_BALANCE" in tokens


def test_invoice_total_token_still_registered_regression():
    """Guardrail: the swap must not remove ``INVOICE_TOTAL`` — other
    templates and tenant customisations may still reference it."""
    tokens = {t["token"] for t in MERGE_TAGS}
    assert "INVOICE_TOTAL" in tokens


def test_invoice_balance_renders_through_render_template():
    ctx = render_context(invoice={"total": 100, "amount_paid": 30})
    out, _ = render_template(
        "You owe {{INVOICE_BALANCE}} on this invoice.", ctx,
    )
    assert out == "You owe $70.00 on this invoice."


# ═══════════════════════════════════════════════════════════════════
# 3 · ``invoice_past_due_7d`` seed body — both channels
# ═══════════════════════════════════════════════════════════════════

def _past_due_tpl():
    tpls = _build_templates("en")
    return next(t for t in tpls
                if t["system_template_id"] == "invoice_past_due_7d")


def test_past_due_sms_body_uses_invoice_balance():
    body = _past_due_tpl()["sms_template"]["body"]
    assert "{{INVOICE_BALANCE}}" in body
    assert "{{INVOICE_TOTAL}}" not in body


def test_past_due_email_body_uses_invoice_balance():
    body = _past_due_tpl()["email_template"]["body"]
    assert "{{INVOICE_BALANCE}}" in body
    assert "{{INVOICE_TOTAL}}" not in body


def test_past_due_sms_body_renders_balance_for_partial_payment():
    """End-to-end: render the shipped SMS body against an invoice
    with total=100 / amount_paid=30 and confirm the balance ($70.00)
    appears in place of the former total."""
    sms_body = _past_due_tpl()["sms_template"]["body"]
    ctx = render_context(
        customer={"first_name": "Ada"},
        tenant={"name": "ACME Pools"},
        invoice={
            "total": 100,
            "amount_paid": 30,
            "invoice_number": "INV-01",
        },
    )
    out, _ = render_template(sms_body, ctx)
    assert "$70.00" in out
    assert "$100.00" not in out


def test_past_due_email_body_renders_balance_for_partial_payment():
    email_body = _past_due_tpl()["email_template"]["body"]
    ctx = render_context(
        customer={"first_name": "Ada"},
        tenant={"name": "ACME Pools"},
        invoice={
            "total": 100,
            "amount_paid": 30,
            "invoice_number": "INV-01",
        },
    )
    out, _ = render_template(email_body, ctx)
    assert "$70.00" in out
    assert "$100.00" not in out


# ═══════════════════════════════════════════════════════════════════
# 4 · Sibling reminder surface — ``invoice_reminder_email`` seed.
#     Was a "scope-guard still-uses-total" bookmark at
#     ``38670451f`` ship time; flipped positive at
#     ``TD-invoice-reminder-email-seed-balance`` close-out.  The
#     sibling seed now also uses ``{{INVOICE_BALANCE}}`` with the
#     ``_invoice_balance`` resolver wired through the emailer's
#     render context (``emailer.py:695`` passes ``"invoice": inv``).
# ═══════════════════════════════════════════════════════════════════

def test_sibling_email_reminder_seed_uses_invoice_balance():
    """The ``invoice_reminder_email`` seed body renders the
    outstanding balance (``total − amount_paid``) via the
    ``{{INVOICE_BALANCE}}`` merge-tag.  Flipped from the
    pre-TD-invoice-reminder-email-seed-balance bookmark that
    asserted the drift still existed.  Keeps a bit of coverage on
    the sibling file so a future ``INVOICE_BALANCE`` → stale-swap
    regression trips here immediately."""
    from migrations.seed_invoice_reminder_template import BODY_DEFAULT
    assert "{{INVOICE_BALANCE}}" in BODY_DEFAULT
    assert "{{INVOICE_TOTAL}}" not in BODY_DEFAULT
