# AquaTerra Pool & Landscaping — CRM PRD

Field-service CRM covering admin, technician (Expo mobile), and customer-portal (React web) surfaces. FastAPI backend on port 8001, React CRA frontend on port 3000, MongoDB via `MONGO_URL`.

## Personas
- **Admin / Office** — schedules crews, sends quotes/invoices, runs the business
- **Technician** — mobile app + limited web (clock-in gated)
- **Customer** — portal for services, invoices, estimates, payments

## Core requirements (static)
- Auth (JWT, admin/tech/customer roles) + impersonation
- Customers, Jobs (with VIP tags, waitlist, work-order PDFs)
- Quotes / Estimates / Invoices (with Master Invoices + Stripe)
- Customer portal (approve estimates, pay invoices)
- Ops hub (dispatch, schedule, routes, crews, timesheets, equipment)
- **Finance + Reports** (this phase)
- Marketing, SEO, GBP (future)

## Implemented (2026-07)
- **Phase 0** — backend/mobile drop-in + web scaffold
- **Phase 1** — auth, admin dashboard, tech clock-in gate
- **Phase 2** — customers + jobs (VIP, waitlist, chemistry, PDFs)
- **Phase 3** — quotes/invoices/master invoices + Stripe
- **Phase 4** — customer portal (impersonation, invites, all surfaces)
- **Phase 5** — Ops hub (dispatch/schedule/routes/crews/timesheets/equipment)
- **Phase 6 — Finance + Reports (2026-07)**
  - Backend: 11 new endpoints — `/reports/{forecast,forecast-cards,revenue-by-city,revenue-by-crew,revenue-by-customer,gross-sales,invoiced-items}`, `/payments/list`, `/billing-plans/run` (run-all-due), `/export/jobs`, `/export/invoices`. OpenAPI now at 211 paths.
  - Frontend: `/reports` hub, `/reports/business-summary`, `/reports/forecast`, 5 revenue-slice pages, `/income-by-category`, `/income-categories`, `/payments`, `/auto-billing`, `/impexp`.
  - Shared `DateRangePicker.jsx` with URL-query sync (start/end/preset).
  - Sidebar Reports + Finance groups (collapsible).
  - `AdminOnly` route guard prevents technician deep-links to Phase-6 routes.
- **Automatic Late Fees (2026-07)**
  - Backend: `run_late_fee_assessment` (daily @ 02:00 UTC via APScheduler cron) + admin endpoints `GET/PUT /api/settings/late-fees` and `POST /api/finances/late-fees/run`. Idempotent via `is_late_fee: true` line-item marker. Recomputes subtotal/tax/total/remaining_balance and logs to `activity_logs`. Master invoices unchanged — child invoices each carry their own fee.
  - Frontend: `/settings/late-fees` form (Enable, Amount, Grace days, Run now). Invoice detail line-items table highlights late-fee rows with a red "LATE FEE" chip + amber row background. Invoices list gains a "Has late fee" filter chip. OpenAPI now at 213 paths.
- **Terms & Conditions field (2026-07)**
  - Backend: `terms: Optional[str]` added to `QuoteIn`/`EstimateIn`. Auto-fills from `/api/settings/terms` defaults on create if not provided. New `PUT /api/quotes/{qid}` for partial doc updates. New `GET /api/quotes/{qid}/pdf` renderer includes terms. Work-order PDF pulls terms from linked quote/invoice. OpenAPI 216 paths.
  - Frontend: `/settings/terms` (default quote + invoice terms editor with Save/Reset). New-quote/invoice/estimator forms auto-fill terms with a "Reset to default" link. Detail pages show Terms section with inline edit modal. Portal invoice + estimate details show terms too.
- **Legal Documents CMS + Portal ToS (2026-07)**
  - Backend: `db.legal_documents` collection seeded on startup with the verbatim Pool Maintenance Terms of Service scraped from `poolandlandscapingofvistancia.com`. Endpoints: `GET /api/legal/{slug}` (public), `GET /api/legal` + `PUT /api/legal/{slug}` (admin, bumps version), `POST /api/portal/terms/acknowledge` + `GET /api/portal/terms/status` (customer). Acks stored on `customer.tos_acknowledgements`. OpenAPI 220 paths.
  - Frontend: `/portal/terms` renders markdown via `react-markdown` with print styles + "I have read and agree" flow; portal-home yellow nudge banner appears until ack. Admin `/settings/legal` list + `/settings/legal/{slug}` two-panel markdown editor with live preview.
- **Phase 7 — AI Marketing Studio + Sequence Automations (2026-07)**
  - Backend: 2 new routers — `marketing_studio.py` (21 endpoints) and `sequences.py` (7 endpoints), plus 5 public/embed endpoints. **OpenAPI now at 252 paths.**
  - All AI paths **degrade gracefully** with `{stubbed: true, ...}` responses when `EMERGENT_LLM_KEY` is absent — full UI stays wired end-to-end.
  - Endpoints: brand memory · campaigns CRUD + generate + agent-chat · post variants (platform-tuned char limits) · visuals (picsum placeholder) · queue approve/reject/bulk-approve/publish · scheduling slots · performance · review-reply drafts · agents list · campaign/email/SMS template libraries · sequences CRUD + enroll/pause/resume/unenroll/enrollments · public /checkins /company-card /portal-widget.js /ai-chat-widget.js
  - Two new APScheduler jobs — `marketing_autopost` (every 10 min) + `sequences_tick` (every 15 min). Startup log confirms `SEO + chem + late-fee + marketing_autopost + sequences_tick schedulers registered`.
  - **Seeds (idempotent) on startup**: 6 campaign templates, 5 email templates, 3 SMS templates, 3 sequences (Welcome / Review Request / **Overdue Invoice Sequence** fulfilling the aging-nudge deferral).
  - Frontend: `MarketingPages.jsx` + `SequencePages.jsx` — 13 pages consolidated (Hub, Brand, Campaigns list/new/detail, Posts, Approval Queue, Calendar, Scheduling, Performance, Templates, Reviews, Sequences list/new/detail). Admin sidebar Marketing group with 11 children. All routes AdminOnly-guarded.
  - Publish endpoint enforces approval at API level — 400 if item not approved.
- **Phase 8 — SEO Studio + WordPress + GBP + Overdue Auto-Enrollment (2026-07)**
  - **Overdue Invoice Sequence auto-enrollment**: extended `run_late_fee_assessment` to also enroll customers with 30+ day past-due invoices into the seeded sequence — piggybacks on the existing daily 02:00 UTC cron (no new scheduler). Idempotent (skips active enrollments), re-enrolls unenrolled customers. Logs `type: "sequence-auto-enrolled"` to activity_logs. Also added `POST /api/sequences/auto-enroll/overdue-run` for manual/testing runs.
  - Backend SEO: added `PATCH /api/seo/articles/{aid}` for editor updates + `_ai_json` stub-fallback so keyword suggest / article generate / audit all degrade gracefully to placeholder skeletons keyed by request.
  - Backend GBP: added `GET /api/gbp/status` (connection-state probe), `GET /api/gbp/oauth/auth-url` (returns 424 with friendly message when unconfigured), `POST /api/gbp/oauth/callback` alias. Existing GBP endpoints untouched.
  - **OpenAPI now at 256 paths.**
  - Frontend: `SeoPages.jsx` — 7 pages (Hub, Articles list, Article editor with markdown + live preview, Keyword Suggest, SEO Audit, Rank Grid, WordPress settings) plus GBP Hub. Admin sidebar Marketing group extended with SEO + GBP children.
  - Article editor supports save, schedule, meta description, markdown editing + preview.
  - WordPress settings: connection form + test connection + weekly auto-drip toggle.
  - GBP not-connected state renders CTA card and Connect button surfaces the friendly 424 message.

## Prioritized backlog
- **DONE · Phase 7** — AI Marketing Studio
- **DONE · Phase 8** — SEO Studio + WordPress + GBP
- **DONE · Phase 9** — AI Employees + AI Chat + Tasks + Escalation + RingCentral + Access
- **DONE · Phase 10** — D2D Sales (Zillow · knocks · leaderboard · Leaflet + Google Maps toggle)
- **DONE · Phase 11** — Landscape AI · CAD Studio · Satellite Measure · Virtual Bid · Digital Card (+ public route) · Weather
- **DONE · Phase 12** — Polish: cleanup, .env.example × 3, robots+sitemap, branded 404, integrations hub with health-checks (10 integrations), landscape description + shopping list, CAD mobile guard
- **P1 · Phase 13** — Full E2E parity testing

## Phase 12 acceptance (2026-07-13)
- 283 OpenAPI paths (added `/settings/integrations/health/{integration}`).
- Removed dead `_staff(user)` helpers + unused `get_current_user` imports from render.py, property.py, cad.py, measurements.py.
- Landscape render endpoint now returns `description` (2-3 sentence LLM rationale) + `shopping_list` (6-10 items with category + estimated_cost) — non-blocking, best-effort.
- Frontend renders description + interactive shopping-list checkboxes below the render image.
- `/settings/integrations` now lists 10 integrations with LIVE/CONFIGURED/NOT-CONFIGURED chips + per-integration health-check buttons that hit real APIs (Google Geocoding OK, Resend HTTP 200, Stripe HTTP 200, Emergent-LLM key-present). Non-configured slots show clear "Set env var in /app/backend/.env" guidance.
- Branded 404 (and 500) pages at `/app/frontend/src/pages/NotFound.jsx` with AquaTerra branding + Return home CTA.
- CAD editor guards against <768px viewport with a friendly "please use tablet/desktop" placeholder.
- `.env.example` created for backend + frontend + mobile.
- `robots.txt` + `sitemap.xml` served from `/app/frontend/public`.

## Punted from Phase 12 (with reasons)
- **Full permissions-matrix per-page enforcement UI** — backend matrix already persists via Phase 9; end-to-end frontend enforcement would touch nearly every page and blow the context budget. Recommend a follow-up phase focused solely on it.
- **"Test as..." role-preview dropdown** — depends on the above; punted together.
- **Impersonation "first-time modal"** — banner already shipped; modal is polish, deferred.
- **Currency + date + timestamp audit across every file** — spot-checks show consistent Intl.NumberFormat usage in reports/finance pages; a full sweep is deferred.
- **Loading skeleton + empty-state audit across every page** — most already have friendly empties; comprehensive audit deferred.
- **Ops Hub / Dispatch / Schedule / Reports responsive pass** — desktop-first is intentional; CAD guarded, other pages remain usable via horizontal scroll on mobile.
- **`POST /api/settings/integrations/{key}` to edit envs from the UI + restart backend** — writing to `.env` from a running process + `supervisorctl restart` from inside FastAPI is fragile in this environment. Left as manual `.env` edits + supervisor restart.

## Phase 11 acceptance (2026-07-13)
- 282 OpenAPI paths (up from 274). New: `/virtual-bid/generate`, `/virtual-bid`, `/weather/risk`, `/weather/reschedule-recommendations`, `/cards`, `/cards/{slug}`, `/public/cards/{slug}`, `/public/cards/{slug}/vcard`.
- Landscape AI wired to `POST /api/landscape/render` (Gemini image gen via emergentintegrations). Yard photo → styled photoreal redesign.
- CAD Studio: list + editor with click-to-place elements (rect, circle, palm, cactus, spa, fire pit, text), persistent JSON serialization via `/api/designs/{id}`.
- Satellite Measure: Esri satellite tiles + Leaflet click-to-polygon with live shoelace area calculation in sq ft. Save creates `/api/measurements` doc.
- Virtual Bid: Zillow lookup via `/property/lookup` → LLM-generated bid narrative + tiered pricing (14k/16k/22k gal buckets). Verified with 10840 W Saddlehorn Rd → 22k gal / $179/mo / $485 cleanup with real Claude narrative.
- Digital Card: admin CRUD + public route at `/public/card/{slug}` (no auth) + `.vcf` download (VCARD 3.0).
- Weather: 7-day risk grid (precip/wind/UV → good/fair/poor score), reschedule recommendations query real jobs on poor days, WeatherWidget on admin dashboard.
- **Tech-role guard verified**: mike@aquaterra.com direct-URL attempts on `/landscape`, `/cad`, `/measure`, `/virtual-bid`, `/card`, `/weather`, `/d2d` all redirect to `/`. AI & Tools + D2D Sales groups absent from tech sidebar.

