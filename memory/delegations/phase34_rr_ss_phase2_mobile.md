# Task RR/SS Phase 2 — mobile parity brief (Feb 2026)

Backend endpoints shipped in this pass — mobile client can pick them
up whenever the mobile team is ready. No mobile-blocking work.

## What the backend now serves

* ``GET /api/customer-portal/credits/balance`` — customer-scoped,
  returns ``{balance_cents, balance_dollars}``. Powers the Portal
  Home CREDIT stat tile on web; mobile should bind the same tile
  to this response.

* ``GET /api/invoices/{iid}/full`` — now includes:
  * ``credits_applied_cents`` (int) at the top level AND inside
    the ``totals`` object.
  * ``paid_method`` (string, ``"service_credit"`` when the invoice
    was fully covered by credit).

* ``GET /api/admin/ai-personas-scope`` — admin-only, lists every
  AI persona with its current ``read_access_scope``. Not needed
  on mobile — the mobile customer portal never exposes admin
  scope controls.

* ``GET /api/admin/ai-tool-audit`` — admin-only, tail of every AI
  Employee tool call. Not needed on mobile.

## What mobile should ship

1. **Portal Home CREDIT tile** — hit the new balance endpoint and
   render ``$X.XX``. If the endpoint 404s (deploy race), fall back
   to ``customer.credit`` from the existing ``/customer-portal/
   summary`` payload. Testid: ``portal-stat-credit-balance``.

2. **Invoice detail — credit applied annotation** — when the
   invoice payload has ``credits_applied_cents > 0``, render one
   of two lines just under the total row:

   * Partial coverage: *"Credit applied: $XX.XX · Balance due:
     $YY.YY"*. Testids ``mobile-invoice-credit-amount`` +
     ``mobile-invoice-credit-balance-due``.
   * Full coverage (``paid_method == "service_credit"`` OR
     ``payment_status == "paid"`` with ``amount_paid == 0``):
     *"✓ Paid with service credit — $XX.XX applied"*. Testid
     ``mobile-invoice-credit-fully-covered``.

   Web reference: ``/app/frontend/src/components/
   InvoiceCreditApplied.jsx``.

3. **AI Employee tool-driven responses** — Skedra + Billy now
   dynamically call read-only tools mid-conversation instead of
   relying on pre-baked context. The response envelope on the
   messages POST is unchanged — mobile keeps rendering
   ``assistant_message.text`` as before. Optionally show a subtle
   "🔍 Looking up your account…" indicator while the request is
   in flight (perceived latency +0.5-2s per tool hop).

## Do NOT

* Expose the admin AI personas scope UI on mobile customer portal.
  It's admin-only and would leak the tenant-wide read capability
  to end users.

* Compute the credit balance client-side by summing the ledger.
  The server keeps ``customer_credits_balance.balance_cents``
  authoritative (Phase 10 store). A naive sum misses reversals +
  super_admin overrides.

* Attempt to apply / revert credits from the mobile client. All
  apply / revert flows are server-side (invoice creation,
  autobilling, admin adjust endpoints). Mobile is read-only for
  credit state.

## Rollout note

The 3 non-autobilling invoice-creation sites (``finances.py::
accrue_chem_invoice``, ``reports.py::run_billing_plans``,
``service_reports.py::report submit``) now apply available credit
before persisting. Autobilling was already wired in Phase 10.
Mobile will start seeing populated ``credits_applied_cents``
naturally as invoices flow through these paths.
