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
- **P0 · Phase 12** — Admin/Settings polish
- **P1 · Phase 13** — Full E2E parity testing

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
