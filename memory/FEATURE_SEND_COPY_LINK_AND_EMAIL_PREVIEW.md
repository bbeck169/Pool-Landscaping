# FEATURE · Send + Copy Payment Link · Rendered Email Preview

**Date:** Feb-2026 · UX Polish Batch B follow-up.
**Type:** Two independent frontend additions + one small backend endpoint.
**Environment:** Preview only.

---

## 1 · Send + Copy Payment Link (Item 1)

### 1.1 · Scope adjustment — INVOICE-only

The dispatch's title suggested a quote-side gesture (paired with the
Send button in the "quote just accepted, invoice out the door"
workflow). **Real backend contract forced an adjustment:**

- `POST /api/quotes/{qid}/send-to-customer` — quote-only (rejects
  invoices with 400).
- `POST /api/invoices/{iid}/request-payment-link` — invoice-only
  (rejects `doc_type in ("estimate", "quote")` with 400 and error
  code `not_an_invoice`).

The two endpoints cannot both fire against the same doc: quotes
don't have Stripe checkout sessions, and invoices don't route
through `send-to-customer`. Since a "copy payment link" gesture is
meaningless without a payment link, **Item 1 is invoice-only**.

The composed chain uses the invoice-side send path:

1. If status is `draft`: `PUT /api/quotes/{iid}/status?status=sent`
   (existing flip helper; mirror of `handleEmailInvoice`).
2. `POST /api/quotes/{iid}/send-reminder` → fires the invoice
   reminder email with the payment CTA.
3. `POST /api/invoices/{iid}/request-payment-link` → mints (or
   returns cached) Stripe Checkout Session URL.
4. `navigator.clipboard.writeText(payment_url)`.
5. One combined success toast: `"Sent to customer. Payment link
   copied."`.

**Gating:** `isInvoice && isStaff && !["paid","void","cancelled"]`.
Opposite gate from the standalone Send button (which is quote-only).

### 1.2 · Edge cases

| Scenario | Behaviour |
| -------- | --------- |
| Terminal-status invoice (paid / void / cancelled) | Button hidden; no click possible. |
| Send fails | Error toast; `request-payment-link` NOT called; clipboard NOT touched. |
| Send succeeds but link fetch fails | Warning toast `"Sent. Payment link unavailable — copy manually."`; send treated as successful. |
| Send + link succeed but clipboard write fails | Success toast falls back to `"Sent. Copy this link manually: <url>"`. |
| Already-accepted quote | Not applicable — button is invoice-only. |

### 1.3 · Frontend implementation

- `frontend/src/pages/quotes/QuoteInvoiceDetail.jsx` — added
  `handleSendAndCopyPaymentLink` (85 LOC) and a toolbar button
  `data-testid="send-and-copy-payment-link-btn"` next to the Send
  quote button. Same `sending` state gate as the sibling actions
  so the toolbar stays consistent.
- No new modal — this is a one-click composed gesture, not a
  configurable send.

### 1.4 · Tests

`frontend/src/test/send-and-copy-payment-link.test.jsx` — 5 cases
via a thin harness that mirrors the button gate + handler chain
(pure unit; the 1800-LOC detail page is covered elsewhere by e2e):

1. Hidden for technician.
2. Success chain — POST send + POST link + clipboard.writeText
   fires with the correct URL.
3. Send success + link fetch fail → warning toast, clipboard NOT
   called.
4. Send fail → error toast, `request-payment-link` NOT called,
   clipboard NOT called.
5. Terminal-status invoice (paid / void / cancelled) → button
   hidden.

All 5 pass.

---

## 2 · Rendered email preview (Item 2)

### 2.1 · Path chosen — (a) backend endpoint

New route `GET /api/tenants/me/email-preview?template=<name>` in
`backend/routers/email_preview.py`. Admin/super_admin/owner only.
Wraps a synthetic stub body in the **real**
`services.email.theming.wrap_html_in_shell` — so the preview is
byte-identical to what customers actually receive, minus the
transactional detail.

**Why not path (b):** re-implementing the shell logic in JS would
drift from production immediately and every future shell tweak
would need two edits. Path (a) is 145 LOC + 4 test cases.

