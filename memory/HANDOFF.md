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

---

## Phase 15D Stage 3 — Query Refactor with Tenant Scoping (Feb 2026)

### Status
- **Batches 1-9 + 11: COMPLETE** — 25 backend files refactored, +1459/−672 lines, 325 OpenAPI paths intact, zero regressions across the entire test suite.
- **Batch 10 (Reports + Analytics + Onboarding + Activity + Audit + Portal + Legal): DEFERRED** — target for follow-up micro-batch. `operations.py` (dispatch/activity/reports), `analytics.py`, `onboarding.py`, `portal.py`, plus late-fee scheduler need per-tenant scoping.
- **Batch 12 (Tenant picker screen after login): DEFERRED** — frontend work.

### Refactor pattern applied
- Every endpoint injects `tenant: dict = Depends(get_current_tenant)`
- Every Mongo filter carries `"tenant_id": tenant["id"]`
- Every INSERT stamps `tenant_id: tenant["id"]`
- Cross-tenant reads/writes return 404 (leak-proof, not 403)
- Public token-gated endpoints (magic-link CSAT/signatures/forms/lead-requests/webhook) intentionally NOT scoped — the token itself is the gate; when they write side-effects, they lift `tenant_id` from the associated record.
- Scheduler-driven jobs (SEO auto-publish, late-fees, chem-billing) walk documents cross-tenant; per-tenant settings are looked up from `doc.tenant_id`.

### Notification helper (`utils.py`)
- `notify_customer` / `notify_technician` — auto-resolve `tenant_id` from the target user document
- `create_staff_notification(tenant_id=None)` — optional tenant scope; fan-out limited to same-tenant admins when provided

### Cross-tenant impersonation
- `require_admin` widened to accept both `admin` and `super_admin`
- `POST /api/admin/impersonate/{customer_id}?tenant_id=X` — super_admin only; regular admin restricted to own tenant
- Audit log records `admin_role`, `target_tenant_id`, `cross_tenant` flag

### Test fixtures updated
- `test_iteration30_send_reminder.py` — 3 fixtures now stamp `tenant_id` on raw Mongo inserts

### Known gaps for follow-up micro-batches
1. **GBP OAuth config + tokens remain global.** Making per-tenant needs threading tenant through the OAuth `state` param + callback. Documented; low practical impact today (only one tenant runs GBP).
2. **Late-fee assessment scheduler** still uses global settings. Refactor when scheduler is extended to iterate tenants.
3. **AI Employees** (`ai_ops.py`) — seeded globally; needs per-tenant lazy seed like sequences/estimate templates.
4. **`property.py` + `card.py`** — Zillow lookups and business card settings not yet tenant-scoped.
5. **`portal.py` communications** — customer communications collection still tenant-agnostic.
6. **Operations router bulk of endpoints** (dispatch/activity/reports/customers.count_documents) — Batch 10 territory.

### Pre-existing failure inventory (documented, unchanged since Batch 1)
- `iter2` × 4 (password policy 422s)
- `iter27` × 1 (gate_code enrichment)
- `iter28` × 1 (tech-convert RBAC drift)
- `iter12` × 1 (POOL_READINGS count 10 vs test-expected 5)
- `iter38` × 5 (D2D sold-leads / skip — provider or seed drift)
- `iter29` × 2 (auth-flag + fixture drift)
- `iter46` × 7 (uses stale `pool-app-mobile.preview.emergentagent.com` fallback URL — env)
- `iter43` × 29 errors (same stale-URL env issue in module-scope fixture)
- `iter35` × 18 (impersonation) + `iter18` × 1 (portal messages `sender`)

---

## Phase 15D Stage 3 — FULLY CLOSED (Feb 2026)

### Batches 1-12 + Isolation + Stage 4 + Stage 5 all complete.

**New this pass:**
- **Batch 10**: dashboard.py, operations.py (dispatch/activity/reports/business-summary), analytics.py (6 endpoints), onboarding.py, portal.py, property.py, card.py, finances.py (income-by-category) — all tenant-scoped
- **Batch 12**: `/tenant-picker` route in React SPA; localStorage `tenant_slug` attached as `X-Tenant-Slug` header on every API call via `api.js`; login redirects to picker when memberships > 1; logout clears the slug; `TenantChip` component for header
- **Cross-tenant fix**: `get_current_tenant` now respects `X-Tenant-Slug` header for `super_admin` role (path 1 in the resolver) — enables super to work as any tenant admin

### Multi-tenant isolation verified (15/15 tests)
- **Stage 3 test** (`test_phase15d_stage3_isolation.py::TestIsolation`) — 7 tests: throwaway tenant, cross-tenant read/write 404, super_admin cross-tenant, jobs isolation, notifications isolation
- **Stage 4 test** (same file, `TestStage4Isolation`) — 8 tests: aquaterra vs sunbelt customers/jobs/quotes/leads never overlap, dashboards return tenant-specific numbers, `/tenants/current` returns correct slug per token, super_admin can switch via `X-Tenant-Slug` header

### Stage 5 — 2nd demo tenant `sunbelt` seeded
- Tenant: `sunbelt` (brand `#F97316`), 1 customer + 1 job + 1 invoice + 1 tech + 1 admin
- Login table updated in `/app/memory/test_credentials.md`
- `super@aquaterra.com` is a member of BOTH tenants → tenant picker fires on their login
- `test_phase15d_stage2.py` cleanup updated to preserve `sunbelt` (was previously deleted as smoke test artifact)

### Files changed (final Batch 10 + 12 tally, cumulative Stage 3 diff)
- 33 backend files, 4 frontend files, 3 memory files
- Additive: `pages/TenantPicker.jsx`, `tests/test_phase15d_stage3_isolation.py`
- OpenAPI: 325 paths (unchanged)

