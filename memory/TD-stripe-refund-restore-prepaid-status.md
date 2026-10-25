# TD-stripe-refund-restore-prepaid-status · follow-up (P2)

**Parent:** `TD-stripe-webhook-mark-invoice-paid` (shipped `<commit-hash>`).

## Gap

`services/payments/stripe_charge.py::_apply_refund_to_invoice` flips
`payment_status` to `"refunded"` / `"partially_refunded"` on a Stripe
refund webhook (`charge.refunded` / `refund.updated`) but leaves `status`
pointing at `"paid"` (the terminal value Fix A of the parent ticket
stamped on full payment).

Post-full-refund, the invoice carries:
- `payment_status = "refunded"` ✓
- `amount_paid = 0`  ✓
- `status = "paid"`  ✗ (should restore to pre-paid value)

## Why it matters

- Any downstream filter that uses `status` as a "paid vs live"
  proxy (reports, aging, admin dashboards) still treats the invoice
  as paid after a refund.
- Audit coherence: the invoice visibly says both "paid" (status) and
  "refunded" (payment_status) at the same time.
- Fix A deliberately stamped `previous_status_before_paid` on the
  invoice at the paid-flip point specifically to make this restore
  pass trivial — no backfill needed on the read side.

## Fix shape

In `_apply_refund_to_invoice`:
- When `fully_refunded=True`:
  - `$set status = inv.get("previous_status_before_paid")` if present
    (else leave on `"paid"` — rare legacy row with no crumb).
  - `$unset previous_status_before_paid` so a subsequent re-payment
    won't restore to a stale pre-pre-paid value.
- When `fully_refunded=False` (partial refund): leave `status`
  untouched — the invoice is semantically "paid with a partial refund
  outstanding", which is already handled by `payment_status="partially_refunded"`.

## Scope: forward-only, NO backfill

The parent ticket's `paid_invoice_status_backfill_v1` CLI handles the
historical paid-flip cleanup. Refund-restore is forward-only — a
future refund will trigger the restore via the crumb; existing
refunded-but-stuck-at-paid rows are a known data state that's
cosmetic (not AR-material because `payment_status="refunded"`
already excludes them from Outstanding via Fix B).

## Testing contract

- Full refund with crumb present → status restored to crumb value,
  crumb unset.
- Full refund without crumb (legacy row) → status stays "paid",
  logged.
- Partial refund → status untouched, crumb untouched.
- Replay-safe (refund_key dedup already in place; status restore
  is idempotent on `$set`).
- Tenant isolation preserved.

## Priority rationale

P2 — not AR-material (Outstanding tile already excludes refunded
rows via Fix B's `payment_status != "paid"` guard). Pure coherence
fix. Can be scheduled after higher-value tickets without regression
risk.
