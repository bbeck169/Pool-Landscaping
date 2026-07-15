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

---

## GPS-based auto clock-in + auto clock-out on submit (Feb 2026)

### Backend — +3 endpoints (395 → 406 counted incl. Phase 19 referrals; new for this feature: +2 public + 1 test hook)
- `POST /api/workforce/auto-clock-in` — request `{lat, lng, accuracy}`. Never
  4xx on business misses — returns `{clocked_in:false, reason}` so the client
  can just keep polling. Reasons: `low_accuracy`, `already_clocked_in`,
  `out_of_time_window`, `not_at_any_scheduled_site`.
- `POST /api/workforce/cancel-auto-clock-in/{entry_id}` — 30-second grace
  window, gps_auto entries only, deletes the row entirely.
- `POST /api/workforce/_test/reset-autoclock` — dev-only hook (gated by
  `ALLOW_TEST_HOOKS=1` env var) to reset the in-memory rate-limit map.
  Never registered in production without the flag.
- `time_entries` docs extended with `origin: "manual" | "gps_auto"`,
  `distance_m_from_site`, `closed_by_report`.
- `_haversine_m` + `_settings.geofence_radius_m` reused from existing manual
  clock-in — no drift.
- Rate limit: 60s per user via in-memory `_AUTO_LAST` dict (returns 429).
- Audit: every accept/reject decision logs a `location_pings` doc with
  `kind: "auto_clockin_decision"`, `decision: "clocked_in" | "low_accuracy" |
  "already_clocked_in" | "no_jobs_in_window" | "not_at_any_scheduled_site"`.

### Service-report submit (mandatory clock-out on gps_auto)
- New helper `force_clock_out_if_auto(tenant_id, user_id, job_id)` in
  `workforce.py`. Called by `POST /api/jobs/{jid}/service-report/submit`.
- Guarantees the entry closes when the report was clock-in-triggered via GPS;
  best-effort behavior preserved for `origin == "manual"` entries.
- Response now carries `clock_out_summary: { entry_id, duration_minutes,
  mileage_miles, origin }` when submit closed a shift.

### Frontend web (`TodaySchedule.jsx`)
- `navigator.geolocation.watchPosition` while the tech schedule tab is
  focused. Polls the auto-clock-in endpoint every 15s (client) — server-side
  60s throttle still governs. Silent failure on transient errors.
- On successful auto-clock-in: renders a dark corner toast with customer
  name, distance-from-site, and two buttons: `Cancel` (calls
  `cancel-auto-clock-in`) or `Open now →`. After 10 s of no interaction, the
  page auto-routes to `/jobs/{id}/service-report`.

### Mobile (`(app)/today.tsx`)
- `expo-location.watchPositionAsync` inside `useFocusEffect` — starts when
  the screen focuses, tears down cleanly on blur.
- Same toast UX (bottom bar over the schedule): customer + distance + Cancel
  + Open now.
- 10-second timer → `router.push("/(app)/service-report/{id}")`.
- Manual `Clock In & Start` + `Open Report` buttons on each schedule card
  remain — GPS is additive, not a replacement.

### Tests — `test_auto_clockin.py` (9/9 green in ~6 s)
Uses the `_test/reset-autoclock` hook + `ALLOW_TEST_HOOKS=1` env var to
deterministically clear the rate-limit map between tests. Test file:
- Inside geofence + within ±2h window → `clocked_in:true`, origin=`gps_auto`.
- Outside geofence → `reason:"not_at_any_scheduled_site"`.
- `accuracy > 100m` → `reason:"low_accuracy"`.
- Pre-existing open entry → `reason:"already_clocked_in"`.
- 2 calls within 60 s → second returns **429**.
- Cancel within 30 s → entry deleted; cancel after 30 s → 400.
- Submit on gps_auto entry → `clock_out_summary` present, `closed_by_report:
  true`.
- Aquaterra tech's coords at a Sunbelt job's site → no cross-tenant match.

### Files touched
- **New**: `backend/tests/test_auto_clockin.py`.
- **Extended**: `backend/routers/workforce.py` (+ auto-clock-in, cancel,
  force_clock_out_if_auto, test-reset hook), `backend/routers/service_reports.py`
  (submit calls `force_clock_out_if_auto`), `backend/.env`
  (`ALLOW_TEST_HOOKS=1`), `frontend/src/pages/schedule/TodaySchedule.jsx`
  (geolocation watcher + toast), `mobile/app/(app)/today.tsx`
  (expo-location watcher + toast).

### Live proof (external ingress)
```
POST /api/workforce/auto-clock-in {"lat":33.7005,"lng":-112.228,"accuracy":8}
→ 200 { "clocked_in":true, "entry_id":"5f6b1091-…", "job_id":"a21195…",
        "job_title":"Weekly Pool Service", "customer_name":"Jennifer Carson",
        "distance_m":0.0 }

POST /api/jobs/a21195…/service-report/submit
→ 200 { "submitted_at":"2026-07-14T03:55:29Z",
        "clock_out_summary": {"entry_id":"5f6b1091-…",
                              "duration_minutes":0.0037,
                              "mileage_miles":0.0,
                              "origin":"gps_auto"} }
```

### Deferred (real device only)
- Background-location updates via `expo-task-manager` — foreground watcher
  covers the primary use case (tech opens the app on arrival). Spec called
  this optional.

### Human verification suggested
- Real GPS walk-in test on Expo build: watch the toast appear, tap Cancel
  within 10 s, watch the entry vanish. Then walk in again, let the timer
  expire, confirm the report screen loads.
- Confirm geofence radius (`tenants.settings.geofence_radius_m`) is set to a
  practical value per tenant (default 100 m).

---

## Phase 20A · Batch Dispatch — Route Opt + Auto-Invoicing + Background GPS (Feb 2026)

### Backend — 410 → 411 OpenAPI paths (+1 new; Route Opt was already registered)

**Module 1 · Route Optimization** (`routers/route_optimization.py`)
- `POST /api/schedule/optimize-route` `{date?, start_lat?, start_lng?, user_id?}` →
  `{ ordered_job_ids, total_distance_m, total_duration_s, legs[], cached, algorithm }`
- Google Distance-Matrix path with waypoint-order optimization when
  `GOOGLE_MAPS_API_KEY` present. Falls back to nearest-neighbor Haversine
  when Google unavailable / quota exceeded / <2 GPS-tagged jobs.
- Cache collection `route_optimizations` keyed by
  `(tenant_id, user_id, date, waypoints_hash)`. Hits return immediately with
  `cached:true` and skip Google call.
- Admins may pass `user_id` to plan another tech's day; techs can only plan
  their own.
- WS event `route_optimized` fired to the target user.

**Module 2 · Auto-Invoicing on submit** (`routers/service_reports.py`)
- `POST /api/jobs/{id}/service-report/submit` now:
  1. Checks tenant `settings.auto_invoice_on_submit` (default `true`).
  2. Skips if the job is non-billable OR has no positive priced line items.
  3. Calls the existing `_create_invoice_for_job` helper (invoice pipeline
     — no duplication of Invoice model).
  4. Auto-applies pending `service_credits` for that customer via the
     Phase 19 referral-credit path.
  5. Returns `{ invoice_id: str | null, ... }` so tech UI can toast.
- New admin-gated tenant setting endpoint:
  - `GET  /api/settings/billing` → `{ auto_invoice_on_submit }`
  - `PUT  /api/settings/billing` `{ auto_invoice_on_submit: bool }`
- Web admin toggle at `/settings/billing` (Billing Rules in the sidebar).

**Module 3 · Background GPS (native-build ready)**
- `mobile/src/background/autoClockin.ts`:
  - Task name `BACKGROUND_AUTOCLOCK_TASK`
  - `Accuracy.Balanced`, `distanceInterval: 25 m`, `timeInterval: 60 s`
  - Android foreground service: title `"AquaTerra is tracking arrival"`,
    body `"Auto clock-in enabled"`, color `#0EA5E9`.
- Wrapped in dynamic `await import()` guarded by try/catch. In Expo Go
  (where `expo-task-manager` background APIs are unavailable) the helper
  returns `{started:false, reason:"not_supported_in_expo_go"}` and the UI
  shows an Alert explaining a native EAS build is required — no crash.
- Opt-in toggle at `/app/mobile/app/(app)/settings/auto-clockin.tsx`
  (default OFF, persists via AsyncStorage). Requires role=technician,
  logged in, not currently clocked in — those short-circuits mirror the
  server `auto-clock-in` endpoint.
- `mobile/app.json`:
  - iOS `infoPlist`: `NSLocationAlwaysAndWhenInUseUsageDescription`,
    `NSLocationWhenInUseUsageDescription`, `UIBackgroundModes:["fetch","location"]`.
  - Android `permissions`: `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`,
    `FOREGROUND_SERVICE_LOCATION`.

### Frontend web
- `TodaySchedule.jsx`: "Optimize Route" primary button (brand gradient) +
  "Reset order" secondary in the header when ≥2 jobs. On click, calls
  `/schedule/optimize-route`, reorders cards via `orderedJobItems` memo,
  shows a green savings chip: `Saved X.X mi · Y min`. Chip uses the
  server total minus client-side Haversine baseline of the scheduled-start
  order, matched to the server's 35 km/h assumption.
- `ServiceReport.jsx`: submit response with `invoice_id` shows a green
  fixed-position toast "Report submitted · Invoice #XXXXXXXX created"
  for 2s before navigating back to `/schedule/today`.
- `BillingSettings.jsx` (new) at `/settings/billing`; nav entry
  "Billing Rules" added to admin sidebar under Invoices.

### Mobile
- `today.tsx`: same Optimize/Reset buttons + savings chip below the
  view-mode toggle. Uses `Location.getCurrentPositionAsync` for start
  coords when foreground permission granted.
- `service-report/[id].tsx`: submit success with `invoice_id` shows an
  `Alert.alert("Auto-invoiced", "Report submitted · Invoice #XXXXXXXX created")`
  before returning to `/today`.
- `more.tsx`: new "Auto Clock-In" entry in the tech mini-menu routing
  to the toggle screen.

### Tests
- `tests/test_phase20a.py` — 8/8 green: route ordering (3-job), cache
  hit (second call short-circuits the Google/nearest-neighbor loop),
  tenant isolation, billable → invoice created, non-billable → skipped,
  toggle off → skipped, credit auto-applied, admin can plan another tech.
- `tests/test_service_report.py`, `tests/test_auto_clockin.py`,
  `tests/test_service_templates.py`, `tests/test_schedule.py`,
  `tests/test_social_phase18a1.py` all still green (58 tests total on
  the touched surface).

### Live proof (external ingress)
```
POST /api/schedule/optimize-route → 200
{ordered_job_ids:[...], total_distance_m:0, total_duration_s:0,
 legs:[], cached:false, algorithm:"trivial"}

GET  /api/settings/billing (admin) → 200 { auto_invoice_on_submit:true }
PUT  /api/settings/billing (admin) → 200 { auto_invoice_on_submit:true }
```

### Files touched
- `backend/routers/service_reports.py` (billing settings endpoints)
- `frontend/src/pages/schedule/TodaySchedule.jsx` (Optimize UI + reorder)
- `frontend/src/pages/tech/ServiceReport.jsx` (invoice toast)
- `frontend/src/pages/settings/BillingSettings.jsx` (new)
- `frontend/src/App.js` (route)
- `frontend/src/nav/adminNav.js` (Billing Rules link)
- `mobile/app/(app)/today.tsx` (Optimize UI + reorder)
- `mobile/app/(app)/service-report/[id].tsx` (invoice Alert)
- `mobile/app/(app)/more.tsx` (Auto Clock-In link)

