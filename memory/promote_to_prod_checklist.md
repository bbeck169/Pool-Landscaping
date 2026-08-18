# Promote-to-Production Checklist — `app.plofv.com`

> Companion doc to `/app/memory/env_vars.md` and `/app/backend/.env.production.example`.
> Prepared Feb-2026 by the coding agent. **Not a self-executing runbook** — you
> (with prod access) walk through it. Anything marked `# CONFIRM WITH USER`
> stops the promotion until you fill in the real value.

---

## 1. Pre-flight

- [ ] Working copy clean **or** every uncommitted change intentional.
    - Current uncommitted files at time of prep:
      ```
      M backend/.env.example
      M frontend/yarn.lock
      M mobile/yarn.lock
      ?? test_reports/p41d_batch_stream.log
      ?? test_reports/p41d_cov.log
      ```
- [ ] Branch: `main`
- [ ] Commit sha snapshot: `45182d7cce011e1313b8c4da012c81ab2cef1040` (`45182d7`)
- [ ] Preview URL currently serving this build: `https://poolscape-audit.preview.emergentagent.com`
- [ ] Session-verified tests green (this session):
      - vitest ×40, jest ×12, pytest ×24 = **76 total**
      - Includes: Schedule notes cap, "+ New Scheduled Job" pre-fills, demo-logins hostname strict gate, `/config/features` endpoint, Routes enrichment.
- [ ] `/app/memory/known_issues.md` reviewed — no blocker rows.

---

## 2. Backend env vars to SET on prod (`app.plofv.com`)

Paste block, then replace each `# CONFIRM WITH USER` with the real value before saving.

```
APP_ENV=production
SHOW_DEMO_LOGINS=false
STRIPE_MODE=live
CORS_ORIGINS=https://app.plofv.com,https://www.plofv.com   # CONFIRM WITH USER (add any other prod front-door hostnames)
COMMS_TEST_ALLOWLIST_EMAILS=
COMMS_TEST_ALLOWLIST_PHONES=
# COMMS_WHITELIST_MODE is NOT a var currently read by the codebase.
# The whitelist is enforced whenever APP_ENV != production (see
# services/comms_env_guard.py::_app_env). Setting APP_ENV=production
# above is the switch that flips comms to fail-open for real
# recipients. No additional flag needed.
```

Additional prod-safe values (also flip if not already correct):
```
STRIPE_SECRET_KEY_LIVE=sk_live_…       # CONFIRM WITH USER (real live secret key)
STRIPE_WEBHOOK_SECRET_LIVE=whsec_…     # CONFIRM WITH USER (live webhook signing secret from Stripe dashboard)
STRIPE_PUBLISHABLE_KEY_LIVE=pk_live_…  # CONFIRM WITH USER (pk_live_...; visible in Stripe dashboard)
JWT_SECRET=…                           # CONFIRM WITH USER (must NOT be the preview value; rotate if unsure)
DB_NAME=poolscape                      # CONFIRM WITH USER (prod DB name — may differ from preview "aquaterra")
MONGO_URL=…                            # CONFIRM WITH USER (prod cluster URI)
APP_BASE_URL=https://app.plofv.com
LUMINO_RETURN_URL=https://app.plofv.com/portal/payment-method/return
```

---

## 3. Backend env vars to KEEP unchanged

**Do not clobber** during the promotion — these are secrets already provisioned:

- `EMERGENT_LLM_KEY` — universal LLM key (OpenAI / Claude / Gemini text + Nano Banana + Sora + Whisper).
- `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET` — transactional email.
- `RC_CLIENT_ID`, `RC_CLIENT_SECRET`, `RC_JWT`, `RC_SERVER_URL`, `RC_WEBHOOK_URL`, `RC_VERIFICATION_TOKEN`, `RC_MODE` — RingCentral voice/SMS.
- `HOMEWORKS_*` / OAuth DCR client secrets (if provisioned separately).
- `GOOGLE_API_KEY`, `GBP_CLIENT_ID`, `GBP_CLIENT_SECRET`, `GOOGLE_MAPS_API_KEY` (backend-side).
- `OPENWEB_NINJA_API_KEY`, `WEATHERAPI_KEY`, `YELP_API_KEY`, `MAPBOX_ACCESS_TOKEN`.
- `LUMINO_API_URL`, `LUMINO_API_TOKEN`, `LUMINO_WEBHOOK_SECRET`, `LUMINO_ZAPIER_SHARED_SECRET`.
- `ZAPIER_INVOICE_LINK_WEBHOOK_URL`, `SUPERCOOL_MCP_URL`, `MCP_TOKEN_ENCRYPTION_KEY`.
- `WORDPRESS_URL`, `WORDPRESS_USER(NAME)`, `WORDPRESS_APP_PASSWORD`, `WORDPRESS_AUTO_PUBLISH`.
- `METERED_TURN_URLS`, `METERED_TURN_USERNAME` — Walkie-Talkie WebRTC.
- `TURNSTILE_SECRET` (if enabled).