## Phase 10 acceptance (2026-07-13)
- 274 OpenAPI paths. New: `/api/d2d/*` (already wired), `/api/settings/maps`, `/api/settings/integrations`, `/api/public/map-settings`, `/api/admin/geocode-addresses`.
- D2D module: dashboard, canvassing map (Leaflet), knocks list, open leads, sold-leads (Zillow live), team report + CSV, gamified leaderboard.
- Retroactive Leaflet: `/dispatch/map` (today's jobs by status + tech pins) and `/schedule/map` (per-tech route polylines).
- `MapView` component swaps between Leaflet ↔ Google Maps based on `settings.map_provider`; `/settings/maps` UI toggle.
- `/settings/integrations` shows masked previews of all 7 integrations (LLM/Google/OpenWeb Ninja/Resend/Stripe/Twilio/RingCentral).
- `AddressAutocomplete` component (Google Places, lazy-loaded on first focus) wired into `/customers/new` + `/customers/:id/edit`.
- Geocode backfill: 13 seed customers geocoded on first run (`processed=13, updated=13, errors=0`).
- Fix A (sequences fast-forward): 61-day-old invoices now enroll at the escalation step; verified 3 tasks created on next tick.
- Fix B (RingCentral): webhook parses BOTH legacy `{from:{phoneNumber}}` and nested `{call:{from:"..."}}` shapes.

## Now-live integrations
- Stripe (test key), Emergent LLM, OpenWeb Ninja (Zillow), Resend (test sender), Google (Places + Geocoding + Maps tiles).

## Not-configured integrations
- Twilio (SMS), Google Business Profile OAuth (Client Secret pending), WordPress publish, Stripe webhook signing secret, RingCentral outbound API.

## Known gaps / non-blockers
- Resend account is in test mode: emails only deliver to `brianbeckmanaz@gmail.com` until a verified sender domain is added.
- Google API key is unrestricted — recommend restricting to app domains + specific APIs in Google Cloud Console.
- Address autocomplete not yet wired into `/jobs/new` (jobs inherit customer coords), `/portal/request-service`, or quote/invoice billing addresses — deferrable to Phase 12 polish.
- Route optimization still uses greedy TSP (AI upgrade planned).

## Phase 46 — Phase 45 completion follow-up (2026-07-16)

### Shipped
- **46.1 Not-tested toggle + defaults**: Mobile `ReadingChipRow` gained an explicit "Not tested / —" pill (dims chip strip when null). Backend `ServiceReportPatch` accepts optional `not_tested_flags: Dict[str, bool]`; new reports bootstrap with `not_tested_flags: {}`. Defaults (Free Cl 3, Total Cl 3, pH 7.6, Alk 100, CYA 70) are auto-applied when toggling back on. Dosing (`services/pool_dosing._normalize`) and algae-risk (`reports._chlorine_ppm`) already skip null values.
- **46.2 Workstream card**: Added `WorkstreamPillRow` (Water Test / Chemicals / Checklist / Private Note / Public Note / Repair / Shopping / Time / Location) — green when backing job data exists, gray otherwise. Added `job-card-view-details-{id}` primary CTA button below the pill row. Full photo-panel + thumb strip redesign deferred; existing card content preserved to avoid breaking other consumers.
- **46.3 Time Clock UIs**: New landscaping-only screens at `/landscape/time-clock` (web) and `mobile/app/landscape-time-clock.tsx`. Wire `POST /api/timeclock/punch`, `GET /api/timeclock/mine-today`, `GET /api/timeclock/mine-summary` (renamed from `/today`+`/summary` to avoid collision with existing `ops.timeclock_today` admin overview). Web uses `navigator.geolocation`, mobile uses `expo-location`. Non-landscaping users see a friendly "landscaping crew only" card (backend still returns 403 `not_landscaping`).
- **46.4 Pool Service Report**: New `/admin/reports/pool-service` web page — week picker, sortable table (Tech / Serviced / Skipped / Total), totals summary, and client-side CSV export. Reuses existing `GET /api/reports/pool-service?date_from&date_to` from `routers/jobs.py`. Added to admin Reports nav.
- **46.5 Web chemicals parity**: New `ChemicalPickerModal.jsx` mirrors the mobile `ChemicalPickerSheet` (same shared CHEMICALS_CATALOG, same commit semantics). Wired into `PoolChecklistForm.jsx` via a dashed "Quick add chemical" button below the existing `ChemicalDropdownStack`.
- **46.6 Playwright menu-404 audit**: `check_menu_404s.py` now walks nav links parsed from `adminNav.js` + `roleNav.js` via a real Chromium via Playwright, writes `/app/memory/menu_audit_report.json`. Auto-falls back to HTTP-only mode when `playwright` isn't installed. `pip install playwright && playwright install chromium` installed.
- **Landscaping user seeded**: `landscaper@aquaterra.com` / `password123`, `department: "landscaping"`, tenant aquaterra. Seed is idempotent (runs every startup, only inserts if missing, corrects the department + tenant on existing rows). Credentials logged in `/app/memory/test_credentials.md`.
- **api.js**: Now unwraps FastAPI dict-shape details (`{code, msg}`) so 403 responses surface real error messages to the UI (used by the landscaping guard).

### Verified
- `bash /app/scripts/preflight.sh` → exit 0.
- Metro bundle 200 (`/node_modules/expo-router/entry.bundle?platform=web&…`).
- Backend endpoints tested via curl: login as landscaper OK, `POST /api/timeclock/punch` in+out OK, `/mine-today` + `/mine-summary` return live shifts, admin `/reports/pool-service` returns 3 rows for the current week (Mike 4, Unknown 2, Sara 0/1).
- Playwright smoke: admin login → `/admin/reports/pool-service` renders `pool-service-report` container with `6 serviced · 1 skipped` totals and 3 rows; admin visiting `/landscape/time-clock` shows `landscape-time-clock-blocked`.

### Deferred / Follow-ups
- **46.2 photo panel**: The large primary photo + horizontal thumb strip variant from the reference screenshot was not implemented — the existing job card structure retained with the pill row + VIEW DETAILS button added. Full photo layout can land in a follow-up phase.
- **46.6 stale HTTP fallback rows**: When Playwright is available the walker succeeds; when only requests is available the report shows link inventory but not per-link 404 status (SPA HTML is always 200). Consider adding a preflight step that fails when any `spa-404` row appears.

## Phase 47 — Budgeting Suite + 46.2 closeout (2026-07-16)

### 46.2 closeout — Workstream card LEFT/RIGHT layout
- `mobile/src/components/widgets.tsx` — split into `WorkstreamPillColumn` (LEFT ~40%: 9 vertical pills with `job-card-pill-{name}-{id}` testIDs) + `WorkstreamPhoto` (RIGHT ~60%: primary photo at 200px height with full-width blue "VIEW DETAILS" overlay, `job-card-photo-{id}` + `job-card-view-details-{id}`) + `WorkstreamThumbStrip` (up to 6 additional thumbs below, `job-card-thumb-{i}-{id}`). Placeholder gradient when no primary photo. Old horizontal `pillWrap` + `WorkstreamPillRow` component removed.
- `backend/routers/jobs.py` — `list_jobs` now augments every job with `has_water_readings`, `has_chemicals_added`, `has_checklist`, `has_private_note`, `has_public_note`, `has_repair_request`, `has_shopping_request` derived from the latest per-job service report. Wraps in try/except so failures degrade gracefully (pills render gray). Mobile pill column prefers these authoritative flags with legacy field fallbacks.

### 47.1 — Budget Setup + backend
- NEW `backend/routers/budgets.py` — `GET/PUT /budgets/{year}`, `POST /budgets/{year}/copy-from/{prev}?scale`, `GET /budgets/current/markup`, `GET /budgets/current/dashboard`, `GET /budgets/{year}/dashboard`, `GET /budgets/health-summary`. Monthly targets normalized to 12 months, integer-cent storage, `computed.*` recalculated on every write. Literal-path routes declared BEFORE `/budgets/{year}` (comment in file explains the FastAPI ordering trap).
- NEW `frontend/src/pages/budget/BudgetSetup.jsx` — 12-row × 8-column editable table (revenue + 6 expense buckets + target profit %), sidebar summary with computed billable hourly + markup %, copy-from-prior-year with scale factor, labor burden input.
- Nav entries added (Budget Setup / Dashboard / Wizard) in `nav/adminNav.js` under Reports.

### 47.2 — Estimator integration
- `backend/routers/estimator.py::create_estimate` — stamps every NEW draft estimate with `budget_markup_pct`, `budget_markup_source` (`budget`/`default`), `budget_markup_applied_at`. Also sets `markup_pct` to the budget value so the estimator math immediately reflects the target. Falls back to 40% default when no budget doc exists (via `budgets.get_current_markup`).
- `backend/routers/budgets._recalc_open_estimates` — on budget save cascades the new markup onto ALL `draft`/`sent` estimates across BOTH `estimator_estimates` and `estimates` collections. Accepted/closed estimates immutable.

### 47.3 — Job Costing view
- NEW `GET /jobs/{id}/costing` — labels baseline (from attached estimate or `job.price`) vs actuals (labor from `time_entries`, materials from service-report `chemicals_added` × `chemical_costs`, equipment from `inventory_reservations`) and returns per-bucket `progress.*_pct` + estimated + actual net profit.
- NEW `frontend/src/pages/budget/JobCostingPanel.jsx` — coloured progress bars (green < 80%, yellow 80–100%, red > 100%), profit tiles at the bottom. Embedded inside `JobDetail.jsx` above Photos, admin/super_admin only.

### 47.4 — Revenue Target dashboard
- NEW `frontend/src/pages/budget/BudgetDashboard.jsx` — 4 stat cards (This Month / YTD / YTD Net Margin / Pace) + monthly Actual-vs-Target bar chart using recharts. Renders `no_budget_for_year` banner when the budget is missing with an inline link to Setup. Consumes `/budgets/{year}/dashboard`.

### 47.5 — Know Your Numbers wizard
- NEW `frontend/src/pages/budget/BudgetWizard.jsx` — 4-step wizard (Net Profit → Op-Ex → Preview → Apply). Live math preview client-side, authoritative math on `POST /budgets/{year}/wizard/apply` which stores `wizard_inputs.computed.*` for audit.
- Backend `apply_wizard` — supports either dollar or percent input, optional seasonal weighting (summer bump). Applies an even-split across 12 months with per-category apportionment.

### 47.6 — AI CFO tie-in
- `backend/routers/budgets.build_budget_context` — compact blob (`annual_target/actual, ytd_target/actual, pace, ytd_net_profit_pct, current_month, computed.markup_pct/billable_hourly/break_even, expense_targets_ytd`) merged into every CFO Q&A context via `_build_financial_context`.
- `frontend/src/components/cfo/QnAPanel.jsx` — 3 suggested-prompt chips (`cfo-qna-chip-on`, `-which`, `-what`): "On track for annual revenue?" · "Which category is over budget this month?" · "What markup should I use?".
- LLM path unchanged — reuses the Emergent LLM key via `_call_llm_text`.

### Mobile — Budget Health card
- NEW `mobile/src/components/BudgetHealthCard.tsx` — read-only admin widget. Consumes `/budgets/health-summary`, shows this-month + YTD actual vs target and a coloured pace pill (green/yellow/red). Silent when the role is not admin/super_admin. Mounted at the top of `mobile/app/(app)/index.tsx`.

### Small UI tweak (user request during Phase 47)
- `frontend/src/layouts/AppLayout.jsx` — Universal top-right hamburger (`web-menu-trigger`) now hidden when `role === "admin"` (they already have the admin sidebar + AdminTopBar). Still rendered for super_admin, technician, customer.

### Verified
- `bash /app/scripts/preflight.sh` → exit 0.
- Metro bundle `/node_modules/expo-router/entry.bundle?...` → HTTP 200.
- Budget flow (curl):
  - `PUT /budgets/2026` writes with `computed.markup_pct: 100.0` (huge revenue vs cost test data).
  - `POST /budgets/2026/wizard/apply` (opex=$400k, margin=15%, seasonal=true) writes and echoes `computed`.
  - `GET /budgets/current/dashboard`, `/budgets/current/markup`, `/budgets/health-summary` all return expected shapes.
  - `POST /estimator/estimates` returns `budget_markup_pct: 15.0`, `budget_markup_source: "budget"`.
  - After a subsequent `PUT /budgets/2026`, all draft estimates carry the new `budget_markup_pct: 100.0` (cascade OK).
  - `POST /cfo/qna` returns `context_snapshot.budget.pace: "behind"` (context wired).
- Playwright smoke:
  - `admin@aquaterra.com` → `/admin/budget`, `/admin/budget/dashboard`, `/admin/budget/wizard`, `/jobs/{id}` all render their testIDs + no `not-found-page` marker.
  - `admin@aquaterra.com`: NO `web-menu-trigger` in DOM.
  - `mike@aquaterra.com` (tech), `customer@aquaterra.com`: `web-menu-trigger` IS in DOM.
- Screenshot captured of `/admin/budget/dashboard` showing 4 stat cards + monthly bar chart with January's actual bar.

### NOT built (per user)
- Auto-email Friday Pool Service Report — deferred per user request. HANDOFF note reflected.

## Phase 48 — Manual-entry chemicals everywhere (2026-07-16)

### Files changed
- `mobile/src/components/checklist/ReadingChipRow.tsx` — REWRITTEN. Chip scale removed. Single `TextInput` (`decimal-pad`) per reading + not-tested pill + unit label. Per-key validation (pH 0-14 2dp; chlorine 0-10 2dp; alkalinity 0-500 1dp; CYA 0-300 1dp; salt 0-6000 int). Red border on invalid; blocks save-through until user fixes. Preserves Phase 46.1 defaults as placeholders.
- `frontend/src/components/checklist/PoolChecklistForm.jsx` — REWRITTEN Chemical Readings section into an inline `ReadingInputRow` component (same validation/units/defaults as mobile). Removed the "Quick add chemical" button + ChemicalPickerModal invocation (redundant now that the stack is inline manual entry). CHIP_SCALES/PALETTES/_chipToValue/_isChipSelected/_phSweet are now dead but left in place to keep the diff small (call sites removed).
- `frontend/src/components/checklist/ChemicalDropdownStack.jsx` — REWRITTEN into a plain text-input stack driven by CHEMICALS_CATALOG. `snapRecommendationToPreset` retained as no-op for `add_from_recommendation` callers.
- `mobile/src/components/checklist/ChemicalDropdownStack.tsx` — REWRITTEN into a plain `TextInput` stack driven by CHEMICALS_CATALOG. Same commit/clear semantics as web. `CHEM_TYPES` and `snapRecommendationToPreset` kept as compat exports.
- `frontend/src/components/checklist/ChemicalPickerModal.jsx` — added `CHEMICALS_CATALOG_WEB` alias export so the new inline stack can import the shared list without a mobile→web loop.

### Verified
- `bash /app/scripts/preflight.sh` → exit 0. Metro bundle 200. Web bundle 200.
- Playwright mobile Expo Web (mike, `/job/{id}/checklist`): 10 reading text inputs, 10 not-tested toggles, 9 chemical row inputs, **0 legacy chip testids** in DOM. Screenshot shows PH row with invalid value "75" triggering red border + "Value out of range (0-14, 2dp)" error.
- Playwright web (admin, calendar → event → ChecklistModal): renders PH 7.6 (unit `pH`), Free Cl 3 (`ppm`), Combined Cl empty (`ppm`), Total Alkalinity 100 (`ppm`), Calcium Hardness visible. Each row has NOT TESTED toggle. Screenshot captured.
- Grep for `<Slider` / `<Slider ` / `CHIP_SCALES` reference in checklist components: only remaining occurrence is a dead const in `PoolChecklistForm.jsx` (kept to minimize diff) and a comment in mobile — no rendered chips.

## Phase 49 — Manual-entry parity + landscape widget + tech nav gates (2026-07-16)

### 49.0 — mobile checklist remnant fix
- `mobile/app/job/[id].tsx` — replaced the legacy `<FieldReport>` picker (which mounted the old `ChemicalReadings` modal picker) for `canManage && !isCustomer` with an **OPEN SERVICE REPORT** primary CTA that routes to `/job/[id]/checklist` (the sole surface running the new manual-entry `PoolChecklistForm`). Customer read-only path still renders `FieldReport` (report summary, no picker).
- `mobile/src/components/checklist/PoolChecklistForm.tsx` — added `mergedReadings` that merges the backend `chemical_reading_fields` template with saved `chemical_readings` so all default rows always render, even when the persisted report only carries a subset (e.g. legacy jobs with just PH). `updReading` now writes against `mergedReadings`. Both loops (fields → rows) now iterate `mergedReadings`.
- `frontend/src/components/checklist/PoolChecklistForm.jsx` — added the same `readingFields` prop + `mergedReadings` memo + iteration.
- `frontend/src/components/checklist/ChecklistModal.jsx` — passes `readingFields={report.chemical_reading_fields || []}` into `PoolChecklistForm`.

### 49.1 — default readings ship in "tested" state
- `mobile/src/components/checklist/ReadingChipRow.tsx` — introduced `DEFAULT_TESTED_KEYS` set (Free Cl · Total Cl · PH · Alkalinity · CYA + aliases). Row's `notTested` is now a `manualNotTested` boolean (local state, initial `= !hasValue && !DEFAULT_TESTED_KEYS.has(key)`). Toggle-OFF clears value and lets placeholder show default; Toggle-ON sets `manualNotTested=true` and nulls the value.
- `frontend/src/components/checklist/PoolChecklistForm.jsx::ReadingInputRow` — same logic mirrored for web.

### 49.2 — mobile bottom tab bar hidden
- `mobile/app/(app)/_layout.tsx` — `tabBarStyle: { display: "none" }`. Navigation is via the top-right hamburger.
- `mobile/src/components/tools/sections.ts` — added **Workstream** + **Landscape Time Clock** tiles to `TECH_SECTIONS.daily` so the hamburger covers what the tab bar used to expose.

### 49.3 — landscape clock in/out widget at top of home
- NEW `frontend/src/components/LandscapingClockWidget.jsx` — self-hides for non-landscape users. Big brand/red toggle button, running timer, this-week total, "Full view" link. Mounted at top of `AppLayout.jsx` before `<Outlet />` (visible on every page for landscape users, invisible otherwise).
- NEW `mobile/src/components/LandscapingClockWidget.tsx` — mirror of web. Mounted at top of `mobile/app/(app)/index.tsx` (Dashboard) and `mobile/app/(app)/schedule/calendar.tsx` (landscape tech's actual landing route).
- `backend/utils.py::auth_response` — now emits `department` in the login payload so both widgets can auto-hide client-side without a `/auth/me` roundtrip.

### 49.4 + 49.5 — tech nav no longer sees Customers / Quotes / Invoices
- `frontend/src/nav/roleNav.js::TECH_NAV` — Records section trimmed to D2D Leaderboard + Business Card. Customers + Quotes & Invoices entries removed.
- `frontend/src/App.js` — introduced `NoTech` wrapper that redirects `role === "technician"` to `/`. Wrapped `/customers/*`, `/quotes/*`, `/invoices/*` (incl. Master Invoices) routes. Playwright verified all three routes redirect `mike@aquaterra.com` to `/schedule`.
- Mobile: `TECH_SECTIONS` in `sections.ts` already excludes these entries; no changes needed. Only `ADMIN_SECTIONS` carries them.

### 49.6 — Unusual reading "Recheck?" auto-flag
- `backend/routers/service_reports.py::last_readings` — response now includes `recent_readings: { key: [v1,v2,v3,v4] }` (up to last 4 numeric values per key across the last completed reports).
- `mobile/src/components/checklist/PoolChecklistForm.tsx` + `frontend/src/components/checklist/PoolChecklistForm.jsx` — bootstrap consumes `recent_readings` and forwards to the row.
- `mobile/src/components/checklist/ReadingChipRow.tsx` + `frontend/.../PoolChecklistForm::ReadingInputRow` — compute rolling median of the recent 4 values; when a typed draft is `> 2 × median` OR `< 0.5 × median`, show a yellow "⚠ Recheck? Recent median X · you typed Y" hint (testid `pool-reading-{key}-recheck`). Autosave NOT blocked; hint is warning-only.

### Verified
- `bash /app/scripts/preflight.sh` → exit 0. Metro bundle 200. Web bundle 200.
- `POST /auth/login` for landscaper returns `department: "landscaping"`; for mike returns `null`.
- `GET /service-reports/last-readings?customer_id=…` returns `readings + recent_readings` (ph: [7.4], chlorine: […], alkalinity: […]).
- Playwright — mobile (mike): 10 reading inputs rendered on `/job/{id}/checklist`, "—" for 5 default-tested keys, "Not tested" for the rest. Screenshot shows PH `7.6` with previous 7.4/9h, Free Cl `3` with previous 0.5 ppm/9h, Combined Cl blank + NOT TESTED, Total Alkalinity next.
- Playwright — landscaper on web: `landscape-clock-widget` visible on `/schedule`. Non-landscape mike: widget absent.
- Playwright — landscaper on Expo Web: widget at top of `/schedule/calendar` ("Off the clock · 0h 01m · This week · Full view · Clock In"). No bottom tab bar.
- Playwright — mike hitting `/customers`, `/quotes`, `/invoices` → all redirect to `/schedule` (NoTech guard).
- Grep `<Slider\| Slider ` in checklist components → zero rendered occurrences.

## Phase 55 — Unified Notification Bell + Preferences (2026-07-16, LANDED)

### Backend
- NEW `backend/services/notifications.py` — central `emit(user_ids, kind, title, body, ...)` helper. Honors per-user preferences (bell/email/sms). Email routes through Resend when `RESEND_API_KEY` set, otherwise mocks to `email_delivery_log`. SMS routes through RingCentral when `RC_OUTBOUND_ENABLED=true`, otherwise queues a mocked `sms_messages` row. Realtime WS/SSE + Expo push fan-out best-effort. Body truncated to 500 chars.
- NEW `backend/routers/notifications.py` — dedicated router. Endpoints: `GET /notifications`, `GET /notifications/unread-count`, `GET /notifications/kinds`, `POST /notifications/{id}/read`, `POST /notifications/mark-all-read` (+ legacy `/read-all` alias), `DELETE /notifications/{id}`, `GET /settings/notifications`, `PUT /settings/notifications`. Registered FIRST in `server.py::include_router` so it wins over legacy `/notifications` duplicates in `jobs.py` + `ai_ops.py`.
- 18 KIND_LABELS: rc_sms_inbound/rc_call_inbound/rc_voicemail/rc_fax, job_assigned/completed/cancelled, dispatch_alert, autosave_conflict, invoice_paid/overdue, payment_received/refunded, tech_message/tech_note/customer_message, lead_new, system_alert.
- Emitters wired: `ringcentral.py::_notify_admins` fans out to admins on inbound SMS/call/voicemail/fax (Phase 54 side). `stripe_admin.py::_apply_paid_invoice` fans out to admins on invoice_paid.
- Preference merge: `default_prefs()` returns `bell:true, email:false, sms:false` for every kind; user overrides layered on top.
- Pre-existing bug fixed: `ringcentral.py::_match_customer_by_phone` now matches both scalar `phone` and array `phones` fields on customer docs.

### Web frontend
- NEW `frontend/src/components/NotificationBell.jsx` — Radix DropdownMenu bell. Two variants: `inline` (AdminTopBar right side) + `floating` (fixed top-right for non-admin, next to hamburger). Polls `/notifications/unread-count` every 30s + reacts to realtime `notification` events. Dropdown shows latest 10 rows + "Mark all read" + "See all →".
- NEW `frontend/src/pages/notifications/NotificationsPage.jsx` — full history page with Today/Yesterday/Earlier buckets, filter chips per kind, unread-only toggle, per-row Mark-read + Delete + Open (deep-link) actions, realtime status pill.
- NEW `frontend/src/pages/settings/NotificationPrefs.jsx` — kind × channel toggle grid, all-on / all-off per channel, undo/save controls, channel hints.
- `AdminTopBar.jsx` + `UniversalMenu.jsx` — bell mounted for admin + non-admin roles.
- `adminNav.js` — added Notifications + Notification Prefs entries.
- `App.js` — routes `/notifications` and `/settings/notifications` (any authenticated role).

### Testing
- iteration_9.json — 9/9 backend tests pass, 100%. Zero critical issues.

## Phase 53 — Full Stripe Integration (2026-07-16, LANDED)

### Backend
- NEW `backend/routers/stripe_payments.py` — money endpoints under `/api/stripe/`:
  - `POST /checkout/session` — Hosted Checkout for invoice pay-now. Deterministic idempotency key on (tenant, invoice, total_cents, paid_cents). Statement descriptor "POOL LANDSCPE VISTANCA". Line-item name from invoice title/customer.
  - `GET /checkout/status/{session_id}` — polling fallback that idempotently applies payment if webhook lags.
  - `POST /payment-intent` — Stripe Elements in-app card form. `automatic_payment_methods=enabled`.
  - `POST /refunds` — admin-only. Guards: exists, status=paid, amount ≤ remaining. Syncs invoice `amount_paid` down.
  - `GET /payments` — reconciliation ledger feed with rollup {paid_cents, refunded_cents, net_cents, count}.
  - `GET/POST /products` — thin Stripe Products/Prices wrapper for admin CRUD.
  - `POST /subscriptions` — auto-creates Stripe Customer from our CRM customer if needed. Persists to `db.stripe_subscriptions`.
- EXTENDED `backend/routers/stripe_admin.py::stripe_webhook` — real handlers replacing scaffolds:
  - Idempotency guard via `db.stripe_events` keyed on `event.id`.
  - `checkout.session.completed`, `payment_intent.succeeded`, `payment_intent.payment_failed`, `charge.refunded`, `invoice.paid` (+`invoice.payment_succeeded` alias), `customer.subscription.{created,updated,deleted}` all wired.
  - `_apply_paid_invoice(row, payload)` — idempotent ledger + invoice sync + admin notification (Phase 55).
  - `invoice.paid` on a subscription auto-generates a recurring `db.jobs` row from the customer's recurring_job_template when one exists.
- Ledger schema `db.stripe_payments`: id, tenant_id, customer_id, invoice_id, kind (checkout|payment_intent|subscription), session_id, payment_intent, charge_id, amount_cents, currency, status (initiated|processing|paid|failed|refunded), customer_email, receipt_url, refunded_cents, fee_cents, net_cents, created_at, updated_at, metadata.
- Money-moving contract: when `STRIPE_SECRET_KEY` missing/invalid, endpoints return `{"mocked":true,"reason":"stripe_not_configured"}` 200 OK — frontend renders disabled state without an error banner. Amounts are ALWAYS server-side lookup — never trust a frontend-supplied amount.

### Web frontend
- NEW `frontend/src/lib/stripe.js` — memoized `getStripePromise()` that lazy-loads Stripe.js using key from `/api/stripe/publishable-key`. Never bakes the key into the build.
- NEW `frontend/src/components/stripe/StripePayments.jsx` — `<PayNowButton>` (Hosted Checkout redirect), `<PayInAppForm>` (Elements PaymentElement wrapped in `<Elements>` provider), `<RefundButton>` (admin-only refund modal with amount input), `<StripeCheckoutReturn>` (post-redirect status poller — hits `/stripe/checkout/status/{session_id}` up to 5× at 2s intervals).
- NEW `frontend/src/pages/finance/StripeReconciliation.jsx` — `/admin/finance/stripe-payments`. 4 rollup cards + status filter chips + row table with receipt link + inline refund. Admin-only.
- `QuoteInvoiceDetail.jsx` — Pay with Stripe button added next to Record payment; `<StripeCheckoutReturn>` mounted at top.
- `adminNav.js` — added Stripe Payments entry under Reports.
- Installed `@stripe/react-stripe-js@4.1.0` + `@stripe/stripe-js@9.10.0` via yarn.

### Live-Stripe verification
- Real `cs_...` Checkout Session created (150.00 USD test invoice) — Hosted URL returned.
- Real `pi_...` PaymentIntent created — client_secret returned.
- Ledger correctly records kind=checkout + kind=payment_intent rows at status=initiated.

### Testing
- iteration_10.json — 17/17 backend tests pass, 100%. Zero critical defects. Two functional code-review notes applied: redundant PI.retrieve() call in webhook handler collapsed to single call; float-based idempotency key changed to integer cents.

## Backlog (in queue, in order)
1. **Phase 56** — Customer CSV Import 12-column update (Customer Since / Email / Service address Street / City / State / Postal Code / Phone / Mobile / First Name / Last Name / Tags / Notes). Tolerant date parsing, E.164 phone normalization (reuse Phase 54 helper), soft dedup on (tenant_id, email, mobile), backward-compat with old headers.
2. **Phase 57** — Tech Department Assignment + Department-Gated Experience. PATCH `/api/users/{id}` for department. Split TECH_NAV into TECH_POOL + TECH_LANDSCAPE. New LandscapeChecklistForm (web + mobile). Route guards for `/pool-checklist/*` vs `/landscape-checklist/*`. Landscape clock widget on Profile.
3. **Phase 58** — Global rebrand AquaTerra → Pool & Landscaping. New logo assets (icon + full). Web + mobile header swap. Login page. manifest.json + index.html. Email + PDF templates. Preserve tenant slug "aquaterra" and test-fixture emails.

## Phase 55.1 · Fix Pass + CFO Feature (2026-07-16, LANDED)

### FIX 1 — Stripe RBAC (P0 live-payment abuse vector, tester-reported)
- `routers/stripe_payments.py::_authorize_invoice_pay(user, inv)` — new gate applied to `POST /checkout/session`, `POST /payment-intent`, `GET /checkout/status/{session_id}`. Admin/super_admin → full; customer → own invoices only (`inv.customer_id == user.customer_id`); tech/dispatcher/etc → 403.
- `/checkout/status/{session_id}` additionally requires BOTH sides of `customer_id` non-empty before matching to prevent unrelated callers polling arbitrary sessions.
- `GET /stripe/subscriptions?customer_id=X` gated: admin sees any; customer only their own.
- Refunds + subscriptions create + products CRUD already admin-only via `require_admin`.

### FIX 2 — Notification portal leak (P0)
- `db.notifications` now carries `audience: "internal" | "portal"` (default `"internal"`).
- `_mine_filter` for `role: customer` → `user_id == me AND audience == "portal"`.
- Non-customer branch → `audience: {$in: ["internal", null]}` (legacy rows count as internal).
- All admin-facing emitters (`_notify_admins`, `_apply_paid_invoice`) explicitly pass `audience="internal"`.
- Customer-facing notifications will need explicit `audience="portal"` and portal-safe copy — no auto-forwarding of admin fan-outs to the portal bell.

### FIX 3 — Unmatched inbound comms fan-out
- 4 new kinds added to `KIND_LABELS`: `rc_sms_inbound_unmatched`, `rc_call_inbound_unmatched`, `rc_voicemail_unmatched`, `rc_fax_unmatched` (22 total kinds).
- `ringcentral.py::_default_tenant_id()` — resolves `RC_DEFAULT_TENANT_SLUG` or falls back to `aquaterra` slug + logs a warning when unset.
- All 4 RC handlers (`_handle_sms_event`, `_handle_telephony_event`, `_handle_voicemail_event`, `_handle_fax_event`) now emit the `*_unmatched` variant when customer match fails, routed to the default tenant's admins, with `href=/admin/unmatched-communications` and body truncated to 100 chars.

### FIX 4 — RC webhook token verification
- `POST /api/ringcentral/webhook` now verifies `Verification-Token` (or `X-Verification-Token` / `x-rc-verification-token`) header against `RINGCENTRAL_WEBHOOK_TOKEN` env. Mismatch/missing ⇒ 401.
- `Validation-Token` echo path preserved BEFORE the token check for RC subscription-registration handshake.

### FEATURE — Stripe cash weekly aggregation into CFO digest
- NEW `services/reports.py::stripe_cash_weekly(tenant_id, month)` — buckets `db.stripe_payments` by ISO Monday-start week, filters `status in [paid, refunded]` on `updated_at` within month range, returns `[{week_starting, cash_collected_cents, refunds_cents, net_cents}]`.
- NEW `GET /api/cfo/stripe-cash-weekly?month=YYYY-MM` admin endpoint.
- `POST /api/cfo/price-increase-suggestions` LLM prompt enriched with "Stripe cash collected by week" block so the AI CFO frames price-increase talking points against measurable ROI.
- `PricingInsights.jsx` now renders a "Cash Collected via Stripe" card at the top with 4 week-tiles, net-total, and per-week colored bars.

### Testing
- iteration_11 — 20/20 pass, 1 live-Stripe skip. Zero critical defects remaining.

### Curl RBAC matrix
| # | Actor | Endpoint | Target | Expect | Actual |
|---|-------|----------|--------|--------|--------|
| 1 | admin | POST /stripe/checkout/session | any | 200 | 200 ✅ |
| 2 | tech | POST /stripe/checkout/session | any | 403 | 403 ✅ |
| 3 | tech | POST /stripe/payment-intent | any | 403 | 403 ✅ |
| 4a | customer | POST /stripe/checkout/session | own invoice | 200 | 200 ✅ |
| 4b | customer | POST /stripe/checkout/session | other customer's | 403 | 403 ✅ |
| 5 | tech | POST /stripe/refunds | any | 403 | 403 ✅ |
| 6 | anon | POST /ringcentral/webhook | no token | 401 | 401 ✅ |
| 7 | anon | POST /ringcentral/webhook | wrong token | 401 | 401 ✅ |
| 8 | customer | GET /notifications | leak check | 0 internal | 0 ✅ |

## Phase 56 · Customer CSV Import 12-column rewrite (2026-07-16, LANDED)
- NEW `backend/services/customer_import.py` — 12-column spec (Customer Since, Email, Service address Street, City, State, Postal Code, Phone, Mobile, First Name, Last Name, Tags, Notes). Case-insensitive header match. Tolerant date parser (`Jul 01 2026` / `Jun 23` / `6/23/2026` / `2026-06-23` — year defaults to current). E.164 phone normalization reuses Phase 54 `_normalize_phone_e164`. 2-letter state validated + auto-uppercased. Postal code kept as text (leading zeros preserved). Tags parsed as comma-separated. Legacy CSV shape (Name/Address/Phone) still accepted with `deprecation_warnings`.
- REWRITTEN `POST /api/import/customers` — returns `{total_rows, imported_count, created_count, updated_count, skipped_count, errors:[{row,reason}], deprecation_warnings}`. Soft dedup on (tenant_id, email, mobile) → UPDATE not create.
- NEW `GET /api/import/customers/template` — canonical CSV with 1 sample row (admin only).
- Web UI (`CustomersList.jsx::ImportModal`): 12-column expected-columns table with per-column notes, template download button, post-import result panel with stats cards + per-row error list + deprecation banner.
- Verified against user's real 3-row sample: 3/3 rows imported cleanly, dates + phones + tags all correct.

## Phase 55.2 · CFO JSON parser hardening (folded into Phase 56)
- NEW `services/cfo._parse_pricing_suggestions(text)` — attempts (1) direct `json.loads`, (2) strip ```json``` fence, (3) regex-extract first `{...}` or `[...]` block, (4) return `[]` + error message.
- Endpoint response gains `raw_output_preview: <first 500 chars>` when parse fails so the UI can surface a graceful error banner.
- NO auto-retry (avoids burning tokens per spec).

## Phase 57 · Tech Department Assignment + Gated Experience (2026-07-16, LANDED)
### 57.1 · Admin dept assignment
- NEW `PATCH /api/users/{user_id}` (admin-only) — accepts `{department: "pool" | "landscaping" | null}`. Rejects unknown values with 400; rejects setting department on non-technician users. Emits Phase-55 notifications to the target user + all admins. Writes an audit-log row in `db.audit_log` with actor + changes.
- `GET /api/team` now tenant-scoped.
- Web UI (`OpsHub::TeamRoster`): 4 filter chips (All / Pool / Landscape / Unassigned) + colored dept badge + inline `<select>` dropdown per tech row with live PATCH.

### 57.2 · Department-gated nav
- NEW `TECH_POOL_NAV` and `TECH_LANDSCAPE_NAV` in `frontend/src/nav/roleNav.js`. Landscape variant hides Pool Calculators. Pool variant is the safe default for unassigned techs.
- NEW `navForRoleAndDept(role, department)` exported alongside legacy `navForRole`. `UniversalMenu` reads current user's department and dispatches.
- Curl matrix: PATCH admin→200, invalid dept→400, forbidden field→400, tech PATCH→403 (all pass).

### 57.3 · Landscape Checklist
- Existing `LandscapingChecklistForm.jsx` (Phase 31) preserved — checklist template already wired via `ChecklistModal::clientType`.
- `lib/checklistType.js::getChecklistType(job)` now consults:
  1. `job.checklist_kind` explicit override.
  2. `job.technician_department` (attached by Phase 57 job-detail enrichment).
  3. Keyword sniff on service_type / job_type / title (added `cleanup` keyword).
  4. Default: `pool` (safest for this business).
- `GET /api/jobs/{id}` now enriches `technician_department` from the assigned tech's user doc.

## Phase 58 · Rebrand AquaTerra → Pool & Landscaping (2026-07-16, LANDED)
- Assets: `/app/frontend/public/logo-icon.png` (1024×1024, transparent, 915 KB) + `/app/frontend/public/logo-full.png` (1024×1024, opaque, 615 KB) mirrored into `/app/mobile/assets/`. Both verified PNG-signature valid.
- Header: `AppLayout.jsx` sidebar + mobile menu now render the icon via `<img src="/logo-icon.png">`. `data-testid="app-logo-icon"` + `app-brand-short`.
- Login: `Login.jsx` hero renders `logo-full.png` at 280px max-width, replacing the `~` glyph placeholder.
- Browser title already correct ("Pool & Landscaping of Vistancia"). Added `<meta name="description">` + `<link rel="icon">` + `<link rel="apple-touch-icon">` to `index.html`.
- Global text replace across `/app/frontend/src` + `/app/mobile/src` + `/app/mobile/app` + `/app/backend/routers` + `/app/backend/seed.py`: 25 files touched. Collapsed `Pool & Landscaping of Vistancia — AquaTerra` → `Pool & Landscaping of Vistancia`. Replaced remaining plain `AquaTerra` → `Pool & Landscaping`.
- Preserved (per rules): tenant slug `"aquaterra"`, seed emails `*@aquaterra.com`, env-var names, statement descriptor "POOL LANDSCPE VISTANCA", auth strings, and `/tests/*` fixtures (SEO tests intentionally verify the OLD brand string).
- Grep confirmation: `grep -rn AquaTerra` returns 0 hits in `/app/frontend/src`, `/app/mobile/src`, `/app/mobile/app`, and `/app/backend/routers/` (excluding `/tests/`, `HANDOFF.md`, `PRD.md`, `test_credentials.md`, and Metro's compiled cache blobs — the latter regenerate automatically on next Expo build).
- Screenshots captured: `login_new.png`, `header_new.png`, `team_dept.png`.

## Guardrails honored across 55.2 / 56 / 57 / 58
- `/app` only. Preflight exit 0. `RC_OUTBOUND_ENABLED` untouched. Stripe descriptor unchanged. Tenant slug `"aquaterra"` unchanged. Seed emails unchanged. Phase 55/53/55.1 audience filter + Stripe RBAC gate preserved. English only.

═══════════════════════════════════════════════════════════════════
## Version 58.0 · Shipped snapshot (2026-07-16)
═══════════════════════════════════════════════════════════════════

The Pool & Landscaping of Vistancia CRM ships as a multi-tenant field-service
platform with three surfaces — a React (CRA) admin web SPA at
`https://poolscape-audit.preview.emergentagent.com`, an Expo Universal mobile
app (iOS + Android + Web) sharing the same FastAPI backend, and a public
customer portal. The admin experience is organized around a **6-category
information architecture** (`ADMIN_NAV_V2`: Finance · AI Employees · Marketing ·
Operations · Customers · Reports) exposed both as top-bar chips (wide viewports)
and a single unified hamburger sheet (narrow viewports + mobile) — no legacy
mobile-tab bar. The primary work surface is the **Workstream card layout**
where every job renders as an inline actionable card with quick-access buttons
(Complete · Move · Rearrange · Reassign) and a per-role visibility mask.
Technicians see a role-tabbed sidebar whose "On the Job" section is
department-gated: `navForRoleAndDept(role, department)` returns `TECH_POOL_NAV`
(includes chemical calculators + pool checklist) for `department: pool` and
`TECH_LANDSCAPE_NAV` (hides pool tools, exposes landscape clock + mowing/edging
checklist) for `department: landscaping`; the checklist form itself is
auto-selected server-side via `_derive_checklist_kind()` on every
`GET /api/jobs/{id}` read using an explicit override → tech department →
service_type keyword → pool default priority. Payments are handled through a
full Stripe stack (Hosted Checkout, Elements PaymentIntent, refunds,
subscriptions, reconciliation ledger with per-row fees/refunds/net), all
gated to admin OR the invoice's own customer via `_authorize_invoice_pay`.
Notifications flow through a unified `services/notifications.emit()` bell that
honors per-user Bell/Email/SMS preferences and enforces a strict
`audience: internal | portal` filter so admin fan-outs never leak to the
customer portal. RingCentral drives all telephony (SMS/call/voicemail/fax
with matched + unmatched fan-out) with `RC_OUTBOUND_ENABLED=false` locking
outbound to a mocked queue until the operator explicitly flips it. Backend
startup runs an idempotent `ensure_deployment_indexes()` migration that pins
the three deploy-critical indexes (`stripe_events.event_id` unique,
`notifications.(tenant_id, user_id, created_at desc)`, `budgets.(tenant_id, year)`
unique). Deploy verdict is 🟢 READY with two user-side vendor-dashboard
registrations pending (Stripe webhook subscription + RC subscription click).

## Phase 56.2 / 56.3 — SHIPPED (Feb 2026)

### Phase 56.2 · Active/Inactive Customer Split
- `GET /api/customers` accepts `is_active` + `count_only` params.
- New `PATCH /api/customers/{id}/activation` with shared Phase 34f cascade helper (`_apply_activation_cascade`) reused by PUT.
- Web: `/customers`, `/customers/active`, `/customers/inactive` routes with segmented tabs + live counts. Row-level Mark Inactive / Reactivate actions with Radix confirm + optimistic updates.
- Web `CustomerDetail.jsx`: pill + `testID=customer-active-toggle` inline switch (admin only). Non-admins see the read-only pill.
- Mobile: mirrored on `mobile/app/customer/[id].tsx` with native `Alert.alert` confirm.
- Phase 55 admin notification on state change (via shared helper).

### Phase 56.3.A · Customer First/Last Name Split + Google Places
- `CustomerIn` model: added `first_name` / `last_name` (optional).
- Server: `_sync_customer_names` bidirectionally reconciles `first_name` / `last_name` / `name` on every write.
- Startup idempotent migration `migrate_customer_names_split` back-fills legacy docs (0 rows migrated — all customer records already had first/last from Phase 56 CSV importer).
- Web `CustomerForm.jsx`: two separate required inputs for first/last on new customers; edits fall back to splitting legacy `name` on first whitespace.
- `AddressAutocomplete.jsx`: prefers `REACT_APP_GOOGLE_MAPS_API_KEY`, falls back to `REACT_APP_GOOGLE_API_KEY`. Places selection now also returns `country`.
- `GOOGLE_MAPS_API_KEY` env added to backend + frontend + mobile `.env` files (never echoed).
- `GET /api/config/frontend-env` (public) returns non-secret runtime keys (Google Maps + Stripe publishable).
- `GET /api/google-maps/health` (admin) returns `{configured, referrer_restrictions_note}` without hitting Google APIs.

### Phase 56.3.B · Unified Role+Department Widget + Add Team Member
- `_DEPARTMENTS` extended to `{"pool", "landscaping", "both"}`.
- `_VALID_DEPTS_BY_ROLE` whitelist: `admin → {both, null}`, `technician → {pool, landscaping, null}`.
- **"All" refined** — maps to `role: "admin", department: "both"` (admin RBAC + full pool + landscape tech surface).
- `PATCH /api/users/{id}`: accepts `role` + `department` in one call; blocks self-role-change; protects `super_admin` targets (403).
- **NEW `POST /api/users`** — admin-only Add Team Member with duplicate-email 409, invalid combo 400, MOCKED email invite via `email_delivery_log`, returns `temp_password` once for admin to relay.
- `GET /api/team/role-options` publishes canonical role/department combos.
- `_derive_checklist_kind` handles department `"both"` — pool default, landscape when service_type keyword matches.
- `navForRoleAndDept(role, department)`: `both` returns full `TECH_NAV` union.

### Phase 56.3 follow-ups
- **Landscape Clock Widget** visibility extended to admin + super_admin on both web (`AppLayout` auto-mounts globally) and mobile.
- `_require_landscaping` gate extended: admins/super_admins pass regardless of department; techs must be `landscaping` or `both`; pool techs still 403.
- **Clock-in Gate on schedule events** (`useClockInGate` hook + `ClockInGateDialog`): strict landscape techs must be clocked in before opening a scheduled event; dialog prompts with GPS-aware clock-in. Admins / "All" / pool techs / customers exempt. Wired into `CalendarSchedule.jsx` event-tap and grid `onOpenJob`.
- New `GET /api/timeclock/mine-status` lightweight probe (`{clocked_in, punch_count}`) used by the gate for snappy calendar taps.

### Chemical Reading Order (top-5)
- Reordered `POOL_READING_FIELDS_DEFAULT` and `POOL_READINGS`:
  1. Combined Chlorine → 2. Free Chlorine → 3. pH → 4. Total Alkalinity → 5. Cyanuric Acid
- Zero DB-stored custom pool templates existed — no migration needed. UI order change only.

### Deferred to Phase 56.3.C
- Roster UI rewrite in `OpsHub.jsx > TeamRoster` — swap department-only dropdown for the unified 4-option dropdown + filter chips (All | Pool Tech | Landscape Tech | Admin | All (Both) | Unassigned) + `+ Add Team Member` header button wired to the new `POST /api/users`. Backend fully ready.

## Phase 56.3.C — Team Roster UI Rewrite + Tech Job-Create RBAC (SHIPPED)

### Team Roster rewrite (`OpsHub.jsx > TeamRoster`)
- Unified 4-option Role dropdown per row: Pool Tech (blue), Landscape Tech (green), Admin (purple), All (gold).
- Filter chips: All roles | Pool Tech | Landscape Tech | Admin | All (Both) | Unassigned.
- Colored `data-testid=team-role-badge-{id}` badges next to each user, always visible.
- Self-demotion protection: caller's own row shows the badge only, no dropdown, with a "(you)" tag.
- `+ Add Team Member` header button (`data-testid=team-add-btn`) — admin/super_admin only.
- New `AddTeamMemberModal` with First/Last (required), Email (validated), Phone (optional), Role dropdown (4 options), Send invite email checkbox (default checked; MOCKED to `email_delivery_log`).
- On success shows temp password in a one-shot modal (`data-testid=team-add-temp-password`) for admin to copy.

### Tech job-create RBAC (P0 gate)
- Backend: `POST /api/jobs` already used `require_admin` — techs and customers already blocked (403). Confirmed with curl matrix.
- Web: `CalendarSchedule.jsx` introduces `canCreateJobs` flag from `user.role`; hides `calendar-new-job`, `grid-new-job`, and swallows `onSelectSlot` empty-slot navigation for techs. Confirmed via Playwright — Mike Rivera (pool tech) sees 0 create buttons on `/schedule`; admin sees 1.
- Web: `CustomerDetail.jsx` already protected via `<NoTech>` route guard (App.js).
- Mobile: `mobile/app/(app)/schedule/calendar.tsx` already gates on `isAdmin` — no changes needed.
- Recurring-jobs create endpoint (`POST /api/recurring-jobs`) also uses `require_admin` — techs blocked.

### Curl matrix (verified)
```
POST /api/jobs :
  admin        → 200
  super_admin  → 200
  pool tech    → 403
  landscape    → 403
```

### Files touched
- `frontend/src/pages/ops/OpsHub.jsx` (TeamRoster rewrite + AddTeamMemberModal + ROLE_OPTIONS)
- `frontend/src/pages/schedule/CalendarSchedule.jsx` (`canCreateJobs` gate + empty-slot swallow + button hide)

### Screenshots
- `/app/test_reports/56_3_C_team_roster.png` — roster with 4-option dropdowns + badges + Add button
- `/app/test_reports/56_3_C_add_team_modal.png` — Add Team Member modal open
- `/app/test_reports/56_3_C_tech_schedule_no_new.png` — Mike Rivera's schedule showing NO "New job" button

### Deferred (tracked)
- Mobile Add-Team-Member sheet mirroring web modal.
- `role_badge` cross-training UX on user profile card (payroll / dispatch) — not requested yet.

## Phase 56.4 · Tech "Request a Job" workflow — SHIPPED

**Backend** (`backend/routers/job_requests.py`, registered in `server.py`):
- `POST /api/job-requests` — technicians + admins may file. Status locked to `pending`; reviewer fields locked to null.
- `GET /api/job-requests?status=&mine=` — techs scoped to own; admins see all.
- `GET /api/job-requests/{id}` — owner or admin only (403 otherwise).
- `PATCH /api/job-requests/{id}` — admin only. Accepts `status` (approved / rejected — not `converted`), `rejection_reason`, `notes`. Sets `reviewed_at` + `reviewed_by_user_id`.
- `POST /api/job-requests/{id}/convert` — admin only. Creates a real job via the shared insert-shape used by `POST /api/jobs`, sets `status: "converted"`, records `converted_job_id`.
- Phase-55 notifications: new request → all admins; approve/reject → requesting tech; convert → requesting tech.

**Web** (`frontend/src/pages/job_requests/JobRequestsPages.jsx`, routes registered in `App.js`):
- `/request-job` — form modal-style page (customer selector optional + hint fields, service type, when, priority, notes).
- `/admin/job-requests` — filter chips (Pending / Approved / Rejected / Converted / All) + table with Approve / Convert (opens `ConvertModal`) / Reject (opens `RejectModal`) actions.

**Curl matrix (verified):**
```
POST tech creates                      → 200
GET  tech list scoped to self          → 1 row, no others
GET  tech view of other tech's request → 403
GET  admin list sees all               → 2 rows
PATCH tech attempts                    → 403
POST  tech convert attempts            → 403
PATCH admin approve                    → 200 (status=approved, reviewer set)
POST  admin convert                    → 200 (job_id returned, status=converted)
```

## Phase 56.5 · Seasonal chlorine targets + tab-preferred dosing — SHIPPED

**Config** (`backend/config_chlorine_targets.py`):
- `CHLORINE_HIGH_SEASON_MONTHS = {3..9}`
- `CHLORINE_HIGH_SEASON_TARGET_PPM = 5.0`
- Low-season range 1.0–3.0
- `CHLORINE_TAB_GALLONS_PER_TAB_PER_WEEK = 10_000`
- `CHLORINE_RAPID_BOOST_GAP_PPM = 2.0`
- `CHLORINE_TAB_ROTATION_LOOKBACK_VISITS = 3`

**Dosing engine** (`backend/services/pool_dosing.py`) — season-aware target, tabs/liquid decision:
- Rules (first-match wins): `chemical_preferences.no_tabs` → liquid; high-season rapid boost (gap > 2 ppm) → liquid; tabs in last 3 visits → liquid (rotation); otherwise → tabs.
- Tabs shipped in `unit: "tabs"` (integer count from `pool_gallons / 10_000` with +1/+2 bump for larger gaps).
- **Liquid chlorine now shipped in `unit: "gal"` (2dp)** — previously oz.
- **Muriatic acid (pH + TA lowering) now shipped in `unit: "gal"` (2dp)** — previously oz.
- Every recommendation carries `target_ppm`, `season` (`high` / `low`), `preferred_form` (`tabs` / `liquid`), `preferred_form_reason` string.

**Router wiring** (`backend/routers/service_reports.py::recommend_chemicals`):
- Fetches customer doc (`chemical_preferences`), scheduled_date, last 3 submitted reports, and passes them to `compute()`.

**Unit tests** (`backend/tests/test_phase56_5_dosing.py`): 19 tests, all passing:
- Month → season mapping (March–Sep high / Oct–Feb low).
- High season tabs by default; rapid-boost gap → liquid.
- `no_tabs` customer flag → forced liquid.
- Recent tab visits → rotate to liquid.
- Low season prefers tabs with 1–3 ppm range.
- Muriatic acid + Liquid chlorine both ship in `gal` (2dp).

**Sample live payload (July 2026 tenant, 20k gal, fc=4.0, ph=8.0):**
```
Chlorine tabs (3" trichlor)  qty=2   unit=tabs  season=high  form=tabs
Muriatic acid                qty=0.37 unit=gal
```
Rapid-boost scenario (fc=1.5): `Liquid chlorine (12.5%) qty=0.27 unit=gal target_ppm=5.0 form=liquid`.

## Business Card tech tweak — SHIPPED
- `frontend/src/pages/tech/BusinessCard.jsx` and `mobile/app/card.tsx`: technicians (any department) see Company card only. Toggle hidden. `showingPersonal` computation gates the personal card render defense-in-depth. Admins/super_admins/customers unchanged.

## Phase 56.6 · Pool Job Wizard Flow — SHIPPED

**Web (`frontend/src/components/checklist/`):**
- New `PoolChecklistWizard.jsx` — 6-step wizard shell with progress bar, clickable step dots (green ✓ when completed, blue when active), Back / Next buttons, and a "Save & exit" header button.
- Sections mapped:
  1. Readings (existing block, reordered)
  2. Recommended Chemicals + Chemicals Added
  3. Checklist
  4. Photos (customer-facing pool)
  5. Customer Notes (public — portal + email)
  6. Internal Notes (private) + tagged internal-issue photo pool
- Extended `PoolChecklistForm.jsx` with a `wizardStep` prop that gates section rendering (null ⇒ legacy single-scroll mode). Added `internalNotes` prop + Step-5 / Step-6 sections.
- `ChecklistModal.jsx` mounts the wizard by default for `pool` client type; `?legacy=true` query param bypasses the wizard for A/B fallback. Legacy footer suppressed when wizard active. Autosave now includes `wizard_step`, `internal_notes`, and `photos` so Save-&-Exit resumes at the correct step.

**Backend (`backend/routers/service_reports.py`):**
- `ServiceReportPatch` extended with `wizard_step: int?`, `internal_notes: str?`, `photos: [dict]?`. Uses `body.dict(exclude_unset=True)` so partial patches remain idempotent (Phase 40 offline queue safe).

**Photo tagging:** photo objects gain a `tag: "general" | "internal_issue"` field; the wizard splits/merges based on this so the customer-facing photo pool and the private "photos for issue" pool live in the same array without divergence risk.

**Guardrails preserved:**
- Only `pool` client type uses the wizard — landscape / generic unchanged.
- Autosave, Phase 44 Fix C refs, Phase 49.6 recheck hint, Phase 50.C sparkline, Phase 46.1 not-tested flags, offline queue idempotency — all still intact.
- Preflight → exit 0.

**Verification** — Playwright screenshots at `/app/test_reports/56_6_wizard_step{1..6}.png` show every step rendering distinct content (readings, chemicals, checklist, photos, customer notes, internal notes) with a functioning progress bar and step navigation. Step dots correctly reflect active/completed state.

**Deferred to Phase 56.6.B:**
- Mobile wizard (`mobile/src/components/checklist/PoolChecklistWizard.tsx`) with swipe navigation. Backend contract identical — mobile can mount the same shape.
- Optional target-line on the free-chlorine sparkline reading Phase 56.5 `target_ppm`.
- Full Phase 49.6 recheck-confirm surface on Close Job (wizard button already calls `closeJob` — confirmation flow may need a fresh call-site pass).

## Phase 56.5b · Soda Ash / Sodium Bicarbonate → lbs display — SHIPPED

Small dosing unit fix bundled ahead of Phase 56.7 mobile ship (2-file
backend change; frontend renders the payload verbatim so web + mobile
parity is automatic — same pattern used for the muriatic acid + liquid
chlorine gallons conversion).

**Changes** (`backend/services/pool_dosing.py`):
- Soda ash: was `qty × oz`, now `round(oz / 16, 1) × lbs`. Reason string
  mentions the lbs value (e.g. "1.5 lbs raises pH gently…").
- Sodium bicarbonate (baking soda): same treatment — was `qty × oz`, now
  `round(oz / 16, 1) × lbs`.
- Chemistry math unchanged (still per 10k-gallon `scale`, same delta
  formulas). Only presentation + `reason` string touched.

**Verified**:
- 19/19 Phase 56.5 dosing unit tests still passing (loose bounds).
- Live payload sample (pH 7.0, TA 60, 20k gal): Soda ash → 1.5 lbs,
  Sodium bicarbonate → 10.5 lbs.
- Muriatic Acid + Liquid Chlorine remain in gallons (unchanged).
- Chlorine Tabs remain integer count (unchanged).
- Preflight → exit 0.

**Chemicals Added catalog** (`backend/routers/service_reports.py`
`POOL_CHEMICALS_CATALOG_DEFAULT`) already lists Shock (Cal-Hypo) +
Soda Ash with `default_unit: "lbs"` — no change needed. The manual
entry dropdown was correct all along; only the AI recommendation
formatter had the mismatch.

**Note on "Shock"**: the deterministic recommender does not currently
emit a Shock recommendation (algae risk / very-high-cyanuric handling
is TODO). When it lands, it will use `unit: "lbs"` per the catalog
default. No display code change required in advance.

## Phase 56.9 · Chlorine tabs default + Luis Marquez rename — SHIPPED

**Item 1 — Chlorine Tabs as always-default form** (`backend/services/pool_dosing.py`):
- `_decide_chlorine_form` simplified: tabs always win unless the customer
  profile explicitly signals override.
- Two overrides retained: `chemical_preferences.no_tabs: True` (opt-out),
  `chemical_preferences.prefer_liquid_chlorine: True` (per-customer opt-in).
- Removed: rapid-boost auto-demote-to-liquid guard, and tab-rotation
  guard. Both replaced by explicit operator overrides so the recommender
  stays predictable ("what did I ask for = what I get").
- New `preferred_form_reason` copy: "Tabs recommended for steady residual
  — override to liquid if shocking or during algae bloom."
- Tests updated in `tests/test_phase56_5_dosing.py`: three replaced tests
  now assert tabs-default at rapid-boost gap, no rotation-to-liquid after
  recent tab visits, plus one net-new test for the `prefer_liquid_chlorine`
  operator override. 20/20 tests passing.

**Item 4 — Luis Marquez rename**: DB drift-fix applied to
`landscaper@aquaterra.com` (`name: "Luis Marquez"`, first/last also set).
Seed already had the correct name — no re-seed action needed to preserve.
`test_credentials.md` updated with the display name + Phase 56.9 note.

**Item 3 (Zillow investigation — no code change)**: `/api/property/*`,
`/api/d2d/*`, and `/api/zillow/*` all use `require_admin` in
`backend/routers/{property,d2d,zillow_admin}.py`. The frontend banner
"Zillow data unavailable — {reason}" (see `frontend/src/pages/d2d/D2dPages.jsx`
lines 175/248/515 and `PropertyLookupPage.jsx` line 164) surfaces the
backend's 403 "Admin access required" detail for non-admin callers.
Working as designed: Zillow enrichment is a rate-limited paid external
API (OpenWeb Ninja) and admin-gating protects the budget from field-tech
exploration. Not shipping a change — waiting on explicit user go-ahead
per the instruction.

**Item 2 (Visible algae field + AI algae remediation) — promoted to
Phase 56.10** for its own tested ship (new UI toggle on both surfaces,
new dosing formulas, high-pH ordering guard).

**Files touched**:
- `/app/backend/services/pool_dosing.py`
- `/app/backend/tests/test_phase56_5_dosing.py`
- `/app/memory/test_credentials.md`
- `/app/memory/PRD.md`


## Phase 56.13a — Training subsystem + CPO chapter drafts (Feb 2026)

Multi-tenant training platform for internal upskilling. This phase ships
the subsystem + CPO prep content drafts only — no DB seed yet.

**Backend subsystem:**
- New collections: `training_modules`, `training_progress`,
  `training_quiz_attempts`.
- New Pydantic models in `backend/models.py`: `TrainingLesson`,
  `TrainingQuizChoice`, `TrainingQuizQuestion`, `TrainingQuiz`,
  `TrainingModuleIn`, `TrainingModuleUpdate`, `TrainingProgressIn`,
  `TrainingQuizSubmit`.
- New router `backend/routers/training.py` (8 endpoints):
  `GET/POST /api/training/modules`,
  `GET/PATCH/DELETE /api/training/modules/{code}`,
  `POST /api/training/modules/{code}/progress`,
  `POST /api/training/modules/{code}/quiz`,
  `GET /api/training/modules/{code}/attempts`.
- Two module classes: **system modules** (`is_system=True`, no
  `tenant_id`, seeded by trusted scripts only, cross-tenant read-only)
  and **custom modules** (`is_system=False`, tenant-scoped,
  admin-editable via API).
- Custom module with same `code` as a system module overrides the system
  version at the tenant scope.
- RBAC: customer → 403 everywhere; techs see modules matching their
  `department` (`pool` or `landscaping`, plus modules tagged `both`);
  admins see all; only admins may create/patch/delete custom modules.
- System modules are immutable via API — PATCH and DELETE return 409.

**CPO prep content (drafts):**
- 9 chapters authored in-house at 706-918 words each:
  01_water_chemistry_fundamentals, 02_sanitization_and_oxidation,
  03_filtration, 04_circulation_and_hydraulics,
  05_disinfection_and_rwi_prevention, 06_chemical_feed_and_automation,
  07_facility_safety, 08_regulations_and_code, 09_math_and_calculations.
- 50 original multiple-choice questions in `quiz.json` (5-6 per chapter,
  4 choices, exactly 1 correct, one-sentence explanation).
- Badge label = **"CPO Prep — Completed"** (never "CPO Certified" —
  enforced by test).
- Persistent disclaimer on the module doc: *"This is prep material only.
  Official CPO certification requires enrollment with an authorized
  provider (PHTA / NSPF)."*

**IP-safety commitments (locked):**
- 100% original authorship, in-house engineering team.
- No verbatim content from PHTA, NSPF, or any commercial CPO course.
- External standards (ANSI/APSP-11, ANSI/APSP-16, ANSI/APSP-7,
  CDC MAHC, VGB Act, ISPSC, ADA, OSHA HCS, NEC 680, NFPA 704, IAPMO,
  NSF/ANSI 50) cited by name and canonical URL only.

**Seed script (dry-run, DB unchanged this session):**
- `backend/training_seed/training_cpo.py` reads the 9 `.md` chapters +
  `quiz.json`, assembles the module doc, and defaults to `dry_run=True`.
- Committing requires `python -m training_seed.training_cpo --commit`
  which was NOT invoked in this session.
- After user reviews the drafts, a follow-up **Phase 56.13a-commit**
  ship will run the commit.

**Tests (27 total, all passing):**
- `tests/test_training.py` (16 tests): RBAC across all 5 role
  permutations, department filter, tenant isolation, progress upsert,
  quiz scoring math, attempts list scoping, system-module immutability.
- `tests/test_training_cpo_seed.py` (11 tests): quiz-answer invariant,
  ≥50 questions, badge-label guard, disclaimer verbatim, chapter word
  bounds, chapter sha256 spot-check logging, dry-run reports
  `committed=False`.

**Updated priority order:**
1. ✅ Phase 56.13a (shipped this phase).
2. Phase 56.13a-commit — after user approves chapter drafts.
3. Phase 56.10 — Visible algae field + AI remediation dosing.
4. Phase 56.11 — Customer Equipment Photo Library (11 equipment types,
   ≤4 photos each, admin-only delete, tenant isolation).
5. PAUSED: 56.9b Zillow, T1-T6 calculators, 56.13b/c training UI,
   56.13d supplemental pool modules, 56.14 landscaper training,
   56.15 handbook.

**Files touched:**
- `backend/models.py` (Training* Pydantic models appended)
- `backend/routers/training.py` (new, 8 endpoints)
- `backend/server.py` (router registration)
- `backend/tests/conftest.py` (cleanup rules extended)
- `backend/tests/test_training.py` (new)
- `backend/tests/test_training_cpo_seed.py` (new)
- `backend/training_seed/__init__.py` (new)
- `backend/training_seed/training_cpo.py` (new)
- `backend/training_seed/training_cpo_chapters/01..09_*.md` (9 new)
- `backend/training_seed/training_cpo_chapters/quiz.json` (new)
- `memory/HANDOFF.md`
- `memory/PRD.md`


## Phase 56.13a-commit — CPO seed committed + Certificate of Completion (Feb 2026)

**Part 1 — Seed committed**
- `python -m training_seed.training_cpo --commit` executed. DB now
  contains 1 system training module: `code="cpo-prep"`,
  `is_system=true`, `department="pool"`, 9 lessons, 50 questions.

**Part 2 — Certificate feature**
- New collection `training_certificates` (one per tenant/user/module).
- `TrainingCertificate` Pydantic model in `backend/models.py`.
- Auto-award rule: on any `POST /api/training/modules/{code}/quiz`
  with `passed=true`, generate a certificate (idempotent).
  Retakes with a higher score update the score in place — no
  duplicate rows.
- Certificate ID format: `{MODULE_UPPER}-{YEAR}-{SEQ:06d}`
  (e.g. `CPO-PREP-2026-000001`), monotonic per tenant + module.
- 4 new endpoints:
  - `GET /api/training/certificates` — user's own certs
  - `GET /api/training/certificates/admin` — admin audit view
  - `GET /api/training/certificates/{cert_id}` — get one (owner/admin)
  - `GET /api/training/certificates/{cert_id}/pdf` — inline PDF stream
- PDF renderer via reportlab landscape letter:
  - Prominent red subtitle: **"CPO Prep — Not Official Certification"**
  - Bordered red disclaimer block with "does NOT constitute official
    Certified Pool Operator certification..." + PHTA/NSPF citation.
  - Footer: Certificate ID + "Generated by Pool & Landscaping" + date.

**Answer-key redaction (extra tightening)**
- `GET /api/training/modules/{code}` strips `correct_choice_ids` and
  `explanation` from every quiz question when caller is not admin/
  super_admin. Techs cannot read the answer key via the API.

**Tests — 35 total (all passing)**
- 24 subsystem tests in `test_training.py` (+8 new for certs + redaction).
- 11 integrity tests in `test_training_cpo_seed.py`.
- PDF tests byte-match assert the disclaimer + subtitle are in the PDF
  and the phrase "CPO Certified" is absent.

**Deferrals (v1):**
- No revocation UI, no cert expiration, no email delivery of the PDF.

**Files touched:**
- `backend/models.py`, `backend/routers/training.py`,
  `backend/training_seed/training_cpo.py`, `backend/tests/conftest.py`,
  `backend/tests/test_training.py`, `memory/HANDOFF.md`, `memory/PRD.md`.

**Priority order:**
1. ✅ Phase 56.13a (subsystem + drafts).
2. ✅ Phase 56.13a-commit (seed + PDF cert).
3. **NEXT: Phase 56.10** — Visible algae field + AI remediation dosing.
4. Phase 56.11 — Customer Equipment Photo Library.
5. PAUSED: 56.9b Zillow, T1-T6 calculators, 56.13b/c UI, 56.13d supplemental modules, 56.14 landscaper training, 56.15 handbook.

## Phase 56.10 — Visible algae field + AI remediation dosing (Feb 2026)

Extends the AI pool-dosing recommender with an algae-remediation branch
driven by a new tech-facing toggle on the Pool Checklist wizard.

**Backend:**
- `services/pool_dosing.compute()` accepts `visible_algae: "none" | "light" | "heavy"`.
- New constants in `config_chlorine_targets.py`:
  `CAL_HYPO_AVAILABLE_CHLORINE_PCT=73`, `ALGAE_LIGHT_SHOCK_PPM=10`,
  `ALGAE_HEAVY_SHOCK_PPM=30`, `POLYQUAT_OZ_PER_10K_GAL=4.0`,
  `ALGAE_HIGH_PH_THRESHOLD=7.6`.
- `light` state emits 1 cal-hypo entry (10 ppm boost, unit=lbs,
  category="algae_remediation", severity="light", guidance to brush +
  run filter 24h).
- `heavy` state emits 2 entries: triple-shock cal-hypo (30 ppm, lbs) +
  Polyquat 60 (4 oz per 10k gal, unit=oz), with extended guidance
  (backwash after 24h + recheck FC).
- High-pH guard: when pH > 7.6 AND algae is set, prepend a
  category="ordering_note" entry telling the tech to lower pH first.
- Algae entries are appended AFTER the 6-item routine cap — they
  always ship even when the routine list is full.
- `RecommendChemicalsBody.visible_algae` + `ServiceReportPatch.observations`
  are the API-boundary shapes.

**Web:**
- `PoolChecklistWizard.jsx` passes `observations` through to
  `PoolChecklistForm.jsx`.
- Form step 1 renders a pill-style toggle group (None / Light / Heavy)
  under the readings analysis card. Persists via
  `onChange({ observations: { visible_algae: value } })`.
- Form step 2 renders three distinct sub-sections when the payload
  includes categorized entries:
  - Top warning callout for `ordering_note` entries (yellow).
  - Standard recommendation list for routine entries.
  - Red-tinted **Algae Protocol** card for `algae_remediation` entries,
    with per-entry guidance-note bullets and Add buttons.

**Mobile:**
- Backend plumbing wired (`observations` prop + `visible_algae` in
  fetch body). UI toggle group DEFERRED to the mobile pool-wizard
  port. Current mobile form has all sections in a single block, so
  adding the toggle without the wizard boundary would clutter the
  screen; will follow the web pattern when the mobile wizard lands.

**Tests:**
- `tests/test_phase56_10_algae.py` — 13 tests, all passing.
- Existing 20 Phase 56.5 dosing tests still pass.

**Files touched:**
- `backend/config_chlorine_targets.py`, `backend/services/pool_dosing.py`,
  `backend/routers/service_reports.py`,
  `backend/tests/test_phase56_10_algae.py`,
  `frontend/src/components/checklist/PoolChecklistForm.jsx`,
  `frontend/src/components/checklist/PoolChecklistWizard.jsx`,
  `mobile/src/components/checklist/PoolChecklistForm.tsx`,
  `memory/HANDOFF.md`, `memory/PRD.md`.

**Priority order:**
1. ✅ Phase 56.13a (subsystem + drafts).
2. ✅ Phase 56.13a-commit (CPO seed + PDF cert).
3. ✅ Phase 56.10 (this ship).
4. **NEXT: Phase 56.11** — Customer Equipment Photo Library.
5. **PAUSED**: 56.9b Zillow, T1-T6, 56.13b/c, 56.13d, 56.14, 56.15.
6. **DEFERRED**: mobile pool-wizard algae toggle UI (waiting on wizard port).


## Phase 56.11 — Customer Equipment Photo Library (Feb 2026)

Field-service techs photograph 11 fixed equipment types per customer,
up to 4 photos each, so the next visit has a visual baseline for
warranty, algae before/after, and equipment-condition audits.

**Backend:**
- New enum module `backend/config_equipment_types.py` with 11 types
  (Filter Pump, Cleaning Pump, Waterfall Pump, Filter, Heater, Salt
  Cell, Cleaning System, Automation, Heater Plumbing, Check Valves,
  Jandy Valves), a 4-photo cap, and 3 allowed tags (`general`,
  `algae_before`, `algae_after`).
- New router `backend/routers/customer_equipment_photos.py` — 4 endpoints:
  `GET /api/equipment-types`,
  `GET /api/customers/{cid}/equipment-photos` (grouped),
  `POST /api/customers/{cid}/equipment-photos` (cap-enforced, tag-validated),
  `DELETE /api/customers/{cid}/equipment-photos/{pid}` (admin only).
- Collection `customer_equipment_photos`. Strict tenant isolation.
- Reuses the base64 data-URL upload pattern from the checklist
  PhotoUploader — no new storage backend required.

**RBAC:**
- customer role → 403 everywhere.
- technician (pool + landscape, department-agnostic) → view + upload.
- admin / super_admin → view + upload + delete.

**Algae hook:**
- Photo tags accept `algae_before` and `algae_after`. Web lightbox
  badges `algae_before` photos with a red `ALGAE` chip so the visit
  history is visually scannable. The wizard step-4 "consider tagging
  a wall close-up" soft prompt is a UI-only follow-up (data + API
  already support it).

**Web UI:**
- New component `CustomerEquipmentLibrary.jsx` — 11 accordion
  sections + 2×2 photo grid + dashed "+ Add photo" placeholder
  (hidden at cap) + lightbox with admin-only delete button.
- New "Equipment" tab on the customer detail page.

**Mobile UI:**
- DEFERRED — mobile customer detail screen does not have an equipment
  section yet. Backend is ready to serve mobile clients when the
  mobile UI ships.

**Tests — 12 total, all passing:**
- Enum returns 11 types in order.
- 4-photo cap enforcement (5th → 400).
- Customer forbidden from view + upload.
- Tech can view + upload; tech delete → 403; admin delete → 200.
- Cross-tenant read → 404.
- Grouped response includes all 11 types even when empty.
- Tag allow-list; unknown tag → 400.
- Unknown equipment type → 400.
- OpenAPI schema includes the new paths.

**Non-goals (locked):**
- No AI-based equipment identification.
- No maintenance schedules on the library (covered elsewhere).
- No "before/after" side-by-side rendering on the checklist (future).

**Files touched:**
- `backend/config_equipment_types.py`,
  `backend/routers/customer_equipment_photos.py`,
  `backend/server.py`, `backend/tests/conftest.py`,
  `backend/tests/test_phase56_11_equipment_photos.py`,
  `frontend/src/components/customers/CustomerEquipmentLibrary.jsx`,
  `frontend/src/pages/customers/CustomerDetail.jsx`,
  `memory/HANDOFF.md`, `memory/PRD.md`.

**Priority order:**
1. ✅ Phase 56.13a (subsystem + drafts).
2. ✅ Phase 56.13a-commit (CPO seed + PDF cert).
3. ✅ Phase 56.10 (visible algae + AI remediation).
4. ✅ Phase 56.11 (customer equipment photo library) — THIS SHIP.
5. Awaiting user direction on the queue (56.9b, T1-T6, 56.13b/c,
   56.13d, 56.14, 56.15 all paused).
6. Deferred UI follow-ups: 56.11-mobile, 56.11-followup (wizard
   algae-photo prompt), 56.10-mobile.


## Phase 56.13b — Training Web UI + "Tests" Nav (Feb 2026)

The web surface for the CPO training subsystem that landed in 56.13a-commit.

**Nav:**
- "Tests" chip in AdminTopBar QuickAccessRow (admin, super_admin,
  technician; hidden for customer) using `GraduationCap` icon.
- "Training / Tests" entry in TECH_NAV.records for all techs.
- Routes: `/tests`, `/tests/:code`, `/tests/:code/quiz`,
  `/admin/training`. `/training` aliases to `/tests`.

**Pages:**
- `TrainingList.jsx` — department-grouped card grid with progress
  rings + Start/Resume/Review CTA. Empty-state, admin "Manage
  modules" link, system-module badges.
- `TrainingModuleDetail.jsx` — split-panel lesson list + markdown
  body via `react-markdown`. Mark-complete, Prev/Next, and a Take
  Quiz banner that appears once all lessons are marked complete.
  Yellow disclaimer callout renders the module's disclaimer string.
- `TrainingQuiz.jsx` — one-question-at-a-time runner with 4 pill
  choices, Prev/Next, and a final Submit gated on all-answered.
  Results screen: pass/fail banner, cert block with PDF download
  button (linking to `/api/training/certificates/{id}/pdf`),
  per-question review with the tech's own answer marked.
- `AdminTraining.jsx` — read-only table of every module. System
  modules render with a lock badge. V1 has NO tenant-custom
  editor — deferred to a follow-up.

**Certifications surface on user profile — DEFERRED to
56.13b-followup**. `GET /api/training/certificates` is live from
56.13a-commit and surfaced via the results screen; a dedicated
section on the team-member detail page lands with the mobile UI.

**Non-goals (v1, locked):** no drag-reorder, no rich-text editor,
no forum, no email cert delivery, no confetti animation, no
leaderboard.

**Files touched:**
- `frontend/src/pages/training/{TrainingList,TrainingModuleDetail,
  TrainingQuiz,AdminTraining}.jsx` (all new)
- `frontend/src/App.js` (imports + 4 routes)
- `frontend/src/layouts/AdminTopBar.jsx` (Tests chip)
- `frontend/src/nav/roleNav.js` (Training entry)
- `memory/HANDOFF.md`, `memory/PRD.md`

**Priority order:**
1. ✅ Phase 56.13a (subsystem + drafts).
2. ✅ Phase 56.13a-commit (CPO seed + PDF cert).
3. ✅ Phase 56.10 (visible algae).
4. ✅ Phase 56.11 (equipment photo library).
5. ✅ Phase 56.13b (training web UI) — THIS SHIP.
6. **NEXT: Phase 56.13c** — Training Mobile UI.
7. Then: 56.10-mobile, 56.11-mobile.
8. Then: 56.13b-followup — profile certs section + custom-module editor + leaderboard.
9. Paused: 56.9b Zillow, T1-T6, 56.13d, 56.14, 56.15.


## Phase 56.16 — Landscape Checklist Rewrite (URGENT — Feb 2026)

Field-tech blocker: the landscape checklist was cluttered with per-item
notes and a single ambiguous "Notes" field, and the seed template had
the wrong items.

**Fixed:**
- Canonical 10-item checklist (Sprayed or Pulled Weeds → Irrigation
  Repair), stored in `backend/config_landscape_checklist.py`.
- Per-item note textarea removed from the landscape form (web +
  mobile). Pool checklist per-item notes UNCHANGED.
- Notes split: "Job Notes (Internal — not visible to customer)"
  persists to `internal_notes`; "Customer Notes (visible to
  customer)" persists to `customer_notes` (new field on
  `ServiceReportPatch`).
