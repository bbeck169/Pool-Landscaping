"""TD-invoice-reminder-email-seed-balance · Feb-2026 · Phase 1 pytest.

End-to-end verification that the sibling ``invoice_reminder_email``
seed template now renders the OUTSTANDING BALANCE (``total −
amount_paid``) rather than the stale pre-ship figure.

Operator-brief fixture: invoice ``total=100``, ``amount_paid=30``
→ rendered body contains ``70.00``, NOT ``100.00``.

Pre-ship latent-correct-via-accident note
-----------------------------------------
Before this ticket shipped, the seed body copy read "outstanding
balance of ``${{INVOICE_TOTAL}}``" + the shipped emailer at
``emailer.py:695`` stuffed the balance figure into the flat
``ctx["invoice_total"]`` string.  The dual-registry drift at
``services/marketing/merge_tags.py:2076`` (where ``INVOICE_TOTAL``
was registered a second time with label "Invoice — Balance" and a
resolver that reads ``ctx["invoice_total"]`` as a flat string)
made the old placeholder resolve to the balance value.  The seed
body said "balance" and rendered the balance correctly — not
because of a correct wiring, but because of a quirk two layers
down.

That latent-correct-via-accident path survives for OTHER callers
of ``INVOICE_TOTAL`` as long as the dual-registry drift exists
(it is explicitly scoped-out of this ticket; see
``TD-invoice-total-dual-registry-drift``).  This ticket re-aligns
the seed by naming the behavior it intends: ``INVOICE_BALANCE``
with a resolver that reads ``invoice.total − invoice.amount_paid``
directly from the invoice doc the emailer now also threads into
ctx under ``"invoice"``.
"""
from __future__ import annotations

from migrations.seed_invoice_reminder_template import (
    BODY_DEFAULT,
    MERGE_TAGS,
)
from services.marketing.merge_tags import render_context, render_template


# ═══════════════════════════════════════════════════════════════════
# Seed-level assertions
# ═══════════════════════════════════════════════════════════════════

def test_body_uses_invoice_balance_not_invoice_total():
    assert "{{INVOICE_BALANCE}}" in BODY_DEFAULT
    assert "{{INVOICE_TOTAL}}" not in BODY_DEFAULT


def test_body_copy_still_reads_outstanding_balance():
    """Body copy semantic preserved — the operator-facing phrase
    "outstanding balance" was correct even in the latent-via-
    accident era."""
    assert "outstanding" in BODY_DEFAULT
    assert "balance" in BODY_DEFAULT


def test_merge_tags_list_declares_invoice_balance():
    assert "INVOICE_BALANCE" in MERGE_TAGS
    assert "INVOICE_TOTAL" not in MERGE_TAGS


# ═══════════════════════════════════════════════════════════════════
# End-to-end render through the shared ``render_template``
# ═══════════════════════════════════════════════════════════════════

def _ctx_with_invoice(total: float, amount_paid: float):
    """Mirrors the ctx shape the shipped emailer passes at
    ``emailer.py:695`` after the TD-invoice-reminder-email-seed-
    balance ctx fix — includes the full invoice doc under
    ``"invoice"`` so the ``_invoice_balance`` resolver sees
    the fields it needs."""
    return render_context(
        tenant={"name": "ACME Pools"},
        customer={"name": "Ada Lovelace"},
        invoice={
            "invoice_number": "INV-7",
            "total": total,
            "amount_paid": amount_paid,
            "due_date": "2026-02-28",
        },
        customer_name="Ada",
        invoice_number="INV-7",
        invoice_due_date="2026-02-28",
        pay_link="https://pay.example/x",
    )


def test_rendered_body_shows_balance_for_partial_payment():
    """Operator-brief fixture: ``total=100``, ``amount_paid=30`` →
    rendered body contains ``70.00``, NOT ``100.00``."""
    ctx = _ctx_with_invoice(total=100, amount_paid=30)
    out, _ = render_template(BODY_DEFAULT, ctx)
    assert "70.00" in out
    assert "100.00" not in out


def test_rendered_body_shows_total_when_no_payments_applied():
    """Fresh invoice with no payments applied → balance == total."""
    ctx = _ctx_with_invoice(total=850, amount_paid=0)
    out, _ = render_template(BODY_DEFAULT, ctx)
    assert "850.00" in out


def test_rendered_body_shows_zero_when_fully_paid():
    """Benign no-stale-render outcome if the invoice flipped to
    ``paid`` between enqueue and render — reminder reads
    ``$0.00`` rather than the stale pre-payment total."""
    ctx = _ctx_with_invoice(total=100, amount_paid=100)
    out, _ = render_template(BODY_DEFAULT, ctx)
    assert "0.00" in out
    assert "100.00" not in out


def test_rendered_body_keeps_other_tokens_resolving():
    """Guardrail — the swap must not break the surrounding
    placeholders (``INVOICE_NUMBER``, ``INVOICE_DUE_DATE``,
    ``PAY_LINK``, ``CUSTOMER_NAME``)."""
    ctx = _ctx_with_invoice(total=100, amount_paid=30)
    out, _ = render_template(BODY_DEFAULT, ctx)
    assert "INV-7" in out
    assert "2026-02-28" in out
    assert "https://pay.example/x" in out
    assert "Ada" in out