If any of these are **currently empty in prod** and you need them working, provision them separately — this checklist does not touch them.

---

## 4. Frontend build env

Repo state:
- `/app/frontend/.env` → currently seeded for **preview** (`REACT_APP_BACKEND_URL=https://poolscape-audit.preview.emergentagent.com`, `REACT_APP_PUBLIC_ENV=preview`).
- `/app/frontend/.env.production` — **does NOT exist yet**. Emergent-managed deploy substitutes the backend URL at build time; confirm with the platform team before creating one.

At build/deploy time the prod frontend bundle must have:
```
REACT_APP_BACKEND_URL=https://app.plofv.com
REACT_APP_PUBLIC_ENV=production
```
`WDS_SOCKET_PORT=443` and the Google Maps keys are safe to keep as-is (public keys, referrer-restricted in Google Cloud Console).

**Belt-and-suspenders reminder**: even if `REACT_APP_PUBLIC_ENV=preview` accidentally ships in the prod bundle, the client-side hostname gate (`src/utils/env.js::isPreviewOrDev()`) will still hide the demo-logins block on `app.plofv.com`. That check is the durable defense.

---

## 5. Mobile Expo build env

Repo state (`/app/mobile/.env`):
```
EXPO_PUBLIC_BACKEND_URL=https://poolscape-audit.preview.emergentagent.com
EXPO_PUBLIC_ENV=preview
EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_51NE9yg…RwKZ   # already committed; verify this matches prod
```

Before an `eas build --profile production` (or App Store / Play Store submission), the mobile `.env` (or `eas.json` production profile) must have:
```
EXPO_PUBLIC_BACKEND_URL=https://app.plofv.com
EXPO_PUBLIC_ENV=production
EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_…             # CONFIRM WITH USER (match backend STRIPE_PUBLISHABLE_KEY_LIVE)
EXPO_PUBLIC_GOOGLE_API_KEY=…                             # CONFIRM WITH USER (prod-referrer-restricted key)
EXPO_PUBLIC_GOOGLE_MAPS_API_KEY=…                        # CONFIRM WITH USER
EXPO_PUBLIC_MAPBOX_TOKEN=                                 # optional; leave blank if unused in prod
```

**Do not ship a mobile build with `EXPO_PUBLIC_ENV=preview`.** The hostname gate in `mobile/src/utils/env.ts::isPreviewOrDev()` reads `EXPO_PUBLIC_BACKEND_URL`, so as long as the backend URL is `app.plofv.com` the demo-tiles gate stays closed. Still — flip the label to `production` for observability.

`pk_live_51NE9yg…RwKZ` is currently committed to the mobile `.env` — that is safe (publishable key, not secret), but confirm it matches the backend `STRIPE_PUBLISHABLE_KEY_LIVE` before shipping.

---

## 6. Deploy steps

No `Dockerfile` / `render.yaml` / `fly.toml` / `vercel.json` exists in the repo → deploy path is **Emergent-managed** (platform button / `deployment_agent`).

- [ ] Commit + push all doc updates (this file, `.env.production.example`, `env_vars.md`, `known_issues.md`) to `main`.
- [ ] Verify commit sha lands in the deploy pipeline (should be a descendant of `45182d7`).
- [ ] On the Emergent dashboard for `app.plofv.com`: open Env Vars, apply Section 2 diff, save.
- [ ] Trigger deploy of the current `main`.
- [ ] Wait for platform "healthy" callback (60–90s typical based on preview boot times).

If the deploy path is actually something else (Docker Compose on a VPS, Render, Fly, …) — grep once more, adjust this section, and re-verify with the user.

---

## 7. Post-deploy smoke checklist

Run in order. Each must pass before moving on.

**7a. Backend reachability**

There is **no `/api/health` endpoint** in this codebase (checked `/app/backend/server.py` + all routers). Use the public config endpoints as reachability probes instead:

```bash
curl -sS -m 8 -o /dev/null -w "%{http_code}\n" https://app.plofv.com/api/
# expected: 200

curl -sS -m 8 https://app.plofv.com/api/config/features
# expected: {"demo_logins_enabled": false}

curl -sS -m 8 https://app.plofv.com/api/config/public
# expected: {"show_demo_logins": false, "app_env": "production"}
```

**7b. Web login page** — open `https://app.plofv.com/login` in a fresh incognito window.
- [ ] Sign-in form renders.
- [ ] The "DEMO LOGINS (Preview Only)" block is **NOT visible**.
- [ ] `super@aquaterra.com` / `admin@aquaterra.com` / `mike@aquaterra.com` seed accounts are **NOT** listed anywhere on the page.