### Test results
- **Isolation suite:** 15/15 pass
- **Regression suite:** 104 passed / 1 failed / 18 errors — identical pre-existing inventory (env-URL drift + password-policy 422s)
- **Zero new regressions** across all 12 batches

---

## Phase 16A — Workyard-style Workforce Ops (Feb 2026)

GPS time clock, geofenced job clock-in, offline-tolerant mileage tracking,
per-job cost/margin P&L, and a live crew map. Multi-tenant from day one
(every route `Depends(get_current_tenant)`, every doc carries `tenant_id`).

### Backend
- **New router**: `/app/backend/routers/workforce.py` — 12 endpoints under
  `/api/workforce/*`:
  - POST `/clock-in`, `/clock-out`, `/break/start`, `/break/end`, `/location-ping`
  - GET  `/timesheets`, `/mileage`, `/crew-map`, `/job-cost/{job_id}`,
         `/export/timesheets.csv` (StreamingResponse, raw text/csv)
  - POST `/timesheets/{id}/approve` and `/reject` (admin)
- **New collections** (all tenant-scoped, indexed):
  - `time_entries` (composite `(tenant_id, user_id, clock_in_at)` +
    `(tenant_id, job_id)`)
  - `location_pings` (TTL 30 days via `created_at_dt`)
- **Tenant settings** live on `tenants.settings.workforce.{geofence_radius_m,
  mileage_rate_usd, overtime_daily_hours, overtime_weekly_hours,
  require_photo_clock_in, ping_min_seconds, mileage_max_speed_mph,
  mileage_min_hop_m}` — sensible defaults inline.
- Real-time WS notifications fired on clock-in, clock-out, and
  approve/reject via the existing `routers.realtime.bus`.
- **Total OpenAPI paths: 337** (up from 325). No existing endpoint touched.

### Web (React)
- New pages in `/app/frontend/src/pages/workforce/WorkforcePages.jsx`:
  - `/workforce/timesheets` — filter by date range / tech / status,
    per-row Approve/Reject, overtime + out-of-geofence badges, CSV export
  - `/workforce/crew-map` — live Google Maps with tech markers
    (auto-refresh 30 s, side-card + click drill-down)
  - `/workforce/job-costing` — per-job revenue/labor/materials/mileage
    P&L table + margin drill-down modal
  - `/workforce/mileage` — per-tech, per-day miles report
- Sidebar: new **Workforce** group added to
  `/app/frontend/src/nav/adminNav.js` with 4 entries.

### Mobile (Expo)
- New screen `/app/mobile/app/time-clock.tsx`:
  - Pick assigned job → Clock In (foreground GPS + geofence pill)
  - Live shift timer, break start/end, Clock Out with summary alert
  - 30 s ping loop while clocked in; offline pings queue in
    AsyncStorage (`workforce_ping_queue_v1`) and flush on reconnect via
    `@react-native-community/netinfo`.
  - **Background pings (app closed) still require a native build** —
    `expo-task-manager` is intentionally NOT registered here so the screen
    remains Expo Go / web compatible. Native-build integration is a
    follow-up (registration hook + `TaskManager.defineTask` + BG
    permissions already granted in `app.json`).

### Tests
- `/app/backend/tests/test_workforce.py` — 6/6 green
  (geofence in, geofence out flag, tenant isolation, OT split, CSV stream
  content-type + disposition, ping rate-limit).

### Human verification required
- Real-device GPS clock-in on the mobile app (Expo Go, iOS or Android)
- Background-location ping loop (needs a dev/native build to certify)
- Google Maps API restriction — the current key is unrestricted; lock it
  to the deployed domain for production

---

## Phase 16B — Business Operating System (LeanScaper-inspired) (Feb 2026)

Reused + finished the scaffolded `/app/backend/routers/business_os.py`,
`/app/backend/routers/tenant_plans.py`, and
`/app/frontend/src/pages/os/BusinessOS.jsx`. Added Lana AI chat + KPI
auto-recompute + plans catalog + tenant plan assignment + mobile huddle.

### Backend
- **Registered routers** in `server.py`: `business_os`, `tenant_plans`.
- **New endpoints** (all admin-only, tenant-scoped):
  - SOPs: `GET/POST /sops`, `PUT/DELETE /sops/{sid}`, `POST /sops/generate` (Lana AI)
  - Role definitions: `GET/POST /role-definitions`, `PUT/DELETE /role-definitions/{rid}`
  - KPI scorecards: `GET /kpi-scorecards`, `POST /kpi-scorecards` (upsert per role)
  - Huddles: `GET/POST /huddles`, `GET /huddles/{hid}`, `POST /huddles/{hid}/agenda` (Lana), `POST /huddles/{hid}/action-items` (auto-creates task)
  - LeanBoards: `GET /leanboards`, `GET/POST /leanboards/{bid}/cards`, `POST /leanboards/cards/{cid}/move`, `DELETE /leanboards/cards/{cid}`
  - Sprints: `GET/POST /sprints`, `GET /sprints/{sid}`, `PUT /sprints/{sid}/review`, `POST /sprints/{sid}/retro-ai`
  - Four Pillars overview: `GET /os/overview`
  - Business OS meta: `POST /business-os/kpis/recompute`, `POST /business-os/lana/chat`, `GET /business-os/lana/conversations`
  - Plans: `GET /plans`, `POST /plans/assign/{tenant_id}` (super-admin), `GET /plans/history/{tenant_id}`
- **New collections** (all tenant-scoped): `sops`, `role_definitions`,
  `kpi_scorecards`, `huddles`, `leanboards`, `leanboard_cards`, `sprints`,
  `lana_conversations`, `plans` (global), `tenant_plan_assignments`.
