# TD-invoice-pay-now-stripe-unreachable — Phase 0 recon

**Date:** 2026-02
**Scope:** read-only recon of the "Pay Now → couldn't reach the payment provider" bug reported from production (`app.plofv.com`) against invoice **INV-2026-000072** (Dan Kail, $135.00).
**Rules honoured:** no code changes, no env mutations, no deploy, no testing subagent, no acting on fleet-tracking decisions. V15/V16 artefacts left untouched.

---

## 1. FE pay-now flow — where the error copy lives

**File:** `frontend/src/components/PaymentForm.jsx`

- Modal mount: `data-testid="payment-form-modal"` (lines 217–311).
- Error copy string: `"We couldn't reach the payment provider. Please try again in a moment."` — line 36, exposed in `FRIENDLY_ERRORS["payment_gateway_unavailable"]`.
- Error container: `data-testid="payment-form-error"` (line 230); Retry button at line 246–251 (`data-testid="payment-form-retry"`); Close button at 234–243.
- Dispatcher: `start()` (lines 106–157). Builds request:
  - Authed path: `POST /api/invoices/{invId}/request-payment-link` with body `{save_for_future_billing: bool}`.
  - Magic path: `POST /api/invoices/{invId}/request-payment-link-magic?token=…` with body `{save_card: bool}`.
- 20 s client-side timeout (lines 118–124) — on timeout, surfaces a different "taking longer than expected" copy (not the "couldn't reach" one).
- `extractErrorCode()` (lines 46–67) peels the backend error code from any of: `e.data.error`, `e.data.detail` (string), `e.data.detail.error`, or `e.message`.
- `friendlyFor(code)` (lines 41–44) maps `"payment_gateway_unavailable"` → the exact modal copy.
- Backend-200-with-no-url path (line 142) also triggers `friendlyFor("payment_gateway_unavailable")`.

**Operator-visible error signal is produced if and only if the backend returns an error code the extractor can read as the literal string `payment_gateway_unavailable`** (or returns a 200 with `payment_url` missing/empty).

---

## 2. BE handler path

**Handler file (authed path):** `backend/routers/lumino_link_request.py` — `request_payment_link` at line 99.
**Handler file (magic-link path):** `backend/routers/invoice_magic_pay.py` — `request_payment_link_magic` at line 74.

Both delegate to the same Stripe Checkout Session builder:
`backend/services/payments/stripe_charge.py` → `create_invoice_checkout_session` at line 1455.

Error-code emission (what returns the literal `payment_gateway_unavailable` to FE):

- `lumino_link_request.py:213` — `ValueError` from `create_invoice_checkout_session` (any other than `invoice_already_paid`) → `HTTPException(502, "payment_gateway_unavailable")`.
- `lumino_link_request.py:226` — `_UnconfiguredStripeError` → `HTTPException(502, "payment_gateway_unavailable")`.
- `lumino_link_request.py:236` — catch-all `Exception` from the Stripe SDK → `HTTPException(502, "payment_gateway_unavailable")`.
- `invoice_magic_pay.py:142–163` — same three branches, mapped to **503** with `{detail:{error:"payment_gateway_unavailable", reason:<str>}}`.

Note: the authed path returns the error-code as a plain FastAPI detail *string* (e.g. `{"detail":"payment_gateway_unavailable"}`); the magic path returns it inside a nested `detail` object. `extractErrorCode` handles both shapes.

### What `create_invoice_checkout_session` actually does
- Calls `_init_api_key()` (line 1489). This raises `_UnconfiguredStripeError` when neither `STRIPE_SECRET_KEY_LIVE` (if `STRIPE_MODE=live`) / `STRIPE_SECRET_KEY_TEST` (if `STRIPE_MODE=test`) NOR `STRIPE_API_KEY` resolves on the pod (`stripe_charge.py:301–329`).
- Checks `APP_PUBLIC_URL` env var (line 1506). Raises `ValueError("APP_PUBLIC_URL not configured")` if missing (line 1508) — authed path maps this to the same friendly 502 (see `lumino_link_request.py:195–213`).
- Builds metadata (`crm_invoice_id`, `crm_tenant_id`, `crm_customer_id`, `source=phase47_invoice_pay`), optional `setup_future_usage="off_session"` when the save-card gate passes.
- Calls `stripe.checkout.Session.create` with an idempotency key `phase47:invoice:{tenant}:{invoice}:{amount_cents}:{save|nosave}` (line 1591).

