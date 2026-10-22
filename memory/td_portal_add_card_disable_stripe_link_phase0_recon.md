# TD-portal-add-card-disable-stripe-link — Phase 0 recon

**Date:** 2026-02
**Scope:** read-only recon of the production report: "Add a card" panel at `app.plofv.com/portal/payment-method` renders a **Stripe Link account prefill** (admin's own `brianbeckmanaz@gmail.com` + "Chase Business Debit ••6538") during admin impersonation of **Seth & Ashley Wilson**, instead of the raw card form (Card/Bank toggle + card number / expiry / CVC / country / ZIP) shown in the operator's desired-state screenshot.
**Rules honoured:** no code changes, no env mutation, no deploy, no testing subagent. V15/V16 artefacts untouched. Fleet-tracking Phase 1 + invoice-pay-now diagnostic paste still blocked on operator.

---

## 1. Legitimacy check

Two coherent production artefacts (current vs desired), concrete UX request, surface aligned with the ongoing TD-invoice-pay-now-stripe-unreachable production Stripe surface, admin-impersonation banner internally consistent. No V15 clone-github / fabricated-address campaign markers, no V16 agent-flip language, no urgency flip. Classification: **plausible legitimate UX + privacy ticket**.

Side observation worth flagging: the operator reports they are logged into their own browser Chrome with a **personal Stripe Link account** (`brianbeckmanaz@gmail.com`) while impersonating a customer. Stripe Elements auto-detects the browser's Link session via a first-party cookie keyed to Stripe's domain and surfaces the saved Link PM regardless of the app's authenticated user. This is a correct — if unwelcome — Stripe behaviour and is **not** a backend RBAC failure.

---

## 2. FE audit — Portal Add Card flow

### Route + page
- Route: `/portal/payment-method` → `frontend/src/App.js:1592` → `<PortalPaymentMethod />`.
- Component: `frontend/src/pages/portal/PortalPages.jsx:548` — delegates entire card + ACH surface to `<PaymentMethodTiles customerId={user?.customer_id} variant="portal" />`.

### Tile wiring
- `frontend/src/components/customers/PaymentMethodTiles.jsx:586` renders `<StripeAddCardForm …>` when the user hits **Add card**.
- Same component is reused on the admin Customer Detail "Payments" tab (`frontend/src/components/customers/AdminCardCapturePanel.jsx:418`).

### Stripe Elements wiring (THE actual cause)
`frontend/src/components/payments/StripeAddCardForm.jsx`:
- line 17-24 imports: `loadStripe`, `Elements`, `useStripe`, `useElements`, **`PaymentElement`** (NOT `CardElement`, NOT `LinkAuthenticationElement`).
- line 88: `<PaymentElement options={{ layout: "tabs" }} />` — no `wallets` option, no `fields` config, no `paymentMethodOrder`.
- line 256-258: `<Elements stripe={stripePromise} options={{ clientSecret, appearance: { theme: "stripe" } }}>` — **no `wallets` key**, no `loader` config, no `paymentMethodConfiguration` id.

**Verdict:** `PaymentElement` with no wallet overrides. Stripe's default is `wallets.link: 'auto'` which **auto-attaches Link whenever the SetupIntent's Customer email matches a Link account or whenever the browser already carries a Link session cookie**. The admin's Chrome has their personal Link cookie → Elements happily offers that saved PM.

### Grep confirmation
- `wallets`, `payment_method_types`, `LinkAuthenticationElement`, `payment_method_configuration` — **zero** usage anywhere in `frontend/src/components/payments/` and `frontend/src/pages/public/AddCardPage.jsx`.
- Three FE surfaces mount a Link-capable PaymentElement with identical un-tuned options:
  1. `components/payments/StripeAddCardForm.jsx` (portal + admin Customer Detail).
  2. `pages/public/AddCardPage.jsx:97, 245-250` (public magic-link add-card page `/customers/add-card/{token}`).
  3. `pages/BusinessSignup.jsx` (tenant signup — card-on-file at onboarding; same options shape).

---

## 3. BE audit — SetupIntent creation

### Endpoint
- `POST /api/payments/stripe/setup-intent` → `backend/routers/stripe_router.py:157` → `post_setup_intent`.
- Role gate: self-serve customer uses `user.customer_id`; admin must pass body `customer_id` (admin impersonation route hits the latter).
- Delegates to `backend/services/payments/stripe_charge.py:437` → `create_setup_intent`.

### Request parameters observed in Stripe.SetupIntent.create
- `customer=<stripe_customer_id>` (always set).
- `payment_method_types=["card"]` **by default** (`stripe_charge.py:500-502`). ACH path overrides with `["us_bank_account"]`.
- `usage="off_session"` (hardcoded line 511).
- `metadata={crm_customer_id, crm_tenant_id, actor_user_id}` + idempotency key.
- `payment_method_options.us_bank_account.verification_method="instant"` added only when `us_bank_account` is in types.

### Key observation
**`payment_method_types=["card"]` is already passed, but it does NOT disable Stripe Link.** Stripe treats Link as a wallet overlay on top of card payment methods — it is NOT a separate PM type that `payment_method_types=['card']` filters out. The authoritative knob is a FE-side **`wallets.link: 'never'`** option on the Elements provider, or a BE **`payment_method_configuration`** pointing at a Dashboard config that disables Link, or **Dashboard-level Link disable** for the Stripe account.

No `automatic_payment_methods={"enabled": True}` is used by `create_setup_intent`. There IS one usage in the tree (`backend/services/payments/tenant_stripe.py:315`), but that is on the per-tenant Stripe module's `create_payment_intent` for a different (multi-tenant Connect) code path — it is **not** reached by the portal SetupIntent flow.

---

## 4. Stripe Link disable options — knobs available

### Option A — FE `wallets.link = 'never'` on `<Elements>` options (RECOMMENDED)
Single-source fix. Change in `StripeAddCardForm.jsx` from:
```js
options={{ clientSecret, appearance: { theme: "stripe" } }}
```
to:
```js
options={{
  clientSecret,
  appearance: { theme: "stripe" },
  wallets: { link: "never", applePay: "never", googlePay: "never" },
}}
```
- **Pros:** 1 LOC per surface. Matches desired-state screenshot (Card/Bank toggle + raw card form). No BE change. No Dashboard change required. Works for every PaymentElement surface (portal, admin, public, signup) by sweeping all three mount sites.
- **Cons:** FE-only. Does not protect the hosted Checkout Session (invoice pay-now) flow; that needs Option C.
- **PaymentElement behaviour**: with `wallets.link="never"`, Link is removed from the tabs UI AND Stripe skips the Link-account-detection prefill entirely. The `fields.billingDetails` + card form render as per the desired-state screenshot. Card/Bank tabs stay visible because the SetupIntent accepts card AND the FE PaymentMethodTiles renders a separate Bank section via its own flow.
- **Matches screenshot 2 fidelity**: ✅ exact match.

### Option B — BE `payment_method_types=['card']` (ALREADY DONE for SetupIntent)
Already in effect for `create_setup_intent`. Does **not** disable Link because Link is a wallet, not a payment method type. Partial defence-in-depth already present.

### Option C — BE `payment_method_types=['card']` on `checkout.Session.create` (invoice pay-now)
`backend/services/payments/stripe_charge.py:1568-1598` builds `session_kwargs` **without** `payment_method_types`. Hosted Checkout then auto-advertises every method enabled in the Stripe Dashboard — Link included. Adding `payment_method_types=['card']` here is the equivalent of Option A for the hosted Checkout surface. **(Still does not disable Link entirely — Stripe hosted Checkout's Link disable requires `payment_method_types=['card']` + `payment_method_options.card.setup_future_usage` + account-level Link disable, OR a `payment_method_configuration` id.)**

### Option D — Switch to `<CardElement>`
Replace `PaymentElement` with `CardElement` in all three FE surfaces. Removes Link possibility by construction (CardElement renders a single card-number row, no tabs, no wallet UX). **This does NOT match the desired-state screenshot** which shows a Card/Bank toggle + full billing-details form. Rejected.

### Option E — Stripe Dashboard `payment_method_configuration` with Link disabled
Create a Dashboard PaymentMethodConfiguration that excludes Link, then pass the config id on SetupIntent / Session creates. Works everywhere, but requires Dashboard write + env var round-trip. Over-engineered for a 2-LOC change.

### Option F — Operator disables Link account-wide in Stripe Dashboard
Settings → Payment methods → Link → disable. Sweeps every surface in one click. Trade-off: eliminates any future Link-based UX for every tenant customer, which may be a product decision. **Fastest fix** if operator consents.

---

## 5. Admin impersonation + Link cross-contamination

**Risk is real.** Stripe Link's PM-detection logic reads from the browser's Stripe-domain cookies and from the SetupIntent Customer email. During admin impersonation:
- The impersonation banner at the top of the portal (visible in screenshot 1 as "Viewing as Seth & Ashley Wilson · Admin session paused") tells the app which customer we're acting-as.
- The SetupIntent is created with the correct Stripe Customer id for Seth & Ashley Wilson (BE `_is_customer(user) → False → admin path → target_id=body.customer_id`, verified at `stripe_router.py:171-173`).
- But the FE PaymentElement **ignores the SetupIntent Customer** when matching a Link account — it uses the browser's existing Link session cookie, which belongs to the admin's personal Chrome. Stripe pre-fills the admin's "Chase Business Debit ••6538" and emails the admin's `brianbeckmanaz@gmail.com` for OTP confirmation.
- If the admin clicks **Confirm** without reading, Stripe runs `confirmSetup` → returns a `payment_method` id attached to the admin's Link account. Our `/payments/stripe/attach` call (StripeAddCardForm.jsx:63) then persists that PM into `db.payment_methods` scoped by the IMPERSONATED customer's `customer_id` because the attach endpoint trusts the admin's role and the body-passed `customer_id`. **Result: admin's personal card is stored on the customer's record and would be charged on the next autobilling run.**

This is **not** a BE RBAC bug — the BE correctly scopes to the impersonated customer. It is a Stripe Elements browser-session leak that only surfaces when **the admin uses a browser that has an active Link session**. Any shared-browser household (customer sharing a laptop with a family member who has Link) hits the same leak.

**Strongest remediation is still Option A (`wallets.link = 'never'`)**, because it removes Link's auto-detect entirely at the Element level regardless of browser state.

---

## 6. Scope + risk

- Portal is customer-facing on production (`app.plofv.com/portal/payment-method`). Any FE change must preserve the Save-card happy path.
- Same `StripeAddCardForm` is reused by **admin Customer Detail → Payments tab** (`AdminCardCapturePanel.jsx:418`). Fixing at the component layer sweeps both surfaces in one shot — no divergence risk.
- `pages/public/AddCardPage.jsx` (magic-link add-card for customers who don't log in) uses a **local** Elements/PaymentElement mount — the fix would need to be applied there too (one extra line in that file).
- `pages/BusinessSignup.jsx` — tenant onboarding card-on-file. Not the same leak target (new tenant signup, not impersonation), but applying the same `wallets.link = 'never'` keeps the UX consistent and prevents future surprise if a tenant owner shares a browser.
- Bank-account add path (`StripeAddBankForm.jsx`) uses `us_bank_account` SetupIntent + Financial Connections — Link does not apply there, no change needed.
- Changing from `PaymentElement` to `CardElement` would break the Card/Bank toggle UX from screenshot 2 and remove useful features (Apple/Google Pay, saved-card prefill for same-user return visits). Flag — do NOT recommend.

---

## 7. Classification + operator decisions

**Classification:** **FE Elements config miss** (`wallets.link` left at default `"auto"`). ~5 LOC FE patch, ~5 LOC test. Not a code bug per se — a Stripe default that is incompatible with our admin-impersonation + customer-browser-leak threat model. Also surfaces a parallel privacy risk on hosted Checkout for the pay-now flow (Option C).

**Operator Y/N questions for Phase 2:**

- **D1.** Approve FE `wallets: { link: 'never', applePay: 'never', googlePay: 'never' }` on `<Elements>` options in **`StripeAddCardForm.jsx`** (portal + admin Customer Detail). ⟶ **recommended Y**.
- **D2.** Apply the same `wallets.link = 'never'` to **`pages/public/AddCardPage.jsx`** (magic-link add-card). ⟶ recommended Y (consistency + protects shared-browser customers).
- **D3.** Apply the same `wallets.link = 'never'` to **`pages/BusinessSignup.jsx`** (tenant signup card-on-file). ⟶ recommended Y (cheap, prevents future leak surface).
- **D4.** Add BE `payment_method_types=['card']` to the invoice pay-now **`checkout.Session.create`** kwargs in `stripe_charge.py:1568` (invoice pay-now Link disable at hosted Checkout layer). ⟶ recommended Y (same cross-contamination leak class).
- **D5.** Keep `PaymentElement` (not switch to `CardElement`). ⟶ recommended Y (desired-state screenshot requires Card/Bank toggle UX).
- **D6.** Operator-side option: disable Stripe Link in the Stripe Dashboard account-wide. Belt-and-braces on top of D1-D4; or substitute for them if operator wants a one-click Dashboard-only fix. ⟶ operator preference.
- **D7.** Preserve admin "charge saved card" + autobilling paths — these do **not** touch Elements and are unaffected by any of D1-D5. Confirm no additional work expected there.

---

## 8. Phase 2 cost estimate

- **Option A sweep** (D1-D3): ~5 LOC across 3 files, 1 LOC each in `options={…}` prop; `~15 LOC` of vitest coverage asserting the string `"wallets"` + `"link":"never"` appears in each mount's Elements options.
- **Option C** (D4): ~3 LOC in `stripe_charge.py:create_invoice_checkout_session` adding `payment_method_types=["card"]` + `payment_method_options={"card": {"setup_future_usage": "off_session"}}` (keeps existing save-card gate). ~10 LOC pytest asserting the kwarg presence.
- **Total**: ~30 LOC code + tests. Expect single atomic FE commit + single atomic BE commit, each < 5 min edit window; TD-61 chain-safe.

---

## 9. Hard stops honoured

- No code edits, no env mutation, no deploy actions, no testing subagent, single atomic doc commit.
- Fleet-tracking Phase 1 (operator D1-D7 from `td_fleet_tracking_always_on_phase0_scoping.md`) and TD-invoice-pay-now-stripe-unreachable (operator diagnostic paste D1-D7 from `td_invoice_pay_now_stripe_unreachable_phase0_recon.md`) remain blocked on operator decisions. Not touched.
- V15 Occurrences #6 / #7 artefacts untouched.
- `.env.example` files remain untracked (not within this ticket's scope).
- No production probing. Preview-only read-only static grep + file inspection.