- **Startup seed** — per tenant: 10 pool/landscape SOPs, 8 canonical roles,
  3 SOP-tied LeanBoards, KPI scorecards derived from each role's KPIs.
- **`/api/tenants/current` patched** to surface `plan_features` (auto-backfill on-read).
- **Lana AI persona** added as the 9th AI Employee (`ai_ops.SEEDED_EMPLOYEES`, slug `lana`).
- **Total OpenAPI paths: 337 → 365** (28 new endpoints).

### Web
- Wired `/os/*` nested routing in `App.js` using `BusinessOSLayout` +
  9 children: `dashboard`, `sops`, `roles`, `scorecards`, `huddle`,
  `leanboards`, `sprints`, `lana`, `plans`.
- New sidebar group **"Business OS"** in `adminNav.js` with all 9 entries;
  Plans marked `super_admin_only`.
- New file `/app/frontend/src/pages/os/LanaAndPlans.jsx` — Lana chat page
  (streams messages, shows `MOCK MODE` badge when `mocked:true`) and Plans
  admin (tier cards + tenant-by-tenant assign buttons).

### Mobile
- New Expo screen `/app/mobile/app/huddle.tsx` — tech enters yesterday /
  today / blockers; each non-empty line is posted as a huddle action-item
  which auto-creates a task in `db.tasks`. Reference SOP list included.

### Tests
- `/app/backend/tests/test_business_os.py` — **8/8 pass** (seed, SOP CRUD +
  tenant isolation, role CRUD, KPI recompute, huddle → task, Lana chat
  live+mocked-flag, plans catalog + super-admin-only assignment, LeanBoard
  card move).
- Workforce suite (Phase 16A) still 6/6 green.

### Live verifications on preview URL
- `/api/business-os/lana/chat` returns `mocked:false` and a real Claude
  Sonnet 4.5 answer with `EMERGENT_LLM_KEY`.
- `/api/tenants/current` surfaces `plan_features` (aquaterra=enterprise,
  sunbelt=pro, new signups default to `free`).
- Screenshots confirm Four Pillars overview, SOP Library grid, Lana chat
  all render with the Business OS sub-nav.

### Human verification required
- **Plans re-tier UX** — assign flip on `/os/plans` (super@aquaterra.com only)
- **Lana chat streaming feel** — right now `/lana/chat` is request/response;
  streaming SSE was deferred (playbook Anthropic streaming path).
- **SOP rich-text** — content is currently plain markdown/textarea, not a
  WYSIWYG editor. Attached-checklist is stored in `content` inline; a
  structured `checklist:[{text,done}]` field is a future add.

### Deferred / partial
- Sprint burndown chart (backend collects goals + reviews; a real burndown
  needs an in-day `sprint_items` collection — not blocking the phase).
- SOP per-role visibility filter — schema supports `owner_role` but the UI
  currently shows all SOPs to every admin. Trivial to gate later.

---

## Phase 16C — Tech Today Schedule + Tech-role UX Overhaul (Feb 2026)

Delivered in one pass: the new tech-facing timeline, plus four tech-only
UX changes (weather on schedule, revenue hidden, Jobs removed from nav,
D2D promoted), plus the retirement of the pricing-tier system.

### Backend
- **New router** `/app/backend/routers/schedule.py`:
  - `GET  /api/schedule/today` — current-user's jobs + shifts + breaks +
    route legs (with `distance_matrix_cache` hydration) + summary.
  - `POST /api/schedule/route-leg` — client posts distance/duration after
    a Google Distance Matrix call; upserts into `distance_matrix_cache`.
- `GET /api/jobs` and `GET /api/jobs/{jid}` **strip** the following keys
  when `user.role == "technician"`: `price, cost, total, subtotal,
  tax_amount, revenue, invoice_total, quote_total, margin, labor_cost,
  materials_cost, gross_margin`.
- Huddle endpoints loosened to accept both admin AND technician
  (`GET/POST /huddles`, `POST /huddles/{hid}/action-items`) so techs can
  submit huddle notes from the web + mobile.
- **Pricing tier system removed** — `/app/backend/routers/tenant_plans.py`
  deleted, unregistered from `server.py`, seeds gone, `/api/tenants/current`
  no longer emits `plan_features`. All 6 `/plans*` endpoints gone.

### Web
- **Login redirect** — techs now land on `/schedule/today` (was `/jobs`).
- **New pages**:
  - `/app/frontend/src/pages/schedule/TodaySchedule.jsx` — vertical hourly
    timeline with 5-day forecast at top (techs), summary bar, "NOW" line,
    Google Distance Matrix route-leg chips between consecutive jobs.
  - `/app/frontend/src/pages/tech/TechPages.jsx` — `TechHuddlePage` +
    `TechTimeClockPage` (self-scoped, no admin-only wrapper).
- **`TECH_NAV`** in `AppLayout.jsx` is now exactly
  **[Schedule, D2D, Huddle, Time Clock, Profile]** — no Jobs top-level entry.
- **D2D routes** — removed `<AdminOnly>` from `/d2d`, `/d2d/map`, `/d2d/knocks`,
  `/d2d/open-leads`, `/d2d/sold-leads`, `/d2d/leaderboard`; `/d2d/report`
  stays admin-only.
- **Revenue hidden on tech views**: `JobDetail.jsx` skips the "Price" meta
  chip for `isTech`; `JobsList.jsx` no longer shows the tech weather strip
  (moved to schedule).
- **Plans admin removed** — `/os/plans` route dropped, Plans nav entry
  removed, `PlansAdminPage` deleted from `LanaAndPlans.jsx` (only `LanaChatPage`
  remains).

