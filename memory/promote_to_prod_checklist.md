# Promote preview → prod runbook · `app.plofv.com`

**Last updated:** Feb-2026 · finalized after user confirmed
"default all + staged cutover" scope.

**Assumptions locked in by the user:**
- Prod host: `https://app.plofv.com` (+ `www.plofv.com` legacy).
- Prod Mongo already exists; DB name will be `poolscape`.
- Stripe **live-mode** keys are already provisioned on the prod
  backend and are NOT to be re-pasted here (`STRIPE_SECRET_KEY_LIVE`,
  `STRIPE_PUBLISHABLE_KEY_LIVE`, `STRIPE_WEBHOOK_SECRET_LIVE`).
- Comms allowlist is intentionally empty on prod (all real customer
  addresses can receive mail/SMS once `APP_ENV=production`).
- JWT secret is being ROTATED at Stage 2 (see § 2).
- Cutover is **staged**: cosmetic first, comms live second.

> No code changes ship as part of this doc. Every value below goes
> into the Emergent dashboard's env panel for the `prod` deployment.
> Never commit the JWT secret to git.

---

## 0 · Pre-flight

- [ ] Preview backend is healthy:
      `curl https://poolscape-audit.preview.emergentagent.com/api/config/features`
      → `{"demo_logins_enabled":true}` (200).
