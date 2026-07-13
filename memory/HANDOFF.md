# AquaTerra Pool & Landscaping CRM — Handoff

**Handoff date:** 2026-07-13
**Build:** Phase 0 → Phase 13 complete · 283 OpenAPI paths · web + mobile + backend all running.

---

## What was built (by phase)

- **Phase 0 — Foundation.** Ported the source FastAPI backend into `/app/backend` and the Expo mobile app into `/app/mobile`. Scaffolded a fresh CRA React web app in `/app/frontend` sharing the backend.
- **Phase 1 — Auth & Dashboards.** Role-aware layouts (admin · technician · customer), JWT auth, tech clock-in gate on `/schedule`, admin dashboard KPIs.
- **Phase 2 — Customers + Jobs.** Full CRUD, VIP tags, waitlist, alerts, chemicals catalog + AI dosing, recurring visits, WO PDF/email, CSV import/export, bulk actions.
- **Phase 3 — Quotes/Invoices/Payments.** Estimates, quote→invoice conversion, master invoicing, Stripe Checkout + card-on-file + webhook, Venmo/Zelle/Cash App handles, automatic invoice SMS.
- **Phase 4 — Customer Portal.** Home/services/invoices/estimates/payments/documents/messages/profile, portal invite/reset/revoke, admin impersonation banner.
- **Phase 5 — Ops Hub.** Dispatch, schedule, routes with greedy TSP + manual reorder, workstream, crews, team, timesheets, timeclock, coverage, maintenance, pool-service, equipment + requests, price-book, log-history, job-timers, avg-job-time.
- **Phase 6 — Finance + Reports.** Reports hub, Business Summary, Forecast (weighted quotes), revenue by city/crew/customer, gross sales, invoiced items, Payments Ledger, Auto-Billing, Import/Export, Income by Category.
- **Phase 6.5 — Late fees + Terms + Portal ToS.** APScheduler daily late-fee assessor with red LATE FEE chip, global terms defaults on quotes/invoices/PDFs, versioned `legal_documents` collection + customer ack flow + admin markdown editor (live-scraped source ToS at 5,438 chars).
- **Phase 7 — Marketing Studio.** Brand memory, campaigns, one-shot AI generation per channel, post generator, hero images, approval queue with publish enforcement, calendar, auto-scheduler cron, performance dashboard, AI review reply drafts, multi-agent @mention chatter, 6 seeded campaign templates, 5 email templates, 3 SMS templates. **Sequence Automations Engine** with 3 seeded sequences (Welcome, Reactivation, Overdue Invoice). Overdue auto-enroll piggybacks on late-fee cron.
- **Phase 8 — SEO Studio + WordPress + GBP.** Article editor with keyword suggest + audit + rank grid, WordPress publish settings + test-connection, GBP Hub (connection state, posts, reviews, business info, calendar, AI settings — degrade gracefully without OAuth creds).
- **Phase 9 — AI Employees + Tasks + Comms + Access.** 8 seeded personas (Ava/Max/Riley/Sam/Nora + 3 marketing agents), AI Chat with persistent per-employee threads, Tasks CRUD + kanban + escalation task auto-created on Day-30 of Overdue Invoice Sequence, unified Communications inbox, Notifications bell + unread count, Access Settings permissions matrix, Access History audit viewer, RingCentral webhook + call logs + settings.
- **Phase 10 — D2D Sales.** Dashboard, canvassing map (Leaflet + Zillow blue pins via OpenWeb Ninja), knocks CRUD, open leads, sold leads, team report + CSV, gamified leaderboard. Retroactive Leaflet on `/dispatch/map` and `/schedule/map`. `MapView` swaps Leaflet ↔ Google Maps by `settings.map_provider`. `AddressAutocomplete` component (Google Places) on customer forms. `/settings/integrations` + geocode backfill.
- **Phase 11 — AI & Tools.** Landscape AI (photo → styled photoreal render via Gemini nano-banana), CAD Studio (canvas editor with elements + JSON persist), Satellite Measure (Esri tiles + shoelace area), Virtual Bid (Zillow lookup + Claude bid narrative + tiered pricing), Digital Business Card (admin editor + public `/public/card/:slug` + `.vcf` download), Weather (7-day risk grid + reschedule recs).
- **Phase 12 — Polish.** Dead-code cleanup, `.env.example` × 3, `robots.txt` + `sitemap.xml`, branded 404/500, Landscape render enhanced with description + shopping-list, `/settings/integrations` now with 10 integrations + real health-check buttons, CAD editor mobile guard.
- **Phase 13 — Parity + E2E + Handoff.** Full parity audit, 2 gap closures (`/leads`, `/checkins`), 3 E2E user-journey pytest files, `seed_frozen.py` idempotent demo seed, this document.

---

## Preview URLs

- **Web (React):** https://poolscape-audit.preview.emergentagent.com
- **Backend API:** https://poolscape-audit.preview.emergentagent.com/api  (OpenAPI at `/api/openapi.json`)
- **Expo mobile preview:** delivered via Expo tunnel — `EXPO_TUNNEL_PROXY_URL` in `/app/mobile/.env`
- **Production deployment:** https://poolscape-audit.emergent.host (redeploy from preview to push new changes)

## Demo accounts (all password `password123`)

| Role | Email |
|---|---|
| Admin | `admin@aquaterra.com` |
| Technician | `mike@aquaterra.com` |
| Customer | `customer@aquaterra.com` |