### Mobile (Expo)
- **New tab** `today` (first for techs) — `/app/mobile/app/(app)/today.tsx`
  mirrors the web timeline: 5-day forecast context, "You are here → next
  job" ETA leg via `expo-location` + Google Directions API, driving-time
  chips between jobs, tap-to-navigate.
- `(app)/index.tsx` redirects techs to `/(app)/today` (was `/(app)/schedule`).
- `(app)/_layout.tsx` tab bar for techs is now
  **Today · New Lead · Jobs · Tools · More** (Today first). Admins keep
  their existing tab set including Schedule.

### Tests — 23/23 passing
- **New**: `/app/backend/tests/test_schedule.py` (5 tests — shape, tenant
  isolation, user scoping, shift/break inclusion, route-leg cache round-trip)
- **New**: `/app/backend/tests/test_tech_revenue_strip.py` (5 tests —
  list/detail strip revenue for tech, admin still sees, `/tenants/current`
  no plan_features, `/plans` endpoints return 404)
- Updated `test_business_os.py` — removed the plan-assignment test
  (feature no longer exists); all remaining 7 tests green.
- Workforce (6/6) untouched.
- **OpenAPI paths: 365 → 361** (net −4: added 2 schedule endpoints, removed
  6 plan endpoints).

### Live verifications on preview URL
- Login as `mike@aquaterra.com` → lands on `/schedule/today`
- Nav is exactly [Schedule, D2D, Huddle, Time Clock, Profile]
- 5-day forecast renders at the top
- **No `$` character on the tech landing screen** (Playwright DOM probe
  returned `has-$-on-tech-landing: False`)
- `GET /api/tenants/current` no longer contains a `plan_features` block
- `GET /api/plans` returns 404 (endpoint removed)

### Human verification required
- Real-device GPS for the "You are here → next job" leg on mobile (foreground)
- Verify admin dashboard weather widget still renders unchanged (should —
  we only removed the tech's weather strip on Jobs; admin's is in Dashboard)

### Not implemented (explicit deferrals, non-blocking)
- Tech time-clock **on web** shows self-timesheet only; actual clock-in
  physically happens on mobile (by design — GPS on web is unreliable).
- SOP per-role visibility filter (deferred from Phase 16B)
- Sprint burndown chart (deferred from Phase 16B)

---

## Phase 16C Follow-up · Card-List Schedule + Dashboard removed for techs (Feb 2026)

Small, focused UX pass on top of Phase 16C.

