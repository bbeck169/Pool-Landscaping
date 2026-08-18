# Environment variables — Pool & Landscaping

## `SHOW_DEMO_LOGINS` (backend, `.env`)
Controls whether the login page's demo-account quick-sign-in tiles are
rendered. Default: **`false` / unset**.

* `SHOW_DEMO_LOGINS=true` → `/api/config/features` reports
  `demo_logins_enabled: true`. Combined with a preview / dev hostname
  this renders the demo tiles.
* Any other value (or unset) → `demo_logins_enabled: false`. Tiles
  are hidden regardless of hostname.

Belt-and-suspenders: the frontend ALSO requires the hostname to be a
preview / dev host (`isPreviewOrDev()` in `src/utils/env.js`). Neither
gate on its own is sufficient — both must agree.

**Production posture**: leave `SHOW_DEMO_LOGINS` unset on every
customer-facing deploy (`app.plofv.com` etc.). This defends against a
mis-configured hostname somehow slipping past the client gate — the
server never advertises the flag as enabled.

## `APP_ENV` (backend, `.env`)
Downstream services consult this for preview-vs-production behaviour
(comms whitelist, Stripe demo-mode, Zillow guardrails etc.). Not used
for the demo-logins gate anymore (see Feb-2026 P0 hotfix #3), but
should still reflect the deploy accurately:

* `APP_ENV=production` on `app.plofv.com` and any other customer host.
* `APP_ENV=preview` on `*.preview.emergentagent.com`.
* `APP_ENV=development` on local dev.
