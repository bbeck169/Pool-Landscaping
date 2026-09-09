# DIAG — Estimate-vs-Invoice Reminder + Payment-link Login Redirect (P0 bugs)

**Status:** ✅ **SHIPPED — Feb-2026** (preview + code ready to ship on next prod deploy).

## Bug A · "invoice Estimate has an outstanding balance …"

### Symptom
Admin clicks **Send reminder** on an **Estimate** detail page. Customer receives an email:
> Subject: *Payment reminder — Estimate*
> Body: *"Hi Valarie Lira, This is a friendly reminder that invoice **Estimate** has an outstanding balance of **$27,273.00** (was due now)."*  with a **Pay Now** button.

The word `invoice` is hardcoded and `title` (a legacy string field storing the doc-type label — "Estimate" / "Invoice") is spliced into the subject and body. Estimates cannot have an outstanding balance; the CTA is wrong.

### Root cause
`POST /api/quotes/{qid}/send-reminder` was a single handler that always ran the invoice payment-reminder path. `emailer._reminder_html` also spliced `inv.get('title', '')` into the "invoice X has an outstanding balance …" copy, so an Estimate row whose `title` was the legacy doc-type label ("Estimate") produced the exact prod copy.

### Fix
1. **Router branches on `doc_type`** — `routers/quotes.py::send_reminder` now dispatches:
   * `doc_type in {estimate, quote}` → `send_estimate_reminder_email(inv, tenant, review_url)`, mints a fresh magic-link via `_sign_estimate_token`, drops the "outstanding balance" / "was due" / "Pay Now" copy, uses a **Review Estimate** / **Review Quote** CTA pointing at `/e/estimate?token=…`. Audit event scope name is `estimate_reminder_sent` / `quote_reminder_sent`.
   * `doc_type == invoice` (default) → the existing `send_invoice_reminder_email` path is preserved, but the copy substitutes the invoice's **`invoice_number` / `doc_number` / `#<id[:8]>`** (never `title`).
2. **Depth-in-defence guard** — `emailer.send_invoice_reminder_email` now refuses (`return False` + `logger.warning`) any doc whose `doc_type != "invoice"`. Symmetric guard on `send_estimate_reminder_email`.
3. **Display-number helper** — new `emailer._invoice_display_number()` returns `invoice_number → doc_number → #<id[:8]>` and **never** falls back to `title`.
4. **Toolbar hides the "Payment link" button on non-invoices** — `pages/quotes/QuoteInvoiceDetail.jsx` gates on `shouldShowPaymentLinkButton({isInvoice, docStatus, paymentStatus})`. Hidden on estimates and on invoices in `draft` / `void` / `paid` states.
5. **Endpoint refuses non-invoice ids** — `POST /api/invoices/{id}/request-payment-link` now returns 400 `not_an_invoice` when the doc is a quote/estimate. (`find_invoice_dual` already filters by `doc_type=invoice`, so many payloads return 404 `invoice_not_found` first — either 400 or 404 is acceptable per the spec.)

## Bug B · "Pay Now" → `/portal/login?reason=link_expired`

### Symptom
Customer clicks **Pay Now** in a payment reminder email. Instead of landing on the Stripe payment surface, they hit `/portal/login?reason=link_expired` with a yellow "Your one-click link has expired" banner. Payment blocked.

### Root cause
`emailer._reminder_html` preferred a `portal_cta_url` minted by `services.portal_magic_links.build_invoice_pay_url` (endpoint `/api/portal/auto-login?t=<jwt>`) over the public pay URL (`/pay/invoice/{id}?token=<jwt>`). The portal auto-login token had a **72-hour TTL**; on expiry the endpoint 302'd to `/portal/login?reason=link_expired` — the general-purpose auth wall. Payment links should never require login.

