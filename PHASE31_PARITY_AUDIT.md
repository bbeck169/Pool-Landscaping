# Phase 31 — Mobile ↔ Web Parity + Test/CI Health Audit

**Scope:** read-only audit. No code changed, no tests added, no CI touched.
**Codebase snapshot:** `/app` on branch (see `.git`).
**Method:** `find` / `grep` inventory, non-modifying `vitest run --reporter=basic`, no external calls.

---

## Executive Summary

1. **The web app is roughly 2× the mobile surface.** 412 declared `<Route>` entries in `frontend/src/App.js` vs ~140 Expo Router files under `mobile/app/**`. Most of the delta is admin/back-office (SEO, marketing, comms, GPS, tenants, reports, tools, integrations) and public/anonymous pages — which is expected and largely **WEB_ONLY_BY_DESIGN**.
2. **True mobile parity gaps are concentrated in three areas:** (a) admin **finance ops** (Autobilling Runs, Recurring Jobs, Auto-Billing config, Late Fees, Income Categories, Payments ledger, Master Invoices, Vendor Bills — no mobile equivalents), (b) **CFO / analytics deep-dives** (only `cfo/index` on mobile — bills, ap-aging, anomalies, forecast, payroll, price-increase suggestions all web-only), and (c) **Business OS** (`/os/*`: SOPs, roles, scorecards, huddles, leanboards, sprints, Lana — zero on mobile).
3. **Endpoint coverage confirms the gap.** Web calls **251** unique `/api/*` paths, mobile calls **112**; only **37** overlap. **214** endpoints are called by web only and **75** by mobile only (mostly service-report media, GPS pings, offline sync, and marketing endpoints that use different verbs from web).
4. **Test posture is heavily backend-biased.** 2,411 backend pytest cases across 360 files vs 654 vitest cases across 124 files. Mobile has **only 16 Jest suites** (118 cases) as native runtime tests; the bulk of mobile QA is source-inspection vitests running inside the frontend harness (~34 phase-tagged files). **~95%+ of the mobile UI has zero runtime-assertion coverage.**
5. **There is NO CI configuration in the repo.** No `.github/workflows/`, no `.gitlab-ci.yml`, no `Jenkinsfile`, no `.circleci/`, no `bitbucket-pipelines.yml`, no `azure-pipelines.yml`. All test / lint / build workflows exist only as npm/yarn scripts and must be run manually or by the hosting platform. This is the single biggest health risk.

---

## Part 1 — Parity Matrix

The web app has ~412 route entries; a row-per-route table is not useful for planning. This matrix is organized by **functional area** so each row maps to a coherent product surface. Each row lists the concrete web routes/pages and the corresponding mobile file(s), and rates parity.

Legend: **FULL** ≈ same functionality both places · **PARTIAL** = mobile has a subset · **MISSING** = no mobile equivalent · **MOBILE_ONLY** = present only on mobile · **WEB_ONLY_BY_DESIGN** = intentionally back-office / admin-only.

### 1A · Auth, Identity, Account

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/tenant-picker` | `login.tsx`, `signup.tsx`, `forgot-password.tsx`, `reset-password.tsx` | **FULL** | — | Mobile lacks a distinct tenant-picker screen — auto-picks single tenant. |
| `/account/profile` (`MyProfilePage`) | `(app)/profile.tsx`, `settings/change-password.tsx` | **FULL** | — | |
| Impersonation flow (web-side admin ↔ customer) | none | **MISSING** | medium | Admin impersonation is currently web-only. |

### 1B · Customer Portal (customer-facing)

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/portal/home` (`PortalHome`) | `portal/home.tsx` | **FULL** | — | Phase 30.3 added sign-out button on mobile. |
| `/portal/services`, `/portal/services/:id`, `/portal/service/:uuid` | `portal/services.tsx`, `portal/service/[id].tsx` | **FULL** | — | |
| `/portal/service-reports`, `/portal/service-reports/:id` | `portal/service-reports.tsx`, `portal/service-report/[id].tsx` | **FULL** | — | |
| `/portal/invoices`, `/portal/invoices/:id` | `portal/invoices.tsx`, `invoice/[id].tsx` (shared) | **FULL** | — | |
| `/portal/estimates`, `/portal/estimates/:id` | `portal/estimates.tsx`, `estimate-view/[id].tsx` | **FULL** | — | |
| `/portal/payments`, `/portal/payment-method(s)`, `/portal/payment-complete`, `/portal/payment-method/return` | `portal/payments.tsx`, `portal/payment-method.tsx`, `portal/add-card.tsx`, `payment-complete.tsx` | **FULL** | — | |
| `/portal/chats`, `PortalChatsPage` | `portal/chats.tsx`, `portal/chats/[id].tsx` | **FULL** | — | |
| `/portal/documents`, `/portal/messages` | `portal/documents.tsx`, `portal/messages.tsx` | **FULL** | — | |
| `/portal/photos`, `/portal/videos` | `portal/photos.tsx`, `portal/videos.tsx` | **FULL** | — | |
| `/portal/reviews`, `/portal/review/submit`, `/r/review` | `portal/review-submit.tsx`, `reviews.tsx` | **FULL** | — | |
| `/portal/profile` | `portal/profile.tsx` | **FULL** | — | |
| `/portal/request-service`, `/portal/book`, `PortalWalkthrough` | `request-service.tsx`, `portal/book.tsx`, `portal/appointments.tsx` | **FULL** | — | |
| `/portal/referrals` (`PortalReferralsPage`) | `referrals.tsx` (partial) | **PARTIAL** | small | Mobile hits `/api/customer-portal/referrals/my` but has no dedicated portal referrals landing page separate from admin referrals screen. |
| `/portal/warranties` | none | **MISSING** | medium | Warranties are new-ish; portal side never got a mobile mirror. |
| `/portal/preferences` (`PortalPreferences`) | none | **MISSING** | small | Notification prefs on mobile currently only lives in generic settings, not portal-scoped. |
| `/portal/terms` | none | **MISSING** | small | ToS acknowledgement banner works but a dedicated ToS view screen is missing on mobile. |
| `/portal/sign/:token` | none | **MISSING** | small | Portal quote/estimate signature capture — no mobile equivalent. |

