# TD-sms-reminder-use-balance-not-total · follow-up (P3)

**Parent:** `TD-bulk-send-invoice-email-reuse-individual-send-template`
(shipped as a sibling of this doc).

## Gap

`backend/routers/invoices_bulk_send.py::_send_single_invoice` builds the
SMS body as:

```python
sms_body = (
    f"{ctx['tenant_name']}: invoice {ctx['invoice_number']} "
    f"(${ctx['invoice_total']}) ready. Pay: {ctx['payment_link']}"
)
```

`ctx['invoice_total']` resolves to `invoice.total` (not `balance`). For a
partially-paid invoice, this says "invoice $100" even when $40 was
already collected — the customer sees the gross amount, not the
outstanding balance.

The dunning-side `_send_sms` reminder (`routers/dunning.py::_send_reminder`)
has the same drift — both share `_build_context`.

## Why P3

- Cosmetic drift, not a correctness bug — the customer still pays
  via the `payment_link` which routes to the pay-sheet that shows
  the correct balance.
- Operator did not flag it in Ticket N's framing.
- Email template (Ticket N canonical renderer) already uses the
  correct `balance` via `t_email_body("...body", balance=f"{balance:,.2f}")`
  — the drift is SMS-only.

## Fix shape

Two options:

**Option A — fix `_build_context`:** replace `invoice_total` key with
`balance` (or add `balance` alongside and migrate callers). Impacts
EVERY `_build_context` consumer (dunning + bulk-send SMS build +
other sites). Needs an audit of all consumers to confirm none
depend on the gross-total value.

**Option B — scoped fix at the SMS build sites:** compute `balance`
locally in `invoices_bulk_send.py` + `routers/dunning.py::_send_reminder`
before composing the SMS body. Narrower blast radius.

Recommendation: Option B. The gross-total value may be the correct
one for email subject lines on some templates ("Invoice $X") and
changing `_build_context` globally risks downstream regressions. The
SMS body is the only confirmed drift surface.

## Testing contract

- Partial-payment invoice (total $100, paid $40) → SMS body says
  `(${60.00})`, not `(${100.00})`.
- Fully unpaid invoice → unchanged (balance == total).
- Email subject + body unchanged (already uses balance via the
  canonical renderer).
- Tenant isolation preserved.

## Scope

Pure code change; no backfill. SMS is point-in-time, not stored.

## Priority rationale

P3 — cosmetic. Does not block a payment or confuse the pay-sheet.
Can be scheduled alongside other dunning/comms polish work.