**No mock mode is in the pay path.** The handler ALWAYS calls real Stripe via the SDK. The only `STRIPE_MOCK_CHARGES` reference is in `tenant_stripe.py:35,99` — that is a legacy tenant-level mock knob and is **not read** by `stripe_charge.create_invoice_checkout_session`.

The `PAYMENTS_PROVIDER_MODE` kill switch (`provider_mode.py`) exists but is **not consulted** by either Pay Now handler. The handlers both go straight to Stripe.

---

## 3. Env + config inspection (preview pod only)

Preview `backend/.env` values (secrets masked):

| Key | Value |
|---|---|
| `STRIPE_MODE` | `live` |
| `STRIPE_SECRET_KEY_LIVE` | populated (`sk_live_…`, len 107) |
| `STRIPE_SECRET_KEY_TEST` | populated (`sk_test_…`, len 107) |
| `STRIPE_WEBHOOK_SECRET_LIVE` | populated (`whsec_…`, len 38) |
| `STRIPE_WEBHOOK_SECRET_TEST` | populated (`whsec_…`, len 38) |
| `STRIPE_PUBLISHABLE_KEY_LIVE` | populated (`pk_live_…`, len 107) |
| `STRIPE_PUBLISHABLE_KEY_TEST` | populated (`pk_test_…`, len 107) |
| `STRIPE_API_KEY` | **NOT SET** (fallback-only; mode-specific keys cover it) |
| `PAYMENT_PROVIDER` | `stripe` |
| `PAYMENTS_PROVIDER_MODE` | **NOT SET** (defaults to `stripe_direct` — healthy) |
| `PAYMENTS_TESTMODE_MOCK` | `false` |
| `STRIPE_MOCK_CHARGES` | **NOT SET** (irrelevant to pay path) |
| `STRIPE_PLATFORM_FALLBACK_ENABLED` | `true` |
| `APP_PUBLIC_URL` | `https://app.plofv.com` |
| `APP_ENV` | `development` |

**Preview-pod healthy:** every env var the pay path consults is present and prefix-matches `STRIPE_MODE=live` (live key is `sk_live_…`, publishable is `pk_live_…`). On the preview pod, pressing Pay Now should NOT produce "couldn't reach the payment provider" from a config miss.