- New customer-portal read endpoints:
  `GET /api/customers/me/service-reports` +
  `GET /api/customers/me/service-reports/{id}` — both redact
  `internal_notes` and internal/issue photos. Non-customer role → 403.

**Deferred:**
- Customer-facing portal UI page (backend contract is shipped;
  React page = Phase 56.16-followup).
- Legacy `JobDetail.jsx` "Field Report" widget still has a stale
  hardcoded 8-item list — recommend sunset.

**Tests:** 5 tests in `test_phase56_16_landscape.py` (3 passed, 2
skipped due to empty schedule/today — behavior verified via curl).

**Files touched:**
- `backend/config_landscape_checklist.py` (new)
- `backend/routers/service_reports.py`
- `backend/tests/test_phase56_16_landscape.py` (new)
- `frontend/src/components/checklist/LandscapingChecklistForm.jsx`
- `frontend/src/components/checklist/ChecklistModal.jsx`
- `mobile/src/components/checklist/LandscapingChecklistForm.tsx`
- `memory/HANDOFF.md`, `memory/PRD.md`

**Priority order:**
1-5: ✅ (56.13a, 56.13a-commit, 56.10, 56.11, 56.13b).
6. ✅ Phase 56.16 — Landscape Checklist Rewrite (URGENT — this ship).
7. **NEXT: Phase 56.13c** — Training Mobile UI + Team CPO Readiness
   (deferred from this session due to token budget).