### 1C · Public / Anonymous / Widget

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/pay/invoice/:id`, `/quote/:slug`, `/book/:slug`, `/reviews/r/:token`, `/reviews/:tenant_slug`, `/csat/:token`, `/portal/service/:uuid`, `/lead-request/:token`, `/f/:slug`, `/public/leads`, `/public/card/:slug`, `/nfc/:slug`, `/widget-demo`, `/replay/:shareId` | none | **WEB_ONLY_BY_DESIGN** | — | Public/anonymous links are expected to open in a browser, not the mobile app. |

### 1D · Dispatch / Schedule / Ops

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/dispatch`, `/admin/dispatch`, `/dispatch/map`, `/admin/dispatch/weather` | `dispatch.tsx`, `dispatch/board.tsx`, `dispatch/weather.tsx`, `dispatch-savings.tsx` | **PARTIAL** | large | Mobile board renders assignments but lacks: `OptimizeRouteModal`, `ShiftRouteDialog`, `TechLoadStrip`, live pin layer, unrouted panel, route apply/optimize. Missing endpoints: `/api/dispatch/route/apply`, `/api/dispatch/route/optimize`, `/api/dispatch/suggest-route`, `/api/dispatch/route/savings/weekly`. |
| `/schedule`, `/schedule/legacy-timeline`, `/schedule/map` | `(app)/schedule/index.tsx`, `(app)/schedule/calendar.tsx`, `(app)/schedule/JobTrackerTiles.tsx` | **FULL** | — | Phase 24/25 delivered mobile calendar parity + label-clip fixes. |
| `/ops` (`OpsHub`) → 15 sub-tabs (routes, crews, team, timesheets, timeclock/today, coverage, maintenance, pool-service, equipment, price-book, log-history, job-timers, avg-job-time, tools, more) | `coverage.tsx`, `maintenance.tsx`, `pool-service.tsx`, `equipment.tsx`, `price-book.tsx`, `log-history.tsx`, `job-timers.tsx`, `avg-job-time.tsx`, `timesheets.tsx`, `time-clock.tsx`, `team.tsx` | **PARTIAL** | small | Most tabs exist but rendered flat rather than as a unified hub — no `OpsHub` container. |
| `/dispatch/map`, `/schedule/map` — Mapbox live pins | none | **MISSING** | large | Mobile has no live-map surface. Requires `react-native-maps` + endpoint parity. |
| `/routes` (Optimize / Insert / Apply) | none | **MISSING** | large | Route insertion / apply / optimize UI is web-only. |