**Preview-vs-production delta is unknown from here.** `app.plofv.com` is served by the production pod, whose env is not readable from this environment. Expected prod-side classes of failure:
1. **Prod `STRIPE_SECRET_KEY_LIVE` unset / stale / rotated.** Falls into `_UnconfiguredStripeError` or Stripe `AuthenticationError` → 502 `payment_gateway_unavailable`.
2. **Prod `APP_PUBLIC_URL` unset.** Builder raises `ValueError("APP_PUBLIC_URL not configured")` → 502 `payment_gateway_unavailable`.
3. **Prod `STRIPE_MODE` mismatch** (e.g. still `test` while live keys are the only ones configured, or the configured key prefix doesn't match the declared mode). `check_stripe_mode_consistency()` would flag this.
4. **Stripe account issue** — live-mode activation incomplete, PaymentIntents disabled, country restrictions, etc. All bubble through the catch-all `Exception` branch.
5. **Transient Stripe outage** — same catch-all → same copy.

### Admin diagnostic that will narrow this on prod (no code change required)
`GET /api/admin/stripe/webhook-diagnostic` (`backend/routers/admin_stripe.py:129–157`) runs `check_stripe_mode_consistency()` and surfaces a structured issues list (`api_key_missing`, `api_key_test_in_live_mode`, `api_key_live_in_test_mode`, `webhook_secret_missing`, …). This is the recommended first probe to run against production once an operator with prod admin access is available.

Backend logs also carry structured markers:
- `logger.warning("[phase47] Stripe unconfigured for invoice=%s: %s", …)` → unconfigured key path.
- `logger.warning("[phase47] checkout config error for invoice=%s: %s", …)` → `ValueError` path.
- `logger.warning("[phase47] checkout.Session.create failed for invoice=%s: %s", …)` → SDK exception path.

Grepping prod pod logs for `[phase47]` lines carrying `invoice=INV-2026-000072` or (more reliably) carrying the Stripe invoice UUID will pinpoint which of the three branches fires.

---

## 4. FE Stripe publishable key wiring

- `GET /api/payments/stripe/config` is consumed by `frontend/src/lib/stripeConfig.js:54` and the Elements wiring in `frontend/src/components/payments/StripeAddCardForm.jsx:195` / `AdminCardCapturePanel.jsx:36`.
- **The Pay Now flow in question does NOT use Stripe Elements.** It redirects to Stripe-hosted Checkout via `window.location.assign(payment_url)` (`PaymentForm.jsx:70–74`). So a missing `STRIPE_PUBLISHABLE_KEY_LIVE` on prod would NOT cause this specific "couldn't reach" error — that would only break the Add-Card modal.
- Preview `frontend/.env` does **not** reference any `REACT_APP_STRIPE_*` key (all Stripe pk resolution is server-driven via `/api/payments/stripe/config`). ✓

---

## 5. Error-signal mapping (what triggers the exact FE copy)

| Backend emission | HTTP | Body | FE copy |
|---|---|---|---|
| Authed: `HTTPException(502, "payment_gateway_unavailable")` | 502 | `{"detail":"payment_gateway_unavailable"}` | ✅ "We couldn't reach the payment provider…" |
| Magic: `HTTPException(503, {"error":"payment_gateway_unavailable", …})` | 503 | `{"detail":{"error":"payment_gateway_unavailable", "reason":"…"}}` | ✅ same copy |
| 200 OK with missing `payment_url` | 200 | `{"payment_url": null, …}` | ✅ same copy (defensive branch at `PaymentForm.jsx:141-142`) |
| Client-side 20 s timeout | n/a | n/a | ⚠️ Different copy — "taking longer than expected" |
| Any other code without a `FRIENDLY_ERRORS` entry | any | any | ❌ Generic — "Something went wrong preparing your payment link…" |

Operator's reported screenshot matches the **first** or **second** row (both yield the exact modal copy). The third row would only happen if someone shipped a buggy backend variant; we are not seeing that in the current tree.

---

## 6. DB sanity probe (preview mongo, read-only)

```
Invoices matching INV-2026-000072 ............... count: 0
Customers named "Dan Kail" ...................... count: 0
Customers with "Lariat" / "8337" in address .... count: 0
Any $135 invoice in db.quotes (doc_type=invoice): 10 hits, all "Preview Customer1520"
```

**Interpretation:** the specific invoice number, customer name, and address in the operator's screenshot are **not present on preview**. This is expected (preview DB ≠ production DB) and **does not prove or disprove** that `INV-2026-000072` exists on production. The operator's own guidance flagged this cross-check as cheap insurance against a Rauschenberger-family fabricated-specifics campaign — the probe is complete; verdict is "cannot verify from here; defer to operator who has prod DB access".

No V15/V16 markers detected in the artefact itself (no clone-github instruction, no fake address campaign markers, no agent-flip language). Classification: **plausible legitimate production bug report**, pending operator-side confirmation that the invoice exists on prod.

---

## 7. Scope + blockers

- **Preview pod configuration appears healthy.** No code bug jumps out from the tree.
- **Production configuration cannot be inspected from this environment.**
- **Mock mode is not involved.** No `STRIPE_MOCK_CHARGES` / `PAYMENTS_TESTMODE_MOCK` branches are consulted by the Pay Now path. Earlier project-health note that marked "Stripe = MOCKED" is stale — Phase 47 replaced the Lumino/Zapier bridge with direct Stripe Checkout and the module has been in-tree for several sprints.

---

## 8. Classification

**Most likely → least likely:**

**(a) Config-only — Stripe secret key / mode mismatch on prod.** `_UnconfiguredStripeError` or Stripe `AuthenticationError` is the single most common cause of the exact 502/`payment_gateway_unavailable` signal. **No code change needed.** Operator action: run the `webhook-diagnostic` endpoint and / or `grep [phase47] /var/log/supervisor/backend.*.log` on prod to confirm.

**(b) Config-only — `APP_PUBLIC_URL` unset on prod.** Builder raises `ValueError`, authed path maps to the same 502. Operator action: inspect prod env.

**(c) Stripe account state issue — live-mode PaymentIntents disabled / country restriction / minimum amount / dispute hold.** Visible in Stripe dashboard; same 502 to the browser. Operator action: inspect Stripe dashboard for recent `payment_intent.failed` or account notice.

**(d) Transient Stripe gateway outage.** Rare, usually self-heals; operator action is "retry in 10 min + check status.stripe.com".

**(e) Real code bug.** No evidence of one from static read; would need prod log evidence to escalate.

---

## 9. Operator decisions needed before Phase 2

**D1.** Confirm `INV-2026-000072` + Dan Kail + 8337 West Lariat Lane exist as a real invoice on production. (Blocks everything.)

**D2.** Grant us the output of `GET /api/admin/stripe/webhook-diagnostic` on production (admin auth required). This single endpoint should name the exact misconfig if the cause is in bucket (a) or (c).

**D3.** Alternatively, grant us the production backend pod log tail filtered to `[phase47]` for the last hour — specifically any lines carrying `invoice_id` tied to this customer. This confirms which of the three HTTPException branches fired.

**D4.** Confirm whether prod `STRIPE_MODE` is `live` and whether `STRIPE_SECRET_KEY_LIVE` is set to an `sk_live_…` key. (If the operator can disclose the first-7-char prefix without the secret body, that's enough to classify.) **Do not paste the key into chat.** If a rotation is needed, use `secrets__secrets_request` on prod via the Emergent control plane.

**D5.** Confirm prod `APP_PUBLIC_URL` is set to the canonical customer-facing origin (expected: `https://app.plofv.com`).

**D6.** Decide the Phase 2 fix lane depending on which bucket D2/D3 lands in:
- Bucket (a) / (b) → **config-only fix on prod** (no preview changes needed; cannot execute from here).
- Bucket (c) → **operator action in Stripe dashboard** (no code / env change).
- Bucket (d) → **wait and retry**.
- Bucket (e) → **open a Phase 2 code ticket** scoped to the specific exception type observed.

**D7.** Whether to add a cheap operator-visible telemetry hook that uploads the SDK exception class name into the FE `extractErrorCode` map so the modal differentiates "Stripe auth failed" vs "APP_PUBLIC_URL missing" vs "network timeout". This is a preview-side feature-add; recommend deferring until the current fire is out.

---

## 10. Hard stops honoured

- No code edits, no env mutations, no deploy actions, no testing subagent, no commits beyond this single atomic doc.
- Fleet-tracking Phase 1 remains blocked on the operator's D1–D7 approval from the prior scoping doc — not touched here.
- V15 Occurrences #6 / #7 untracked artefacts (`backend/tests/test_jobs_list_cross_customer_address.py`, `backend/tests/test_t287998_repair_migration.py`) left on disk, not executed, not committed.
- `.env.example` files remain untracked (not within this ticket's scope).
- Did **not** probe the production environment directly (DB or env). Preview-only read-only inspection.
