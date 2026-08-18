# Environment variables — Pool & Landscaping

Companion to `/app/memory/promote_to_prod_checklist.md` and
`/app/backend/.env.production.example`. Every variable read by the app
lives in this table. Grep `os.getenv(` in `/app/backend/`, `import.meta.env` /
`process.env` in `/app/frontend/src/`, and `process.env.EXPO_PUBLIC_` in
`/app/mobile/` when adding new rows.

## Quick-look flags — the ones the Feb-2026 P0 pivoted on

### `SHOW_DEMO_LOGINS`
Controls whether the login page's demo-account quick-sign-in tiles are
rendered. Default: **`false` / unset**.

* `SHOW_DEMO_LOGINS=true` → `/api/config/features` reports
  `demo_logins_enabled: true`. Combined with a preview / dev hostname
  this renders the demo tiles.
* Any other value (or unset) → `demo_logins_enabled: false`. Tiles
  are hidden regardless of hostname.

Belt-and-suspenders: the frontend ALSO requires the hostname to be a
preview / dev host (`isPreviewOrDev()` in `src/utils/env.js` for web,
`mobile/src/utils/env.ts` for mobile). Neither gate on its own is
sufficient — both must agree.

**Production posture**: leave `SHOW_DEMO_LOGINS` unset (or explicitly
`false`) on every customer-facing deploy (`app.plofv.com` etc.). This
defends against a mis-configured hostname somehow slipping past the
client gate — the server never advertises the flag as enabled.

### `APP_ENV`
Downstream services consult this for preview-vs-production behaviour
(comms whitelist, Stripe demo-mode, Zillow guardrails, Lumino test
gate, QBO sandbox path, etc.). Must reflect the deploy accurately:

* `APP_ENV=production` on `app.plofv.com` and any other customer host.
* `APP_ENV=preview` on `*.preview.emergentagent.com`.
* `APP_ENV=development` on local dev.

