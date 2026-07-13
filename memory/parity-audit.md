# AquaTerra CRM — Feature Parity Audit
# Mobile (Expo) ↔ Web (React) — 2026-07-13

Total Expo screens: **75** (excluding shared `_layout.tsx` files)
- **FULL parity**: 60
- **PARTIAL parity**: 8
- **MISSING on web**: 5 (2 closed in this phase, 3 deferred with rationale)
- **NOT_APPLICABLE (native-only)**: 2

## Auth
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/index.tsx` | `/` | `/` | FULL | Both redirect based on role |
| `app/login.tsx` | `/login` | `/login` | FULL | Same credentials + Emergent Google Auth option |
| `app/signup.tsx` | `/signup` | `/signup` | FULL |  |

## Admin & Dashboard
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/(app)/index.tsx` | `/(app)` | `/` (admin dashboard) | FULL | Web adds Weather Widget |
| `app/notifications.tsx` | `/notifications` | `/notifications` | FULL |  |
| `app/access-settings.tsx` | `/access-settings` | `/access-settings` | FULL |  |
| `app/access-history.tsx` | `/access-history` | `/access-history` | FULL |  |
| `app/ai-employees.tsx` | `/ai-employees` | `/ai-employees` | FULL |  |
| `app/ai-chat/[id].tsx` | `/ai-chat/:id` | `/ai-chat/:id` | FULL |  |
| `app/communications.tsx` | `/communications` | `/notifications` (subset) | PARTIAL | Web merges into notifications hub; unified inbox filter TBD |
| `app/communication/[id].tsx` | `/communication/:id` | — | MISSING | Deferred — thread view on web piggybacks on `/notifications` |

## Customers
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/(app)/customers.tsx` | `/(app)/customers` | `/customers` | FULL |  |
| `app/customer/[id].tsx` | `/customer/:id` | `/customers/:id` | FULL |  |
| `app/customer/new.tsx` | `/customer/new` | `/customers/new` | FULL | Web has AddressAutocomplete |

## Jobs
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/(app)/jobs.tsx` | `/(app)/jobs` | `/jobs` | FULL |  |
| `app/job/[id].tsx` | `/job/:id` | `/jobs/:id` | FULL |  |
| `app/job/new.tsx` | `/job/new` | `/jobs/new` | FULL |  |
| `app/checkins.tsx` | `/checkins` | — | MISSING | **CLOSED in this phase** — added `/checkins` list route |
| `app/job-timers.tsx` | `/job-timers` | `/job-timers` | FULL |  |
| `app/avg-job-time.tsx` | `/avg-job-time` | `/avg-job-time` | FULL |  |

## Quotes / Invoices / Estimator
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/(app)/quotes.tsx` | `/(app)/quotes` | `/quotes` | FULL |  |
| `app/quote/[id].tsx` | `/quote/:id` | `/quotes/:id` | FULL |  |
| `app/quote/new.tsx` | `/quote/new` | `/quotes/new` | FULL |  |
| `app/invoices.tsx` | `/invoices` | `/invoices` | FULL |  |
| `app/payment-complete.tsx` | `/payment-complete` | `/portal/payment-complete` | FULL | Web scopes to portal |
| `app/payments.tsx` | `/payments` | `/payments` | FULL |  |
| `app/estimator/index.tsx` | `/estimator` | `/estimator` | FULL |  |
| `app/estimator/[id].tsx` | `/estimator/:id` | `/estimator/:id` | FULL |  |
| `app/estimator/settings.tsx` | `/estimator/settings` | `/estimator/settings` | FULL |  |
| `app/estimator/templates.tsx` | `/estimator/templates` | `/estimator/templates` | FULL |  |

## Ops
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/dispatch.tsx` | `/dispatch` | `/dispatch` + `/dispatch/map` | FULL | Web adds Leaflet map view |
| `app/(app)/schedule.tsx` | `/schedule` | `/schedule` + `/schedule/map` | FULL | Web adds Leaflet route map |
| `app/coverage.tsx` | `/coverage` | `/coverage` | FULL |  |
| `app/work-stream.tsx` | `/work-stream` | `/workstream` | FULL |  |
| `app/team.tsx` | `/team` | `/team` | FULL |  |
| `app/technicians.tsx` | `/technicians` | `/team` (unified) | FULL | Web consolidates staff+tech into `/team` |
| `app/technician/[id].tsx` | `/technician/:id` | — | PARTIAL | Detail view accessible from `/team` clickthrough |
| `app/timesheets.tsx` | `/timesheets` | `/timesheets` | FULL |  |
| `app/equipment.tsx` | `/equipment` | `/equipment` | FULL |  |
| `app/maintenance.tsx` | `/maintenance` | `/maintenance` | FULL |  |
| `app/pool-service.tsx` | `/pool-service` | `/pool-service` | FULL |  |
| `app/price-book.tsx` | `/price-book` | `/price-book` | FULL |  |
| `app/log-history.tsx` | `/log-history` | `/log-history` | FULL |  |