8. Then: Phase 56.16-followup (portal UI), 56.10-mobile, 56.11-mobile,
   56.13b-followup.
9. Paused: 56.9b Zillow, T1-T6 calculators, 56.13d, 56.14, 56.15.


## Phase 56.13c — Training Mobile UI + Team CPO Readiness widget (Feb 2026)

Three deliverables:

**A. Training Mobile UI (main lift)**
- New Expo Router screens under `mobile/app/(app)/tests/`:
  - `index.tsx` — module list (FlatList of cards, department badges,
    thin progress bar, Start / Resume / Review CTAs).
  - `[code].tsx` — module detail (chip carousel of lessons, in-file
    lightweight markdown renderer for H1/H2/paragraphs/bullets/italic,
    Prev/Mark done/Next footer, floating Take Quiz banner).
  - `[code]/quiz.tsx` — quiz runner + results (pill choices,
    Prev/Next/Submit gated on all-answered, pass/fail banner,
    per-question review, cert PDF via `Linking.openURL`).
- GlobalMenu tile "Tests" added to `TECH_SECTIONS.records` (via
  `sections.ts`).
- No new deps: custom markdown renderer avoids
  `react-native-markdown-display`.
- Progress + certs persist to the same `/api/training/*` endpoints,
  so start-on-web-finish-on-mobile just works.