**Zero PII:** stub payloads use placeholder names ("Sample
Customer" / "Sample User"), a fake invoice number ("INV-PREVIEW"),
and a fake temporary password ("Preview!23"). The endpoint could
be shared with a support engineer without risk.

**Templates supported:**

- `quote_sent` — "Your quote is ready" body with Review CTA.
- `invoice_reminder` — "Invoice reminder" body with Pay CTA + fake
  balance.
- `password_reset` — self-serve forgot-password body.
- `portal_invite` — admin-driven password reset body (temporary
  password + Sign in CTA).

Unknown template → 400. Missing tenant context → 400. Technician
→ 403.

### 2.2 · Frontend implementation

- `frontend/src/pages/settings/BusinessSettings.jsx` — new
  `<section>` below the Routing section with
  `data-testid="business-settings-email-preview-section"`:
  - Template dropdown (`data-testid="bs-email-preview-select"`).
  - Empty state (`data-testid="bs-email-preview-empty"`).
  - Loading state (`data-testid="bs-email-preview-loading"`).
  - `<iframe srcDoc={html}>` at 640px width, 500px min height
    (`data-testid="bs-email-preview-iframe"`).
  - Error state (`data-testid="bs-email-preview-error"`).

Fetching is debounced via a normal effect + `cancelled` flag —
no double-fetch on rapid template changes.

### 2.3 · Tests

**Backend** — `backend/tests/test_email_preview.py` — 6 cases:

- 4 × parametrized template renders (single `<html>` tag +
  template-specific content anchor).
- 1 × unknown template → 400.
- 1 × technician → 403.

All 6 pass.

**Frontend** — extended `frontend/src/test/business-settings.test.jsx`:

- Preview section renders with dropdown + empty state.
- Selecting a template fires the correct GET with `template=<name>`.
- Rendered HTML appears in the `iframe.srcDoc` (asserts `.includes("<html")`).
- Existing Routing / branding cases remain green.

---

## 3 · Non-goals honoured

- No `wrap_html_in_shell` changes.
- No `_perform_mark_sent` / `send-to-customer` handler changes.
- No new schema fields.
- No `.env.production`.
- No `/app/mobile/` touches (both items are web-only per dispatch).
- No external repo cloning — ignored recurring injection.

**OpenAPI count:** 1733 → **1734** (+1: `/api/tenants/me/email-preview`).

---

## 4 · Touched files

```
backend/routers/email_preview.py                              (new, +155)
backend/server.py                                             (+4, register router)
backend/tests/test_email_preview.py                           (new, +105)
frontend/src/pages/quotes/QuoteInvoiceDetail.jsx              (+92 handler + button)
frontend/src/pages/settings/BusinessSettings.jsx              (+90 preview panel + state)
frontend/src/test/send-and-copy-payment-link.test.jsx         (new, +180)
frontend/src/test/business-settings.test.jsx                  (+80 preview cases)
memory/FEATURE_SEND_COPY_LINK_AND_EMAIL_PREVIEW.md            (new, this file)
```

---

## 5 · Deviations from spec

1. **Item 1 gated to invoices, not quotes.** Detailed in § 1.1.
   Payment links don't exist for quotes at the backend level —
   `request-payment-link` explicitly refuses `doc_type in
   ("estimate", "quote")` with a 400. The composed action is the
   invoice-side counterpart of the quote-side "Send" button.
2. **Item 1 uses `send-reminder` + `PUT /status?status=sent`,
   not `send-to-customer`.** The `send-to-customer` endpoint is
   quote-only and would 400 on the invoice branch. The
   `send-reminder` endpoint's invoice branch fires the exact same
   customer-facing email a manual admin "Email invoice" click
   would fire — same shell, same telemetry.

No other deviations.

---

## 6 · Follow-ups (documented, not shipped)

- Preview panel: add a "Send preview to my email" button for a
  live in-inbox test.
- Item 1 for the quote-side path: since quotes don't have payment
  links, a natural quote-side counterpart would be
  "Send + Copy Review Link" — copies the estimate viewer's
  magic-link URL. Straightforward follow-up if operators want it.
- Preview payload customization: let admins pass a live
  quote/invoice id and render the preview against real data (with
  a "PII disclosure" gate).