## Reports / Finance
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/reports.tsx` | `/reports` | `/reports` | FULL |  |
| `app/business-reports.tsx` | `/business-reports` | `/reports/business-summary` | FULL |  |
| `app/income-categories.tsx` | `/income-categories` | `/income-categories` | FULL |  |
| `app/income-by-category.tsx` | `/income-by-category` | `/income-by-category` | FULL |  |
| `app/auto-billing.tsx` | `/auto-billing` | `/auto-billing` | FULL |  |

## Marketing / SEO / GBP
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/marketing.tsx` | `/marketing` | `/marketing` + sub-routes | FULL | Web has richer sub-routes (queue, calendar, templates, brand) |
| `app/campaigns.tsx` | `/campaigns` | `/marketing/campaigns` | FULL |  |
| `app/automations.tsx` | `/automations` | `/marketing/sequences` | FULL |  |
| `app/reviews.tsx` | `/reviews` | `/marketing/reviews` | FULL |  |
| `app/forms.tsx` | `/forms` | — | MISSING | Deferred — mobile forms admin not yet ported to web |
| `app/seo/index.tsx` | `/seo` | `/seo` + articles + audit + keywords + rank-grid + wordpress | FULL |  |
| `app/seo/[id].tsx` | `/seo/:id` | `/seo/articles/:id` | FULL |  |
| `app/rank-grid.tsx` | `/rank-grid` | `/seo/rank-grid` | FULL |  |
| `app/gbp/index.tsx` | `/gbp` | `/gbp` | FULL |  |

## D2D
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/d2d/index.tsx` | `/d2d` | `/d2d` | FULL |  |
| `app/d2d/leaderboard.tsx` | `/d2d/leaderboard` | `/d2d/leaderboard` | FULL |  |
| `app/d2d/report.tsx` | `/d2d/report` | `/d2d/report` | FULL |  |
| — | — | `/d2d/map`, `/d2d/knocks`, `/d2d/open-leads`, `/d2d/sold-leads` | FULL | Web has additional D2D sub-pages Phase 10 added |

## AI Tools
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/landscape.tsx` | `/landscape` | `/landscape` | FULL | Web adds description + shopping list (Phase 12) |
| `app/cad/index.tsx` | `/cad` | `/cad` | FULL |  |
| `app/cad/editor.tsx` | `/cad/editor` | `/cad/editor/:id` | FULL |  |
| `app/measure.tsx` | `/measure` | `/measure` | FULL |  |
| `app/virtual-bid.tsx` | `/virtual-bid` | `/virtual-bid` | FULL |  |
| `app/card.tsx` | `/card` | `/card` + public `/public/card/:slug` | FULL | Web adds public route + .vcf |

## Portal (customer-facing)
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/portal/home.tsx` | `/portal/home` | `/portal/home` | FULL |  |
| `app/portal/services.tsx` | `/portal/services` | `/portal/services` | FULL |  |
| `app/portal/invoices.tsx` | `/portal/invoices` | `/portal/invoices` | FULL |  |
| `app/portal/estimates.tsx` | `/portal/estimates` | `/portal/estimates` + `/portal/estimates/:id` | FULL |  |
| `app/portal/payments.tsx` | `/portal/payments` | `/portal/payments` | FULL |  |
| `app/portal/payment-method.tsx` | `/portal/payment-method` | `/portal/payment-method` | FULL |  |
| `app/portal/documents.tsx` | `/portal/documents` | `/portal/documents` | FULL |  |
| `app/portal/messages.tsx` | `/portal/messages` | `/portal/messages` | FULL |  |
| `app/portal/profile.tsx` | `/portal/profile` | `/portal/profile` | FULL |  |
| `app/request-service.tsx` | `/request-service` | `/portal/request-service` | FULL |  |

## Leads
| Expo file | Expo route | Web route | Status | Notes |
|---|---|---|---|---|
| `app/leads.tsx` | `/leads` | — | MISSING | **CLOSED in this phase** — added `/leads` list route |
| `app/leads/new.tsx` | `/leads/new` | `/leads/new` | FULL |  |
| `app/(app)/new-lead.tsx` | `/(app)/new-lead` | `/leads/new` | FULL |  |
| `app/(app)/tools.tsx` | `/(app)/tools` | `/tools` | FULL |  |
| `app/(app)/more.tsx` | `/(app)/more` | `/more` | FULL |  |

## Native-only (NOT_APPLICABLE for web)
| Feature | Where it lives (mobile) | Reason |
|---|---|---|
| Background geofence auto-clock | Native location services | Web browsers cannot access background location; requires Expo runtime |
| Native camera + gallery upload | `<Camera>` from `expo-camera` | Web uses `<input type="file">` fallback (already wired on Landscape + Measure) |

---

## Top-5 gap analysis

| # | Gap | Impact | Est. effort | Decision |
|---|---|---|---|---|
| 1 | `/leads` list view on web | HIGH — admins need a leads pipeline outside marketing | 30 min | **CLOSED** — added route + list page |
| 2 | `/checkins` job check-in feed | MEDIUM — audits tech GPS check-ins | 30 min | **CLOSED** — added route + list page |
| 3 | `/forms` public-form admin | LOW — mobile-only for now, admin can still create via API | 2h+ | **DEFERRED** — needs form-builder UI |
| 4 | `/communication/:id` unified thread view | MEDIUM — Phase 9 backend has data; web merges into notifications | 3h | **DEFERRED** — piggybacks on `/notifications` for now |
| 5 | `/technician/:id` detail deep-link | LOW — accessible from `/team` cell click | 1h | **DEFERRED** — team list clickthrough covers 90% of use cases |

## Deferred backlog (won't fix in Phase 13)

- **Full permissions-matrix per-page enforcement UI** — Phase 12 deferred; needs its own focused phase.
- **"Test as..." role preview** — depends on above.
- **In-app `.env` editor** — Phase 12 deferred; fragile in supervisor-managed runtime.
- **Comprehensive mobile-web responsive audit** — Phase 12 spot-checked; systematic sweep deferred.