**B. Team CPO Readiness widget**
- New component `frontend/src/components/admin/TeamCpoReadinessWidget.jsx`
  mounted on the admin Dashboard.
- Two-line collapsed summary + expandable per-tech table.
- Fetches `/api/training/certificates/admin` + `/api/team`, computes
  Certified vs Not Started per tech.
- V1 approximation footnoted: "In progress" bucket shows 0 pending a
  bulk-progress endpoint (deferred to 56.13b-followup).

**C. Legacy Field Report widget cleanup**
- No action required — after inspection, the widget is already
  data-driven from `fr.checklist` on the job doc. Stale labels are
  the persisted snapshot on old jobs, per spec.

**Files touched:**
- `frontend/src/components/admin/TeamCpoReadinessWidget.jsx` (new)
- `frontend/src/pages/admin/Dashboard.jsx`
- `mobile/src/components/tools/sections.ts`
- `mobile/app/(app)/tests/{index,[code],[code]/quiz}.tsx` (all new)
- `memory/HANDOFF.md`, `memory/PRD.md`

**Priority order:**
1-6: ✅ (56.13a, 56.13a-commit, 56.10, 56.11, 56.13b, 56.16).
7. ✅ Phase 56.13c — Training Mobile UI + Team CPO Readiness (this ship).
8. **NEXT: Phase 56.16-followup** — customer portal service-reports UI.
9. Then: 56.10-mobile, 56.11-mobile.
10. Then: 56.13b-followup (profile certs + custom-module editor +
    leaderboard + bulk-progress endpoint).