Additional seeded internal accounts for team + roster testing may exist — refer to `/app/backend/seed.py`.

## Live integrations

- **Emergent LLM** — Claude Sonnet 4.5 + Gemini 3.1 nano-banana image generation (chat, marketing generator, SEO articles, chemistry dosing, virtual-bid narrative, landscape rendering).
- **Google** — Places autocomplete + Geocoding + Maps tiles + Directions (unrestricted key — recommend restricting to app domains in Cloud Console).
- **OpenWeb Ninja (Zillow)** — Recently-sold homes for D2D + property lookup for Virtual Bid.
- **Resend** — Transactional email. Sender `onboarding@resend.dev` — verify a domain in Resend to unlock full delivery.
- **Stripe (test mode)** — Checkout, card-on-file, webhook payload accepted (unsigned fallback until signing secret is added).

## Not-yet-configured integrations

Provide these in `/app/backend/.env` then `sudo supervisorctl restart backend`:

| Env var | Purpose | How to get it |
|---|---|---|
| `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` + `TWILIO_FROM_NUMBER` | SMS delivery | twilio.com/console |
| `GBP_CLIENT_SECRET` | Google Business Profile OAuth | Google Cloud Console → OAuth Client. Also requires GBP API allow-listing from Google (multi-week process). Redirect URI: `https://poolscape-audit.preview.emergentagent.com/api/gbp/oauth/callback` |
| `WORDPRESS_URL` + `WORDPRESS_USER` + `WORDPRESS_APP_PASSWORD` | Auto-publish SEO articles | WP dashboard → Users → Application Passwords |
| `STRIPE_WEBHOOK_SECRET` | Signed webhook verification | Stripe dashboard → Developers → Webhooks |
| RingCentral outbound API | Placing calls from CRM | Configure via `/settings/ringcentral` |

## Native-only (Expo mobile) features

Browsers cannot host these — they intentionally remain mobile-only:

- **Background geofence auto clock-in/out** — uses `expo-location` background tracking.
- **Native camera capture** — falls back to `<input type="file" capture>` on web (already wired in Landscape AI + Measure + job photos).
- **react-native-maps performance** — mobile uses native map for D2D canvassing; web uses Leaflet or Google Maps depending on `settings.map_provider`.

## Deferred backlog

- **Permissions-matrix per-page enforcement UI** — backend matrix persists (Phase 9); needs a dedicated frontend sweep across every page.
- **"Test as..." role preview** — depends on above.
- **In-app `.env` editor for integrations** — deferred; supervisor-managed `.env` reloads are fragile.
- **Comprehensive currency/date/timestamp + skeleton + empty-state audit** — spot-checks are green; systematic sweep deferred.
- **Native forms admin** (Expo `/forms`) not yet ported to web.
- **Unified communications thread view** (Expo `/communication/:id`) — web reads from `/notifications` for now.
- **Konva-powered richer CAD editor** — current click-to-place canvas is functional but not draggable/rotatable.

## Operational notes

- **Adding demo users.** Insert directly into MongoDB `users` collection with `bcrypt`-hashed password OR extend `/app/backend/seed.py`. Update `/app/memory/test_credentials.md` afterward.
- **Rotating an integration key.** Edit `/app/backend/.env` → `sudo supervisorctl restart backend`. `/settings/integrations` reflects new status. Hit "Check" on the card to confirm.
- **Freezing/resetting demo state.** `python /app/backend/seed_frozen.py` is idempotent — safe to re-run.
- **Schedulers (APScheduler).** Registered in `server.py` startup. Live cronjobs:
  - `assess_late_fees` — daily at 06:00 UTC. Applies $15 fee to invoices past due, auto-enrolls the customer in the Overdue Invoice Sequence.
  - `run_marketing_autopost` — every 30 min. Publishes queued campaign items whose `scheduled_at` matured.
  - `run_sequences_tick` — every 15 min. Advances active sequence enrollments; escalation steps create tasks + notifications.
  - `run_seo_autopublish` — hourly. Pushes scheduled SEO articles to WordPress (no-op without credentials).
  - `run_auto_chem_billing` — daily 07:00 UTC. Bills auto-approved chemistry line items to open invoices.
- **Where things live.**
  - Backend: `/app/backend/server.py` (mount + startup) · `/app/backend/routers/*.py` (34 routers).
  - Frontend: `/app/frontend/src/App.js` (route table) · `/app/frontend/src/layouts/AppLayout.jsx` (nav) · `/app/frontend/src/pages/**` (grouped by module).
  - Mobile: `/app/mobile/app/**` (Expo Router file-based).
  - Tests: `/app/backend/tests/*.py` (pytest, 45+ files).
- **Ports.** Backend `0.0.0.0:8001` · Frontend `3000` · MongoDB local via `MONGO_URL`. All supervisor-managed — do NOT start manually.

## Regression suite

Run everything:
```bash
cd /app/backend && python -m pytest tests/ -v
```

Phase 13 additions:
- `/app/backend/tests/test_e2e_journeys.py` — 3 E2E flows (admin, tech, customer).
- `/app/backend/tests/test_phase11_admin_guard.py` — Phase 11 admin gating (added by testing agent, 31 tests).
- `/app/backend/tests/test_d2d_auth_alias.py` — D2D authz + outcome/disposition alias (14 tests).

---

**Contact for continued development:** open a new Emergent conversation referencing this repository. The `/app/memory/PRD.md` and `/app/memory/parity-audit.md` are the source of truth for what's shipped vs. deferred.