### Fix
1. **Emailer never mints the portal auto-login URL for payments any more** — `emailer._reminder_html` always uses `build_pay_now_url()` → `/pay/invoice/{id}?token=<30-day JWT>&src=email` (public, no login, runs outside `<AppLayout>` per `App.js`). The `portal_cta_url` kwarg is retained for callsite compat but now ignored.
2. **Legacy expired invoice tokens are rescued** — `routers/portal_auto_login.py` now `_peek_scope_and_id()`-decodes an expired/rejected token with `verify_exp=False`; if the scope is `portal_invoice_pay` or `invoice_pay` (i.e. it was a payment-scoped token), the endpoint redirects to `/pay/invoice/{id}?msg=link_expired` instead of `/portal/login`. Tampered / non-invoice tokens still fall through to the legacy `_expired_response()` — the `reason=link_expired` behaviour is preserved for OTHER magic-link scopes (estimate viewer, portal home).
3. **`PublicInvoicePay.jsx` renders a friendly copy** on `?msg=link_expired`: *"This payment link is no longer valid. To pay this invoice, please contact the business that sent it and ask them to resend the payment link."* — distinct `data-testid="public-invoice-pay-link-expired"` so the QA path is unambiguous.

## Files touched

* `backend/emailer.py` — new `_invoice_display_number()` + `_estimate_reminder_html()`; new `send_estimate_reminder_email()`; refusal guards on both email helpers; `_reminder_html` no longer splices `title`; portal_cta_url path deprecated.
* `backend/routers/quotes.py` — `send_reminder` branches on `doc_type`; distinct audit events (`estimate_reminder_sent`, `quote_reminder_sent`, `invoice_reminder_sent`); response payload includes `doc_type` + `review_url_minted` on the estimate branch.
* `backend/routers/lumino_link_request.py` — 400 `not_an_invoice` guard on quote/estimate ids.
* `backend/routers/portal_auto_login.py` — `_peek_scope_and_id()` helper; expired invoice-scoped tokens redirect to `/pay/invoice/{id}?msg=link_expired`.
* `frontend/src/pages/public/PublicInvoicePay.jsx` — `msg=link_expired` friendly-copy branch.
* `frontend/src/pages/quotes/QuoteInvoiceDetail.jsx` — new exported `shouldShowPaymentLinkButton()` predicate; toolbar Payment-link button gated (invoice-only, non-draft, non-void, non-paid).
* `backend/tests/test_reminder_doc_type_routing.py` (new) — 8 pytests covering router branching, refusal guards, display-number helper, portal peek.
* `backend/tests/test_portal_auto_login_route.py` — updated the existing `test_expired_invoice_token_redirects_to_*` to assert the new public-pay redirect.
* `backend/tests/test_pay_now_magic_link.py` — fixed a pre-existing broken import (`payments_stripe_live` was deleted; the helper now lives in `routers.invoice_magic_view`).
* `frontend/src/test/reminder-doc-type-toolbar.test.jsx` (new) — 8 vitests covering the toolbar predicate + PublicInvoicePay branching.

## Payment flow chosen
**Existing hosted flow via `PublicInvoicePay` → `InvoiceView` → `/api/invoices/{iid}/full-magic`** — no Stripe Checkout Session is created on the reminder path itself; the customer lands on the public invoice-pay page and the existing embedded Stripe Payment Element handles the checkout. This is the current architecture; the P0 fix only changes the URL the customer receives (portal auto-login → public pay page). No Stripe Connect changes required.

## Historical bad-send count (preview DB · Feb-2026)

Query: `db.quotes.count({doc_type in {estimate, quote}, reminder_count > 0})`.

**Result: 2 quote/estimate documents received a total of 5 payment-reminder invocations via the invoice-reminder path.**

| id (truncated) | doc_type | customer | reminder_count | last_reminder_at | email actually sent? |
|-|-|-|-|-|-|
| 66a9…8b48 | quote | Robert Blake | 4 | 2026-02-08 | `email_sent=False` on preview (Resend not configured) |
| a53c…9028 | quote | Drift Datetime | 1 | 2026-01-24 | `email_sent=False` on preview |