11. Paused: 56.9b Zillow, T1-T6, 56.13d, 56.14, 56.15.

---

## Phase 56.16-followup — Customer Portal Service Reports UI (Web) (Feb 2026)

Customer-facing read-only surface at `/portal/service-reports` (list) +
`/portal/service-reports/:id` (detail). Backend endpoints already
existed from Phase 56.16. This ship is web-only; mobile deferred.

**Files touched:**
- `frontend/src/pages/portal/PortalServiceReports.jsx` (new — list +
  detail components).
- `frontend/src/pages/portal/PortalHome.jsx` (new "Service Reports"
  quick-action tile, lucide `ClipboardCheck`, testid
  `qa-service-reports`).
- `frontend/src/App.js` (routes: `/portal/service-reports` and
  `/portal/service-reports/:id`; `/customer/service-reports` alias
  redirects to preserve the spec path).
- `backend/tests/seed_customer_portal_service_reports.py` (new,
  idempotent — seeds 1 completed pool + 1 completed landscape
  service_report for `customer@aquaterra.com`, includes deliberately
  tagged `internal` + `issue` photos and a `SEEDED-INTERNAL:`
  `internal_notes` string so redaction is externally verifiable).

**Sections rendered (detail view):**
- Header (kind chip, Completed pill, visit date, tech, address).
- Algae observation banner (pool only, customer-friendly language —
  never leaks raw remediation doses).
- Water chemistry readings table (pool only, values only, no
  reasoning).
- Chemicals added list (pool only, `name  amount unit`).
- Checklist (pool ~6 items or landscape 10 canonical items) with
  checkmarks.
- Notes from your tech (verbatim `customer_notes`; NEVER
  `internal_notes`).
- Visit photos grid (backend has already stripped internal/issue tags
  before serving to /me).

**Redaction verified live** (`customer@aquaterra.com` on preview):
- `internal_notes` absent from both detail payloads.
- Pool photos: 3 seeded (after/internal/issue) → 1 rendered (after
  only).
- Landscape photos: 3 seeded (after/after/issue) → 2 rendered (both
  afters).
- Admin (no `customer_id`) hitting `/customers/me/service-reports` →
  HTTP 403.
- DOM assertion after react render: `SEEDED-INTERNAL` string not in
  either page's HTML.

**Nav / RBAC:** "Service Reports" tile appears on the customer portal
home (customer-only surface — non-customers are redirected off
`/portal/home` in `App.js`).

**Test credential:** `customer@aquaterra.com` / `password123` (already
in `memory/test_credentials.md` — no new account seeded).

**Preflight:** `bash /app/scripts/preflight.sh` → exit 0 (only the 417
pre-existing dead-import warnings inherited from 56.13c — no new
warnings introduced).

**Regression:** `pytest backend/tests/test_phase56_16_landscape.py` →
3 passed, 2 skipped (same skips as previous ship).

**Priority order after this ship:**
1-8: ✅ (all previous phases + 56.13c + 56.16-followup).
9. **NEXT: 56.10-mobile** — algae toggle on mobile pool wizard step 1
   + algae_remediation section on step 2. Deferred here to keep the
   web ship self-contained.