- [ ] Preview `/api/config/public` returns `{"app_env":"preview", …}`.
- [ ] Latest merge sha is deploying (double-check the Emergent
      dashboard's "Deploy from" branch).
- [ ] `_ensure_indexes` log line present on preview startup:
      `[startup._ensure_indexes] recurring_template_id_1_scheduled_date_1
       shape=partial …`
- [ ] All of THIS session's features exercised on preview at least once:
      Schedule DnD + Send-to-Dispatch, Dispatch db.jobs fallback,
      Ops Routes customer-name fix, Stripe reconciliation
      (paid_from_intents + refunded_from_intents), inline edit modal,
      monthly-nth-weekday recurrence.
- [ ] `test_credentials.md` verified so QA can log into prod after
      cutover (super/admin/manager/tech).

---

## STAGE 1 — Cosmetic-only cutover

Goal: hide the DEMO LOGINS tiles on prod, tighten CORS, but keep
`APP_ENV=preview` so the **comms whitelist stays fail-closed**. Real
customers still get suppressed at this stage. This is intentional —
one variable at a time, one blast radius at a time.

### 1.1 · Env block for the Emergent dashboard (Stage 1)

Paste EXACTLY these two variables into the prod deployment's env
panel and click "Save & redeploy":

```
SHOW_DEMO_LOGINS=false
CORS_ORIGINS=https://app.plofv.com,https://www.plofv.com
```

Leave `APP_ENV=preview` in place. Do NOT touch Stripe/JWT/DB_NAME
yet.

### 1.2 · Post-Stage-1 smoke checks

Run in this exact order — Stage 1 is not "done" until every box
below is green.

- [ ] `curl https://app.plofv.com/api/config/features`
      → `{"demo_logins_enabled": false}` · HTTP 200.
- [ ] `curl https://app.plofv.com/api/config/public`
      → `app_env: preview` (unchanged), `show_demo_logins: false`.
- [ ] Open `https://app.plofv.com/login` in incognito → the DEMO
      LOGINS block is NOT visible. Only the email + password fields
      render.
- [ ] Log in with a real admin account. Land on the dashboard.
- [ ] Navigate `/schedule` → Grid mode. Confirm the DnD panel
      renders (grip icons + tech columns). Drag a card within a
      tech → toast "Route saved". Reload → order sticks.
- [ ] From `/schedule`, click **Send to Dispatch Board** header
      button → navigates to `/admin/dispatch?date=<today>` with
      Route Details populated.
- [ ] Navigate `/dispatch` → pick a tech that has jobs today → the
      Route Details panel populates (this exercises the db.jobs
      fallback shipped Feb-2026). Non-geocoded stops show the amber
      `not geocoded` chip.
- [ ] Navigate `/routes` (Operations → Routes optimizer) → pick a
      tech → rows show the CUSTOMER NAME as the bold primary line,
      not "Weekly Pool Cleaning".
- [ ] Open any job → click **+ New Scheduled Job** → the modal
      opens blank (no `service_type` inheritance leak).
- [ ] Recurrence modal from `/jobs/new` → monthly nth-weekday
      options render for admin / super_admin / manager.
- [ ] Confirm `comms_suppression_log` in Mongo is STILL adding
      entries when you trigger a customer-facing email/SMS. Proves
      the whitelist is still fail-closed:
      ```
      db.comms_suppression_log.count_documents({}) # ← grows on each send
      ```
- [ ] No 500s in `/var/log/supervisor/backend.*.log` during the
      above walk-through.

If ANY of the above is red → stop, do NOT proceed to Stage 2. See
§ 3 Rollback.

---

## STAGE 2 — Real comms + Stripe live-mode

Only run this after every Stage 1 checkbox is green. Stage 2 flips
the whitelist off, rotates the JWT secret (which forces every logged-
in session to log in again — communicate this), and switches Stripe
to live mode.

### 2.1 · Env block for the Emergent dashboard (Stage 2)

Add / update the following variables in the prod deployment's env
panel (leave everything from Stage 1 untouched). Click "Save &
redeploy" once, not per-line:

```
APP_ENV=production
JWT_SECRET=<paste the value from the "Generated JWT secret" section
             at the bottom of THIS runbook; NEVER commit to git>
DB_NAME=poolscape
STRIPE_MODE=live
COMMS_TEST_ALLOWLIST_EMAILS=
COMMS_TEST_ALLOWLIST_PHONES=
```

Notes:
- `COMMS_TEST_ALLOWLIST_EMAILS` and `COMMS_TEST_ALLOWLIST_PHONES`
  are intentionally EMPTY. That disables the allowlist filter so
  every real customer address can receive comms.
- Do NOT re-paste `STRIPE_SECRET_KEY_LIVE`,
  `STRIPE_PUBLISHABLE_KEY_LIVE`, `STRIPE_WEBHOOK_SECRET_LIVE` — user
  confirmed those are already provisioned on the prod backend. If
  they aren't, this deploy will fail on the first webhook and Stage
  2 must be rolled back per § 3.

### 2.2 · Post-Stage-2 smoke checks

- [ ] `curl https://app.plofv.com/api/config/public`
      → `app_env: production`, `show_demo_logins: false`.
- [ ] Re-login required (JWT secret rotated). Admin login works.
- [ ] Trigger an invoice-sent email from the app to YOUR own inbox
      (make yourself a temp customer OR use the "Send test" affordance
      on an invoice). Inbox receives it within ~30 s.
- [ ] `db.comms_suppression_log.count_documents({email:"<your addr>"})`
      → the new email did NOT get suppressed (whitelist is off).
- [ ] Trigger an SMS from the app to your own phone. Phone receives
      it within ~30 s. Same check — no suppression row for this send.
- [ ] Stripe live-mode charge test — attach a real card to a test
      customer, charge $1, then refund immediately. Steps:
      1. Log into the app as admin.
      2. Pick any real customer, hit "Add card on file".
      3. Enter YOUR own card. Stripe Elements loads the LIVE
         publishable key (network tab confirms `pk_live_…`).
      4. Attach succeeds → `stripe_charges` row inserted.
      5. Create a $1.00 invoice for that customer, hit "Charge
         card on file". PaymentIntent visible in the LIVE Stripe
         dashboard.
      6. `db.quotes.findOne({id:"<invoice>"})` shows
         `payment_status:"paid"`, `paid_from_intents:["pi_live_..."]`
         (single entry, no double-count).
      7. Refund the PI from the LIVE Stripe dashboard. Webhook
         fires → `payment_status:"refunded"`, `amount_paid:0`,
         `refunded_from_intents:["chr:pi_live_...:100"]`.
      8. Replay the same webhook via the LIVE Stripe dashboard's
         "Resend event" → no drift on either field.
- [ ] Full-app smoke of all Stage 1 pages + any comms-adjacent
      flow (invoice send, appointment reminder, quote sent).
- [ ] Watch `/var/log/supervisor/backend.*.log` for 15 min. No new
      500s. No new `stripe.SignatureVerificationError`. No new
      "email suppressed — allowlist" entries for real customer
      addresses.

### 2.3 · Announce to team

- [ ] Post in `#deploys`: "Prod cutover complete. All sessions
      forced re-login (JWT rotation). Report any comms failures
      immediately."

---

## 3 · Rollback

### 3.1 · Rollback from Stage 2 → Stage 1

If Stage 2 introduces a comms outage / Stripe failure / auth issue:

- [ ] In the Emergent dashboard, flip `APP_ENV` back to `preview`.
      This alone re-arms the whitelist (fail-closed) — customers
      stop receiving comms immediately.
- [ ] Leave `SHOW_DEMO_LOGINS=false` and the CORS block in place.
      Stage 1 is intentionally NOT rolled back — demo tiles stay
      hidden regardless of env.
- [ ] `STRIPE_MODE=live` can stay set — the whitelist rollback
      alone stops the bleed. Only flip `STRIPE_MODE=test` if the
      Stripe integration itself is misbehaving.
- [ ] Force-redeploy from the dashboard.
- [ ] Verify `/api/config/public` → `app_env: preview`.

### 3.2 · Rollback from Stage 1 → pre-launch (nuclear)

Should never be needed since Stage 1 is cosmetic-only.
If a JavaScript regression from the Stage 1 build breaks the app:

- [ ] In the dashboard, redeploy the previous known-good sha.
- [ ] `SHOW_DEMO_LOGINS=false` env stays — the hostname gate in
      `frontend/src/utils/env.js` also hides demo tiles on prod
      domains as a belt-and-suspenders. Even if the env flag is
      lost, the tiles stay hidden.

---

## 4 · Post-cutover admin tasks (Vistancia specifically)

After Stage 2 is green, help Vistancia see a populated Dispatch
Board (see Feb-2026 diagnostic report):

- [ ] Run one-shot geocode backfill against Vistancia customers:
      `POST /api/admin/customers/geocode-backfill`.
- [ ] Optionally sanity-check the new db.jobs fallback: open
      `/dispatch`, pick a tech that HAS jobs on today's weekday —
      Route Details should populate even if no customer has
      `service_days` set. If not, verify the ISO date is being
      passed as `date=YYYY-MM-DD` in the network tab request.

---

## 5 · Reference — env variable table

| Var                              | Stage 1 value                             | Stage 2 value                                |
|----------------------------------|-------------------------------------------|----------------------------------------------|
| APP_ENV                          | preview  (unchanged)                      | production                                   |
| SHOW_DEMO_LOGINS                 | false                                     | false (unchanged)                            |
| CORS_ORIGINS                     | https://app.plofv.com,https://www.plofv.com | (unchanged)                                |
| JWT_SECRET                       | (unchanged — old preview value)           | <64-char rotate>  · NEVER commit to git      |
| DB_NAME                          | (unchanged)                               | poolscape                                    |
| STRIPE_MODE                      | (unchanged)                               | live                                         |
| STRIPE_SECRET_KEY_LIVE           | already provisioned                       | already provisioned                          |
| STRIPE_PUBLISHABLE_KEY_LIVE      | already provisioned                       | already provisioned                          |
| STRIPE_WEBHOOK_SECRET_LIVE       | already provisioned                       | already provisioned                          |
| COMMS_TEST_ALLOWLIST_EMAILS      | (unchanged — active)                      | ""  (disabled)                               |
| COMMS_TEST_ALLOWLIST_PHONES      | (unchanged — active)                      | ""  (disabled)                               |
| MONGO_URL                        | (unchanged — pod-provisioned)             | (unchanged)                                  |
| REACT_APP_BACKEND_URL            | https://app.plofv.com                     | (unchanged)                                  |
| EMERGENT_LLM_KEY                 | already provisioned                       | (unchanged)                                  |
| SENDGRID_API_KEY / RESEND        | already provisioned                       | (unchanged)                                  |
| RINGCENTRAL_*                    | already provisioned                       | (unchanged)                                  |

---

## 6 · Generated JWT secret

The value below was generated inside the preview pod with
`python -c "import secrets; print(secrets.token_urlsafe(64))"` at
Feb-2026 finalization time. It is stored ONLY in this runbook so
the operator can copy it into the Emergent dashboard once. **It
must never be committed to git and must never be echoed into
`backend/.env.example` or any shell history that is captured.**

```
# PASTE INTO EMERGENT DASHBOARD, DO NOT COMMIT
JWT_SECRET=XIbGHU6JqdlwM4VVeffxHkXg-8eQhUsIjAudcFW9RjG8q-b13MvGf5HirHm1KGgGMR4NQMDCsE_I3MW1Zn3UdQ
```

After Stage 2 deploys with the above value, **delete these six
lines from `/app/memory/promote_to_prod_checklist.md` immediately**
(a single git commit removing the block is fine — the secret was
never in git, only in the preview pod's memory folder).

---

## Feb-2026 · Portal P0 identity leak + add-card 404

Both fixes ship in preview. Prod (`app.plofv.com`) needs a REDEPLOY.

### Backend
- `backend/routers/portal_admin.py` — every `/portal/home` Mongo lookup now scopes by `tenant_id` in addition to `customer_id`. Response now includes `identity_mismatch: bool` when the JWT `email` claim doesn't match the resolved customer's email (log-only server-side; the frontend uses it to surface a banner).

### Frontend
- `frontend/src/pages/portal/PortalHome.jsx` — greeting now binds to `data.customer.first_name` (SERVER-scoped) first, falls back to JWT `user.name` only if the API hasn't responded. Also fixed the arrow-function body bug where `loadSummary` only included the first call.
- `frontend/src/pages/portal/PortalPaymentMethods.jsx` — reads customer id from `id || customer_id` on `/api/me` response (was reading `customer_id` which never existed on the customer doc, causing every portal user to see the "Your account isn't linked" banner + a 403 fetch to `.../payment-methods/undefined`).

### Regression tests shipped
- `backend/tests/test_portal_identity_isolation.py` (3 cases)
- `backend/tests/test_portal_payment_methods_bug2.py` (3 cases)
- `frontend/src/test/portal-identity-and-add-card.test.jsx` (5 cases)

### Post-deploy verification steps
1. Log in on prod as any portal customer.
2. Confirm the greeting matches the customer.
3. Navigate to Payment Method — confirm the page renders "You haven't added a card yet." (NOT the red "Your account isn't linked" banner). Click Add card → confirm the Stripe form loads.
4. If any portal user sees `identity_mismatch=true` in `/api/portal/home` responses, forward the pair (`user_id`, `customer_id`) to fix the DB row.