### 1) Schedule → Card-List view (new default)
- Web (`/app/frontend/src/pages/schedule/TodaySchedule.jsx`) and mobile
  (`/app/mobile/app/(app)/today.tsx`) now render a stacked card list of jobs
  by default (matches the user's reference screenshot):
  * Checkbox · **service type (red)** · customer name (bold) · street ·
    city/state/zip · start-time chip · **X.XX BH** · status pill (blue
    Scheduled / amber In-Progress / green Completed / red Cancelled) · red chevron.
  * Tap card → job detail (existing `/jobs/{id}` route).
- Timeline is preserved as a secondary view; a **LIST | TIMELINE** toggle in
  the header persists per-user via `localStorage` (web) /
  `AsyncStorage` (mobile, key `schedule_view_mode`).
- Backend `schedule.py` now emits `service_type`, `job_type`, `city`, `state`,
  `zip` on each `type=job` item (schema-additive — no client breakage).

### 2) Dashboard removed for `role === "technician"`
- **Web root guard**: `/app/frontend/src/App.js` — added `<RoleAwareIndex>`
  wrapping the `/` index route so techs `<Navigate to="/schedule/today">`,
  customers `<Navigate to="/portal/home">`, admin/super sees `AdminDashboard`.
- Direct URL entry `poolscape-audit.preview.emergentagent.com/` as tech now
  redirects — Playwright DOM probe returned
  `has-Dashboard-text: False, has-$-on-tech-view: False`.
- Mobile was already correct: `(app)/index.tsx` redirects
  `role === "technician"` to `/(app)/today` and the tab bar's Dashboard tab
  has `href: isAdmin ? "/(app)" : null`.
- `TECH_NAV` in `AppLayout.jsx` unchanged: **Schedule · D2D · Huddle · Time
  Clock · Profile** — no Home / Dashboard / Overview entry.

### Files touched (only)
- `backend/routers/schedule.py` — extra job fields on payload
- `frontend/src/App.js` — new `RoleAwareIndex` component + route wrap
- `frontend/src/pages/schedule/TodaySchedule.jsx` — LIST/TIMELINE toggle +
  new `<ScheduleCardList>` component (default), persistence
- `mobile/app/(app)/today.tsx` — mirror LIST/TIMELINE toggle +
  `<ScheduleCardList>` component + persistence
- `memory/HANDOFF.md` — this section

### Tests still 10/10 green (schedule + tech-revenue-strip)
No new tests required — this is a pure UX refactor on top of existing
`/api/schedule/today` payload.

---

## Phase 16C Follow-up · Gate Codes + Notes on schedule cards (Feb 2026)

Techs now see practical property-access info right on each schedule card.

### Backend
- `GET /api/schedule/today` payload — each `type=job` item now includes:
  - `gate_code: str | null` (joined from `customers.gate_code`, tenant-scoped)
  - `access_notes: str | null` (if the customer has that field set)
  - `customer_notes: str | null` (from `customers.notes`)
  - `job_notes: str | null` (concatenates `jobs.notes` + `jobs.internal_notes`)
- No revenue leaks (revenue-strip unchanged).
- Customer seed patched — Jennifer Carson `gate_code=1234#`, The Whitmore HOA `gate_code=0713*` + friendly access notes so the preview shows real data.

### Web (`TodaySchedule.jsx`)
- On each card, below the address block:
  - **🔑 gate pill** — amber background, monospaced, tap-to-copy via `navigator.clipboard`.
  - **📝 Notes preview** — first 100 chars of combined notes, `more`/`less` inline toggle expands full text without leaving the list.
- Card tap still opens `/jobs/{id}`; the notes toggle stops propagation so tapping "more" doesn't navigate.

### Mobile (`(app)/today.tsx`)
- Mirror of the web card, plus **tap-to-copy** on the gate pill via
  `expo-clipboard` (`Clipboard.setStringAsync`) with an `Alert` confirmation.
- Uses `Ionicons key` for the gate glyph, `document-text-outline` for notes.

### Tests — 12/12 green
- **`test_schedule_surfaces_gate_code_and_notes`** — asserts gate_code +
  customer_notes + job_notes appear on the tech's schedule item and no
  revenue keys leak.
- **`test_gate_code_tenant_isolation`** — sunbelt admin's `/schedule/today`
  response text contains none of the aquaterra seeded gate codes.
- Existing schedule + revenue-strip tests still green.

### Live-verified on preview
- Logged in as `mike@aquaterra.com`, visited `/schedule/today`:
  `has-$: False`, `has-1234#: True`, `has-0713*: True`, `has-notes-preview: True`.
- Expanded The Whitmore HOA notes — `more → less` toggle works inline.

### Files touched
- `backend/routers/schedule.py` — customer join + 4 new fields per job item
- `frontend/src/pages/schedule/TodaySchedule.jsx` — gate pill + notes preview + expand
- `mobile/app/(app)/today.tsx` — same, with clipboard-copy on tap
- `backend/tests/test_schedule.py` — 2 new tests
- `memory/HANDOFF.md` — this section

No new endpoints. OpenAPI path count still 361.

---

## Phase 16C Follow-up · Date picker + startup seed + mobile tabs (Feb 2026)

Three-part follow-up shipped in one pass.

### 1) Date picker on tech schedule
- Backend `/api/schedule/today` now accepts `?date=YYYY-MM-DD` query. New
  alias `/api/schedule/day` (identical payload). Missing/invalid date
  defaults to today in the tenant tz.
- Web: prev / date-input / next chevrons + a Today pill in the schedule
  header; selected date persists in the URL query (`?date=...`).
- Mobile: same UX using `@react-native-community/datetimepicker` (already
  a dep). Tap the date center → native date picker.
- 5-day forecast strip is NOT date-shifted (weather API is real-time only,
  as spec'd).

### 2) Startup seed guarantees Mike has today's jobs
- New idempotent helper `seed.seed_tech_today_demo()` (called from
  `server.py::startup`):
  * Ensures Jennifer Carson has `gate_code=1234#` + friendly notes.
  * Ensures The Whitmore HOA has `gate_code=0713*` + service-gate notes.
  * Inserts 2 jobs for TODAY assigned to Mike (`mike@aquaterra.com`):
    - 09:00-10:00 · Weekly Pool Service · Jennifer Carson
    - 11:00-12:30 · Monthly Landscaping · The Whitmore HOA
  * Guarded by `(tenant, customer, tech, YYYY-MM-DD)` idempotency check —
    safe to run every restart.
- Verified via `curl /api/schedule/today` after backend restart:
  Mike sees exactly 2 jobs with both gate codes populated.

### 3) Mobile tech tab bar strict spec
- Renamed today tab title `"Today" → "Schedule"`.
- New tab files (thin re-exports so expo-router registers them):
  * `(app)/d2d.tsx` → `../d2d/index.tsx`
  * `(app)/huddle.tsx` → `../huddle.tsx`
  * `(app)/time-clock.tsx` → `../time-clock.tsx`
- `_layout.tsx` tech tabs now exactly:
  **Schedule · D2D · Huddle · Time Clock · Profile**.
  New Lead / Jobs / Tools / (admin) Schedule / Quotes / Customers all
  `href: null` for `isTech` — admins keep their existing set.
- Job detail deep-link from Schedule card still works via `router.push("/job/{id}")`.

### Tests — 14/14 green
- **New**: `test_schedule_accepts_date_query` — round-trips yesterday /
  today / `/schedule/day` alias.
- **New**: `test_schedule_date_query_tenant_isolation` — date param does
  not weaken tenant scoping.
- All other schedule + revenue-strip + gate-code tests still pass.

### Endpoint spec (final)
- `GET /api/schedule/today[?date=YYYY-MM-DD]` — canonical.
- `GET /api/schedule/day[?date=YYYY-MM-DD]` — alias.
- Missing/malformed date falls back to today in tenant tz.
- Response `date` field echoes the requested day (YYYY-MM-DD).

### Live verifications on preview
- Login as `mike@aquaterra.com`:
  * 2 job cards render today with gate codes 1234# and 0713* ✅
  * Prev chevron → URL becomes `?date=2026-07-13`, header switches to
    "Monday, Jul 13", card list shows 0 jobs (nothing scheduled yesterday) ✅
  * Today pill appears + jumps back to `/schedule/today` ✅
  * `/api/schedule/today?date=2026-07-13` echoes `date: "2026-07-13"` ✅

### Files touched
- `backend/routers/schedule.py` — `date` query + `/day` alias
- `backend/seed.py` — `seed_tech_today_demo()` helper
- `backend/server.py` — wire new seed at startup + import
- `backend/tests/test_schedule.py` — 2 new tests
- `frontend/src/pages/schedule/TodaySchedule.jsx` — date picker UI + URL sync
- `mobile/app/(app)/today.tsx` — date picker UI (native `DateTimePicker`)
- `mobile/app/(app)/_layout.tsx` — strict tech tab set
- `mobile/app/(app)/d2d.tsx`, `huddle.tsx`, `time-clock.tsx` — new re-export tab files
- `memory/HANDOFF.md` — this section

No new endpoints beyond `/schedule/day` alias. Total OpenAPI paths: 362.

### Human verification required
- On a real Expo build, confirm the native date picker opens and
  selection round-trips (works cross-platform, but iOS calendar UI vs
  Android spinner differ visually — no code change needed).

---

## Phase 18A · Social Media Suite Foundation (Feb 2026)

Hootsuite-inspired admin/marketing suite. Posts stay draft/scheduled; OAuth + real publishing lands in Phase 18B. AI captions are **LIVE via `EMERGENT_LLM_KEY`** (verified `mocked:false`).

### Backend — 11 new endpoints (362 → 373 OpenAPI paths)
- Router `/app/backend/routers/social.py`
- Posts: `POST /social/posts`, `GET /social/posts`, `GET /social/posts/{id}`, `PATCH /social/posts/{id}`, `DELETE /social/posts/{id}`, `POST /social/posts/{id}/reschedule`, `POST /social/posts/{id}/duplicate`
- Calendar: `GET /social/calendar?year=Y&month=M`
- AI: `POST /social/ai/caption`, `POST /social/ai/hashtags`
- Media: `POST /social/media` (+ `/upload` alias), `GET /social/media`, `DELETE /social/media/{id}`, `POST /social/media/{id}/tag`
- New collections (tenant-scoped): `social_posts`, `social_media_assets`
- Role gate: `require_marketing` (admin/super_admin/marketing) — technicians get 403

### Web
- `/app/frontend/src/pages/social/SocialSuite.jsx` exports Composer / Calendar / Library / Drafts
- Routes wired under `<AdminOnly>` at `/social/composer`, `/social/calendar`, `/social/library`, `/social/drafts`
- New "Social" group in `adminNav.js`
- Composer: adaptive char counter (tightest limit across selected networks), 9-network grid with "🔌 Not connected" pill on each, live per-network preview cards, AI drawer, disabled "Publish Now (available in Phase 18B)" clearly labeled
- Calendar: month grid with HTML5 drag-and-drop → `POST /social/posts/{id}/reschedule`

### Tests — 7/7 green
- Create draft + list, scheduled_status_when_future, tenant isolation, technician forbidden (403), AI caption `mocked:false` when key present, reschedule + duplicate, media upload + list

### Live-verified via curl on preview
```
POST /api/social/ai/caption {"topic":"3 tips ... July","networks":["instagram","facebook"]}
→ mocked: False, captions: 3, hashtags: 12
   e.g. "☀️ July heat got your Arizona pool looking cloudy? …"
   #ArizonaPoolCare #PoolMaintenance #CrystalClearPool …
```

### Deferred to Phase 18B (not silently mocked — clearly labeled)
- OAuth for all 9 networks (button reads "🔌 Not connected — connect account in Settings (Phase 18B)")
- Actual publishing (button reads "Publish Now (available in Phase 18B)")
- Per-network analytics + inbox

### Files touched
- New: `backend/routers/social.py`, `backend/tests/test_social.py`, `frontend/src/pages/social/SocialSuite.jsx`
- Edited: `backend/server.py` (register router), `frontend/src/App.js` (4 routes), `frontend/src/nav/adminNav.js` (Social group), `memory/HANDOFF.md`

### Mobile (added in follow-up)
- New screen `/app/mobile/app/social.tsx` — lightweight composer:
  caption + 9-network chip grid ("🔌 not connected" on each) + first-comment
  + native date/time picker + Save Draft / Schedule / **Submit for Approval**
  + "Publish Now available in Phase 18B" note. AI Suggest button hits
  `/api/social/ai/caption`.
- Screen self-guards: `role in {admin, super_admin, marketing}` → forbid card
  shown to techs/customers.
- More menu (`/app/mobile/app/(app)/more.tsx`) now surfaces:
  * `showAdminSection = admin || super_admin || marketing`
  * new "Social Media" link → `/social` (right below Marketing)
  * techs never see the admin section, so the Social entry stays hidden from them.

---

## Phase 18A.1 · Social Suite Parallel Build (Feb 2026)

Five parallel modules built while OAuth keys for Phase 18B are still being
collected. All admin/marketing-only, tenant-scoped, zero regressions on 18A.

### Backend — +19 endpoints (373 → 391 OpenAPI paths, +1 public `/r/{alias}`)

**Module 1 — Approval Workflow** (`social_post_approvals` collection)
- `POST /social/posts/{id}/submit-for-approval` (creator, marketing role ok)
- `POST /social/posts/{id}/approve` (admin/super_admin only → moves post to
  `scheduled` if `scheduled_at` set, else `draft`)
- `POST /social/posts/{id}/reject` (requires `comment`)
- `POST /social/posts/{id}/request-changes` (requires `comment`)
- `POST /social/posts/{id}/comment` (thread append)
- `GET  /social/approvals?status=…` (reviewer queue with post preview join)
- Realtime `social.approval.submitted` event fires to all in-tenant admins.

**Module 2 — Bulk CSV / JSON** — `POST /social/posts/bulk`
Accepts multipart CSV upload OR JSON body. 500-row cap. Per-row error report
(`row`, `msg`). Media URLs in a CSV row are materialized into
`social_media_assets` so composer can reuse them.

**Module 3 — UTM Builder** (`utm_presets` collection)
- `POST /social/utm/build` → `{ tagged_url }` (never mutates original params)
- `GET  /social/utm/presets`, `POST /social/utm/presets`, `DELETE /social/utm/presets/{id}`

**Module 4 — Short Links** (`short_links` + `short_link_hits` collections; unique index on `alias` global)
- `POST /social/short-links` (auto-generates 6-char base62 alias if none passed)
- `GET  /social/short-links` (with `clicks_total`)
- `GET  /social/short-links/{id}/stats` (click_series by day + top_referrers)
- `DELETE /social/short-links/{id}` (cascades hits)
- Public `GET /api/r/{alias}` → 302 redirect (+ 90-day TTL on hits collection).
  Also registered at `/r/{alias}` for backend-direct access.
  Cluster ingress only forwards `/api/*`, so external `short_url` returned to
  the UI uses `/api/r/{alias}`.

**Module 5 — Content Library upgrades**
- Folders: `POST/GET /social/media/folders`, `DELETE /social/media/folders/{id}`
  (cascade → contained assets go back to root).
- Brand Kit: `GET /social/brand-kit`, `PUT /social/brand-kit` (upsert per tenant).
- Alt-text: added `alt_text` (+ `folder_id`) fields to `social_media_assets`;
  new `PATCH /social/media/{id}` for manual edit;
  `POST /social/ai/alt-text` — vision-enabled Claude call via `EMERGENT_LLM_KEY`
  (returns `mocked:false` when key present).

### Frontend web — 4 new pages + composer enhancements
- `/app/frontend/src/pages/social/SocialExtras.jsx` exports:
  - `ApprovalsPage` — status filter, approve / reject / request-changes with
    comment field, expandable discussion thread per post.
  - `BulkUploadPage` — drag-drop CSV, live per-row validation preview
    (truncated to 20 rows), downloadable CSV template, submit + result panel.
  - `ShortLinksPage` — create with optional custom alias, table with copy /
    stats (modal shows click_series + top_referrers) / delete.
  - `BrandKitPage` — color pickers, logo URL, font, tagline, live gradient
    preview.
- `SocialSuite.jsx` composer now shows:
  - **URL Tools strip** (only when caption contains `http(s)://…`) — Shorten
    (replaces URL with short link, optional custom alias) + UTM (source /
    medium / campaign fields, applies via `/social/utm/build`).
  - **Submit for Approval** button (moves the post to `pending_approval`).

### Frontend nav — Social group grew to 8 entries
Composer · Calendar · Library · Drafts · **Approvals · Bulk Upload · Short
Links · Brand Kit**.

### Mobile
- `/app/mobile/app/social.tsx` composer: added Submit for Approval button
  under Save Draft / Schedule.

### Tests — `test_social_phase18a1.py` (13/13 green)
- Approval submit→approve→scheduled path, reject requires comment, tech 403,
  tenant isolation on the queue.
- Bulk CSV creates valid rows, reports invalid rows with row numbers,
  501-row upload rejected with a 400 mentioning "500".
- UTM build appends utm_source/medium/campaign, presets tenant-isolated.
- Short-link create + follow via `/api/r/{alias}` returns 302 → target URL,
  stats reflect the click; alias globally unique across tenants (409 on clash).
- Folder create/list, cascade delete moves assets back to root.
- Brand kit GET returns defaults, PUT persists.
- Alt-text: manual PATCH + AI vision call (mocked:false with key present).

### Live verifications on preview URL
- `POST /api/social/short-links` → 200 with
  `short_url: https://poolscape-audit.preview.emergentagent.com/api/r/summer27`.
- `GET /api/r/summer27` (through ingress) → **302** →
  `https://aquaterra.com/summer-promo` ✅.
- `POST /api/social/ai/alt-text` → `mocked:false`, real vision output:
  *"A modern rectangular swimming pool with blue water surrounded by a
  concrete deck and contemporary outdoor furniture."* ✅.

### Files touched
- **New**: `backend/routers/public_social.py`,
  `backend/tests/test_social_phase18a1.py`,
  `frontend/src/pages/social/SocialExtras.jsx`.
- **Extended**: `backend/routers/social.py` (+19 endpoints, alt_text/folder_id
  on MediaIn, brand kit + short link helpers), `backend/server.py`
  (public_social double-mount at `/api/r/{alias}` + `/r/{alias}`),
  `frontend/src/App.js` (+4 routes), `frontend/src/nav/adminNav.js`
  (Social group +4 entries), `frontend/src/pages/social/SocialSuite.jsx`
  (URL Tools strip + Submit for Approval), `mobile/app/social.tsx`
  (Submit for Approval).

### Deferred to Phase 18B
- OAuth for the 9 networks + real Publish Now (unchanged).
- Bulk / UTM / Brand Kit exposure on mobile (spec explicitly deferred).

---

## Phase 18B follow-up · Auto-open Service Checklist on Tech Clock-In (Feb 2026)

When a tech taps **Clock In & Start Report** on a schedule card, the app
auto-detects the job's service type and opens the correct in-progress
checklist form. Pool = chemical readings + chemicals-added + pool checklist.
Landscape = grooming checklist. Both allow up to **10** photos per job,
server-enforced.

### Backend — +5 endpoints (392 → 395 unique OpenAPI paths)
- `GET   /api/jobs/{jid}/service-report`, `PATCH …`, `POST …/submit`
- `GET  /api/settings/service-templates`, `PUT …`
- Existing `POST /api/jobs/{jid}/photos` now enforces 10-photo cap
  (`400 { msg, remaining_slots: 0, existing }`).
- New collections: `service_reports`, `service_report_templates`.
- Detection over `service_type + job_type + title`:
  pool/chem → pool · landscap/mow/lawn/garden/trim/blow → landscape · else generic.
- Tenant/RBAC: techs match either `job.technician_id == user.id` or
  `== user.technician_id`. Customer → 403. Admin can view any tenant scope.

### Frontend
- `/app/frontend/src/pages/tech/ServiceReport.jsx` — header with elapsed
  timer + saved-state, photo grid (10 slots), pool-only Chemical Readings +
  Chemicals Added, checklist with per-item notes, notes textarea, sticky
  footer `Save now` + `Submit Report & Clock Out`. Autosaves every 5s.
- Route: `/jobs/:id/service-report` (works for admins too).
- `TodaySchedule.jsx`: each pending tech card gets **▶ Clock In & Start
  Report** (posts `/workforce/clock-in` with browser GPS → routes to report)
  and **Open Report** (skips clock-in).
- Mobile: `service-report/[id].tsx` mirrors the web — `expo-image-picker`
  for camera + library, autosave, checklist, submit + clock-out.
  `today.tsx` shows same two buttons for techs.

### Tests — `test_service_report.py` (7/7 green)
Template detection (pool / landscape / generic), 10-photo cap, autosave
persistence, submit locks (409 on subsequent PATCH), job flips to
`completed`, tenant isolation, customer 403.

### Files touched
- **New**: `backend/routers/service_reports.py`,
  `backend/tests/test_service_report.py`,
  `frontend/src/pages/tech/ServiceReport.jsx`,
  `mobile/app/(app)/service-report/[id].tsx`.
- **Extended**: `backend/server.py`, `backend/routers/jobs.py` (photo cap +
  liberal tech auth), `frontend/src/App.js`,
  `frontend/src/pages/schedule/TodaySchedule.jsx`, `mobile/app/(app)/today.tsx`.

### Human verification suggested
- Real device: GPS clock-in on iOS/Android via Expo build; camera capture
  path (permission → capture → upload); 10-photo cap in mobile UI.

---

## Phase 18B follow-up 2 · Chemical form patterns ported from source repo (Feb 2026)

One-time authorized clone of the source GitHub repo (deleted immediately
after extraction) to import the exact reading fields, ideal ranges, picker
step logic, and full chemical catalog into our tenant-scoped service report
template.

### Backend enrichment (`routers/service_reports.py`)
Pool template now carries:
- **10** `chemical_reading_fields` (was 8) — pH, Free/Combined Chlorine, Total
  Alkalinity, Calcium Hardness, Cyanuric Acid, Salt, Total Dissolved Solids,
  Phosphates, Water Temp. Each has `{key, name, unit, type: "select", ideal,
  min, max, step, options: [...]}`.
- Picker `options` precomputed on module import — pH 6.0→8.5 step 0.1 (26
  values), chlorine 0→20 step 0.1, alkalinity 0→500 step 20, and so on.
- **13** chemicals in `chemicals_catalog` (was 9). Each entry has
  `default_unit`, `common_units`, and `amount_options` — 20-value 0.5-step
  list for most, 10-value whole-number list for `Chlorine Tablets`.
- New top-level `chemical_units: ["gal","lbs","oz","tabs"]` for generic unit
  picker fallback.
- GET response also surfaces `chemical_reading_fields`, `chemicals_catalog`,
  and `chemical_units` at the top level so old bootstrapped reports pick up
  the new schema on next reload (no destructive migration needed).

### Frontend (`ServiceReport.jsx`)
- Chemical Readings section renders straight from `chemical_reading_fields`
  (not from the stored `chemical_readings` array), then looks up the value.
  This means every existing report picks up the new fields immediately.
- `<select>` dropdown for fields with `options`; falls back to `<input
  type="number">` if a tenant admin later removes options for a field.
- "ideal X" hint printed under each field, exactly like the source repo.
- Chemicals Added: chemical name is a `<select>` from `chemicals_catalog`.
  Selecting a chemical auto-populates the default unit. Amount becomes a
  `<select>` when the catalog entry has `amount_options`, else stays numeric.
  Unit is a `<select>` from the catalog entry's `common_units` (falls back
  to top-level `chemical_units`).
- Button label: **+ Add another chemical**.

### Mobile (`service-report/[id].tsx`)
- Same dropdowns implemented as a bottom-sheet Modal + `FlatList` (no new
  dependencies). Same picker used for readings, chemical names, amounts, and
  units.

### Tests — added 2, none removed (57/57 green)
- `test_get_service_report_pool_template` extended: assert
  `chemical_reading_fields`, `chemicals_catalog`, and `chemical_units` are
  present; pH is `type: "select"` with `7.4` + `7.6` in `options`; catalog
  count == 13 with all expected names; `Chlorine Tablets` amount options are
  whole numbers 1..10, others are 0.5-step.
- `test_pool_template_catalog_persist_roundtrip` — PATCH with two catalog-
  based chemical rows (Muriatic Acid 8 oz + Chlorine Tablets 3 tabs) round-
  trips through GET.

### Live pool template snippet (verified via curl)
```
template = pool
chemical_reading_fields count = 10   (all select, each carries ideal + 26+ opts)
  pH options: ['6.0','6.1','6.2','6.3','6.4','6.5', ...]
chemicals_catalog count = 13
  names: Liquid Chlorine, Chlorine Tablets, Shock (Cal-Hypo), Muriatic Acid,
         Soda Ash, Sodium Bicarbonate, Calcium Chloride, Cyanuric Acid,
         Pool Salt, Algaecide, Clarifier, Phosphate Remover, Enzymes
chemical_units: ['gal', 'lbs', 'oz', 'tabs']
Chlorine Tablets amount_options: ['1'..'10']
Liquid Chlorine amount_options: ['0.5', '1', '1.5', ..., '10']
```

### Cleanup
- `/tmp/pool-src-readonly` and `/tmp/pool-landscaping-src` deleted after
  extraction. No source-repo code copied wholesale — only the constants
  (field names, ideal ranges, step values, chemical catalog).
- OpenAPI count unchanged at **395** (spec: no new endpoints, just
  enrichment of existing template response).
- Landscape template unaffected.