10. Then: 56.11-mobile (equipment library on mobile customer detail).
11. Then: 56.13b-followup (profile certs section + tenant-custom
    module editor + leaderboard + bulk-progress endpoint to unblock
    the CPO widget's in-progress counter).
12. Paused: 56.9b Zillow, T1-T6 calculators, 56.13d, 56.14, 56.15.
13. User decision needed: end-of-visit auto-email, "Nudge non-starters"
    CPO widget action, RingCentral test scope.

---

## Phase 56.10-mobile — Algae Toggle + Protocol Render on Mobile Pool Wizard (Feb 2026)

Web parity ship on the mobile pool checklist form. Backend
(`pool_dosing.py`) already emits `category: "ordering_note"` /
`"routine"` / `"algae_remediation"` with `guidance_note` where
appropriate — this ship wires the matching mobile UI.

**Files touched:**
- `mobile/src/components/checklist/PoolChecklistForm.tsx`
  * Extended `Rec` type with `category` + `guidance_note`.
  * New "Visible algae on walls" card (`mobile-visible-algae-card`)
    below Chemical Readings with 3 pill buttons
    (`mobile-visible-algae-toggle-{none,light,heavy}`); persists to
    `observations.visible_algae` via existing `patchReport`
    autosave (no new endpoint, no new state store).
  * Recommended Chemicals render split into three ordered passes:
    ordering-note callout (`mobile-algae-ordering-note`, yellow, at
    the top), routine rows (unchanged `pool-recommendation-row`),
    and an Algae Protocol sub-card (`mobile-algae-protocol-card`,
    red-tinted, at the bottom) — matches web `PoolChecklistForm.jsx`
    verbatim in when + how each section renders.
  * Algae rows render multi-sentence `guidance_note` as bullet
    points (`mobile-algae-guidance-bullet`) split on sentence
    boundary — brush, extended filter run, backwash notes.
  * **Latent JSX bug fix (byproduct)** — the file had an unmatched
    `{inStep(1) ? (<>` fragment opener with no closing tag; metro/
    esbuild silently accepted it, strict TSC flagged 93 cascading
    errors. Removed the incomplete opener (mobile always renders as
    a single scroll — the caller never wires `wizardStep`), a
    runtime no-op that reduced this file from 93 → 10 TSC errors.
- `mobile/app/job/[id]/checklist.tsx`
  * Passes `observations={report.observations || {}}` into
    `<PoolChecklistForm>` so toggle state survives autosave.

**Constraints held:**
- Reused the existing mobile checklist state pattern
  (`patchReport` merge). No new autosave loop, no new state
  library.
- **No backend changes. No web changes.** `git diff --stat`
  confirms only two mobile files touched.

**Preflight:** `bash /app/scripts/preflight.sh` → exit 0 (417
pre-existing dead-import WARNs; no new WARNs from this ship).

**TSC:** `PoolChecklistForm.tsx` errors 93 → 10 (net improvement of
83; all 10 remaining errors are pre-existing on lines this ship did
not touch).

**Evidence path:** Source-file diff excerpts (per brief's fallback
option) — the Visible Algae card block, the ordering-note callout
block, and the Algae Protocol sub-card block are captured in
`memory/HANDOFF.md`. Expo Web preview reached HTTP 200 but token
persistence across Playwright `goto` calls is unreliable
(`expo-secure-store` writes to a per-page storage key that the test
harness cookie context does not carry across navigations); the
checklist screen landed on the "You don't have permission" gate.

**Priority order after this ship:**
1-10: ✅ (all previous phases + 56.16-followup + 56.10-mobile).
11. **NEXT: 56.11-mobile** — equipment library on mobile customer detail.
12. Then: 56.13b-followup — profile certs section, tenant-custom
    module editor, leaderboard, and
    `GET /training/progress/admin?module_code=cpo-prep`
    bulk-progress endpoint (unblocks Team CPO Readiness widget's
    in-progress counter accuracy).
13. Paused: 56.9b Zillow, T1-T6 calculators, 56.13d, 56.14, 56.15.
14. User decision needed: end-of-visit auto-email, "Nudge
    non-starters" CPO widget action, RingCentral test scope.

---

## Phase 56.11-mobile — Equipment Photo Library on Mobile Customer Detail (Feb 2026)

Mobile parity ship for Phase 56.11 (backend + web already live).
Native mirror of `frontend/src/components/customers/CustomerEquipmentLibrary.jsx`
on the mobile customer detail screen.

**Files touched (mobile-only):**
- `mobile/src/components/customers/CustomerEquipmentLibrary.tsx`
  **(new)** — 11 collapsible sections (from server enum), 2×2
  photo grid per section, dashed "+ Add photo" placeholder that
  disappears at the 4-photo cap, `algae_before` badge on
  thumbnails for cross-surface parity, lightbox via `Sheet`, and
  a full upload flow that reuses the existing `expo-image-picker`
  idiom the customer detail screen already uses for documents.
  Optional caption (max 120 chars) + 3-way tag pill selector
  (`general` / `algae_before` / `algae_after`, default
  `general`). No new picker, no new grid lib, no new modal lib.
  Component-local state; the grouped fetch is the single source
  of truth and re-fetches after every mutation.
- `mobile/app/customer/[id].tsx` — 5-line diff: import the new
  component + render an "Equipment" section between Documents and
  Job History, using the existing `sectionTitle` style.

**RBAC:**
- Delete button in the lightbox is hidden unless
  `useAuth().user.role ∈ {admin, super_admin}`. Two-step
  confirmation via native `Alert.alert`. Defensive: on the
  theoretical 403 the router still returns, surfaces a "Not
  authorized" toast.
- Backend RBAC verified live against the preview API:
  `DELETE /customers/{cid}/equipment-photos/{pid}` as
  `mike@aquaterra.com` (tech) → **HTTP 403**; as
  `admin@aquaterra.com` → **HTTP 200**.

**Preflight:** `bash /app/scripts/preflight.sh` → exit 0 (417
pre-existing dead-import WARNs; no new WARNs).

**TSC:** new file reports **0 errors**; caller file
(`customer/[id].tsx`) shows only 4 pre-existing errors on lines
this ship did not touch (`fontSize.xs` misses at 401/411/422;
`role === "super_admin"` overlap warning at line 72).

**Ship scope guarantee:** `git diff --stat HEAD -- backend/
frontend/` returns **0 files**. Only two mobile paths touched
(one new file, one 5-line edit).

**Evidence path:** Source-file diff excerpts and backend curl
verification captured in `memory/HANDOFF.md`. Expo Web preview
reachable but Playwright login persistence across `goto`
navigations is unreliable (`expo-secure-store` per-page key) —
same precedent as Phase 56.10-mobile; source-diff evidence is the
authoritative path per the brief's fallback.

**Priority order after this ship:**
1-11: ✅ (all previous phases + 56.16-followup + 56.10-mobile +
      56.11-mobile).
12. **NEXT: 56.13b-followup** — profile certs section,
    tenant-custom module editor, leaderboard, and
    `GET /training/progress/admin?module_code=cpo-prep`
    bulk-progress endpoint (unblocks the CPO Readiness widget's
    in-progress counter accuracy).
13. Paused: 56.9b Zillow, T1-T6 calculators, 56.13d, 56.14, 56.15.
14. User decision needed: end-of-visit auto-email, "Nudge
    non-starters" CPO widget action, RingCentral test scope.

---

## Phase 56.13b-followup — Training Profile Certs + Tenant Module Editor + Leaderboard + Bulk-Progress Endpoint (Feb 2026)

Four deliverables bundled: (A) `GET /training/progress/admin` +
widget accuracy fix, (B) profile certs panel, (C) full tenant
module editor, (D) leaderboard w/ CSV export. Closes the
"in-progress counter approximation" footnote from 56.13c.

**Backend (new endpoints — admin-only, tenant-scoped):**
- `GET /api/training/progress/admin?module_code=` — returns one
  row per training_progress doc with `has_started` derived from
  `lessons_completed`.
- `GET /api/training/leaderboard?days=90` — per-user rollup over
  the rolling window (modules_completed, quizzes_passed,
  attempts, certificates_earned, avg_score).
- Existing 56.13a CRUD (`POST/PATCH/DELETE /training/modules`)
  unchanged — system modules stay immutable (409 on write).

**Web:**
- Team CPO Readiness widget now consumes the bulk-progress
  endpoint → accurate three-state breakdown.
- `TechnicianProfile` gains a **Certifications** tab wired to
  new `TrainingCertsPanel.jsx` (PDF download via
  JWT-authenticated blob fetch).
- `AdminTraining.jsx` rewritten (109 → 812 lines):
  segmented Modules / Leaderboard tabs, slide-over editor for
  tenant-custom modules (Basics + Lessons + Quiz — up/down
  reorder, no drag-drop, no rich text, no AI-authoring),
  sortable leaderboard table with CSV export.

**Mobile:** unchanged this ship. Mobile profile screen doesn't
exist yet; explicitly deferred. Not blocking pool tech workflow.

**Files touched:**
- `backend/routers/training.py` (+143 lines)
- `backend/tests/test_phase56_13b_followup.py` (**new**)
- `frontend/src/components/admin/TeamCpoReadinessWidget.jsx`
- `frontend/src/pages/training/AdminTraining.jsx` (rewrite)
- `frontend/src/pages/training/TrainingCertsPanel.jsx` (**new**)
- `frontend/src/pages/phase14/Phase14Pages.jsx`

**Preflight:** `bash /app/scripts/preflight.sh` → exit 0 (418
pre-existing dead-import WARNs, no new WARNs).

**Backend tests:** `pytest test_phase56_13b_followup.py` → 4/4
passed in 27.97s. Covers new endpoints, system-module
immutability, tenant custom CRUD with RBAC on every path.

**Live curl verification (all 8 assertions):**
- `GET /training/progress/admin` → 200 as admin, 403 as tech.
- `GET /training/leaderboard` → 200 as admin (9 rows), 403 as tech.
- `PATCH/DELETE /training/modules/cpo-prep` → **HTTP 409** as
  admin (system module immutability).
- `POST /training/modules` as admin → 200 (tenant custom
  module created).
- `POST/PATCH/DELETE /training/modules` as tech → all 403.

**Screenshots captured:**
- Team CPO Readiness widget expanded with accurate summary.
- Admin training Modules table with SYSTEM badge on cpo-prep.
- Slide-over editor pre-filled with a new tenant module.
- Leaderboard table with sortable columns and CSV export.
- Technician profile Certifications tab with a downloadable cert.

**Priority order after this ship:**
1-12: ✅ (all previous phases + 56.16-followup + 56.10-mobile +
      56.11-mobile + 56.13b-followup).
13. **Paused**: 56.9b Zillow, T1-T6 calculators, 56.13d
    (supplemental pool modules), 56.14 (landscape training),
    56.15 (handbook).
14. **User decision needed**: end-of-visit auto-email, "Nudge
    non-starters" widget action, RingCentral test scope.

The active **training + service-report + equipment** triangle is
now feature-complete for the pool tech workflow.

---

## Phase 56.17 + P0 nav fix — Autobilling Schedule Options + Auto-Run + Master Invoices 404 fix (Feb 2026)

Two things landed:

**P0 fix — Master Invoices 404**: `frontend/src/nav/adminNav.js`
had a stale link to `/master-invoices` while the routes were
mounted at `/invoices/master*`. One-line nav update — fully
resolved. Not caused by any recent phase (predates the session).

**Phase 56.17**: Autobilling gets a monthly-anchor picker with
5 options (`first_friday`, `second_friday`, `third_friday`,
`fourth_friday`, `first_of_month`) and a **daily** APScheduler
tick (replacing the old every-24h chem-billing job's role for
custom-anchor plans). Each plan fires exactly once per calendar
month via a `last_run_month` idempotency guard, with a 7-day
grace window for pod-downtime catch-up (>7-day misses log
`late_missed` and require manual run). All fire attempts
(scheduled, catch-up, manual, error, skip) write to a new
`autobilling_runs` collection.

**Backend**:
- `run_schedule` enum on `BillingPlanIn` / `BillingPlanUpdate`.
- `anchor_date_for_month` + `next_fire_preview` (pure functions).
- `run_daily_autobilling` (new cron job at 06:00 UTC; anchor
  computed in tenant's own timezone via `America/Phoenix`
  default).
- `POST /billing-plans/{id}/run-now` — admin manual fire w/
  409 idempotency guard.
- `GET /billing-plans/{id}/next-fire` — preview endpoint.
- `GET /autobilling-runs` — audit log (admin-only, filters
  by plan_id / status / since).
- `PATCH /tenant/settings { timezone }` — IANA validation.

**Web**: New Plan modal in `FinancePages.jsx` gains the
Run Schedule dropdown + live next-fire preview.

**Backend tests**: `test_phase56_17_autobilling.py` — 6 tests,
all passing. Covers anchor math (Feb 4-Friday case, July
5-Friday case where 4th anchor must be Jul 24 not Jul 31,
Oct-Wed-start, May-Fri-start), timezone helper,
`fifth_friday` rejection (422), run-now RBAC + idempotency,
7-day grace window (fire vs. late_missed), `/autobilling-runs`
RBAC, tenant timezone PATCH.

**Non-goals held**: no per-customer overrides, no weekly/bi-
weekly options, no 5th-Friday option (rare), no cross-month
batching, no upcoming-run email/SMS.

**Deferred**: dedicated `/admin/autobilling-runs` frontend
audit page (endpoint is live; UI page is a small
Phase 56.17-followup).

**Files touched**:
- `backend/models.py`
- `backend/routers/finances.py` (+260 LOC 56.17 block)
- `backend/server.py` (new daily cron job wire-in)
- `backend/tests/test_phase56_17_autobilling.py` (new)
- `frontend/src/pages/finance/FinancePages.jsx`
- `frontend/src/nav/adminNav.js` (P0 fix)

**Preflight**: `bash /app/scripts/preflight.sh` → exit 0.

**Live curl proof**: `fourth_friday` on a plan created today
previews Next billing run = `2026-07-24` (July's 4th Friday);
run-now on it fires with `last_run_month="2026-07"`; second
run-now returns HTTP 409; tech token on `/autobilling-runs`
returns HTTP 403.

**Priority order after this ship:**
1-13: ✅ (all previous phases + 56.17 + P0 fix).
14. **Paused**: 56.9b Zillow, T1-T6 calculators, 56.13d,
    56.14, 56.15.
15. **User decision needed**: end-of-visit auto-email, "Nudge
    non-starters" widget action, RingCentral test scope,
    Phase 56.17-followup autobilling audit UI page.

---

## Session close — Phase 56.9b Step 0 report + defer to fresh session

### Session recap (in ship order)

1. Phase 56.16-followup — Customer portal service reports UI.
2. Phase 56.10-mobile — Algae toggle + protocol on mobile pool wizard.
3. Phase 56.11-mobile — Equipment photo library on mobile customer detail.
4. Phase 56.13b-followup — Bulk-progress endpoint + profile certs +
   tenant module editor + leaderboard.
5. Phase 56.17 + P0 Master Invoices 404 fix — Autobilling schedule
   anchors (5 options inc. `fourth_friday`) + daily auto-run +
   `/master-invoices` → `/invoices/master` nav fix.
6. Phase 56.17-followup — Autobilling runs audit UI page at
   `/admin/autobilling-runs`.
7. Phase 56.9b Step 0 (exploration only, no code touched) —
   **deferred to fresh session**.

Preflight: **exit 0** at every ship boundary in this session.

### Fresh-session brief — Phase 56.9b guardrail-first Zillow ship

Executed Step 0 in this session; deferred Steps 1–10 to a fresh
session to preserve guardrail integrity. Nothing in `/app` was
mutated for 56.9b — Step 0 was a read-only survey. The next
session opens against a clean slate with this as its brief.

**RBAC endpoints to swap in Step 8 (LAST)** — 6 total, currently
`Depends(require_admin)`:
- `backend/routers/property.py`: `/property/lookup`,
  `/property/save`, `/property/saved`, `/property/saved/{pid}`
- `backend/routers/d2d.py`: `/d2d/sold-leads`
- **Stays admin-only** (aggregate reporting, not a lookup):
  `backend/routers/d2d.py::/d2d/report`

**Already tech-accessible (no change needed)** — 5 endpoints on
`property.py`: `/search`, `/search-by-coords`, `/history`,
`/save-note`, `/saved-notes` (mix of
`require_tech_or_admin` / `require_tech_or_admin_write`).

**Clean-slate collections** — neither `zillow_cache` nor
`zillow_usage` exists in Mongo today. Both must be created in
Steps 1 (usage) and 3 (cache) with TTL indexes.

**Widget endpoint home** — `backend/routers/zillow_admin.py` is a
523-byte stub with only `/health`. It's the target file for the
Step 4 admin usage widget endpoint. No refactor needed.

**Web frontend surfaces to touch on Step 6** — 4 pages, exactly as
briefed:
- `pages/property-lookup/PropertyLookupPage.jsx` line 164 (banner
  + chip).
- `pages/d2d/D2dPages.jsx` lines 175, 248, 515 (3 spots).
- `pages/aitools/AiToolsPages.jsx` line 572 (virtual-bid — same
  Zillow lookup, add chip).
- `pages/tech/ToolsHub.jsx` line 35 (tile becomes accessible; no
  banner change).

**Mobile canvassing surface** — NOT YET SURVEYED. First action in
the fresh session is Step 0 continuation: grep `/app/mobile` for
D2D canvassing / sold-leads / property-lookup UI to determine
whether Step 7 (mobile parity) is a real deliverable or a "web
only" note in HANDOFF.

**Configuration** — `OPENWEB_NINJA_API_KEY` env in
`backend/config.py`; base URL
`https://api.openwebninja.com/realtime-zillow-data`.

**Rate-limit caps (from brief, restated)**:
- Techs: 20 / day + 200 / month.
- Admins: uncapped.
- Super_admin: uncapped + can `?override_budget=true` past a
  100 %-consumed tenant budget (writes a
  `zillow_budget_override` audit event).
- Tenant monthly budget default: 1000 / month.
- ≥ 90 % → 200 + `X-Zillow-Budget-Warning: 1` header + JSON
  banner field. ≥ 100 % → 429
  `{error: "tenant_budget_exhausted", ...}` except for the
  super_admin override.
- Cache hits do NOT decrement rate-limit counters. Cache key =
  `sha256(normalized_address)`, 30-day TTL.

**Fresh-session opening actions (in order)**:
1. Step 0 continuation — grep `/app/mobile` for canvassing UI;
   confirm whether Step 7 is real or a web-only note.
2. Step 1 — `backend/services/zillow_rate_limit.py` + `zillow_usage`
   collection w/ TTL indexes.
3. Steps 2 → 7 per the original brief.
4. Step 8 — RBAC swap LAST, only after Steps 1–5 tests are green.
5. Steps 9–10 — HANDOFF/PRD entry + `preflight.sh` exit 0.

### Parallel user decisions (do NOT touch until user greenlights)

- End-of-visit auto-email.
- "Nudge non-starters" CPO widget action.
- RingCentral test scope.

The user is handling these in a separate track. Not blocking
56.9b.

### T-phases (T1–T6)

Explicitly on hold until the user reviews 56.9b evidence AND
provides the design-system audit reply. Do NOT auto-start them.

---

Session closed. `/app` is the source of truth. Fresh session
opens directly on Phase 56.9b guardrail-first work.

---

## Phase 56.9b Option A — Backend Guardrail Infrastructure (Feb 2026)

Steps 1–5 + 9 + 10 landed. Steps 6, 7, 8 explicitly held for
the next session per the Option A boundary. **Zero user-facing
exposure** — the 5 Zillow endpoints stay `require_admin` until
Step 8 flips in a follow-up session.

**Files touched:**
- `backend/services/zillow_rate_limit.py` **(new)** — pure
  library exposing `check_caps`, `log_call`, `read_cache`,
  `write_cache`, `apply_override_or_fail`, `response_headers`,
  `ensure_indexes`, `address_hash`.
- `backend/routers/zillow_admin.py` — new admin-only
  `GET /api/zillow/usage/this-month` widget endpoint. Read-only
  aggregate; never touches the paid API.
- `backend/tests/test_zillow_rbac.py` **(new)** — 7 tests.

**Collections created** (idempotent + TTL indexes):
- `zillow_usage` — one row per counted call.
- `zillow_cache` — SHA-256 `address_hash` key, 30-day TTL.
- `zillow_audit` — `zillow_budget_override` events (and a
  future `zillow_cache_hit` event once Step 6/7 wire in).

**Caps enforced by role**:
- Tech: 20/day + 200/month per user.
- Admin: uncapped per-user, still subject to tenant budget.
- Super_admin: uncapped + `?override_budget=true` bypasses
  100 % tenant budget with an audit event.
- Default tenant budget: 1000/month; overridable via
  `tenant.zillow_monthly_budget`.

**Test results** — `pytest tests/test_zillow_rbac.py -v` →
**7 passed / 0 failed** in 10.30s. Each test seeds an isolated
per-test tenant.

**Preflight**: `bash /app/scripts/preflight.sh` → exit 0.

**Explicit deferrals (Option A boundary)**:
- Step 6 (web frontend chip + banner) — next session.
- Step 7 (mobile parity — 3 primary + 3 sub-screens) — next.
- Step 8 (RBAC swap on 5 endpoints, `require_zillow_access`
  helper in utils.py) — LAST, next session, gated on 6 + 7.

Fresh-session brief for Steps 6/7/8 persisted verbatim in
`memory/HANDOFF.md`.

---

## Phase 56.18 — Human-Readable Invoice Numbers (Feb 2026)

`INV-{YYYY}-{NNNNNN}` for invoices, `MINV-{YYYY}-{NNNNNN}` for
master invoices. Per-tenant, per-year, per-prefix atomic
sequence with idempotent backfill.

**Files touched:**
- `backend/services/invoice_numbering.py` **(new)** —
  `generate_invoice_number`, `assign_invoice_number_if_missing`,
  `assign_by_tenant_id`, `ensure_uniqueness_indexes`,
  `NUMBER_REGEX`. Uses `findOneAndUpdate($inc, upsert=True)` for
  the counter (concurrency-safe).
- `backend/routers/quotes.py` — number assignment on
  `POST /quotes` (when `doc_type=="invoice"`); immutability
  guard on `PUT /quotes/{qid}` (rejects any attempt to change
  `invoice_number`).
- `backend/routers/finances.py` — number assignment on both
  autobilling paths (manual `run_billing_plan` + daily
  scheduler `_fire_billing_plan`).
- `backend/routers/billing.py` — master invoice number
  assignment on `POST /master-invoices`.
- `backend/migrations/backfill_invoice_numbers.py` **(new,
  idempotent)** — orders by `created_at` ASC per tenant, skips
  already-numbered docs, syncs `invoice_number_sequences.next_seq`
  to `$max` so future generation never collides.
- `backend/tests/test_phase56_18_invoice_numbers.py` **(new,
  5 tests, all passing in 4.10s)**.
- `frontend/src/pages/invoices/InvoicesList.jsx` — new leftmost
  "Invoice #" column showing the number in a monospace cell
  (`data-testid="invoice-number-{id}"`).

**New Mongo collection**: `invoice_number_sequences` with unique
index `(tenant_id, year, prefix)`.

**Partial-unique indexes** added on the number fields:
- `quotes`: `(tenant_id, invoice_number)` unique where
  `invoice_number` exists.
- `master_invoices`: `(tenant_id, master_invoice_number)` unique.

**Backfill executed live** — aquaterra: **33 invoices** assigned
(`INV-2026-000001` → `INV-2026-000033`), 0 master invoices (none
existed). All other tenants: 0 invoices (empty).

**Backend tests** — 5/5 passed in 4.10s:
- `test_format_and_sequence` — sequential + regex + INV/MINV
  separate counters.
- `test_concurrency_no_dup` — 20 concurrent `asyncio.gather`
  calls all yield unique numbers.
- `test_assign_if_missing_is_idempotent` — helper never
  overwrites an existing `invoice_number`.
- `test_new_invoice_gets_number_and_is_immutable` — new
  `POST /quotes` returns a valid `invoice_number`; `PUT` with
  an override attempt returns 200 but the number is
  unchanged (defense in depth: Pydantic drops the unknown
  field + router's explicit strip).
- `test_backfill_spot_check` — every invoice in the aquaterra
  list has a valid `invoice_number` matching the regex.

**Preflight**: `bash /app/scripts/preflight.sh` → exit 0 (424
pre-existing dead-import WARNs; none new).

**Non-goals held**: no custom prefix per tenant, no historic
year override (backfill uses each invoice's own `created_at`
year), no manual invoice-number override in v1, no credit-note
numbering.

**Deferrals (called out honestly)**:
- **Master invoice list/detail column** — not shipped;
  `MasterInvoice.jsx` list rendering unchanged. Small
  follow-up.
- **Invoice detail header prominence** — the number appears in
  the detail response JSON but the JSX header layout for
  `InvoicesList` detail view (`InvoiceDetail`) wasn't updated
  in this ship. Backfill-safe deferral.
- **Invoice PDF header** — not touched in this ship. Requires
  updating the PDF template (`reportlab` code path) —
  deferred to 56.18-followup.
- **Search by invoice number** — deferred; the current
  search box searches by title/customer, will match `INV-…`
  strings if a user pastes one but there's no dedicated
  index/filter yet.
- **Mobile invoice list + detail** — deferred (no mobile
  changes in this ship).
- **Customer portal invoice display** — deferred.
- **Email notifications + Stripe checkout description** —
  deferred. Autobilling still fires correctly; the outgoing
  Stripe description will get the number in a followup.
- **Other 6 invoice-birth code paths** (grep for
  `db.quotes.insert_one` in `estimates.py`,
  `service_reports.py`, etc.) — not wired to
  `assign_invoice_number_if_missing` yet. The backfill
  migration is designed to be re-run periodically as a safety
  net for these until they're individually instrumented.

**Ship scope**: `git diff --stat HEAD` → 4 files changed / 23
insertions. Plus 3 new files (service, migration, tests).


---

## Phase 56.19 — Master Invoices 404 + RingCentral Diagnostics (Feb 2026)

**P0 hotfix session** — two urgent items resolved:

### 1. `/master-invoices` 404 → permanent aliases
Bookmarked pre-refactor URLs (`/master-invoices`,
`/master-invoices/new`, `/master-invoices/:id`) now redirect
via React Router `<Navigate>` to the current
`/invoices/master/*` paths. Added a small
`MasterInvoicesRedirect` component that preserves the `:id`
URL param when bouncing detail links (mirrors the
`CustomerServiceReportRedirect` pattern already in `App.js`).

Verified end-to-end via Playwright (admin login → hit each
legacy URL → URL rewrites, `MasterInvoicesList` renders).
Both `.preview` and `.host` hosts return 200 on the aliases.
Grep confirms no stale hardcoded links elsewhere.

### 2. RingCentral diagnostic logging
The RC outbound pipeline is currently broken due to invalid
OAuth client credentials on the user's account. Rather than
attempt live SMS testing, this ship instruments the failure
paths so the next credential rotation surfaces the real error.

- New `_capture_rc_error(exc)` helper extracts
  `exc.response.text()` (bytes-safe, ≤ 200 chars) into
  `{error_class, error_snippet}`. Never touches JWT/secret
  material.
- `POST /api/ringcentral/sms/send` — captures + logs
  `<class> :: <snippet>` and returns 502 with the diag body.
- `POST /api/ringcentral/subscription/register` — same pattern.
- `_fetch_telephony_session_detail` — previously logged only
  the exception class; now logs the RC body snippet too.
- `GET /api/ringcentral/health` — was returning green when
  RC env vars were present, even if auth was broken. Now
  actually runs `platform.get('/restapi/v1.0/account/~/extension/~')`
  when outbound is enabled; on failure returns 503 with
  `rc_auth_ok=false` + `rc_auth_error={error_class, error_snippet}`.

  **Live diagnostic** (as of ship): `error_class=ApiException,
  error_snippet="HTTP 401 invalid_client · Invalid client
  application [eZWHonfT7FQcdQKiw0Xcvw] · errorCode OAU-153"`
  — the actionable answer the user needs to rotate creds.

### 3. Unmatched-communication notification href
All four unmatched-kind bells (call, SMS, fax, voicemail)
previously linked to `/admin/unmatched-communications`, which
was never a frontend route. Fixed the notification generator
to emit `/notifications?kind=<specific_kind>` per kind, and
added an App.js safety-net alias for any pre-56.19 rows still
in Mongo.

Updated `test_phase55_1_fixes.py::TestUnmatchedRC` assertion
to match the new href (3/3 passing).

### Testing status
- `pytest tests/test_phase55_1_fixes.py::TestUnmatchedRC -q` → 3 passed
- `bash scripts/preflight.sh` → exits 0
- Playwright verification of 3 master-invoice legacy URLs → all pass
- Curl verification of RC health (503 + diag body), SMS send
  (502 + diag body), simulate-inbound (new href) — all pass

### Files touched (this session)
- `frontend/src/App.js` — 1 helper, 3 master-invoice aliases,
  1 unmatched-communications alias
- `backend/routers/ringcentral.py` — helper + health + 4 diag
  handlers + 4 href fixes
- `backend/tests/test_phase55_1_fixes.py` — 1 assertion update

### Deferred (unchanged from prior sessions)
- Phase 56.9b Steps 6/7/8 (Zillow web + mobile UI + RBAC swap)
- Phase 56.18-followup (master invoice column etc.)
- Dead-import static WARN (424, pre-existing tech debt)
- Live SMS send (blocked on user rotating RC OAuth credentials
  based on the OAU-153 signal above)


---

## Phase 56.9b — Steps 6+7+8 · Zillow-for-Techs SHIPPED (Feb 2026)

Backend Steps 1–5 (guardrail infra) landed in the prior session.
This ship wires the guardrail into user-visible surfaces and
performs the RBAC swap, completing Option A end-to-end.

### What changed

- **Step 8 (Backend RBAC):** New `require_zillow_access` in
  `utils.py` (super_admin + admin + technician). Swapped 4
  property endpoints + 1 D2D endpoint from `require_admin`.
  `/d2d/report` stays admin-only per spec.
- **Guardrail wiring:** Paid endpoints (`/property/lookup`,
  `/d2d/sold-leads`) now run: `check_caps` → `apply_override_or_fail`
  → 429 (with `reason` + `reset_at`) OR cache-hit fast-path OR
  paid provider call → `write_cache` + `log_call` → refresh caps
  → JSON body + `X-Zillow-*` headers.
- **New endpoint:** `GET /api/zillow/me/usage` returns the caps
  shape for the chip to render.
- **Step 6 (Web):** New `ZillowUsageChip` component
  (auto-polls `/zillow/me/usage`, yellow ≥80%, red at 100% or
  budget exhausted, inline "Ask admin for more" banner). Mounted
  on all 4 Zillow-backed pages.
- **Step 7 (Mobile):** New `ZillowAccess` route guard (mirrors
  backend RBAC — replaces `AdminOnly` on `virtual-bid.tsx` to
  unlock techs). New `ZillowUsageChip` + `ZillowRateLimitedBanner`
  mobile components mounted in the header `right` slot on all 3
  primary Zillow-backed screens.

### Verification (all 5 required curl cases pass)

- Tech successful lookup → 200 with data + `usage` fields + `X-Zillow-*` headers
- Tech at daily cap → 429 `{error:"tech_daily_cap", reset_at:...}`
- Cache hit → 200 with `_cached: true`, tech counter unchanged, `zillow_cache_hit` audit row emitted
- Tenant near-budget → 200 with `X-Zillow-Budget-Warning: 1` + `budget_warning: true` in body
- Super_admin `?override_budget=true` at exhaustion → 200 with `override_audit_id` in body + `zillow_budget_override` audit row in Mongo

Screenshot of tech `mike@aquaterra.com` on `/property-lookup`
shows the chip **"Zillow: 3/20 today · 3/200 mo"** rendered —
previously this surface returned 403 to techs.

### Rollout

- Zero migration required (indexes already created lazily by
  `services.zillow_rate_limit.ensure_indexes` in Phase 56.9b Option A).
- 56.9b Option A is now **complete**. All Zillow-facing surfaces
  are exposed to technicians under enforced per-user (20/day, 200/mo)
  and per-tenant ($1000/mo default) rate limits, with super_admin
  break-glass audit-logged override.

### Deferred (unchanged from prior sessions)

- Phase 56.18-followup (master invoice column, detail header,
  PDF header, search-by-number, mobile invoice UI, email/Stripe
  description hooks, 6 remaining invoice-birth code paths)
- Dead-import cleanup pass (424 static WARN)
- Live SMS send (blocked on user rotating RC OAuth credentials
  per the OAU-153 signal captured in Phase 56.19)
- T1–T6 calculators (queued, not started)
- 56.13d / 56.14 / 56.15 (paused by user)


---

## Phase T1 + T2 — Pool Calculators (Feb 2026)

Small self-contained ship. 5 stateless pool math calculators
mounted on a new tabbed web page under the tech tools hub.

### What changed

- **Backend:** New `routers/pool_calculators.py` with 5 POST
  endpoints (LSI, Volume, Salt, Turnover, Heater Size). Pure
  math — no DB writes. Custom local RBAC dep
  `require_tech_or_above` (super_admin | admin | technician;
  customers 403).
- **Web:** New `pages/tech/PoolCalculators.jsx` (~400 LOC) with
  a tabbed panel per calculator, each with per-tab local state,
  a Compute button, and a copy-to-clipboard result box. Route
  `/tech/tools/calculators` (mounted in `App.js`). Tile added to
  `ToolsHub.jsx` under both tech "On the Job" and admin "Tools"
  sections.
- **Tests:** `backend/tests/test_phase_t1_t2_calculators.py`
  — 22 tests, 22 passed, 0.96s.

### Formulas (canonical reference)

- **LSI:** `pH + tf + cf + af − tds_const` where tf is a linear
  interpolation of the 10-row industry temperature table
  (matches the mobile calc verbatim), `cf = log10(CH) − 0.4`,
  `af = log10(max(1, TA − cya_adj))`, `tds_const = 12.2` if
  TDS ≥ 1000 else 12.1. Interpretation: -0.3…+0.3 balanced,
  <-0.3 corrosive, >+0.3 scaling.
- **Volume (gal):** rect `L·W·d·7.48`, oval `L·W·d·5.9`,
  circle `π·r²·d·7.48`, freeform `L·W·d·7.0`. Accepts avg_depth
  or (shallow + deep) averaged.
- **Salt (lbs):** `gal · (target − current) / 120000`. Over
  target returns 0 lbs + drain-and-refill estimate.
- **Turnover (hrs):** `gal / (GPM · 60)`. Code caps: spa 0.5h,
  commercial ≤4ft 4h, commercial >4ft 6h, residential
  informational only.
- **Heater (BTU/hr):** `gal · 8.33 · ΔT / heat_up_hours`
  (default 24h). Cost varies by heater_type: gas (100k BTU/therm
  × 0.82 eff at $1.50/therm), heat_pump (COP 5.0 at $0.15/kWh),
  electric (COP 1.0 at $0.15/kWh), solar ($0 operating).

### Verification

- **5 curl known-answer cases** all match spec-predicted values
  (LSI 0.03 balanced · Volume 29,920 gal · Salt 116.7 lbs · Turnover
  5.56 hours · Heater 152,717 BTU + $63.22/mo).
- **22/22 pytest** passing in 0.96s. Coverage includes RBAC
  (tech 200 / customer 403), boundary invalids (422), and code-
  compliance branches (residential/commercial shallow/commercial
  deep/spa).
- Playwright: `/tech/tools/calculators` renders 5 tabs; LSI
  compute produces expected 0.03 balanced with copy button.

### Deferrals

- Mobile parity for Turnover + Heater — mobile has 4 calcs
  already (Dosing, Volume, Salt, LSI); adding the 2 new ones is
  queued for a mobile-parity sweep.
- Attach calculator result to customer service report — deferred.
- Per-user saved-calculation history — deferred.


---

## Phase 56.20 — Auto End-of-Visit Email + Calculator Attach (Feb 2026)

Two-item bundle shipped together — same code area, related UX.

### What changed

**Auto email:**
- New service `backend/services/auto_visit_email.py` — renders a
  customer-safe visit summary (subject, HTML, plain-text), dispatches
  via Resend, logs every attempt to `db.outbound_emails`. Non-blocking
  wrapper around the send.
- Hook inserted into `POST /api/jobs/{jid}/service-report/submit`
  right after the invoice-generation block.
- Idempotency on `(kind=visit_summary, service_report_id,
  customer_id)`. Missing key → `status: "not_sent_missing_key"`
  (no crash). Resend error → `status: "failed"` + error snippet
  captured in the audit row.
- Tenant-level opt-in (`db.tenants.settings.auto_visit_email.enabled
  = false` by default).
- 3 new admin endpoints: `GET/PUT /api/settings/auto-visit-email`
  + `POST /api/settings/auto-visit-email/preview` (renders using the
  tenant's most recent submitted report so admin can eyeball before
  turning the toggle on).
- New admin page `/admin/settings/auto-visit-email` with 4 controls
  + live HTML preview.

**Calculator attach bundle** (from the prior ship's suggestion):
- New endpoint `POST /api/service-report/attach-note` — appends a
  tool-generated plain-text summary to a tech's open service report's
  `internal_notes`. Multi-open-reports case returns a picker list.
  Audit row written to `db.service_report_notes_audit`.
- Web ResultBox in the Pool Calculators page gains an "Attach"
  button next to Copy; posts the same plain-text summary the Copy
  button uses. Toast surfaces the status inline.

### Verification (all pass)

- **11/11 pytest** (`test_phase56_20_auto_email.py`) in 1.19s.
- **Live curl:** settings roundtrip, preview render, send-with-key
  (Resend test-mode error captured verbatim in audit row),
  idempotency (2nd call → skipped), missing-key fallback (row
  written with status `not_sent_missing_key` and full payload).
- **Calculator attach:** direct `internal_notes` append + audit row
  in `service_report_notes_audit` confirmed via Mongo query. Multi-
  open-reports branch surfaces the picker list.
- **Playwright:** admin settings page renders, preview button
  produces the HTML preview inline. Tech Pool Calculators page shows
  Copy + Attach buttons stacked on the ResultBox.

### Redaction guardrails (verified)

- `internal_notes` string absent from both `html` and `text` output.
- Photos tagged `internal`, `issue`, or `private` are filtered
  before render.
- Cost/pricing data never included (schema doesn't surface it in the
  customer-facing redacted payload).
- Regex safety scrub applied to `customer_notes` to strip accidental
  `internal_notes:` leaks even if a tech types the label into the
  customer field.

### Rollout notes

- Feature ships **off by default** per tenant. Admin must open
  `/admin/settings/auto-visit-email`, preview, then toggle on.
- Resend key currently in the pod env is a **test-mode** key that
  can only send to the account owner. Production customer sends
  will `status: "failed"` until a rotated key or verified sending
  domain lands. All failures are captured in
  `db.outbound_emails.find({status:"failed"})` with the exact
  Resend error snippet — no redeploy needed to debug.

### Deferrals

- Multi-open-report picker UI on the calculator Attach button
  (currently returns a toast; small ~30-min follow-up).
- Mobile parity: admin settings + attach button on mobile
  calculators — queued for a mobile-parity sweep.
- Resend delivery-event webhooks (opens/clicks/bounces) — deferred.
- Rich HTML templates beyond basic layout — deferred.


---

## Phase T3 — Business Pricing Tools (Feb 2026)

Three admin-only pricing tools shipped as one tabbed page under
`/admin/tools/pricing`.

### What changed

- **Backend:** Extended `routers/pool_calculators.py` with 3 new
  endpoints (`/service-in-cost`, `/cost-per-pool`, `/service-price`).
  All gated by a local `_require_admin` dep (super_admin + admin only,
  techs and customers get 403). Pricing constants live in
  `PRICING_DEFAULTS` and can be overridden per-tenant via
  `db.tenants.settings.pricing_defaults`.
- **Web:** New `pages/admin/BusinessPricingTools.jsx` (~430 LOC)
  with 3 tabs matching the endpoints. Route
  `/admin/tools/pricing` wrapped in `<AdminOnly>`. Portfolio scan
  tab has color-coded outlier flags + filter + CSV export. Price
  recommender surfaces a peer-median comparison for sanity.
- **Tests:** 11/11 passing (`test_phase_t3_pricing_tools.py`).
- **RBAC:** Confirmed 403 for tech + customer roles across all three
  endpoints.

### Verification

- **T3.1 spec case** (20000 gal weekly, 45 min @ $35/hr, 1.25 overhead,
  40% margin, standard 3-chem load) → in-cost $42.50, min price
  $59.50, annualized $3,094.
- **T3.2** aggregated 3 aquaterra customers, computed 64.6% median
  margin, flagged 1 low-margin (Aimee 15%) + 2 high-margin (Whitmore
  91.1%, Jennifer 64.6%).
- **T3.3 spec case** (20000 gal weekly saltwater + heater) →
  **$165.00** exactly (base 135 + salt 15 + heater 10 + gallons 5).

### Deferrals

- **T3-followup:** `pricing_defaults` editor UI (backend already
  supports; needs ~30-min form under `/admin/settings`).
- Distance zone editor UI.
- Historical margin trend chart on Cost per Pool.
- Mobile parity for pricing tools (admin-only feature; likely never
  needed on mobile).


---

## Phase T5 — Business Analysis Tools (Feb 2026)

Two admin-only business analysis tools. Extends the calculators
router with 2 new endpoints; new tabbed page at
`/admin/tools/analysis`.

### What changed

- **Backend:** Route Valuation (3-factor mix of density, churn,
  contract length → lerped between 4x-8x monthly-revenue multiples)
  and Pay Model Comparator (hourly vs per-pool vs route-buy with
  side-by-side margin + tech pay). Both share the same tenant-
  override pattern as T3 (`route_valuation_defaults` +
  `pay_model_defaults` under `tenant.settings`).
- **Web:** New `BusinessAnalysisTools.jsx` (~330 LOC) with 2 tabs.
  Route Valuation surfaces an industry benchmark bar ($1500-$3500
  per-customer band). Pay Model Compare highlights winner cells
  green in the table.
- **Tests:** 10/10 passing.
- **RBAC:** Verified 403 for tech + customer on both endpoints.

### Verification

- **T5.1 spec** (100 cust, $150/mo, dense, 5% churn, 24mo):
  multiple **7.3x**, valuation **$109,500**, per-customer **$1,095**
  (all within spec ±5%).
- **T5.2 spec** (40 cust, 45min, $135/mo, weekly):
  hourly **$2,857.80/mo**, per_pool **$3,117.60/mo**, route_buy
  **$3,510.00/mo** (all within spec ±10%). Recommendation +
  breakeven surfaced correctly.

### Deferrals

- Sensitivity sliders on Route Valuation.
- Route-comparator (two hypothetical routes side-by-side).
- Historical valuation snapshot audit.
- Mobile parity (admin-only feature).

