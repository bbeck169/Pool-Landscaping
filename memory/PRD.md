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