**7c. Authenticated smoke** — log in as a real prod admin account.
- [ ] `/schedule` — grid mode loads, job cards render `notes` when present (`data-testid="job-{id}-notes"`, 2-line clamp).
- [ ] `/routes` — pick a real tech + date, stops render with tech name + color chip; deleted-customer jobs fall back to address.
- [ ] `/jobs/{any}` — click **+ New Scheduled Job** in the header. Modal opens with customer / property / technician pre-filled, `SERVICE TYPE` reads `"Choose a service…"` (blank), scheduled date defaults to today. Submit → toast `Job scheduled for {customer_name} on {date}` — you stay on the original job.

**7d. Comms whitelist active**
- [ ] From a non-demo (real customer) account, trigger an outbound email (e.g. Work Order → Email) and/or SMS (dispatch notify).
- [ ] Confirm the message actually delivers to the real recipient (i.e. the preview allowlist is no longer suppressing).
- [ ] Verify `comms_suppression_log` collection has NO new rows for this delivery — the preview-mode suppression should be inert now that `APP_ENV=production`.

**7e. Stripe live mode**
- [ ] `/api/config/public.stripe_mode` returns `"live"`.
- [ ] Frontend Stripe Elements loads with a `pk_live_…` publishable key (browser devtools → network → any Stripe call).
- [ ] Run a $0.50 real card charge on a low-risk test invoice to prove the pipeline; refund immediately. (Optional — skip if the ops team has already validated live-mode payments in another window.)

**7f. Mobile smoke** (if a fresh EAS build is going out with this deploy)
- [ ] Install the new build on a test device.
- [ ] Open `/login` — demo tiles NOT visible.
- [ ] Log in, open a job, tap `+ New Scheduled Job` — service type reads placeholder `"Select service type"` (blank).

---

## 8. Rollback plan

If **7a/7b/7c** fails:
- [ ] In Emergent dashboard → Deploys → pick the previous "healthy" sha → **Redeploy**.
- [ ] Env-var revert: keep a copy of the pre-change env dump (Emergent dashboard "Export env" or hand-copy Section 2 before saving). Paste back and save.
- [ ] Restore `SHOW_DEMO_LOGINS` / `APP_ENV` to their prior values ONLY if the rollback deploy needs them to boot; the client hostname gate remains active in either direction so the demo-tiles risk stays defused.

If **7d** fails (real email/SMS still suppressed): confirm the backend actually rebooted after the env change — the comms env guard reads `os.environ` at request time, but some adapter modules cache the value at import; a supervisor restart / redeploy resolves it.

If **7e** fails (test charge errors): flip `STRIPE_MODE` back to `test` temporarily so the app keeps functioning, then debug live-mode credentials out-of-band. The `/config/public` publishable key surface is safe to switch on demand — no user data is at risk.

---

## 9. Known gaps to accept before deploy

Reviewed against `/app/memory/known_issues.md` and this session's work:

- **Mobile Routes screen** — not yet built. Web Routes tab (with enrichment) is live; mobile users tap through Schedule instead. Non-blocking for launch.
- **Phase 3 pricebook manual-pricing UI** — parked. 518 items lack `supplier_prices` (audit already run). Margin reports are less accurate for those items until the UI ships. Non-blocking.
- **Tech-id fragmentation** — same human sometimes has different `users.id` vs `technicians.id`; the Routes enrichment endpoint already patches over this server-side but the underlying store is still fragmented. Cosmetic-only downstream.
- **`mobile/app/dev/file-upload.tsx`** — still gated on build-time `process.env.EXPO_PUBLIC_ENV === "preview"`. Same class of bug as the original demo-tiles issue, but blast radius is one unlinked dev-only screen. Patchable next session; NOT a launch blocker.
- **`app.plofv.com` currently has `SHOW_DEMO_LOGINS=true`, `APP_ENV=preview` seeded from a `cp .env.example .env` mistake.** Section 2 of this checklist is the fix. The client-side hostname gate deployed this session already suppresses the visible demo tiles on prod, so shipping the code first + env vars second is safe.

---

**Questions that must be answered by the user before executing Section 2**:

1. **CORS origins** — is `https://app.plofv.com,https://www.plofv.com` the complete allow-list? Any partner iframes / embedded widget hosts to add?
2. **DB posture** — does prod use the same `poolscape` DB name as the `.env.example` shows, or a different name / cluster?
3. **JWT_SECRET** — was the prod value already rotated after the preview environment was stood up, or does it still share the preview value?
4. **Stripe live credentials** — are the `sk_live_…` / `pk_live_…` / `whsec_…` values already provisioned in the prod env, or does someone need to pull them from the Stripe dashboard as part of this promotion?
5. **Comms allowlists** — should `COMMS_TEST_ALLOWLIST_EMAILS` / `COMMS_TEST_ALLOWLIST_PHONES` be emptied entirely on prod, or kept as a safety net for internal QA?

Answer inline in this file, then execute Section 2 → 6 → 7 in order.