Preview did **not** deliver the emails (Resend `RESEND_API_KEY` not set here) — the in-app + SMS notifications did fire. Prod audit for the same query is left to the operator to run since we don't have write access to prod. Historical rows are **not** altered.

## Test results

* Backend pytest — **36 passed** across `test_reminder_doc_type_routing.py` (8), `test_portal_auto_login_route.py` (14), `test_phase_b_quote_notifications.py` (9), `test_pay_now_magic_link.py` (5).
* Backend perf pytest — **2 passed** (`test_perf_customers_search_p95.py` + `test_perf_schedule_dispatch_p95.py`).
* Frontend vitest — **new suite 8/8; regression suites 38/38 green**.
* Curl smoke — estimate reminder returns `doc_type=quote, review_url_minted=true`; invoice reminder returns `ok=true`; expired portal-invoice token redirects to `/pay/invoice/{id}?msg=link_expired`.

## Manual verification checklist (for e1_tester)

**A · Estimate reminder now uses the estimate template**
1. Admin logs into aquaterra as `super@aquaterra.com` / `password123`.
2. Open any Estimate in `sent` state (e.g. `/quotes/<id>` with `doc_type=estimate` or `quote`).
3. Header shows **"Estimate"** (or "Quote").
4. Toolbar shows **Send reminder** and **Send for signature**. **Payment link button is HIDDEN**.
5. Click **Send reminder** → toast confirms sent → response has `doc_type: "estimate"` (visible in devtools Network tab).
6. If the customer has an email, the outbound email subject is **"Reminder: your estimate from {tenant_company_name}"** (no "Payment reminder"). Body includes "**{doc_number}** is awaiting your review", NEVER "outstanding balance" / "was due" / "Pay Now".
7. CTA button in email is **Review Estimate** and links to `/e/estimate?token=…`.

**B · Invoice reminder still works (regression)**
8. Open an Invoice in `sent` / `partially_paid` state. Toolbar shows Send reminder + **Payment link** (both).
9. Click **Send reminder** → response has `ok:true, reminder_count:N` (no `doc_type` field).
10. Outbound email subject is **"Payment reminder — invoice INV-999"** (or the invoice's number). Body substitutes `{doc_number}` — no more "invoice Estimate has an outstanding balance …".
11. CTA button is **Pay Now** and links to `/pay/invoice/{id}?token=…&src=email` (NOT `/api/portal/auto-login?t=…`).

**C · Payment link resolves without login**
12. Copy the **Pay Now** URL from step 11 into a private-window browser (no session).
13. Lands on `/pay/invoice/{id}?token=…` → renders the invoice pay surface. **No `/portal/login` redirect**.
14. Manually craft an expired portal-invoice-pay JWT (or wait 72h) and hit `/api/portal/auto-login?t=<expired_tok>` → 302 to `/pay/invoice/{id}?msg=link_expired` → renders the "This payment link is no longer valid. …" banner. **NOT** `/portal/login?reason=link_expired`.
15. `POST /api/invoices/{estimate_id}/request-payment-link` → 400 (or 404 `invoice_not_found`). No Stripe session created.

**D · Toolbar gating**
16. Draft invoice → **Payment link hidden** (nothing issued yet).
17. Paid invoice → **Payment link hidden** and **Send reminder hidden** (nothing owed).
18. Void invoice → **Payment link hidden**.

## Preview note about Stripe Connect
The reminder email's Pay Now URL points to `/pay/invoice/{id}?token=…` which requires the tenant to have a working Stripe Connect config for real payment. Preview's aquaterra tenant does not have a live Stripe account attached, so the Payment-Element form will render but the "Pay" button will 400 on `POST /api/invoices/{id}/pay` with a Stripe-side config error. That's expected in preview; prod has the real config.