### Native build required
Actual background execution of `BACKGROUND_AUTOCLOCK_TASK` requires cutting
an EAS native build (Expo Go's TaskManager stubs are effectively no-ops).
Code path is Expo-Go-safe today; enable via `eas build --profile production`
once the store submission cycle is ready.

### Human verification suggested
- Optimize a real 3+ job day with distinct GPS coords → confirm the chip
  reports a non-zero savings and the card list visually reorders.
- Submit a service report on a billable job with `auto_invoice_on_submit=true`
  → confirm a draft invoice appears in `/invoices` with the job linked.
- Toggle billing setting OFF, submit again → confirm no invoice created.
- Apply a pending referral credit and submit → confirm the invoice's
  balance reflects the credit.
- EAS build sanity: flip the mobile Auto Clock-In toggle ON, background
  the app, drive to a job site, confirm the foreground-service notification
  appears and an entry is auto-created.

---

## Phase 20B · Customer Portal + Employee Onboarding + Assets + Referral Analytics (Feb 2026)

### Backend — 411 → 434 OpenAPI paths (+23 across 6 new routers)

**Module 20B.1 · Customer portal upgrades** — 3 sub-features
- **20B.1a · Chat threads** (`routers/portal_chats.py`) — new
  `portal_chats` + `portal_chat_messages` collections. Endpoints
  `POST/GET /api/portal/chats`, `GET/POST /api/portal/chats/{id}/messages`,
  `POST /api/portal/chats/{id}/read`. Bus event `portal_chat_message`.
  Techs → 403 across the surface.
- **20B.1b · Appointment booking** (`routers/portal_appointments.py`) —
  `GET /api/portal/availability`, `POST/GET /api/portal/appointments`,
  `POST /api/portal/appointments/{id}/confirm|reject`. Confirmation
  auto-creates a job via the standard pipeline with `source_appointment_id`.
  Bus events: `portal_appointment_pending|confirmed|rejected`.
- **20B.1c · Photo history** (`routers/portal_photos.py`) —
  `GET /api/portal/photos` returns flat list of every service-report photo
  the calling customer can view, with filters for service_type + date range.

**Module 20B.2 · Employee onboarding** (`routers/employee_onboarding.py`)
- `onboarding_templates` (per-tenant, per-role) + `onboarding_assignments`.
- Endpoints: template CRUD, assign, mine, per-step complete/upload/quiz.
- Auto-seeds a `technician` default template with 6 steps (W-4/W-9 upload,
  safety video, chemical quiz, uniform/PPE acks, GPS auto-clockin intro).
- Assignment status transitions `not_started → in_progress → complete`;
  quiz gate = 80% pass mark.

**Module 20B.3 · Assets & maintenance** (`routers/assets.py`)
- `assets`, `asset_maintenance`, `asset_assignments_log`. Endpoints:
  full CRUD + `POST /api/assets/{id}/assign`, maintenance list/create,
  assignment log, and `GET /api/assets/reminders/due?days=` for the
  "next 7 days" reminder scan (emits `asset_maintenance_due` WS events).
- Techs see only assets currently assigned to them; customers → 403.

**Module 20B.4 · Referral tiers + advanced analytics** (`routers/referral_tiers.py`)
- `referral_program_settings` collection + `GET/PUT /api/referrals/settings`
  with non-overlap validation + auto-seeded 100% back-compat default.
- `admin_approve` in `routers/referrals.py` now consults `pick_tier`
  based on the referrer's Nth approved conversion and issues credits at
  the matched `credit_pct` + `credit_months`.
- `GET /api/referrals/admin/analytics/v2` returns funnel (invites →
  signups → converted → credits_redeemed), revenue attribution
  (customers acquired via referral, sum of invoiced totals), cohort
  curve (referrer's first-invite month × conversion month), and
  paginated leaderboard with revenue per referrer.

### Frontend web
- Customer portal sidebar gains `/portal/book`, `/portal/photos`,
  `/portal/chats` — 3 new pages with a matching visual language.
- Admin sidebar gains `Assets`, `Portal Inbox`, `Appointments`,
  `Onboarding Templates`, `Onboarding Queue`, `Referral Analytics`,
  `Referral Tiers`.
- `/onboarding/mine` — self-service employee checklist reachable by
  any authenticated user; shows progress bar per template.
- `AdminAssets` — filterable table (vehicles/equipment/tools) + detail
  drawer with assign dropdown + maintenance history + log form.
- `ReferralTiers` — table editor for tier bands with live "N% off Mmo"
  preview per row; overlap validation surfaces 400 from server.
- `ReferralAnalyticsV2` — funnel bars, revenue tile, cohort chips,
  and top-referrer leaderboard.

### Tests — 17 new (58 → 75 relevant), all green
- `tests/test_portal_20b.py` — 5 (chat flow + isolation, appt flow +
  isolation, photos scoped).
- `tests/test_employee_onboarding.py` — 4 (default seed, template CRUD,
  status transitions, quiz 80% gate).
- `tests/test_assets.py` — 4 (CRUD, assign log, tech-scoped list,
  maintenance + due reminders).
- `tests/test_referral_tiers.py` — 4 (settings default, PUT, overlap
  rejection, `pick_tier` band correctness, analytics v2 sections).

### Live proof
```
POST /api/portal/chats                     → 200 {id, subject, ...}
GET  /api/portal/availability?date_range=5 → 200 {windows: 6, capacity_per_window: 3}
GET  /api/onboarding/templates             → 200 [1 default seeded, 6 steps]
GET  /api/assets/reminders/due?days=30     → 200 {overdue:0, upcoming:0, count:0}
GET  /api/referrals/settings               → 200 {tiers:[{1-1:25%1mo},{2-3:50%1mo},{4+:50%2mo}]}
```

### Files touched
- **backend**: 6 new routers (`portal_chats`, `portal_appointments`,
  `portal_photos`, `employee_onboarding`, `assets`, `referral_tiers`),
  patched `referrals.py` (tier-aware approve), `server.py` (registration).
- **frontend**: 8 new pages (`PortalPhotos`, `PortalBook`,
  `PortalChatsPage`, `AppointmentsQueue`, `AdminAssets`,
  `EmployeeOnboarding` (3 exports), `ReferralInsights` (2 exports));
  updated `App.js` routes, `adminNav.js` links, `AppLayout.jsx`
  customer nav.

### Known limitations
- Mobile-native UI (Expo) parity for these 4 modules is deferred to a
  follow-up phase — the API surface is mobile-ready today.
- Photo storage remains inline in `service_reports.photos`; the
  photos endpoint just proxies. No CDN thumbnails yet.
- The default onboarding template seeds only for the `technician` role;
  admin/marketing defaults can be added later via the template editor UI.

### Human verification suggested
1. Log in as `customer@aquaterra.com` → visit `/portal/book`, submit
   a test booking, log in as admin, confirm at `/admin/appointments`,
   verify the job appears in `/schedule`.
2. `/portal/photos` — verify photos from prior service reports appear.
3. Edit tiers at `/admin/referrals/settings`, approve a pending
   referral, confirm the issued credit matches the picked tier.
4. Add an asset with a `next_due_at` inside 7 days, hit
   `/assets/reminders/due` → confirm the WS toast fires.

---

## Phase 20B · Wave 1 · Mobile parity + Referral Revenue tile (Feb 2026)

### Module A · Mobile screens (Expo)
Built 7 new files exercising every Phase 20B module. All type-clean (`tsc --noEmit` reports 0 new errors on the touched surface).

- **A.1 · Chat threads**
  - `mobile/app/portal/chats.tsx` — thread list with unread badge + New FAB.
  - `mobile/app/portal/chats/[id].tsx` — thread detail with keyboard-avoiding composer + 4s polling for near-realtime.
- **A.2 · Appointment booking**
  - `mobile/app/portal/book.tsx` — service-type chips + window grid from
    `/api/portal/availability` + notes + submission → confirmation screen.
  - `mobile/app/portal/appointments.tsx` — customer's own list with pending/confirmed/rejected pills.
- **A.3 · Photo history**
  - `mobile/app/portal/photos.tsx` — 3-column grid + full-screen modal viewer + filter chips.
- **A.4 · Employee onboarding**
  - `mobile/app/(app)/onboarding/mine.tsx` — assignment cards with progress ring + expandable step sheet with `task | doc_upload | video (WebView) | quiz | policy_ack` handling; quiz gate at 80%.
- **A.5 · Assets**
  - `mobile/app/(app)/assets/index.tsx` — role-aware list (tech = "My Equipment", admin = full inventory with category filter and Add-FAB).
  - `mobile/app/(app)/assets/[id].tsx` — detail with hero + metadata + maintenance timeline + admin-only "Log maintenance" sheet (kind/cost/notes/next_due).

### Tab bar & nav
- `mobile/app/(app)/_layout.tsx`: added **Equipment** tab for technicians between Time Clock and More.
  Tech tab bar now: **Schedule · D2D · Huddle · Time Clock · Equipment · Profile** (6 tabs).
- `mobile/app/portal/home.tsx`: portal home cards now include Book Service, Appointments, Photos, Chat Threads.
- `mobile/app/(app)/more.tsx`: added Assets + My Onboarding entries for admin nav and My Equipment + My Onboarding shortcuts for tech.
- `mobile/app/(app)/today.tsx`: existing `font.semiBold` → `font.semibold` correction (was invalid pre-existing TS typo from Phase 20A).

### Module B · Referral Revenue tile
- **Web** (`frontend/src/pages/admin/Dashboard.jsx`): new `ReferralRevenueTile` component under the KPI grid — brand-gradient card showing `$X` from `revenue_attribution.total_usd` + "N referrals converted · view analytics" subline, navigates to `/admin/referrals/analytics`. Uses shared `api` client.
- **Mobile** (`mobile/app/(app)/index.tsx`): mirror tile with same data, deep-links to `/admin/referrals`.
- No new endpoint — both tiles consume the existing `GET /api/referrals/admin/analytics/v2`.

### Tests
- `tests/test_dashboard_referral_tile.py` — asserts the analytics response provides the fields the tile depends on (funnel.converted int, revenue_attribution.total_usd numeric).
- Full Phase 20B + 20A surface: **30/30 green** in 16.8s (all portal, onboarding, assets, referral tiers, route optimization, phase20a, dashboard tile).

### Live proof
- Web dashboard screenshot captured — the "REFERRAL REVENUE $0" tile renders inline below the KPI grid with the expected "1 referral converted · view analytics" subline.

### Files touched
- **backend**: none (pure UI consumers) + 1 new test file.
- **frontend web**: `pages/admin/Dashboard.jsx` (+ ReferralRevenueTile).
- **mobile**: 7 new screens, `_layout.tsx` (Equipment tab), `portal/home.tsx` (nav cards), `more.tsx` (menu entries), `today.tsx` (font-name fix).

### Known limitations & human checks
- Real-device push notifications: chat polling uses 4s intervals; WS delivery over Expo requires a native build to fire silently in the background.
- Photo upload for onboarding `doc_upload` step is currently "mark complete" (assumes files are uploaded elsewhere); wiring `expo-image-picker` end-to-end to the multipart endpoint is a Wave 2 follow-up.
- Asset photo capture (camera) is not yet wired — admins currently pass `photo_url` when creating assets manually.
- Expo Web bundle isn't served in this environment, so mobile UI screenshots were not captured; the code is TS-clean.

---

## Phase 17A · Agentic SEO Suite — Foundation Layer (Feb 2026)

### Backend — 434 → 444 OpenAPI paths (+10 in `routers/seo_agentic.py`)

Added `beautifulsoup4==4.15.0` to requirements. `httpx` already present.

**17A.1 · Site Auditor** — real HTML crawler (not stubbed)
- `POST /api/seo/audits` — background crawl via FastAPI BackgroundTasks; returns `{audit_id, status:"queued"}`.
- `GET /api/seo/audits` · `GET /api/seo/audits/{id}` · `GET /api/seo/audits/{id}/pages` · `POST /api/seo/audits/{id}/cancel` · `POST /api/seo/audits/{id}/rerun` · `GET /api/seo/ping`.
- Crawler: httpx + BeautifulSoup, concurrency 5, 20s per-page timeout, same-host only, respects `robots.txt`/`sitemap.xml` presence.
- 15+ checks: title/meta length, H1 count, canonical, thin content, alt %, broken links, redirect chains, mixed content, OG/JSON-LD, LCP proxy, duplicate title/meta.
- Scoring: weighted rubric → `{technical, on_page, ux, overall}` all 0–100.
- Collections: `seo_audits`, `seo_audit_pages`.

**17A.2 · Content Scoring** — 8-dimension breakdown + live Claude critique
- `POST /api/seo/content-score` `{url? | html?, target_keyword, secondary_keywords?}` → `{score, breakdown{readability, keyword_density, heading_structure, meta, internal_links, image_alt, content_length, semantic_relevance}, recommendations[], mocked, target_keyword, word_count, kw_density_pct}`.
- `POST /api/seo/content-suggestions` → AI-drafted H2 outline + 3 FAQ pairs + suggested internal links. Live Claude call via `EMERGENT_LLM_KEY`, graceful stub fallback if key absent.
- Flesch reading ease, keyword density scoring, heading/meta/link/alt/length rubrics all implemented locally.

**17A.3 · Rank Heatmap** — geo-grid local rank preview
- `POST /api/seo/rank-heatmaps` `{keyword, center_lat, center_lng, grid_size, radius_miles}` → background task, response flagged `mocked:true` up-front so the UI can label results.
- `GET /api/seo/rank-heatmaps` · `GET /api/seo/rank-heatmaps/{id}`.
- Grid geometry via lat/lng deltas × cos(lat), deterministic-random rank synthesis seeded by `(tenant_id, keyword)` so results are stable across pages.
- **No silent mocking**: response includes `mocked:true` + `mocked_reason` explaining a real SERP provider (SerpAPI / DataForSEO / Google Local) needs configuration.
- Collection: `seo_rank_heatmaps`.

### Frontend web
- New sidebar entries under **SEO & GBP** section: Site Auditor, Content Scorer, Rank Heatmap.
- `/admin/seo/audits` — list + New Audit modal (URL/depth/max_pages) + live polling.
- `/admin/seo/audits/:id` — score cards (Overall/Technical/On-page/UX) + severity-filterable issue list + Rerun button.
- `/admin/seo/content-scorer` — HTML/URL toggle + keyword + Analyze → 8-bar breakdown + recommendations + "Improve" button that fetches AI outline suggestions.
- `/admin/seo/rank-heatmap` — form + colored 5×5 grid (green rank 1-3 → red 20+), avg/top-10/cell drilldown, "SERP provider not configured" banner clearly visible at top when mocked.

### Tests — 6/6 green in 13.9s
- `tests/test_seo_phase17a.py` — audit lifecycle + tenant isolation + tech/customer 403; cancel + rerun paths; content-score full breakdown + role gating; **live LLM call with `mocked:false` semantic score = 72**; heatmap mocked flag + 3×3 grid + isolation + role gating; `/seo/ping` admin-only.

### Live proof (curl)
```
POST /api/seo/audits              → {audit_id, status:"queued"}
POST /api/seo/content-score       → {score:52, mocked:false, semantic:72, recs:4}
POST /api/seo/rank-heatmaps       → {heatmap_id, status:"queued", mocked:true,
                                     reason:"No SERP provider configured..."}
```

### Screenshots
- Site Auditor list + detail (score 32 on example.com — expected low from a tiny page).
- Content Scorer input pane rendered correctly.
- Rank Heatmap 5×5 grid: avg 11.6, 8/25 top-10 cells, mocked banner visible.

### Files touched
- **backend**: new `routers/seo_agentic.py` (~600 LOC), `server.py` registration, `requirements.txt` (+ beautifulsoup4).
- **frontend**: new `pages/seo/SeoAudits.jsx` (+ SeoAuditDetail), `pages/seo/ContentScorer.jsx`, `pages/seo/RankHeatmap.jsx`; `App.js` routes; `nav/adminNav.js` links.

### Known limitations & human checks
- **SERP provider**: Rank Heatmap needs a real SERP integration (SerpAPI, DataForSEO, or Google Maps Local key) before results reflect reality. When configured, add a provider adapter in `_generate_heatmap` and stop flagging `mocked:true`.
- **Crawler**: outbound `example.com` reach works in this environment; real customer domains behind Cloudflare/WAFs may block the UA — expose a User-Agent config in the admin UI later.
- **17B (next)**: Topical Map, LLM Visibility Tracker, Atlas Agent — queued.
- **17C**: OTTO Auto-Fix, Website Studio, White-Label Reports — queued.

---

## Phase 17B · Topical Map + LLM Visibility + Atlas Agent (Feb 2026)

### Shape polish shipped ahead of the modules
- `GET /api/seo/audits/{id}/pages` now returns `{ items, total, offset, limit }` (with `rows` kept as a deprecated alias for one release).
- `GET /api/seo/ping` now returns `{ ok, running_audits, timestamp, crawler_available, llm_available, serp_provider_available, mocked_domains }` — capability flags UI can badge.

### Backend — 444 → 455 OpenAPI paths (+11 in `routers/seo_agentic.py`)

**17B.1 · Topical Map** — real Claude-driven pillar → cluster → support graph
- `POST /api/seo/topical-maps` `{seed_keyword, business_context?, depth?}` — one-shot LLM call; response is a tree of nodes (id/title/intent/estimated_search_volume/suggested_url_slug/parent/level) + edges. Every response is flagged `estimated:true` so nothing is silently promised.
- `GET /api/seo/topical-maps` · `GET /api/seo/topical-maps/{id}`.
- `POST /api/seo/topical-maps/{id}/generate-content` `{node_id}` — drafts a 5-H2 outline + ~500-word HTML for the picked node.
- Live proof: seed `pool cleaning phoenix` produced **43 nodes** via Claude in ~30s.

**17B.2 · LLM Visibility Tracker** — track brand mentions across AI answers
- `POST/GET/DELETE /api/seo/llm-visibility/queries` — CRUD tracked queries.
- `POST /api/seo/llm-visibility/scan` — runs each query on Claude, then a second LLM pass extracts `{brand_mentioned, position, competitors, quote, sentiment}` per response.
- `GET /api/seo/llm-visibility/scans/{scan_id}` · `GET /api/seo/llm-visibility/dashboard?range=30d` — mention rate %, avg position, top competitors, per-day trend.
- **Honest engine labeling**: response includes `engines_scanned: ["claude"]` (only actually-configured providers) + `engines_pending: ["openai","gemini","perplexity"]`. No silent stubs. Adapter slots are in place for when the user provides those keys.

**17B.3 · Atlas Agent** — natural-language SEO ops with tool-calling
- `POST /api/seo/atlas/chat` `{message, conversation_id?}` — Claude picks a tool (`run_site_audit`, `score_content`, `generate_topical_map`, `generate_rank_heatmap`, `scan_llm_visibility`, `list_audits`, `list_topical_maps`, `get_audit_summary`) via strict-JSON output. Server executes the tool and returns `{assistant, tool_calls:[{name, args, status, result}]}`.
- `GET /api/seo/atlas/conversations` · `GET /api/seo/atlas/conversations/{id}` — transcript persistence.
- Live proof: "Run an audit on https://example.com" produced a `run_site_audit` tool call, invoked the crawler, returned an audit_id, and persisted the audit doc. Tenant isolation on conversations verified.

### Frontend web
- New sidebar entries: Topical Map, LLM Visibility, Atlas Agent.
- `/admin/seo/topical-map` — 3-column pillar/cluster/support view, intent color-coded (blue/green/purple/red), CSV export, node drawer with "Generate outline" button.
- `/admin/seo/llm-visibility` — tabs for Queries + Dashboard; honest engine pills at top (`claude` green, `openai|gemini|perplexity` grey with "not configured" label).
- `/admin/seo/atlas` — chat + history sidebar; tool_calls rendered inline with name/args/result JSON.

### Tests — 15/15 green
- `tests/test_seo_phase17a.py` — 6/6 (audit lifecycle, content scoring live LLM, heatmap mocked flag, ping, +2 polish assertions).
- `tests/test_seo_phase17b.py` — 9/9 (audit `items` shape, ping capability flags, topical map structure + isolation, LLM visibility CRUD + honest engines, scan live, Atlas tool-calling + tenant isolation).
- Total combined with Phase 20A/route-optimization: **26/26 green in 131s**.

### Live proof (curl)
```
POST /api/seo/topical-maps
  seed="pool cleaning phoenix" → {map_id, node_count:43, mocked:false}
GET  /api/seo/llm-visibility/dashboard
  → {engines_configured:["claude"], mention_rate_pct:0, total_scans:0}
POST /api/seo/atlas/chat "Run an audit on https://example.com"
  → tool_calls:[{name:"run_site_audit",args:{url},status:"ok",
                 result:{audit_id, status:"queued"}}]
```

### Files touched
- **backend**: extended `routers/seo_agentic.py` (+~700 LOC), no new file.
- **frontend**: `pages/seo/TopicalMap.jsx`, `pages/seo/LlmVisibility.jsx`, `pages/seo/AtlasAgent.jsx`; `App.js` + `nav/adminNav.js`.

### Known limitations & human checks
- SERP provider still unconfigured (17A limitation carries through).
- **OpenAI / Gemini / Perplexity keys needed** to expand LLM Visibility beyond Claude. Adapter functions `_scan_openai() / _scan_gemini() / _scan_perplexity()` are commented in `_configured_engines()` — enable + wire when keys arrive.
- Atlas tool-calling currently uses strict-JSON prompting (works reliably against Claude Sonnet 4.6). Migrating to Anthropic's native tool-use API is a nice-to-have later.
- **17C queued**: OTTO Auto-Fix + Website Studio + White-Label Reports.

---

## Phase 17C · OTTO Auto-Fix + Website Studio + White-Label Reports (Feb 2026)

**The 9-module Agentic SEO Suite is now COMPLETE (9/9).** Modules shipped in
this pass:
1. Site Auditor · 2. Content Scoring · 3. Rank Heatmap (17A)
4. Topical Map · 5. LLM Visibility Tracker · 6. Atlas Agent (17B)
**7. OTTO Auto-Fix · 8. Website Studio · 9. White-Label Reports (17C)**

### Backend — 455 → 470 OpenAPI paths (+15 across 1 new router)

New router: `/app/backend/routers/seo_phase17c.py` (registered in
`server.py` alongside `seo_agentic`).

**17C.1 · OTTO Auto-Fix** — concrete, ready-to-paste patches
- `POST /api/seo/otto/generate-fixes` `{audit_id, max_fixes?}` — walks the
  audit's pages, produces a patch per issue via **Claude Sonnet 4.6 (LIVE,
  `mocked:false`)**. Falls back to a deterministic static template for
  `CANONICAL_MISSING / JSONLD_MISSING / OG_MISSING / SITEMAP_MISSING` when
  the LLM is silent. De-duplicates: repeat calls do NOT recreate pending
  fixes for the same (page_url, issue_code).
- `GET  /api/seo/otto/fixes/{audit_id}?status=…` — list + totals grouped
  by pending / applied / dismissed.
- `POST /api/seo/otto/fixes/{fix_id}/mark-applied`
- `POST /api/seo/otto/fixes/{fix_id}/dismiss`
- `GET  /api/seo/otto/fixes/{fix_id}/patch-file` — downloadable `.html` snippet.
- Collection: `seo_otto_fixes` (tenant-scoped; unique per pending fix).
- Patch types: `title / meta / h1 / alt / canonical / schema / broken_link /
  content / og / sitemap`.

**17C.2 · Website Studio** — page builder with AI section auto-fill
- `POST /api/seo/studio/pages`, `PUT /…/{id}`, `GET /…`, `GET /…/{id}`
- `POST /api/seo/studio/pages/{id}/auto-fill` `{business_context,
  target_keyword}` — **Claude LIVE (`mocked:false`)** generates 5–8 sections
  with typed heading / subheading / body / items. Verified live: 8 sections
  produced (hero, services, features, benefits, testimonials, faq, cta,
  local_business_schema).
- `POST /api/seo/studio/pages/{id}/publish`
- `GET  /api/seo/studio/pages/{id}/export?format=html|markdown|json`
- Public **`GET /api/preview/studio/{slug}`** — no-auth HTML render;
  draft pages 403, missing 404, published render fully-styled HTML page.
- Section types (validated on write): hero, features, benefits, services,
  testimonials, faq, cta, local_business_schema.
- Slug is unique per tenant (409 on collision).
- Collection: `seo_studio_pages`.

**17C.3 · White-Label Reports** — branded PDF (reportlab) + HTML fallback
- `POST /api/seo/reports` `{title, brand_name?, brand_color?, logo_url?,
  audit_id?, heatmap_id?, topical_map_id?, include_llm_visibility?,
  range_days?}` — hydrates data blob, runs **Claude LIVE** for exec summary
  (`{summary, key_wins:[str], top_opportunities:[str]}`). Cross-tenant ids
  → 404. Missing data source (no audit/heatmap/topical/llm) → 400.
- `GET  /api/seo/reports` (list, `data` blob stripped for weight)
- `GET  /api/seo/reports/{id}` (full detail)
- `GET  /api/seo/reports/{id}/download?format=pdf|html` — real PDF via
  reportlab (verified 3537-byte PDF w/ header, score table, exec summary,
  audit block); HTML fallback with `X-Pdf-Fallback: true` header if PDF
  generation ever fails.
- `POST /api/seo/reports/{id}/send` `{to, subject?, message?}` — Resend
  email + PDF attachment (or HTML attachment if PDF gen failed).
  Returns `{sent:false, reason:'resend-not-configured', ...}` when
  `RESEND_API_KEY` is unset (verified graceful path).
- Collection: `seo_reports`.

### 17B naming polish shipped alongside (backwards-compatible)
LLM Visibility endpoints canonicalize on `mention_rate_pct`, `competitors`,
`engines_configured`. Deprecated aliases `mentions_rate_pct`,
`competitors_mentioned`, `engines_scanned` are still returned for one
release. Applies to both `/scan` and `/dashboard` endpoints. Live curl:
```
GET /api/seo/llm-visibility/dashboard
canonical: mention_rate_pct=T, competitors=T, engines_configured=T
aliases:  mentions_rate_pct=T, competitors_mentioned=T, engines_scanned=T
```

### Frontend web
- New pages under `/app/frontend/src/pages/seo/`:
  - `OttoAutoFix.jsx` — reachable at `/admin/seo/audits/:id/otto` and from a
    new **Auto-Fixes** button on the audit detail header.
  - `WebsiteStudio.jsx` — list at `/admin/seo/studio` + editor at
    `/admin/seo/studio/:id` with LIST + auto-fill + publish + export bar
    (HTML / Markdown / JSON) + open-live-preview button when published.
  - `WhiteLabelReports.jsx` — list at `/admin/seo/reports` + detail at
    `/admin/seo/reports/:id` (branded header, score table, exec summary,
    key wins, top opportunities, PDF/HTML download + Email modal).
- Two new admin sidebar entries in `adminNav.js`:
  **Website Studio** + **White-Label Reports**.

### Tests — `test_seo_phase17c.py` (11/11 green in ~91s)
- LLM naming polish: dashboard has canonical + aliases; scan response
  includes `engines_configured` mirrored to `engines_scanned`.
- OTTO: generate creates patches (`mocked:false` verified), mark-applied +
  dismiss flip status, patch-file download returns attachment, tenant
  isolation returns 404 across tenants, tech → 403, duplicate-fix guard.
- Studio: full CRUD + publish + public preview (200 for published, 403 for
  draft, 404 for missing), export in all 3 formats, live auto-fill returns
  8+ sections all of allowed types, tenant isolation + role gate + slug
  uniqueness.
- Reports: create + list (data blob stripped) + detail + PDF/HTML download,
  send email graceful fallback + bad-email 400 + no-data 400, tenant
  isolation + tech/customer 403 + cross-tenant references 404.

Full SEO regression suite: **26/26 green** (15 prior 17A/17B + 11 new).

### Live proof (external ingress)
```
# 17C.1 · OTTO Auto-Fix
POST /api/seo/otto/generate-fixes {"audit_id":"..."} →
  count=1, mocked:false, first fix:
  issue_code=CANONICAL_MISSING patch_type=canonical
  patch_snippet=<link rel="canonical" href="https://example.com/otto" />

# 17C.2 · Website Studio auto-fill
POST /api/seo/studio/pages/{id}/auto-fill →
  mocked:false, count=8, sections=[hero, services, features, benefits,
                                     testimonials, ...]
  first heading: "Phoenix's Most Trusted Pool Service —
                   Crystal Clear Water, Every Week"
GET  /api/preview/studio/{slug} → 200 text/html
                                    (published page renders with title tag)

# 17C.3 · White-Label Reports
POST /api/seo/reports {audit_id, include_llm_visibility:true} →
  status:ready, mocked:false, key_wins=3
  exec_summary: "AquaTerra's digital presence shows a moderate foundation
                  with a site audit score of 75/100 across three audited
                  pages, indicating a functional but improvable technical
                  baseline. ..."
GET  /api/seo/reports/{id}/download?format=pdf →
                                200 application/pdf, 3537 bytes
```

### Files touched
- **New**: `backend/routers/seo_phase17c.py`,
  `backend/tests/test_seo_phase17c.py`,
  `frontend/src/pages/seo/OttoAutoFix.jsx`,
  `frontend/src/pages/seo/WebsiteStudio.jsx`,
  `frontend/src/pages/seo/WhiteLabelReports.jsx`.
- **Edited**: `backend/server.py` (register new router),
  `backend/routers/seo_agentic.py` (LLM Visibility naming polish — canonical
  + deprecated aliases), `frontend/src/App.js` (5 new routes),
  `frontend/src/nav/adminNav.js` (2 new SEO entries),
  `frontend/src/pages/seo/SeoAudits.jsx` (Auto-Fixes button on audit detail),
  `memory/HANDOFF.md` (this section).

### Deferred / non-blocking
- OTTO's "apply to WordPress" one-click — for now the patch is downloadable
  as an HTML snippet and marked applied when the user hits the button.
  Auto-apply through the existing WordPress integration is a future upgrade.
- Studio drag-and-drop section reordering — sections are add/remove today;
  reorder is a nice-to-have.
- Reports scheduling (recurring monthly report auto-generation) — deferred.

---

## Phase 17 · Mobile SEO Suite parity (Feb 2026)

All 9 SEO web pages ported to Expo screens under `/app/mobile/app/admin/seo/`.
Admin-only, tenant-scoped, consumes the same `/api/seo/*` endpoints as web.
Zero new backend endpoints.

### New mobile files (11 route files + 1 shared helper)
- `admin/seo/_shared.tsx` — `AdminOnlyGate`, `ScoreChip`, `SeverityDot`,
  `BrandPill`, `CenterLoader`, `DesktopHint` (underscore-prefixed →
  expo-router ignores it as a route).
- `admin/seo/audits.tsx` — 17A list with score chip per audit + FAB.
- `admin/seo/audits/[id].tsx` — 17A detail: 4-score ring row + tabbed
  Issues / Pages / OTTO Fixes. Auto-refresh while queued/running.
- `admin/seo/content-scorer.tsx` — 17A HTML/URL toggle, keyword input,
  8-bar breakdown + AI recommendations.
- `admin/seo/rank-heatmap.tsx` — 17A form + **table view** (lat/lng/rank/
  top URL). Includes “Best viewed on desktop” hint. Polls until scan done.
- `admin/seo/topical-map.tsx` — 17B seed form + **collapsible pillar → cluster
  → supporting tree** with intent color badges. Desktop hint for graph.
- `admin/seo/llm-visibility.tsx` — 17B tabs: **Queries** (CRUD + Run scan)
  and **Dashboard** (mention %, avg position, engine pills w/ “not
  configured” labels, top competitors).
- `admin/seo/atlas.tsx` — 17B chat: conversation history drawer, tool-call
  cards inline (name, args, status pill, JSON result), keyboard-avoiding
  composer, streaming feel via optimistic user message + spinner.
- `admin/seo/otto.tsx` — 17C cross-audit fix list. Status + patch-type
  chip filters. Tap → detail.
- `admin/seo/otto/[id].tsx` — 17C stacked before/after diff (red / green
  cards), monospace patch snippet block, **Copy patch** (expo-clipboard),
  **Mark applied**, **Dismiss**.
- `admin/seo/studio.tsx` — 17C read-only page list. Tap → WebView
  live-preview (published) or draft summary. Mobile actions: **AI Auto-Fill**
  and **Publish** are 1-tap. Section editing intentionally desktop-only.
- `admin/seo/reports.tsx` — 17C list + New Report modal (title, brand
  name, audit picker, LLM toggle) + **Share PDF** via
  `FileSystem.downloadAsync` (legacy API) → `Sharing.shareAsync`.

### Nav update — `(app)/more.tsx`
- Added `showSeoSection = admin || super_admin` guard.
- New **SEO** section between Management and Tools with the 9 entries
  (icons + labels + testIDs `more-seo-*`).
- Fixed a latent bug: `showAdminSection` was previously referenced but
  never defined (admin Management section was invisible). Now defined as
  `admin || super_admin || marketing`.

### Style consistency
- Reused `colors`, `spacing`, `radius`, `font`, `fontSize` from
  `@/src/theme` and the `Header` widget — no new visual system.
- All list rows / chips / cards match the existing `(app)/*` conventions
  (surface + border + rounded, brand-tint pills).

### Mobile-specific tradeoffs (explicitly labeled in-app)
- **Rank Heatmap** map overlay → table view + `DesktopHint`.
- **Topical Map** graph → collapsible list + `DesktopHint`.
- **Studio** section editor → read-only page list; only Publish + AI
  Auto-Fill work on mobile; editing routed to desktop.
- Rest (Audits, Content Scorer, LLM Visibility, Atlas, OTTO, Reports) are
  full-feature parity.

### 403 gating
Every screen wraps its body in `<AdminOnlyGate>` — non-admin users see a
lock icon + “Admins only” empty state. Non-admin roles never see the
mobile SEO nav section either.

### TypeScript
`tsc --noEmit` on the 12 new/edited files: **0 errors**.
(22 pre-existing errors elsewhere in the codebase, none touched by this pass.)

### Verification
- Container Expo web preview unavailable in this environment — no
  screenshots captured. Code confirmed TS-clean; every route file exports
  a default component; `_shared.tsx` is underscore-prefixed so expo-router
  skips it as a route.
- Human-required check: run `yarn --cwd /app/mobile web` (or scan the
  Expo Go QR from `expo start`) and walk the 9 SEO screens with
  `admin@aquaterra.com / password123`.

---

## Phase 21 · Field Estimator (Feb 2026)

SimplyWise-inspired AI cost estimator. Users: **admins AND technicians**.
Photos + scope → Claude vision → line items priced against the tenant's
rate catalog → upsells → 1-tap **Convert to Quote** into the existing
quotes pipeline.

### Backend — 470 → 483 OpenAPI paths (+13, new `routers/estimator.py`)

Endpoints (mounted under `/api/estimator/*`):
- **Estimates**: POST /estimates, POST /estimates/{id}/generate (Claude
  vision LIVE), GET list, GET detail, PATCH edit, POST add-line-item,
  DELETE line-items/{iid}, POST regenerate-upsells,
  POST convert-to-quote (admin-only), POST pdf, GET pdf.file,
  POST send-to-customer (Resend, graceful when key absent).
- **Rate catalog**: GET, PUT (admin), POST reset-defaults — starter
  catalog of 20 items (labor, materials, equipment, permits).
- **Settings**: GET/PUT tenant `settings.estimator` (default_markup_pct=20,
  tax_rate_pct=0, include_upsells=true).

### AI pipeline (backend `_call_generate` + `_apply_catalog`)
Vision-enabled Claude Sonnet 4.6 via `EMERGENT_LLM_KEY`. Photos passed as
`ImageContent` (up to 6 per call). Room-scan payload from LiDAR is folded
into the prompt when present. Strict JSON output → line items + upsells.
Merge step matches AI `code` against the catalog → stamps
`unit_price_source: "tenant_rate"` (confidence=1.0) when found, else
`"ai_estimate"` with Claude's 0-1 confidence carried through.
Manual line items stamped `"manual"`.

### Convert-to-quote
Folds the estimate's markup into per-line prices so the resulting quote's
total matches the estimate's total. Sets `estimate.status = "converted"`,
persists `quote_id`, writes `source_estimate_id` on the quote. Idempotent:
second call returns `{quote_id, already_converted: true}` without
creating a duplicate quote.

### Collections
- `estimator_estimates` — full doc (photos, room_scan, line_items,
  upsells, totals, status, quote_id, pdf_url, mocked, timestamps).
- `estimator_rate_catalog` — one doc per tenant, items array.

### Frontend web — `/admin/estimator/*`
- List `/admin/estimator` — status filter chips, per-row status pill +
  total, "New estimate" + "Rate catalog" actions.
- New `/admin/estimator/new` — title, service_type, customer picker,
  address, scope textarea, up-to-10 photo URLs, "Generate estimate"
  fires create + generate + redirects to detail.
- Detail `/admin/estimator/{id}` — inline-editable line item table (qty +
  unit price), per-item source pill (green "✓ From your rate catalog"
  or amber "AI estimate — adjust for your market · confidence %"),
  totals sidebar, upsell cards with "+ Add to estimate" one-tap,
  Download PDF, Email modal, Convert to Quote CTA.
- Rate editor `/admin/estimator/rates` — 20-row table, add/edit/delete,
  reset-to-defaults, save.

### Frontend mobile — Expo screens
- `/(app)/estimator/index.tsx` — list with status pills + `+` FAB.
- `/(app)/estimator/new.tsx` — multi-select photo picker (up to 10)
  via `expo-image-picker`, service type chips, customer chips, LiDAR
  scan section (visible only when opted-in from settings).
- `/(app)/estimator/[id].tsx` — totals card, share-PDF via
  `expo-sharing`, convert-to-quote button, line items with source pills,
  upsell cards with "Add to estimate".
- `/(app)/settings/lidar.tsx` — LiDAR toggle. Uses `expo-constants`
  `ExecutionEnvironment` to detect Expo Go vs. native build → shows
  friendly "safe no-op" or "native ready" banner.
- More menu: **Field Estimator** entry added to both admin and tech
  link arrays. **LiDAR Settings** entry added to admin menu.

### Tests — `test_estimator.py` (7/7 green in ~33s)
1. Rate catalog seed + PUT + reset.
2. Create + generate — Claude LIVE, `mocked:false`, ≥4 line items, ≥3
   upsells, extended_price math verified.
3. Rate catalog price match — direct unit test of `_apply_catalog`
   confirming a seeded `pool_tech_hourly` at $88.50 stamps
   `unit_price_source:"tenant_rate"` while unmatched code falls back to
   `"ai_estimate"`.
4. Convert-to-quote — real quote doc created, source_estimate_id set,
   estimate.status flipped, second call idempotent.
5. PDF — 200 with `application/pdf` (or HTML fallback with the same
   header contract), Content-Disposition attachment.
6. Tenant isolation — sunbelt admin 404 on aquaterra estimate.
7. Role gating — customer 403 on all endpoints; tech CAN create but
   CANNOT convert-to-quote and CANNOT edit rate catalog.

**17C regression suite: 13/13 still green.** TypeScript: 0 errors on
all new mobile files.

### Live proof (external ingress)
```
POST /api/estimator/estimates {...pool resurface...} → estimate_id
POST /api/estimator/estimates/{id}/generate →
  mocked:false, line_items=10, upsells=5, total=$16,188
  first item: "PebbleTec pool resurfacing …" qty=400 sqft
              $/u=$12.50  src=ai_estimate  conf=0.88
POST /api/estimator/estimates/{id}/convert-to-quote →
  quote_id created, quote.total == estimate.total ($16,188)
PUT  /api/estimator/rate-catalog {items:[...]}  → 200, items overwritten
```

### Files touched
- **New backend**: `backend/routers/estimator.py`,
  `backend/tests/test_estimator.py`.
- **New web**: `frontend/src/pages/estimator/EstimatorPages.jsx`
  (list + new + detail + rates in one file, 4 exports).
- **New mobile**: `mobile/app/(app)/estimator/index.tsx`,
  `mobile/app/(app)/estimator/new.tsx`,
  `mobile/app/(app)/estimator/[id].tsx`,
  `mobile/app/(app)/settings/lidar.tsx`.
- **Edited**: `backend/server.py` (register router),
  `frontend/src/App.js` (4 routes),
  `frontend/src/nav/adminNav.js` (Field Estimator nav entry),
  `mobile/app/(app)/more.tsx` (Field Estimator on both admin + tech
   link lists, LiDAR Settings on admin).

### Human-required checks
- **LiDAR native binding** — the wrapper ships as a placeholder that's
  safe-no-op in Expo Go. To activate real ARKit RoomPlan scans, an
  EAS iOS build + community RoomPlan module (or a custom native module)
  is required. The toggle in `/settings/lidar` persists user intent
  and will pick up the module at runtime once installed.
- **Real photo QA** — smoke tests used stock Unsplash pool photos.
  Snap a real tech-in-the-field photo and confirm Claude's line-item
  breakdown holds up (quantities, category classification).

---

## Phase 22 · Automated invoice dunning (Feb 2026)

Configurable per-tenant reminder cadence + AR aging analytics. Backend
scanner runs every 60 min via APScheduler.

### Backend — 486 → 494 OpenAPI paths (+8)

New router `routers/dunning.py`:
- **Settings** GET / PUT / POST reset-defaults
- **Manual send** POST /invoices/{id}/send-reminder
- **History** GET /invoices/{id}/history
- **Pause/Resume** POST /pause/{id}, /resume/{id}
- **Queue** GET /queue?days=N
- **Analytics** GET /analytics/ar-aging

Default cadence (6 stages, one settings doc per tenant):
`pre_due_3d` (–3d, email) → `on_due_day` (0d, email) →
`past_due_7d` (7d, email) → `past_due_14d` (14d, email + sms) →
`past_due_30d` (30d, email + sms, flag `at_risk`) →
`past_due_60d` (60d, email + sms, flag `in_collections`).

Templates use `{customer_name}`, `{invoice_number}`, `{invoice_total}`,
`{due_date}`, `{days_past_due}`, `{payment_link}`, `{tenant_name}`,
`{tenant_phone}`. **Payment link** = Stripe hosted `PaymentLink` when
`STRIPE_SECRET_KEY` is set (cached on the invoice), else in-app
`{APP_PUBLIC_URL}/portal/invoices/{id}/pay`.

Scanner (`run_dunning_scan`, registered as APScheduler job every 60 min):
walks every tenant → active-dunning invoices → for each due stage
computes `days_past = today - due_date`, fires stages where
`days_past >= offset` AND no prior `dunning_reminders` doc exists for
`(invoice, stage)`. Also flips `sent → past_due` when due, and stamps
`risk_status = at_risk / in_collections` at the escalation thresholds.

Channels:
- **Email** LIVE via Resend when `RESEND_API_KEY` set. Persists a
  `dunning_reminders` doc with real status (`sent | failed | pending_resend`).
- **SMS** via Twilio — returns `status: "pending_twilio"` with
  `error: "twilio-not-configured"` when keys absent. **No silent mock.**

### Collections
- `dunning_settings` (one per tenant)
- `dunning_reminders` (indexed by tenant_id + invoice_id + sent_at)

### Frontend web — 3 admin pages
- `/admin/dunning/settings` — full cadence editor (enable toggle,
  at_risk/in_collections thresholds, per-stage name + offset days +
  channel checkboxes + subject/email/SMS templates).
- `/admin/dunning/queue` — table of next-N-days reminders with Send-now
  + Pause per row.
- `/admin/dunning/analytics` — 4 KPI cards (total outstanding, DSO,
  collection rate, at-risk/in-collections counts) + horizontal bar chart
  of the 4 aging buckets.

Sidebar entries added under Billing: **Dunning queue · AR aging · Dunning setup.**

### Frontend mobile
`(app)/dunning/queue.tsx` — read-only queue with tap-to-send-now (admin
gated via `AdminOnly`-style check in the component). Nav entry added to
`more.tsx` admin link array. Full editing stays on desktop.

### Tests — `test_dunning.py` (11/11 green in ~17s)
1. Default settings seeded on first GET after wipe.
2. PUT validates unique offsets, non-empty channels; reset-defaults works.
3. Manual send persists a `dunning_reminders` doc with honest status
   (sent / pending_resend / failed with error surfaced).
4. SMS returns `pending_twilio` with clear reason when keys absent.
5. Scanner fires the correct stage on an 8-day past-due invoice AND is
   idempotent — second scan does not re-fire.
6. Pause blocks scanner; resume + rescan fires again.
7. Escalation: 31d → `risk_status: "at_risk"`, 61d → `"in_collections"`.
8. Queue lists upcoming reminders in the window.
9. AR aging analytics correctly buckets 4 seeded invoices across
   `current / aging_30 / aging_60 / aging_90`.
10. Tenant isolation — sunbelt admin 404 on aquaterra invoice history.
11. Role gating — tech + customer 403 on all 5 dunning endpoints
    (settings, queue, analytics, history, manual send).

**Regression: prior 8 estimator + 13 SEO 17C tests still green.**

### Live proof (external ingress)
```
GET  /api/dunning/settings → 6 stages seeded, escalation {30, 60}
PUT  /api/dunning/settings {escalation:{25,55}} → 200
POST /api/dunning/invoices/{id}/send-reminder →
  channel=email, status=failed
  error="You can only send testing emails to your own email address …"
  (Resend live, sandbox restriction — HONEST failure surfaced)
GET  /api/dunning/queue?days=30 → 18 reminders scheduled
GET  /api/dunning/analytics/ar-aging →
  current=$871, aging_30=$250, aging_60=$754, aging_90=$280
  aging_total=$2155, DSO=29.9d, collection_rate=21%
  at_risk=3, in_collections=1
```

### Human-required checks
- **Verify a domain on Resend** — currently the sandbox restricts sends
  to the account owner. Verify a domain at resend.com/domains and set
  `EMAIL_FROM` to `hello@<yourdomain>` so reminders reach real customers.
- **Provide Twilio credentials** — set `TWILIO_ACCOUNT_SID`,
  `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM` (a purchased phone number) to
  activate SMS. Until then, SMS rows write `pending_twilio`.
- **Real Stripe** — the code uses `stripe.PaymentLink.create` for hosted
  payment links. It needs a live `STRIPE_SECRET_KEY`. Without it,
  reminders fall back to the in-app portal URL — still works, just not
  a Stripe-hosted page.

---

## Phase 29A · Mobile Wave A Parity (Feb 15 2026)

Mobile-only port of Phase 26 Wave A (Dispatch Board, Weather Reschedule,
Batch Checks + Payroll CSV) into the Expo app. Backend / DB / web untouched.

### Screens
- `/(app)/dispatch/board.tsx` — unassigned-jobs list, per-row auto-assign,
  bulk auto-assign, `auto_assign_on_create` toggle, active-tech list
  (deduped by `user_id || id` to hide the known Phase 26 polish
  cosmetic dup).
- `/(app)/dispatch/weather.tsx` — mode picker (manual / auto), threshold
  summary, "Run weather scan" button, proposed-events accept/reject
  with optional YYYY-MM-DD override date, decided-events history.
- `/(app)/payroll/batch.tsx` — two tabs: manual batch (bank + payees +
  lines, live total, open PDF in browser) and Payroll CSV
  (`expo-document-picker` → preview → execute → open PDF).

### Nav wiring
- Mobile Tools Hub (`(app)/tools.tsx`) admin sections got two new groups
  **Dispatch** (Board + Weather) and **Payroll** (Batch/CSV).
- `(app)/more.tsx` admin Management list retargets **Dispatch** to
  `/(app)/dispatch/board` and adds Weather + Batch entries.
- Three hidden `<Tabs.Screen>` registrations in `(app)/_layout.tsx`
  (href: null — reachable via router.push, invisible on the tab bar).

### API helper
- `mobile/src/api.ts` gained `api_base()` and async `getAuthToken()` so the
  CSV upload can attach the bearer through `multipart/form-data` without
  hijacking the JSON wrapper.

### Verification
- Backend regression: **42/42 green** across Phase 26/27/28/checks/inventory
  suites in 106s.
- Curl-verified all 7 endpoints my screens hit return 200 as
  `admin@aquaterra.com` on the external ingress URL.
- Metro bundler clean (no new SyntaxErrors in mobile logs).

### Deferred
- Native date picker on weather override (currently plain text field).
- Route batch-PDF through `expo-sharing` instead of `Linking.openURL()`.
- CSV column-mapper UI (mobile caps at 20 preview rows).

### Files touched
- **New**: `mobile/app/(app)/dispatch/board.tsx`,
  `mobile/app/(app)/dispatch/weather.tsx`,
  `mobile/app/(app)/payroll/batch.tsx`,
  `memory/HANDOFF_P29A_MOBILE_WAVE_A.md`.
- **Edited**: `mobile/app/(app)/_layout.tsx`, `mobile/app/(app)/tools.tsx`,
  `mobile/app/(app)/more.tsx`, `mobile/src/api.ts`.

**Backend, DB, web: untouched (per phase brief).**

### Phase 29A · Fix pass (Feb 15 2026, post-tester)
Tester (T2) surfaced two defects on the Dispatch Board mobile screen. Fixed in `mobile/app/(app)/dispatch/board.tsx` only; no backend, no other screens.

- **Defect 1 (tech dedup key wrong).** The duplicate rows for the same tech return different `id` AND `user_id` values but the same email. Replaced the `user_id || id` key with a three-tier fallback: `email → name → id`, all trimmed and lowercased. When two rows share a key, the one with more populated `preferred_service_types` wins. Verified by curling `/api/dispatch/technician-skills` as admin: 3 raw rows (2× Mike Rivera + 1× Sara Nguyen) collapse to 2 unique techs (`email:mike@aquaterra.com` and `email:sara@aquaterra.com`). Backend dedup deferred to a future P3 pass as instructed.
- **Defect 2 (bulk auto-assign silent).** The success message was being nuked by the immediate `await load()` call that resets msg state. Reordered to `load()` first, then set the toast, and additionally show a native `Alert.alert()` popup (guaranteed visible even if the list scrolls) with `"{ok} jobs assigned · {fail} skipped"`. Errors surface the first API error message in the alert body. Matches the existing inline-toast idiom used by the Weather screen — no new library added.

Backend regression re-run after the fix: **18/18 green** (`test_phase26_wave_a` 13 + `test_phase26_polish_p21_audit` 5).

---

### Phase 29B · Check Writer key rotation (Feb 15 2026)

Rotated the Check Writer's symmetric encryption off the shared JWT_SECRET-derived key onto a dedicated `CHECKS_ENCRYPTION_KEY` env var. Backend + a single migration endpoint only. Web/mobile untouched. MICR E-13B font work remains deferred pending a licensed asset.

**Env var** — `CHECKS_ENCRYPTION_KEY` in `/app/backend/.env`, generated once via `base64.urlsafe_b64encode(os.urandom(32))`. Kept in the standard `.env` file per the env-additive-only rule. If the var is missing at boot the module logs a WARNING (`"CHECKS_ENCRYPTION_KEY not set — using legacy JWT_SECRET-derived key…"`) and the app keeps running on the legacy key — never crashes.

**Read path** (`_decrypt`) — tries the new key first, then the legacy JWT_SECRET-derived key as fallback. Returns empty string only if both fail (matches pre-P29B behavior).

**Write path** (`_encrypt`) — always uses `_fernet_write()`, which returns the new key if loaded and the legacy key as a last-resort fallback so the app is never brick-locked by a bad env var.

**Migration endpoint** — `POST /api/checks/admin/re-encrypt`. Admin-only, tenant-scoped. Walks every `bank_accounts` row for the current tenant, decrypts with either key, re-encrypts with the new key, updates the row. Idempotent — already-migrated rows still decrypt (with the new key alone) and get re-written with a fresh ciphertext.

Response shape: `{scanned, migrated, skipped, failed, using_dedicated_key}`.

**Test hook** — `_reload_fernet_from_env()` re-reads the env var for the module-level singleton so pytest can force env states without a full restart.

**Files touched**
- `backend/routers/checks.py` — new `_legacy_fernet` / `_load_new_fernet` / `_reload_fernet_from_env` / `_fernet_write` helpers; `_encrypt` / `_decrypt` rewired; `POST /checks/admin/re-encrypt` added.
- `backend/.env` — appended `CHECKS_ENCRYPTION_KEY=…` (new secret, base64 urlsafe, 32-byte).
- `backend/tests/test_phase29b_check_crypto.py` — new (4 tests).

**Test results**
- New suite: **4/4 passed**.
- Phase 29B + `test_checks` + `test_phase26_wave_a` + `test_phase28_warranties`: **37/37 passed** in 16 s.
- Full boot test: with `CHECKS_ENCRYPTION_KEY` removed the backend restarted cleanly, logged the exact warning, and `/api/openapi.json` + `/api/checks/bank-accounts` both returned 200.
- OpenAPI still lists all previously-registered paths; new endpoint `/api/checks/admin/re-encrypt` visible.

**Deferred (P29B-follow-up)**
- MICR E-13B TTF font — still blocked on the licensed asset. Current PDF renderer left completely untouched. When the font ships, the `/checks/checks/{cid}/print` path is where the glyphs need to be wired in.
- Optional: a "rotate secret" job that generates a new key, migrates all tenants, and archives the previous key envelope. Not urgent — the current model already survives one rotation gracefully.

---

### Phase 29C · Permissions UI + Test-as-role preview (Feb 15 2026)

Web-only. Extended the pre-existing Phase 14 permissions hook, added a compact preview picker, hardened `can()` against matrix shape drift, exposed a per-user RBAC endpoint, and gated the most sensitive destructive actions on 4 pages. Mobile Expo enforcement is queued for a later phase.

#### A · Bucket table (what each role sees)
Actual roles in the users collection: `super_admin`, `admin`, `technician`, `customer`. Matrix also carries stub roles `marketer` and `sales` (no seeded users but selectable in the previewer).

| Bucket | Pages / features | Enforcement path |
|---|---|---|
| **Always-on** (super_admin, admin) | Dashboard, Tools Hub, Business Card, Profile | AdminSidebar bypass |
| **Feature-gated** | Customers, Jobs, Quotes, Invoices, Payments, Dispatch, Weather, Warranties, Marketing, SEO, Reports, Inventory, Estimator | `can(feature,"read")` on nav entries |
| **Admin/super-admin only (hard rule)** | Check Register + Bank Accounts + Payees, Payroll CSV Execute, Check-encryption Rotate, Permissions editor, Audit logs, Tenants, Team | `hard_rule:"admin_only"` on nav + backend `require_admin` |
| **Tech-only nav** | Schedule, D2D, Time Clock, Tools Hub, Profile | Role-based `TECH_NAV` |
| **Customer-only nav** | Portal Home, Book, Invoices (own), Estimates (own), Photos, Messages | Role-based `CUSTOMER_NAV` |
| **Deny (silently hidden)** | Anything not granted for the role; deep-linked URLs render `<Forbidden />` when wrapped in `RequirePermission` | client-side + backend `403` |

#### B · Client-side enforcement layer
- **`/app/frontend/src/hooks/usePermissions.jsx`** rewritten. New:
  - `useRole()` — returns effective role (real or previewed).
  - `useCan(perm, action?)` — accepts `"Feature"` or `"Feature.action"`.
  - `<Gate perm="…" action="…" [showForbidden] [reason] [fallback]>` — hide-or-forbid.
  - `<Forbidden reason="…" [onHome]>` — bordered "access denied" block with a Return-home button (`data-testid="forbidden-block"`).
  - `<RequirePermission perm="…">` — route wrapper.
  - `AVAILABLE_ROLES` constant used by the picker.
  - `previewRole` now persisted in `sessionStorage` (not localStorage) so a stale preview never survives a logout / new tab.
  - `can()` is now **shape-tolerant** — accepts either `{feature:"write"}` (v1 server shape) or `{feature:["read","write"]}` (v2), and is case-insensitive on the feature key so `Customers` and `customers` both match.
  - Super-admin bypass fixed: bypass only applies when NOT previewing — so "Test as customer" actually shows the customer restricted UI.
- Legacy `<PermGate>` kept as an alias to avoid churn.

#### C · Backend contract
- New router: **`/app/backend/routers/rbac.py`** exposing `GET /api/rbac/me/permissions`. Tenant-scoped: reads a tenant-specific matrix if present, else the global seeded matrix, else the defaults baked into the router. Response shape: `{role, permissions:{feature:{read:bool,write:bool,...}}, is_admin, tenant_id}`. Admin/super-admin get `{__all__: {read:true, write:true}}` so the UI can short-circuit.
- Existing `GET /api/permissions` (full matrix) and `PUT /api/permissions` (admin-only editor) untouched.
- **No** matrix editor UI built this phase — noted in the backlog.

#### D · "Test as Role" preview
- **`/app/frontend/src/components/RolePreviewSwitcher.jsx`** — compact pill with an `<select>` listing the 6 previewable roles + an "Exit" pill. Only real admins/super-admins see it (`canPreview`).
- Mounted in two places:
  - **Admin sidebar** — top of the sidebar, right under the `⌘K` palette trigger.
  - **Mobile top-bar** — next to the "Sign out" button.
- Selecting a role sets `previewRole` (session-scoped). Yellow banner "🔍 Preview mode — permissions as <role>. Click to exit." already existed in `AppLayout.jsx`; the switcher now feeds it. Two exit affordances: the banner button and the pill's `Exit` button.
- Backend calls STILL carry the real user's JWT — server RBAC unaffected. The switcher's tooltip and this HANDOFF section spell that out.

#### E · Gated inline actions (spot-sweep across sensitive actions)
Wrapped 7 destructive actions across 4 files with `<Gate>`:

| File | Action | Perm |
|---|---|---|
| `pages/dispatch/DispatchPages.jsx` | Auto-assign all (`dispatch-assignall-btn`) | `Jobs.write` |
| `pages/dispatch/DispatchPages.jsx` | Weather scan (`weather-scan-btn`) | `Jobs.write` |
| `pages/customers/CustomersList.jsx` | Bulk delete (`bulk-delete`) | `Customers.write` |
| `pages/checks/CheckBatchPages.jsx` | Create checks batch (`batch-save`) | `Settings.write` |
| `pages/checks/CheckBatchPages.jsx` | Payroll CSV execute (`payroll-execute-btn`) | `Settings.write` |
| `pages/checks/ChecksPages.jsx` | Delete bank account (`check-bank-delete-*`) | `Settings.write` |
| `pages/checks/ChecksPages.jsx` | Delete payee (`check-payee-del-*`) | `Settings.write` |

Jobs list, Invoices list, and Users management pages have no top-level destructive buttons (all destructive UI lives on detail sub-pages) — noted for the follow-up sweep.

#### F · Tests
- **`/app/backend/tests/test_phase29c_rbac.py`** — 11 tests, all green. Covers endpoint registration, per-role shape (super_admin, admin, tech, customer), no-auth denied, and server-side RBAC spot-checks (techs and customers get 403 on `/checks/bank-accounts POST`, `/checks/admin/re-encrypt POST`, and `/dispatch GET`).
- Broader regression: `test_phase29c_rbac` + `test_phase29b_check_crypto` + `test_phase26_wave_a` + `test_phase28_warranties` + `test_checks` = **48/48 passed** in 48 s.

#### G · Live browser smoke (Playwright)
Logged in as `admin@aquaterra.com`, verified:
- `role-preview-switcher` and `role-preview-select` render in the sidebar.
- Switching to `technician` fires the yellow banner (`preview-banner`).
- Sidebar switches to `TECH_NAV`: **Marketing** disappears, **Schedule** remains — the effective-role plumbing is honored downstream.
- `GET /api/rbac/me/permissions` returns:
  - `super_admin` → `is_admin:True perms:['__all__']`
  - `admin` → `is_admin:True perms:['__all__']`
  - `technician` → `is_admin:False perms:['Jobs','Customers']`
  - `customer` → `is_admin:False perms:[]`
- No new console errors, webpack "compiled with warnings" (pre-existing `esbuild-loader` chatter only).

#### H · Test credentials
No new accounts. Existing 4 demo users cover the 4 seeded roles. `marketer` / `sales` are matrix-only (no seeded user) — usable via the "Test as" preview.

#### I · Files touched
**New**
- `backend/routers/rbac.py`
- `backend/tests/test_phase29c_rbac.py`
- `frontend/src/components/RolePreviewSwitcher.jsx`

**Edited**
- `backend/server.py` — register `rbac` router.
- `frontend/src/hooks/usePermissions.jsx` — full rewrite (Phase 14 baseline preserved, new exports).
- `frontend/src/layouts/AdminSidebar.jsx` — mount the switcher.
- `frontend/src/layouts/AppLayout.jsx` — mount the switcher on mobile top-bar.
- `frontend/src/pages/dispatch/DispatchPages.jsx` — 2 `<Gate>` wraps + import.
- `frontend/src/pages/customers/CustomersList.jsx` — 1 `<Gate>` wrap + import.
- `frontend/src/pages/checks/CheckBatchPages.jsx` — 2 `<Gate>` wraps + import.
- `frontend/src/pages/checks/ChecksPages.jsx` — 2 `<Gate>` wraps + import.
- `memory/HANDOFF.md` — this section.

#### J · Out of scope / deferred
- Matrix editor UI (backlog).
- Deep sweep of remaining ~30 pages (only the highest-signal 4 files gated here).
- Mobile Expo permission enforcement — separate future phase.
- `dispatcher` role — brief listed it but the DB doesn't have such a role; not adding a phantom.

---

### Phase 30 · Calendar Redesign (Feb 15 2026)

Retired the admin/dispatcher Jobs list and the tech "Today" schedule. Both roles now land on a single unified **Calendar Schedule** with Day / Week / Month / Custom-range views on web AND mobile. Customer portal untouched — Phase 30 hard rule.

#### Web (`/app/frontend/`)
- **New** `pages/schedule/CalendarSchedule.jsx` — `react-big-calendar` + `date-fns` localizer. Day / Week / Month / Agenda views built-in, plus a Custom-range preset row (7d / 30d / 90d / This quarter) with from/to date inputs and a live "N jobs in range" pill. Filter toolbar ported from the old JobsList: text search, technician, service type, status.
  - Empty-slot click → `/jobs/new?date=YYYY-MM-DD&time=HH:mm`.
  - Event click → `/jobs/:id`.
  - "New job" button gated by `<Gate perm="Jobs" action="write">` (Phase 29C).
  - Color-coded by status (`scheduled/active/completed/pending/requested/reopened/cancelled/on_hold`) — legend shown below the calendar.
- **Deleted** `pages/jobs/JobsList.jsx`. `JobNew` and `JobDetail` kept (calendar navigates into them).
- **Router (`App.js`)** — `/jobs` now `<Navigate to="/schedule" replace />`, `/schedule/today` redirects to `/schedule`, `/schedule` renders `CalendarSchedule`. Legacy timeline preserved at `/schedule/legacy-timeline` for one-cycle rollback safety.
- **Nav** — `adminNav.js` Jobs entry replaced with `{ to:"/schedule", label:"Schedule", feature:"jobs" }`; keyboard shortcut `j` now targets `/schedule`. `AppLayout.jsx` tech `TECH_NAV` Schedule entry retargeted to `/schedule`. `RoleAwareIndex` tech redirect now points at `/schedule`. Mobile-parity tile in `pages/tech/ToolsHub.jsx` retargeted.
- Library added: `react-big-calendar@^1.20.0` via yarn.

#### Mobile (`/app/mobile/`)
- **New** `app/(app)/schedule/calendar.tsx` — `react-native-calendars` with 4 view modes: Month (grid + multi-dot markers per status), Week (7-day agenda list from focused date), Day (single-day list), Custom (7d/30d/90d preset chips + free-form range). Tap a marked day → jump to Day view. Tap event card → `/job/[id]`. Admin gets a "+" icon in the header that opens `/job/new?date=YYYY-MM-DD`.
- **Deleted** `app/(app)/schedule.tsx` (old SectionList schedule).
- **`app/(app)/jobs.tsx`** — kept for the customer flow, but now redirects admin/technician to `/(app)/schedule/calendar` at the top of the component. Customer branch untouched.
- **`app/(app)/_layout.tsx`** — added `<Tabs.Screen name="schedule/calendar">` visible to admin AND tech. `today` and `jobs` screens set to `href: null` (still reachable via router.push for legacy links, hidden from the tab bar).
- **`app/(app)/tools.tsx`** — both tech and admin Tools Hub tiles now point at `/(app)/schedule/calendar`.
- Library added: `react-native-calendars@1.1314.0` via yarn.

#### Backend
- `routers/jobs.py` `GET /api/jobs` gained two optional query params: `start` and `end` (inclusive YYYY-MM-DD bounds on `scheduled_date`). Zero behaviour change when both are omitted — matches pre-Phase-30 responses. `Dict` added to the `typing` import. No schema change.

#### Permissions (Phase 29C compliance)
- Sidebar entry uses `feature: "jobs"` — same key the old Jobs list had, so gating and preview-mode behaviour is identical.
- "New job" button on the calendar wrapped in `<Gate perm="Jobs" action="write">`; techs in preview mode see the calendar but not the create button.
- Server-side RBAC on `/api/jobs` unchanged.

#### Tests
- **New** `backend/tests/test_phase30_schedule.py` — 2 tests: narrow-window range filter returns a strict subset with every `scheduled_date` inside the window; open-ended `start=2099` returns ≤ full-set and `end=1990` returns `[]`. Skipped gracefully if the tenant has no dated jobs.
- Broader regression: `test_phase30_schedule` + `test_phase29c_rbac` + `test_phase29b_check_crypto` + `test_phase26_wave_a` + `test_phase28_warranties` = **37/37 passed** in 14 s.

#### Live browser smoke (Playwright, admin@aquaterra.com)
- `/schedule` renders `data-testid="calendar-schedule"` with title "Schedule", filter toolbar, preset row.
- Month / Week / Day / Agenda RBC toolbar buttons all switch views cleanly.
- `calendar-preset-7d` → "2 jobs in range" pill appears.
- Legacy `/jobs` → 302 redirect to `/schedule` ✓
- Legacy `/schedule/today` → 302 redirect to `/schedule` ✓
- Customer portal (`customer@aquaterra.com`) untouched: `/portal/home` renders Home / Services / Book / Request / Invoices / Estimates / Payments / Photos / Documents / Messages / Chat Threads / Profile / Terms exactly as before.
- Web webpack: **compiled with warnings** (pre-existing esbuild-loader deprecation only; no new errors).
- Metro/Expo bundler log: **clean** — no new SyntaxErrors after the delete + add.
- Known noise: 18 `"Encountered two children with the same key"` warnings from `react-big-calendar` when multiple events share a start slot. Not fatal, not blocking; standard library warning. Filed as a follow-up polish item.

#### Files touched
**New**
- `frontend/src/pages/schedule/CalendarSchedule.jsx`
- `mobile/app/(app)/schedule/calendar.tsx`
- `backend/tests/test_phase30_schedule.py`

**Edited**
- `backend/routers/jobs.py` — `start`/`end` query params + `Dict` import.
- `frontend/src/App.js` — replace `JobsList` import + route with calendar + legacy redirect; retarget tech default landing.
- `frontend/src/nav/adminNav.js` — Jobs entry → Schedule entry; keyboard shortcut `j`.
- `frontend/src/layouts/AppLayout.jsx` — TECH_NAV Schedule entry retargeted.
- `frontend/src/pages/tech/ToolsHub.jsx` — Schedule tile retargeted.
- `frontend/package.json` — `react-big-calendar` added.
- `mobile/app/(app)/_layout.tsx` — new `schedule/calendar` tab; `today` + `jobs` hidden.
- `mobile/app/(app)/jobs.tsx` — admin/tech redirect to calendar; customer flow byte-for-byte identical.
- `mobile/app/(app)/tools.tsx` — Schedule tiles retargeted.
- `mobile/package.json` — `react-native-calendars` added.
- `memory/HANDOFF.md` — this section.

**Deleted**
- `frontend/src/pages/jobs/JobsList.jsx`
- `mobile/app/(app)/schedule.tsx`

#### Out of scope (deferred)
- Drag-and-drop reschedule from calendar.
- Recurring-job scheduling engine.
- Job-detail drawer / modal (still uses the standalone `/jobs/:id` page).
- Silencing the react-big-calendar "duplicate key" warnings — cosmetic, filed for follow-up.

#### Phase 30 · Fix pass — Grid default + toggle + redirects (Feb 15 2026)
Mobile-only follow-up to Phase 30. Web (`/app/frontend/src/pages/schedule/CalendarSchedule.jsx`) untouched.

**T4b redirects (blocker fix)**
- New `mobile/app/(app)/schedule/index.tsx` renders `<Redirect href="/(app)/schedule/calendar" />` so the bare `/schedule` deep-link no longer 404s to "Unmatched Route".
- `mobile/app/(app)/today.tsx` rewritten from the old day-list into a one-liner `<Redirect href="/(app)/schedule/calendar" />` — kills the legacy `/today` unmatched-route case without breaking bookmarks / push-notification links.
- `mobile/app/(app)/_layout.tsx` registers the new `schedule/index` screen with `href: null` so Expo Router picks it up but keeps it off the tab bar.
- Verification: `curl` on `/schedule` and `/today` after login flows redirect cleanly to `/(app)/schedule/calendar`; no `"Unmatched Route"` substring in the DOM at either URL; Metro entry.bundle returns HTTP 200.

**Grid ↔ Calendar toggle (default = Grid)**
- `mobile/app/(app)/schedule/calendar.tsx` fully rewritten. Top-level view is now a binary segmented control `[Calendar] [Grid]` — persisted via `storage.setItem("aq-schedule-mode-v1", …)` (AsyncStorage on native, session-scoped web fallback).
- Removed the old Month/Week/Day/Custom sub-modes — simpler surface per brief.

**Grid view (default)**
- Day header: `<` prev-day, `[Today]` pill (highlighted when focused date == today), `>` next-day, right-aligned full label (`Tuesday, Jul 14, 2026`).
- Bulk-action pill row (Jobs.write gated via `canWriteJobs`):
  - **Complete** → `PUT /api/jobs/{id} {status:"completed"}` per checked row, then `Alert.alert` + list refresh.
  - **Move** → opens inline date input; on confirm, `PUT /api/jobs/{id} {scheduled_date:"YYYY-MM-DD"}` per checked row.
  - **Rearrange** → toggles reorder mode with per-row up/down chevrons; **Save order** hits `POST /api/jobs/reorder {job_ids:[…]}` (admin-only endpoint). Non-admins see the local reorder + a friendly `Alert` explaining the persist requires admin — no phantom endpoint invented.
- Card layout per screenshot 1: circular checkbox (turns brand-color when checked), service-type tag in the tag colour, bold customer name, address, notepad+`BH` row (`actual_hours ?? billable_hours ?? estimated_hours ?? 0`), and a status pill on the right — `completed → "Closed" (green)`, `scheduled/pending → "Open" (amber)`, `active → "In progress" (blue)`, etc. Trailing `→` chevron opens `/job/[id]`.
- Recurring jobs get a `🔁 ` prefix on the service-type tag.

**Calendar view**
- Header: `<` prev-week, Month/Year title (e.g. "July 2026"), `>` next-week, plus a **BH 👁 toggle** pill (default ON — cards show billable hours; when off, hours are hidden).
- Horizontally-scrollable 7-column week (Mon → Sun), each column with a sticky day-of-week + day-of-month header (today highlighted in brand color).
- Events stacked vertically in each column; card background + left border tinted by service type (Weekly Landscaping → green, Monthly Landscaping → indigo, Irrigation → blue, Rock → amber, Pool/Chem → cyan, Cleaning → pink, other → neutral). Recurring jobs prefixed with `🔁 `. Tap → `/job/[id]`.

**Endpoints used (no new ones)**
- `GET /api/jobs?start=…&end=…` — Phase 30 range filter.
- `PUT /api/jobs/{id}` — status + scheduled_date changes.
- `POST /api/jobs/reorder` — bulk route ordering (admin-only).

**Files touched**
- **New**: `mobile/app/(app)/schedule/index.tsx`.
- **Rewritten**: `mobile/app/(app)/today.tsx` (now a redirect), `mobile/app/(app)/schedule/calendar.tsx` (Grid+Calendar rewrite).
- **Edited**: `mobile/app/(app)/_layout.tsx` — registered new `schedule/index` screen.
- **Not touched**: web frontend, backend endpoints/schema, other mobile screens.

**Verification**
- Metro bundle: **entry.bundle=HTTP 200**, no new SyntaxErrors in `mobile.err.log`.
- Backend regression: `test_phase30_schedule` + `test_phase29c_rbac` = **13/13 passed** in 4 s (untouched by this pass).
- Live browser (mobile Expo web preview): `/schedule` and `/today` both resolve without "Unmatched Route".
- Zero console errors on the Expo bundle.

**Deferred (still)**
- True native drag handle for rearrange (would need `react-native-draggable-flatlist`; currently uses up/down chevrons — same outcome, one tap slower).
- Silencing web-only `react-big-calendar` key warnings (web-only, out of this pass's scope).

#### Phase 30W · Web schedule Grid/Calendar toggle (Feb 15 2026)

Web-only mirror of the Phase 30 mobile fix pass. `/app/frontend/src/pages/schedule/CalendarSchedule.jsx` gained a top-level `[Calendar] [Grid]` segmented control. **Grid is the default** on fresh sessions; the choice persists in `sessionStorage["aq-schedule-mode-v1"]` and is also mirrored to the URL `?mode=…` so shareable links open in the right view.

**Grid view (default)** — matches the mobile grid card-for-card, adjusted for desktop density:
- Day-nav header: `<` prev-day, **Today** pill (highlighted when the focused date is today), `>` next-day, right-aligned "Wednesday, Jul 15, 2026" label.
- Bulk-action pill row, all Jobs.write gated via the Phase 29C `<Gate perm="Jobs" action="write">`:
  - **Complete (N)** → `PUT /api/jobs/{id} {status:"completed"}` per checked job, then toast + refresh. Disabled at count 0.
  - **Move these events (N)** → inline `<input type="date">` picker; on confirm, `PUT /api/jobs/{id} {scheduled_date}` per checked row.
  - **Rearrange** → toggles per-row up/down chevrons; **Save order** hits `POST /api/jobs/reorder {job_ids:[…]}`. If the server answers 403/404 (non-admin), the pill is disabled next click and a small "Rearrange not available for this role." hint renders next to it — no phantom endpoint invented.
- Row layout: circular checkbox → service-type tag in the tag colour (Weekly Landscaping = green, Monthly Landscaping = indigo, Irrigation = blue, Rock = amber, Pool/Chem = cyan, Cleaning = pink, other = neutral — same palette as mobile) → customer (bold) → address → notepad icon + `X.XX BH` (falls back through `actual_hours → billable_hours → estimated_hours → 0`) → status pill (`completed → "Closed" (green)`, `active → "In progress" (blue)`, `scheduled/pending → "Open" (amber)`, etc.) → trailing `→` chevron to `/jobs/:id`. Recurring jobs get a `🔁 ` prefix on the service tag.
- Empty state shows a "Nothing on {date}" card with a Jobs.write-gated **New job** button that opens `/jobs/new?date=YYYY-MM-DD`.

**Calendar view (unchanged behaviour)** — same `react-big-calendar` Day / Week / Month / Agenda sub-tabs, custom-range preset row, and status legend as before. Only the wrapper is now conditional on `mode === "calendar"`.

**Filter toolbar** stays visible in BOTH modes and drives a single `filteredJobs` memo — no duplicate state. Calendar mode consumes `events = filteredJobs.map(jobToEvent)`; Grid mode consumes `dayJobs = filteredJobs.filter(d = focused day)` sorted by `route_order` then `scheduled_time`.

**Files modified (1)**
- `frontend/src/pages/schedule/CalendarSchedule.jsx` — added mode state, sessionStorage persistence, service palette + status-pill helpers, new `<GridPanel>` component, wrapped RBC in a conditional, added toast + move-picker inline UI. Icon imports extended (`ChevronLeft`, `ChevronRight`, `CheckCircle2`, `Move`, `ArrowUp`, `ArrowDown`, `FileText`, `Save`).

**Not touched (per hard rule)**
- Mobile app, backend endpoints/schema, customer portal, other web pages.

**Verification**
- Backend regression: `test_phase30_schedule` + `test_phase29c_rbac` + `test_phase29b_check_crypto` = **17/17 passed** in 6 s.
- Webpack: **compiled with warnings** (only the pre-existing esbuild-loader deprecation; no new errors).
- Live browser (Playwright, admin@aquaterra.com):
  - Fresh session → `/schedule` renders `[data-testid="grid-view"]`; `[data-testid="calendar-view"]` absent → Grid is the default ✓
  - Toggle → **Calendar**: `.rbc-toolbar` present, `grid-view` gone ✓
  - **Reload** while in Calendar → still Calendar → sessionStorage persistence works ✓
  - Toggle back → **Grid**, reload → still Grid → persistence both directions ✓
  - Day label reads `Wednesday, Jul 15, 2026`; bulk-action pill row with `Complete (0)` / `Move these events (0)` / `Rearrange` visible; 4 seeded jobs render as cards with correct service-tag colours (`Weekly Pool Service` = green, `Monthly Landscaping` = indigo, `Landscaping` amber, `General` neutral); `🔁` prefix present on the recurring GENERAL job.

**Screenshots** (attached in the browser proof for this pass)
- `/tmp/schedule_grid_web.png` — Grid mode with 4 seeded jobs.
- `/tmp/schedule_calendar_web.png` — Calendar mode after toggle, RBC Week view rendering the same jobs.

**Known noise (unchanged from Phase 30)**
- 13 `react-big-calendar` "duplicate key" console warnings when multiple events share a slot. Pre-existing; cosmetic; scoped for a future silencing pass.

#### Phase 30X · Remove time-of-day from Schedule surface (Feb 15 2026)

The Schedule surface is now **date-only** on web AND mobile. Landscaping / pool service is booked per-day; the UI no longer implies hourly slotting. Backend schema (`scheduled_date`, `scheduled_time`, `duration_minutes`) is unchanged — Job Detail can still show / edit time-of-day internally, but the Schedule listing no longer surfaces it.

**Web (`frontend/src/pages/schedule/CalendarSchedule.jsx`)**
- `jobToEvent()` now emits `allDay: true`, `start = 00:00:00`, `end = 23:59:59.999`. No more `job.scheduled_time` reads, no `setHours`, no `duration_minutes`.
- Default `view` state flipped `"week"` → `"month"`.
- RBC `views` prop trimmed from `["day","week","month","agenda"]` to `["month","agenda"]` — Day & Week buttons no longer render in the toolbar.
- Added `formats={{ timeGutterFormat, eventTimeRangeFormat, agendaTimeFormat, agendaTimeRangeFormat: () => "" }}` — belt-and-suspenders blanking of any time labels the built-in formatter might still emit.
- `onSelectSlot` no longer appends `&time=…` to the create URL — just `?date=YYYY-MM-DD`.
- Grid-panel row: removed the `{j.scheduled_time ? … }` fragment on the meta row; only the `FileText` icon + BH value remain.
- Grid sort: dropped the `scheduled_time` tiebreaker, sorts by `route_order` alone.
- Cleaned up a stray leftover-code block at EOF that had been silently living below the module close.

**Mobile (`mobile/app/(app)/schedule/calendar.tsx`)**
- Grid `JobRow` meta row no longer renders the `time-outline` icon + `job.scheduled_time`; only notepad + billable-hours remain.
- Calendar-view multi-day column sort dropped the time comparator — order matches the API response (stable, per-day).
- Grid sort likewise sheds the `scheduled_time` tiebreaker.
- `scheduled_time` field intact on the `Job` type so the file still typechecks against the shared shape.

**Files touched**
- `frontend/src/pages/schedule/CalendarSchedule.jsx`
- `mobile/app/(app)/schedule/calendar.tsx`

**Untouched (per hard rules)**
- Backend endpoints, job schema, job-detail page (`/jobs/:id`), customer portal, mobile customer flow.

**Verification**
- Backend regression: `test_phase30_schedule` + `test_phase29c_rbac` = **13/13 passed** in 4.6 s.
- Webpack: **compiled with 1 warning** (pre-existing esbuild deprecation only).
- Metro/Expo: clean, no new SyntaxErrors.
- Live browser (Playwright, admin@aquaterra.com):
  - `?mode=calendar` → RBC toolbar text is exactly `"Today Back Next July 2026 Month Agenda"` — **Day** and **Week** buttons gone; Month is the active view; `.rbc-month-view` rendered; `.rbc-time-gutter` absent; **8 events** rendered as full-day coloured bars; first event text contains no `HH:mm` pattern.
  - `?mode=grid` → 4 seeded job cards render with `0.00 BH` on the meta row and **zero** matches for `\b\d{1,2}:\d{2}\b` across all cards.
- Phase 29C RBAC gates and Phase 30W Grid/Calendar toggle both intact (verified by re-clicking the toggle mid-test).

**Deferred (unchanged)**
- The 13 `react-big-calendar` "duplicate key" console warnings still trigger when multiple events share a day. Cosmetic; scoped for a future silencing pass.
