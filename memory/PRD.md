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

## Prioritized backlog
- **P0 · Phase 7** — AI Marketing Studio (see `/app/memory/phase-7-plan.md`)
- **P1 · Phase 8** — SEO Studio + WordPress + GBP
- **P1 · Phase 9** — AI Employees / AI Chat / access settings + RingCentral
- **P1 · Phase 10** — D2D Sales
- **P2 · Phase 11** — Landscape AI · CAD · Measure · Virtual Bid
- **P2 · Phase 12** — Admin/Settings polish
- **P2 · Phase 13** — Full E2E parity testing

## Known gaps / non-blockers
- Leaflet maps for `/dispatch/map` and `/schedule/map` (deferred)
- `EMERGENT_LLM_KEY`, `RESEND_API_KEY`, `TWILIO_ACCOUNT_SID` missing — degrades gracefully
- Route optimization uses greedy TSP (AI upgrade planned)