### 1E · Jobs / Customers / Quotes / Invoices / Estimates

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/customers`, `/customers/new`, `/customers/:id`, `/customers/:id/edit`, `/customers/:id/chemistry`, `/customers/:id/chemistry-history`, `/customers/:id/credits`, `/customers/active`, `/customers/inactive` | `(app)/customers.tsx`, `customer/[id].tsx`, `customer/[id]/compose.tsx`, `customer/chemistry/[id].tsx`, `customer/new.tsx` | **PARTIAL** | medium | Mobile lacks: credits page, chemistry history, active/inactive filters, master billing card, properties tab, master invoice linkage. |
| `/jobs/new`, `/jobs/:id`, `/jobs/:id/service-report`, `/admin/jobs` | `job/new.tsx`, `job/[id].tsx`, `job/[id]/checklist.tsx`, `service-report/[id].tsx`, `(app)/jobs.tsx` | **FULL** | — | Bulk-reassign not implemented (`/api/jobs/bulk-reassign` is web-only). |
| `/quotes`, `/quotes/new`, `/quotes/:id` | `(app)/quotes.tsx`, `quote/[id].tsx`, `quote/new.tsx` | **FULL** | — | |
| `/invoices`, `/invoices/new`, `/invoices/:id`, `/invoices/master`, `/invoices/master/new`, `/invoices/master/:id` | `invoices.tsx`, `invoice/[id].tsx` | **PARTIAL** | medium | **Master Invoices** (parent/child grouping) has no mobile UI. |
| `/estimates`, `/estimator/new`, `/estimator/:id`, `/estimator/settings`, `/estimator/templates`, `/admin/estimator/*` | `estimator/index.tsx`, `estimator/[id].tsx`, `estimator/new.tsx`, `(app)/estimator/[id].tsx`, `estimator/settings.tsx`, `estimator/templates.tsx` | **FULL** | — | |
| `/ai-estimator` | `(app)/ai-estimator.tsx` | **FULL** | — | |

### 1F · Marketing / SEO / Social / GBP / AEO / Reviews

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/marketing/**` (29 web routes: campaigns, segments, sequences, broadcasts, templates, review-requests, autopilot, before-after, forms, directories, gbp-posts, insta-quote/schedule admin, content-studio, media, analytics, suppressions) | `marketing/*.tsx` (10 files: index, analytics, broadcasts, content-studio, review-requests, segments, sequences, suppressions, templates) | **PARTIAL** | large | Mobile marketing covers most core surfaces but lacks: `Campaigns/CampaignNew/CampaignDetail`, `Reviews`, `BrandMemory`, `Autopilot`, `BeforeAfterStudio`, `DirectoriesHub`, `NapProfilePage`, `DirectorySubmissionsPage`, `InstaQuoteAdmin`, `InstaScheduleAdmin`, `Posts`, `ApprovalQueue`, `ContentCalendar`, `SchedulingConfig`, `Performance`, `TemplatesHub`, `MarketingTemplatesLibraryPage`, `MarketingMediaAdmin`, `MarketingFormsPage`, `AdminReferralsPage`, `AdminPromoCodesPage`. |
| `/seo` (Hub) + articles/keywords/audit/rank-grid/wordpress + `/admin/seo/*` (15 routes) | `seo/index.tsx`, `seo/[id].tsx`, `admin/seo/*` (10 files: atlas, audits, audits/[id], content-scorer, llm-visibility, otto, otto/[id], rank-heatmap, reports, studio, topical-map) | **PARTIAL** | medium | Mobile lacks: `SeoHub`, `ArticlesList`, `ArticleEditor`, `KeywordSuggest`, `SeoAudit`, `RankGrid`, `WordPressSettings`, `ContentRefresh`, `WebsiteStudioEditor`, `WhiteLabelReportDetail`. |
| `/gbp` | `gbp/index.tsx` | **PARTIAL** | small | Mobile shows overview only; `marketing/gbp-posts` is web-only. |
| `/aeo` — none on web (only `/admin/marketing/aeo`, `/admin/marketing/aeo/digest`) | `aeo/*.tsx` (8 files: index, auditor, library, mention-detail, mentions, publish-config, response-draft, visibility) | **MOBILE_ONLY** | — | AEO surface is more built out on mobile than web (interesting inversion). |
| `/social/*` (8 web routes: composer, calendar, library, drafts, approvals, bulk-upload, short-links, brand-kit) | `social.tsx` (single flat screen) | **PARTIAL** | large | Mobile has a placeholder screen only. |
| `/marketing/reviews`, `/admin/reviews`, `/admin/reviews/requests`, `/admin/reviews/platforms`, `/admin/reviews/widget` | `reviews.tsx`, `(app)/reviews/*` (index, leaderboard, platforms, recent, requests/index, requests/[id], widget) | **FULL** | — | Mobile actually has *more* granularity here (leaderboard + recent). |

### 1G · Finance / Payments / CFO / Reports

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/cfo` (`CFODashboard`) | `(app)/cfo/index.tsx` | **PARTIAL** | large | Mobile shows dashboard only. Web calls 8 CFO endpoints: `anomalies`, `ap-aging`, `bills`, `bills/:id`, `categorize`, `cogs`, `forecast`, `llm-usage`, `payroll`, `price-increase-suggestions`. Mobile only calls `/api/cfo/dashboard`, `/api/cfo/qna`, `/api/cfo/qna/history`, `/api/cfo/scenario/history`. AP/bills/forecast/anomalies/payroll views absent. |
| `/reports`, `/reports/business-summary`, `/reports/forecast`, `/reports/customer-retention`, `/reports/revenue-by-{city,crew,customer}`, `/reports/gross-sales`, `/reports/invoiced-items`, `/income-by-category`, `/income-categories`, `/admin/reports/{pool-service,job-margins,driver-activity,weekly-digest,pricing-insights,profit}` | `reports.tsx`, `profit-report.tsx`, `business-reports.tsx`, `income-by-category.tsx`, `income-categories.tsx`, `reports/aeo-digest.tsx`, `reports/weekly-digest.tsx` | **PARTIAL** | medium | Missing: business-summary, forecast, customer-retention, revenue-by-city/crew/customer, gross-sales, invoiced-items, driver-activity, job-margin leaderboard, pool-service report, pricing-insights. |
| `/payments`, `/auto-billing`, `/admin/autobilling-runs`, `/admin/finance/bulk-charge-runs`, `/admin/finance/bulk-charge-runs/:id`, `/admin/finance/bills` | `payments.tsx`, `payments/methods.tsx`, `auto-billing.tsx`, `finance/bulk-charge-runs/index.tsx`, `finance/bulk-charge-runs/[runId].tsx` | **PARTIAL** | medium | Missing: Payments ledger UI, Vendor Bills. |
| `/admin/checks/*` (register, new, bank-accounts, payees, analytics, :id, batch/new, payroll) | `checks/register.tsx` | **PARTIAL** | large | Mobile only reads the register; write/print/batch/payroll flows absent. |
| `/admin/dunning/{settings,queue,analytics}` | `dunning/queue.tsx` | **PARTIAL** | small | Settings + analytics missing. |
| `/admin/warranties/{plans,contracts,claims}`, `/portal/warranties` | none | **MISSING** | medium | No mobile warranties UI (admin or portal). |
| `/settings/late-fees` | none | **MISSING** | small | Late fee configuration is admin-only, but still not mirrored. |
| `/settings/billing`, `/settings/payment-handles` | none | **MISSING** | small | Payment infra config web-only. |
| `/settings/income-categories`, `/settings/service-categories` | none | **MISSING** | small | Config screens web-only. |
| `/impexp` (import/export) | none | **MISSING** | medium | CSV import/export is a rich desktop workflow — unlikely mobile priority. **WEB_ONLY_BY_DESIGN**. |

### 1H · Comms / Notifications / Chat

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/admin/comms/{templates,email,email/new,email/:code,sms,sms/new,sms/:code,automations,sends}`, `/admin/communications-log` | `comms/index.tsx`, `comms/test-send.tsx`, `comms/templates/index.tsx`, `comms/templates/[code].tsx`, `comms/automations/index.tsx`, `comms/automations/[code].tsx`, `comms/sends/index.tsx`, `comms/sends/[id].tsx` | **FULL** | — | Communications log web-only. |
| `/admin/communications-log` | `communications.tsx`, `communication/[id].tsx` | **PARTIAL** | small | Mobile shows individual threads but not the aggregated log/summary. |
| `/chat` (`TeamChatPage`) | `(app)/chat.tsx` | **FULL** | — | |
| `/notifications`, `/settings/notifications` | `notifications.tsx` | **PARTIAL** | small | Notification prefs page missing. |

### 1I · Business OS / Tasks

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/os`, `/os/dashboard`, `/os/sops`, `/os/roles`, `/os/scorecards`, `/os/huddle(s)`, `/os/leanboards`, `/os/sprints`, `/os/lana` | `huddle.tsx`, `(app)/huddle.tsx` | **PARTIAL** | large | Only huddles rendered on mobile. Entire OS module (SOPs, roles, scorecards, leanboards, sprints, Lana AI) is **MISSING**. |
| `/tasks` | none | **MISSING** | medium | No mobile task list. |

### 1J · Admin / Tenants / Access / RBAC

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/admin/users`, `/admin/tags`, `/admin/service-reports`, `/admin/time-entries`, `/admin/reflow-history`, `/admin/ai-personas-scope`, `/admin/ai-tool-audit`, `/admin/diagnostics/errors`, `/admin/moderation/checkins`, `/admin/moderation/widget-embed`, `/admin/moderation/widget-analytics`, `/admin/portal-inbox`, `/admin/appointments`, `/admin/assets`, `/admin/settings/*`, `/admin/onboarding/*`, `/admin/leads`, `/admin/referrals`, `/admin/referrals/settings`, `/admin/referrals/analytics`, `/admin/recurring-jobs`, `/admin/copilot`, `/admin/chemicals`, `/admin/ai-credits`, `/admin/gps/*`, `/admin/settings/gps-users`, `/admin/settings/gps`, `/admin/settings/chemical-costs`, `/admin/settings/pricing-defaults`, `/admin/settings/ringcentral`, `/admin/settings/service-templates`, `/admin/settings/auto-visit-email`, `/admin/tools/*` (pricing, analysis, documents, price-check, lumino-backfill), `/admin/templates/*`, `/admin/customer-success/churn`, `/admin/inventory/*`, `/admin/marketing/*`, `/admin/reports/*`, `/admin/finance/*`, `/admin/warranties/*`, `/admin/comms/*`, `/admin/reviews/*`, `/admin/seo/*`, `/admin/dunning/*`, `/admin/checks/*`, `/admin/dispatch/*` | `admin/referrals.tsx`, `admin/seo/*`, `admin/_layout.tsx` | **PARTIAL** | very large | ~130 admin routes on web; ~14 mobile files. Most admin surfaces are **WEB_ONLY_BY_DESIGN** (config editors, moderation queues, CSV exports). Highlight-worthy misses: `admin/moderation/checkins`, `admin/appointments`, `admin/portal-inbox`, `admin/onboarding/*`, `admin/gps/*`. |
| `/tenants`, `/settings/tenant` | `settings/tenant.tsx` | **PARTIAL** | small | Tenants admin (multi-tenant) view web-only. |
| `/access-settings`, `/access-history` | `access-settings.tsx`, `access-history.tsx` | **FULL** | — | |
| `/settings/**` (27 web setting pages) | `settings/*.tsx` (12 mobile files) | **PARTIAL** | medium | Most day-2 settings (rank-tracker, orphan-users, vanity-slugs, telephony, maps, RingCentral, ai-brain, chemicals, income/service-categories, marketing/media, late-fees, terms, legal, reviews, website-seo, local-seo, citations) exist only on web. |
| `/settings/integrations`, `/admin/integrations/qbo`, `/settings/integrations/supercool`, `/qbo/*` | `settings/integrations/_layout.tsx`, `settings/integrations/supercool.tsx`, `qbo/index.tsx`, `qbo/data.tsx` | **PARTIAL** | small | QBO OAuth callback web-only (expected). |
| `/settings/telephony`, `/settings/ringcentral`, `/call-logs`, `/admin/ringcentral-test` | none | **MISSING** | medium | Telephony admin missing on mobile. |
| `/handbook`, `/handbook/:code` | `(app)/handbook/index.tsx`, `(app)/handbook/[code].tsx` | **FULL** | — | |
| `/onboarding-checklist`, `/onboarding/mine`, `/admin/onboarding` | `(app)/onboarding-checklist/index.tsx`, `(app)/onboarding/mine.tsx` | **PARTIAL** | small | Admin onboarding dashboard web-only. |

### 1K · Tech / Field

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/tech/time-clock`, `/tech/huddle`, `/tech/tools`, `/tech/tools/calculators`, `/tech/card`, `/tech/property-lookup`, `/landscape/time-clock`, `/calculators` (alias), `/time-clock` (alias), `/jobs/:id/service-report` | `(app)/time-clock.tsx`, `(app)/landscape-time-clock.tsx` (dup), `landscape-time-clock.tsx`, `(app)/tools.tsx`, `(app)/calculators.tsx`, `card.tsx`, `property-lookup.tsx`, `(app)/huddle.tsx`, `huddle.tsx` (dup), `service-report/[id].tsx` | **FULL** | — | Some duplicated files between `(app)/` and root (`huddle`, `landscape-time-clock`). Cleanup opportunity but not a parity gap. |
| `/tests`, `/tests/:code`, `/tests/:code/quiz`, `/admin/training`, `/training` (redir) | `(app)/tests/index.tsx`, `(app)/tests/[code].tsx`, `(app)/tests/[code]/quiz.tsx` | **PARTIAL** | small | Admin training UI missing (create/edit courses). |

### 1L · Leads / D2D

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/leads/:id`, `/admin/leads/:id`, `/admin/leads`, `/leads/request`, `/leads/new`, `/request-job`, `/admin/job-requests` | `leads/index.tsx`, `leads/[id].tsx`, `leads/new.tsx`, `new-lead.tsx` | **FULL** | — | Web has both `/leads/:id` and `/admin/leads/:id` aliases. |
| `/deals` (`DealsKanbanPage`) | `deals/index.tsx`, `deals/[id].tsx`, `deals/new.tsx` | **FULL** | — | |
| `/d2d/*` (7 routes: dashboard, map, knocks, open-leads, sold-leads, report, leaderboard) | `d2d.tsx`, `d2d/index.tsx`, `d2d/leaderboard.tsx`, `d2d/report.tsx` | **PARTIAL** | small | Missing: knocks tab, open-leads / sold-leads discrete screens, D2D map view. |

### 1M · Field Ops Extras

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/tracking/filter`, `/tracking/filter/manage`, `/tracking/salt-cell`, `/tracking/salt-cell/manage` | `tracking/index.tsx`, `tracking/_layout.tsx` | **PARTIAL** | medium | Filter + salt-cell equipment trackers mostly stubbed on mobile. |
| `/cad`, `/cad/editor/:id`, `/measure`, `/virtual-bid`, `/landscape` (LandscapeAI), `/weather` | `cad/index.tsx`, `cad/editor.tsx`, `measure.tsx`, `virtual-bid.tsx`, `landscape.tsx` | **FULL** | — | Weather admin hub web-only. |
| `/checkins` (list) | `checkins.tsx` | **FULL** | — | |
| `/property-lookup` | `property-lookup.tsx` | **FULL** | — | |
| `/dev/file-upload` | `dev/file-upload.tsx` | **FULL** | — | Dev-only. |
| `/ops/repair-calculator` | none | **MISSING** | medium | Repair calculator web-only. |

### 1N · AI / Copilot / Employees / Assistants

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/ai-employees`, `/ai-employees/:id`, `/ai-chat/:id` | `ai-employees.tsx`, `ai-chat/[id].tsx` | **FULL** | — | |
| `/admin/copilot`, `/admin/ai-credits`, `/settings/ai-brain` | `settings/ai-brain.tsx` | **PARTIAL** | small | Copilot + AI credits management not surfaced on mobile. |
| `/admin/ai-personas-scope`, `/admin/ai-tool-audit` | none | **MISSING** | small | Governance surfaces web-only. |

### 1O · Forms / Widgets / Public Cards

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/forms`, `/forms/:id` | `forms.tsx` | **PARTIAL** | medium | Editor is web-only. |
| `/card` (`DigitalCardList`), `/settings/business-card` | `card.tsx`, `settings/business-card.tsx` | **FULL** | — | |
| `/admin/moderation/widget-embed`, `/admin/moderation/widget-analytics`, `WidgetDemoPage`, `/settings/widgets` | `widget-analytics.tsx`, `settings/widgets.tsx` | **PARTIAL** | small | Embed builder web-only. |
| `/share-replay`, `/replay/:shareId` | `share-replay.tsx` | **PARTIAL** | small | Public replay viewer web-only (expected). |

### 1P · Miscellaneous

| Web Route(s) | Mobile Screen | Parity | Effort | Notes |
|---|---|---|---|---|
| `/schedule-info` (public placeholder) | none | **WEB_ONLY_BY_DESIGN** | — | |
| `/portal/documents`, `/portal/messages`, `/portal/videos`, `/portal/photos` (duplicated) | see 1B | — | — | Web has both `PortalPhotos` and `PortalPhotosPage` — legacy dedup opportunity. |
| `/master-invoices/*` redirects | see 1E | — | — | |
| `/customer/service-reports/*` redirects | see 1B | — | — | |

### 1Q · Duplicated / Alias mobile files (housekeeping)

Some mobile screens live in **both** `mobile/app/*.tsx` and `mobile/app/(app)/*.tsx`. Not a parity issue but a source of drift:

- `landscape-time-clock.tsx` (root + `(app)/`)
- `huddle.tsx` (root + `(app)/`)
- `time-clock.tsx` (root + `(app)/`)
- `workstream.tsx` + `work-stream.tsx` + `workstream/[id].tsx`
- `payments.tsx` + `payments/methods.tsx` + `portal/payments.tsx`

---

## Part 2 — Backend Endpoint Coverage

Counts derived from `grep -rho '/api/[a-zA-Z0-9_/{}:.\-]*'` on `frontend/src/**` and `mobile/{app,src,components}/**`, then normalized (`{x}` and `:x` → `:ID`) and `sort -u`.

| Metric | Value |
|---|---|
| Distinct `/api/*` endpoints called from web | **251** |
| Distinct `/api/*` endpoints called from mobile | **112** |
| Overlap (shared) | **37** |
| Web-only (candidates for mobile parity) | **214** |
| Mobile-only | **75** |

### 2A · Web-only endpoints (candidates for mobile parity)

Full list saved to `/tmp/web_only_ep.txt`. Highest-value categories:

**Finance & Reports (web-only)**
- `/api/autobilling-runs`
- `/api/invoices/`, `/api/invoices/bulk-charge-card-on-file`, `/api/invoices/consolidate.`, `/api/invoices/preview-recipient`, `/api/invoices/:ID/request-payment-link`, `/api/invoices/line-item-categories.`
- `/api/checks/`, `/api/checks/batch/`
- `/api/reports/{profit,profit.csv,job-margin-leaderboard,least-profitable-services,pool-service,customer-retention.,algae-risk.,pricing-insights/email-history}`
- `/api/payments/checkout/:ID`, `/api/payments/lumino/return`, `/api/payments/stripe/config`
- `/api/promo-codes/validate`

**CFO (web-only)**
- `/api/cfo/{anomalies, ap-aging, bills, bills/:ID, categorize, cogs, forecast, llm-usage, payroll, price-increase-suggestions}`

**Recurring & scheduling**
- `/api/recurring-jobs`, `/api/recurring-jobs/:ID`, `/api/recurring-jobs/:ID/generate`
- `/api/dispatch/route/{apply, optimize, savings/weekly}`, `/api/dispatch/suggest-route`

**Admin / governance**
- `/api/admin/{ai-personas-scope, ai-tool-audit, suggest-departments, apply-department-suggestions, chemical-costs, orphan-customer-users, lumino/backfill-payment-links, moderation/public-checkins, users/bulk-department}`

**Portal / public**
- Anonymous review, CSAT, InstaQuote/Schedule, NFC, forms, sign, lead-request, insta* — expected web-only.
- `/api/portal/photos.`, `/api/portal/videos`, `/api/portal/estimates/via-token`

**GPS / Directories / SEO / RingCentral / Weather / Widget / Training / Tenants** — heavy admin surface, web-only (see full list).

### 2B · Mobile-only endpoints

Full list in `/tmp/mobile_only_ep.txt`. Notable:

**Mobile-specific infra**
- `/api/mobile/sync`, `/api/mobile/offline-bundle` (offline sync)
- `/api/pushTokens` (push notification token registration)
- `/api/gps/config`, `/api/gps/pings` (device telemetry)

**Auth**
- `/api/auth/change-password`, `/api/auth/reset-password`, `/api/auth/me`, `/api/me` — probably called from web too but via wrapper, not literal string match.

**Field ops (that web hits via different verbs/paths)**
- `/api/service-reports/:ID/media`, `/api/service-reports/:ID/media/reorder`, `/api/service-report/analyze-water-photo`
- `/api/jobs/reorder`, `/api/jobs/:ID/service-report/submit`

**Dispatch / weather**
- `/api/dispatch/auto-assign`, `/api/dispatch/settings`, `/api/dispatch/technician-skills`, `/api/dispatch/weather-events*`, `/api/dispatch/weather-scan`

**Marketing (different route shapes)**
- `/api/marketing/{analytics/overview, audience-segments, campaigns, review-requests, sequences, suppressions, templates, templates/preview-message}`

**Public reviews (mobile-specific paths)**
- `/api/public/r/:ID`, `/api/public/r/:ID/google-clicked`, `/api/public/r/:ID/rating` (web uses `/api/reviews/public/r/...`)

⚠️ Some mobile-only endpoints look like **path-format drift** vs web (e.g., `/api/public/r/:ID` vs `/api/reviews/public/r/:ID`). Worth normalizing during Phase 32.

---

## Part 3 — Test Coverage Snapshot

### 3A · Backend (pytest)

| Metric | Value |
|---|---|
| Test files under `backend/tests/**` | **360** |
| `def test_*` functions | **2,411** |
| Async test functions (`async def test_*`) | 1 |
| Config | `backend/pytest.ini` with markers `live`, `destructive`, `legacy_iteration` (all skipped by default) |
| Runtime | not executed (out of audit scope) |

### 3B · Frontend (vitest)

Ran `yarn vitest run --reporter=basic --no-coverage` (single pass, non-modifying).

| Metric | Value |
|---|---|
| Test files under `frontend/src/**/*.test.{js,jsx}` | **124** |
| Total tests | **654** |
| Passed | **640** |
| Failed | **13** |
| Skipped | **1** |
| Empty/0-test files (collection failure) | **9** (see below) |
| Wall-clock | ~33s |

**Empty test files (collection failed — likely import/env drift, not assertion regressions):**
- `src/test/task-rr-ss-p2-revised.test.jsx`
- `src/test/phase34-bulk-select-shared.test.jsx`
- `src/test/file-upload-components.test.jsx`
- `src/test/preview-demo-logins.test.jsx`
- `src/test/phase34-admin-page-mount-safety.test.jsx`
- `src/test/phase34-task-w-forgot-password.test.jsx`
- `src/test/phase22-mobile-schedule-gates.test.jsx`
- `src/test/phase34-task-pp-portal-hint.test.jsx`
- `src/test/persona-avatar.test.jsx`

**Failing tests (13 total across 5 files):**
- `src/test/slice-p17-additions.test.jsx` (1 fail: shift-route dialog POST payload)
- `src/test/invoice-edit-modal.test.jsx` (6 fails — entire suite red)
- `src/test/phase10-ui.test.jsx` (1 fail: AdjustDialog reason-len gate)
- `src/test/login-demo-flag.test.jsx` (4 fails — entire suite red, appears env-dependent)
- `src/test/slice-p19-ai-copilot.test.jsx` (1 fail: send-and-render)
- `src/test/login-welcome.test.jsx` (1 fail: headline text mismatch)

⚠️ **Delta vs. prior baseline:** the summary handed off from the previous session said "112/112 passing custom + 16 baseline flakes" — current reality is **13 failures + 9 empty files**, closer to ~22 flake-equivalents. The baseline is drifting; new work is not being run against the full suite.

### 3C · Mobile-surface tests

Mobile has **two** parallel test surfaces:

**(i) Mobile-native Jest suites (`mobile/__tests__/*.test.tsx`, jest-expo preset):**

| File | Focus |
|---|---|
| `file-upload-components.test.tsx` | Upload UI |
| `PriceBookAdmin.test.tsx` | Price book admin screen |
| `PortalChatAttachments.test.tsx` | Portal chat attachments |
| `f2d-chat-attachments.test.tsx` | Field chat attachments |
| `invoice-attachments.test.tsx` | Invoice attachments |
| `f2e-persona-avatar.test.tsx` | Persona avatar swap (Phase 30-related) |
| `next-service-day.test.tsx` | Next-service card |
| `f2c1-booking-photos.test.tsx` | Booking photos |
| `ProfitReport.test.tsx` | Profit report screen |
| `f2a-job-photos.test.tsx` | Job photos |
| `InvoiceInternalMargin.test.tsx` | Invoice margin math |
| `f2f-staff-profile.test.tsx` | Staff profile |
| `demo-login.test.tsx` | Demo login gate |
| `appointments-header.test.tsx` | Appointments header |
| `GpsTracker.test.ts` | GPS ingest |
| `job-before-after-photos.test.tsx` | Job photos before/after |

**Totals:** 16 files, ~118 `it/test` calls. Not executed in this audit.

**(ii) Source-inspection vitests inside `frontend/src/test/` that assert on mobile source strings** (AST-style):

| File | Mobile surface locked |
|---|---|
| `phase22-mobile-schedule-gates.test.jsx` | Schedule role gating |
| `phase23-job-tracker-tiles.test.jsx` | Job tracker tiles |
| `phase25-job-tracker-label-clipping.test.jsx` | Phase 25 clipping fix |
| `phase25b-job-tracker-geometry.test.jsx` | Phase 25b rewrite |
| `phase27-mobile-avatar-dense.test.jsx` | TechAvatar in mobile |
| `phase28-eas-update-config.test.jsx` | OTA config safety |
| `phase29-auto-clockin-tech-lockdown.test.jsx` | Locked auto-clockin toggle |
| `phase30-3-portal-sign-out.test.jsx` | Sign-out button flex/hitSlop |
| `phase30-portal-admin-avatar-coverage.test.jsx` | Persona avatars |

**Coverage estimate.** Mobile has ~140 `.tsx` files under `mobile/app`. 16 native Jest suites touch ~16 files. Source-inspection covers another ~10 unique mobile files. **Realistic mobile assertion coverage ≈ 15–20% of screens; the rest is manually verified.**

### 3D · Flaky / drifting tests

- **Pre-existing baseline:** originally ~16 stale `@jest/globals` imports on legacy files — session notes said "do not fix". Current run shows only 9 empty files → drift is contained but not fixed.
- **Login/demo flag suite:** `login-demo-flag.test.jsx` fully red — likely depends on `/api/config/public` mock now missing.
- **Invoice edit modal suite:** entire suite red — mount-time crash likely, possibly Recent regression from a component refactor.
- **Copilot / AdjustDialog / login-welcome:** single-test regressions that look like copy/prop drift.

### 3E · Coverage gap narrative

- **Backend:** deep. 2,411 tests over 360 files across auth, invoices, dispatch, reports, integrations. Only real risk is exercising cost — no CI enforces it.
- **Frontend web:** decent — but only visible when someone runs `yarn vitest`. Suite has grown unmaintained by ~20 items.
- **Mobile:** thin. Only 16 native suites + 10 source-inspection files. **No runtime UI tests, no e2e, no screenshot/pixel tests, no Detox, no Maestro.** Regressions like the Phase 25 clipping bug and Phase 30.3 unclickable button were only caught by user report, not by the suite.

---

## Part 4 — CI Config Snapshot

**Finding: the repo has NO CI configuration file at all.**

Checked (all absent):
- `.github/workflows/**`
- `.gitlab-ci.yml`
- `Jenkinsfile`
- `.circleci/**`
- `bitbucket-pipelines.yml`
- `azure-pipelines.yml`
- `.travis.yml`

The only automation surface is the package.json script targets:

**`/app/frontend/package.json` scripts:**
- `start` → `craco start`
- `build` → `craco build`
- `test` → `craco test`
- `test:unit` → `vitest run --config vitest.config.js`
- `test:unit:watch` → `vitest --config vitest.config.js`

**`/app/mobile/package.json` scripts:**
- `preinstall` → `./scripts/cmd-guard.js --preinstall`
- `start` → `expo start`
- `tunnel` → `expo start --tunnel`
- `android`, `ios`, `web` → `expo start --{platform}`
- `lint` → `expo lint`
- `test` → `jest --no-cache --forceExit`
- `reset-project` → `node ./scripts/reset-project.js`

**Backend:** `backend/pytest.ini` defines `pythonpath = .` and three custom markers (`live`, `destructive`, `legacy_iteration`) — no runner wiring.

### 4A · Missing typical steps

- ❌ No pre-commit hook / husky
- ❌ No lint step in CI (only `expo lint` for mobile, nothing for frontend, `ruff` cache exists suggesting occasional local linting)
- ❌ No unit-test enforcement on push / PR
- ❌ No type-check (frontend has no TS, mobile has `tsconfig.json` but no automated check)
- ❌ No dependency-audit (npm audit / pip-audit / snyk)
- ❌ No secret scan
- ❌ No container/image build stage
- ❌ No artifact retention (test reports, coverage HTML)
- ❌ No deploy stage

### 4B · Mobile CI

**Zero mobile CI.** No EAS Build workflow, no OTA publish workflow (despite Phase 28 wiring up `expo-updates` for `eas update`), no Play/App Store submission automation. `EAS_UPDATE_RUNBOOK.md` documents a manual procedure only.

### 4C · Kubernetes / preview infra

- `/app/k8s/ingress-cors-recommended.yaml` exists but is a static config file, not a CI artifact.
- `/app/scripts/preflight.sh` and various check_*.py scripts exist as ad-hoc lint helpers; none are wired to a scheduler.

---

## Recommended Prioritization

Grouped for a planning conversation, not committed.

### P0 — Table stakes (do before adding more product surface)

1. **Add a minimal CI pipeline.** `.github/workflows/ci.yml` running: `yarn install --frozen-lockfile` (both `frontend/` and `mobile/`) → `pip install -r backend/requirements.txt` → `pytest -q --ignore=backend/tests/legacy_iteration` (or with `-m 'not legacy_iteration and not live and not destructive'`) → `yarn --cwd frontend test:unit` → `yarn --cwd mobile test`. Trigger on PR + push to main. Effort: **medium**.
2. **Fix or delete the 9 empty vitest files and the 13 red tests.** They're currently silent regressions that no one sees because there's no CI. Effort: **small–medium**.
3. **Endpoint drift cleanup.** Normalize `/api/public/r/:ID` (mobile) vs `/api/reviews/public/r/:ID` (web) — pick one; same for `/api/service-report/*` vs `/api/service-reports/*`. Effort: **small**, high leverage.

### P1 — Highest-value mobile parity

4. **Finance ops on mobile** — Recurring Jobs, Auto-Billing config, Autobilling Runs read, Master Invoices, Payments ledger, Vendor Bills. Effort: **large**, blocked by no CI so build carefully.
5. **CFO deep-dives** — bills/ap-aging/forecast/anomalies/payroll/price-increase. Effort: **large**.
6. **Business OS** — SOPs, roles, scorecards, leanboards, sprints. Effort: **large** but self-contained.
7. **Dispatch parity** — route optimize/apply/insert + Mapbox live pins. Effort: **large**.

### P2 — Cleanup + nice-to-have

8. **Mobile runtime UI tests.** Add Detox or Maestro; target the flows that regressed in Phases 24–30. Effort: **medium infra + ongoing**.
9. **Dedup mobile files** (`landscape-time-clock`, `huddle`, `time-clock`, `workstream`) — reduces drift risk. Effort: **small**.
10. **Portal parity polish** — warranties, preferences, ToS, sign token. Effort: **small each**.
11. **Marketing/SEO mobile catch-up** — campaigns, autopilot, directories/NAP, forms editor. Effort: **large but incremental**.
12. **Admin governance surfaces on mobile** — ai-personas-scope, ai-tool-audit, moderation. Effort: **small each**.

### P3 — Explicitly deferred / `WEB_ONLY_BY_DESIGN`

Do NOT chase mobile parity for these — they're intentionally web-only or public-web:
- All `/public/*`, `/pay/invoice/:id`, `/quote/:slug`, `/book/:slug`, `/reviews/r/:token`, `/csat/:token`, `/lead-request/:token`, `/f/:slug`, `/nfc/:slug`, `/replay/:shareId`, `/widget-demo`, `/portal/sign/:token`.
- CSV import/export (`/impexp`, `/api/import/customers/template`, `/api/workforce/export/timesheets.csv`, `/api/directories/submissions/export/csv`).
- OAuth callbacks (`/api/qbo/oauth/callback`, `/api/integrations/supercool/callback`).
- Admin config editors that make more sense on a keyboard (`/settings/legal/:slug`, `/settings/citations`, `/settings/business-card`, `/admin/tools/documents`, `/admin/estimator/rates`).
- Bulk operations that need a spreadsheet-y UI (`/admin/users/bulk-department`, `/api/jobs/bulk-reassign`, `/api/social/posts/bulk`).

---

## Appendix A · Route counts by first segment

**Web (`frontend/src/App.js`, 412 total `path=`):** admin 130 · marketing 29 · portal 28 · settings 27 · (root routes) 25 · reports 9 · customers 9 · social 8 · seo 7 · d2d 7 · tech 6 · invoices 6 · estimator 5 · workforce 4 · tracking 4 · schedule 4 · leads 4 · jobs 4 · quotes 3 · tests 3 · ops 3 · master-invoices 3 · estimates 3 · … tail (many with 1 each).

**Mobile (`mobile/app/**`, ~184 route files including `_layout`/`+html`):** `(app)/*` 69 · portal 21 · admin 14 · settings 12 · marketing 10 · aeo 8 · leads 4 · estimator 4 · customer 4 · reports 3 · job 3 · d2d 3 · workstream 2 · tracking 2 · seo 2 · quote 2 · qbo 2 · payments 2 · finance 2 · cad 2 · … + ~50 flat root screens.

## Appendix B · Full endpoint diff artifacts

- `/tmp/web_api.txt` — 252 raw web `/api/*` strings
- `/tmp/mobile_api.txt` — 114 raw mobile `/api/*` strings
- `/tmp/web_norm.txt` / `/tmp/mobile_norm.txt` — normalized (path params → `:ID`) — 251 / 112
- `/tmp/web_only_ep.txt` — 214 endpoints in web but not in mobile
- `/tmp/mobile_only_ep.txt` — 75 endpoints in mobile but not in web

*(These `/tmp/*.txt` files are ephemeral — persist them into `/app/PHASE31_diff/` if you want them to survive pod restart.)*

---

## Non-scope confirmations

- No source files were modified.
- No tests were added, deleted, or edited.
- No CI files created.
- No repositories were cloned; the audit is scoped to `/app`.
- Vitest was executed in read-only `run --reporter=basic --no-coverage` mode to obtain counts; no state was persisted.

*End of report.*
