# Mobile delegation — Service credit auto-apply on invoices

**Feb 2026 · Task SS followup for the mobile customer portal.**

Backend already does the heavy lifting via Phase 10's
``services/credits_apply.py`` — mobile just needs to reflect the
new fields in its existing invoice + home views.

## What the backend now sends

**Invoice documents** (both list + detail endpoints) carry:
* ``credits_applied_cents`` (int) — how much service credit was
  applied to this invoice at creation / autobilling time.
* ``paid_method`` — set to ``"service_credit"`` when the invoice
  was fully covered by credit.
* ``paid_at`` — timestamp of the credit-triggered paid transition.
* ``status`` / ``payment_status`` — flip to ``paid`` when the
  credit fully covered the invoice; the mobile client's existing
  "Paid" pill should render automatically once it inspects these
  fields.

**Customer document** (portal profile / home stats endpoint)
carries:
* ``credits_balance_cents`` (int) — the live balance. Powers the
  Home "CREDIT" stat tile.
* ``credits_ledger`` (list of entries) — inline history. Not
  exposed on the mobile client currently; may be surfaced on a
  future "Credits history" screen.

## What mobile should ship

1. **Portal Home CREDIT tile** — bind the value to
   ``customer.credits_balance_cents / 100`` formatted as USD. Use
   the existing money formatter; do NOT compute the balance
   client-side by summing the ledger — the server keeps
   ``credits_balance_cents`` authoritative.
2. **Invoices list + detail** — when ``credits_applied_cents > 0``,
   render a subtle annotation under the amount: *"Credit applied:
   $XX.XX"*. Recommended testid ``mobile-invoice-credit-applied``.
3. **"Paid" chip trigger** — mobile already renders a Paid chip
   based on ``payment_status == "paid"``; no change needed.
   Optionally render an extra chip labelled *"Paid with credit"*
   when ``paid_method == "service_credit"``.

## Do NOT

* Ship a mobile UI for admin manual credit issuance
  (``POST /api/customers/{cid}/credits``). That endpoint is
  ``require_admin``-gated and is not intended for the customer
  portal audience.
* Sum ledger deltas on the client to compute a balance — the
  server keeps ``credits_balance_cents`` authoritative and
  reflects idempotency + super_admin overrides that a naive sum
  would miss.
* Attempt to apply / revert credits from the client. All apply /
  revert flows are server-side (invoice creation, autobilling,
  admin endpoints). Mobile is read-only for credit state.