Not used for the demo-logins gate anymore (see Feb-2026 P0 hotfix #3),
but every other consumer still relies on it.

---

## Full table

Columns:
- **Var** — env var name.
- **Prod safe value** — what to put in `app.plofv.com`'s env. `TODO` = real secret from ops.
- **Purpose** — what the code does with it.
- **Read by** — `be` (backend), `fe` (web), `mo` (mobile).

| Var | Prod safe value | Purpose | Read by |
| --- | --- | --- | --- |
| `MONGO_URL` | `TODO` — prod cluster URI | Primary datastore. | be |
| `DB_NAME` | `poolscape` (confirm) | Mongo database name. | be |
| `CORS_ORIGINS` | `https://app.plofv.com,https://www.plofv.com` | Whitelisted browser origins. Never `*` in prod. | be |
| `JWT_SECRET` | `TODO` — rotate | HS256 signing secret for auth tokens. | be |
| `JWT_TTL_MINUTES` | `1440` | Auth token lifetime. | be |
| `APP_ENV` | `production` | Global env label (comms whitelist, Zillow / Lumino / Stripe test gates). | be |
| `APP_BASE_URL` | `https://app.plofv.com` | Used in email links + Lumino return URL. | be |
| `SHOW_DEMO_LOGINS` | `false` (or unset) | Feature flag surfaced via `/api/config/features`. | be |
| `EMERGENT_LLM_KEY` | `TODO` | Emergent universal key: Claude Sonnet text, GPT + image gen, Gemini + Nano Banana, Sora 2, Whisper. | be |
| `OPENAI_API_KEY` | (blank) | Only set if a dedicated OpenAI account is needed. | be |
| `RESEND_API_KEY` | `TODO` | Transactional email delivery. | be |
| `EMAIL_FROM` | `cs@plofv.com` | Reply-to / from address. | be |
| `RESEND_FROM_ADDRESS` | `cs@plofv.com` | Explicit sender. | be |
| `RESEND_FROM_NAME` | `Pool & Landscaping of Vistancia` | Display name. | be |
| `RESEND_FROM` | `cs@plofv.com` | Legacy alias — some code paths still read it. | be |
| `RESEND_WEBHOOK_SECRET` | `TODO` | Verifies inbound Resend webhooks. | be |
| `GOOGLE_API_KEY` | `TODO` | Backend Google APIs (maps geocode, places). | be |
| `GBP_CLIENT_ID` / `GBP_CLIENT_SECRET` | `TODO` | Google Business Profile OAuth. | be |
| `GOOGLE_GBP_INTEGRATION_ENABLED` | `true` (when GBP live) | Toggle for GBP scraper cron. | be |
| `OPENWEB_NINJA_API_KEY` | `TODO` | Property / Zillow enrichment. | be |
| `WORDPRESS_URL` / `WORDPRESS_USER(NAME)` / `WORDPRESS_APP_PASSWORD` / `WORDPRESS_AUTO_PUBLISH` | (blank or `false`) | Blog auto-publish (WooCommerce plugin). Opt-in. | be |
| `FACEBOOK_INTEGRATION_ENABLED` | `false` | Facebook cross-post toggle. | be |
| `YELP_API_KEY` | `TODO` if used | Yelp reviews scraper. | be |
| `WEATHERAPI_KEY` | `TODO` | Schedule-page weather strip. | be |
| `RC_CLIENT_ID` / `RC_CLIENT_SECRET` / `RC_JWT` / `RC_SERVER_URL` / `RC_WEBHOOK_URL` / `RC_VERIFICATION_TOKEN` / `RC_MODE` | `TODO` (all secrets) | RingCentral voice + SMS. `RC_MODE=live` in prod. | be |
| `SUPERCOOL_MCP_URL` | `https://mcp.supercool.com/mcp` | Homeworks MCP endpoint. | be |
| `MCP_TOKEN_ENCRYPTION_KEY` | `TODO` — 32-byte b64 | AES-GCM key for MCP OAuth token storage. | be |
| `SUPERCOOL_DAILY_IMAGE_LIMIT` | `100` | Per-tenant/day AI-image cap. | be |
| `COMMS_TEST_ALLOWLIST_EMAILS` | (blank in prod) | Preview allowlist. Whole whitelist bypassed when `APP_ENV=production`. | be |
| `COMMS_TEST_ALLOWLIST_PHONES` | (blank in prod) | Same as above for SMS. | be |
| `PAYMENT_PROVIDER` | `stripe` | Selects Stripe vs Lumino as primary. | be |
| `STRIPE_MODE` | `live` | Selects live vs test key pair. | be, fe, mo |
| `STRIPE_SECRET_KEY_LIVE` | `TODO` — `sk_live_…` | Live-mode server secret. | be |
| `STRIPE_WEBHOOK_SECRET_LIVE` | `TODO` — `whsec_…` | Verifies live webhook signatures. | be |
| `STRIPE_PUBLISHABLE_KEY_LIVE` | `TODO` — `pk_live_…` | Public key surfaced via `/api/config/public`. | be, fe, mo |
| `STRIPE_SECRET_KEY_TEST` / `STRIPE_WEBHOOK_SECRET_TEST` / `STRIPE_PUBLISHABLE_KEY_TEST` | (blank in prod) | Test-mode counterparts. Prod should NOT rely on them. | be |
| `PAYMENTS_TEST_ALLOWLIST_CUSTOMERS` | (blank in prod) | Preview allowlist for real charges during QA. | be |
| `LUMINO_API_URL` / `LUMINO_API_TOKEN` / `LUMINO_WEBHOOK_SECRET` / `LUMINO_RETURN_URL` / `LUMINO_ZAPIER_SHARED_SECRET` | `TODO` | Alt payment rail (Zapier bridge). | be |
| `ZAPIER_INVOICE_LINK_WEBHOOK_URL` | `TODO` | Zapier catch-hook for invoice links. | be |
| `MAPBOX_ACCESS_TOKEN` | `TODO` — `pk.eyJ…` (safe to expose) | Dispatch-board map tiles. Blank → fallback banner. | be |
| `METERED_TURN_URLS` / `METERED_TURN_USERNAME` | `TODO` if walkie-talkie feature live | metered.ca TURN servers for WebRTC. | be |
| `TURNSTILE_SECRET` | (blank unless enabled) | Cloudflare Turnstile challenge. | be |
| `REACT_APP_BACKEND_URL` | `https://app.plofv.com` | All web `/api/*` calls key off this. | fe |
| `REACT_APP_PUBLIC_ENV` | `production` (informational only) | Legacy label — no longer gates demo tiles. | fe |
| `REACT_APP_GOOGLE_API_KEY` / `REACT_APP_GOOGLE_MAPS_API_KEY` | Prod-referrer-restricted key | Web map surfaces. Safe to expose (public keys). | fe |
| `WDS_SOCKET_PORT` | `443` | Vite HMR socket port (harmless in prod build). | fe |
| `ENABLE_HEALTH_CHECK` | `false` | Legacy toggle for a health probe route. Currently unused. | fe |
| `EXPO_PUBLIC_BACKEND_URL` | `https://app.plofv.com` | Mobile API base + used by `mobile/src/utils/env.ts` hostname gate. | mo |
| `EXPO_PUBLIC_ENV` | `production` | Informational label; a stale `preview` value here no longer leaks demo tiles thanks to `isPreviewOrDev()`. | mo |
| `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` | `pk_live_…` | Mobile Stripe surface. Must match backend `STRIPE_PUBLISHABLE_KEY_LIVE`. | mo |
| `EXPO_PUBLIC_GOOGLE_API_KEY` / `EXPO_PUBLIC_GOOGLE_MAPS_API_KEY` | Prod-referrer-restricted | Mobile map surfaces. | mo |
| `EXPO_PUBLIC_MAPBOX_TOKEN` | (blank or `pk.eyJ…`) | Optional; dispatch map falls back gracefully when blank. | mo |
| `EXPO_TUNNEL_SUBDOMAIN` / `EXPO_PACKAGER_HOSTNAME` / `EXPO_PACKAGER_PROXY_URL` / `EXPO_USE_FAST_RESOLVER` / `METRO_CACHE_ROOT` | (unset / dev-only) | Metro bundler flags — not read at runtime. | mo (build-time only) |

## Where to update this table

Add a new row when you introduce an env var. Prefer `os.getenv("X", default)`
in Python and `process.env.X` / `import.meta.env.X` in JS so a missing value
fails visibly instead of silently.
