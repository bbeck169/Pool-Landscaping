# Web ↔ Mobile Parity Gap Report
> Generated: 2026-07-24 | Web source: `/app/frontend/src/App.js` | Mobile source: `/app/mobile/app/**/*.tsx`

---

## Customer Portal Routes

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/portal/home` | `portal/home.tsx` | ✅ Y | — | — |
| `/portal/services` | `portal/services.tsx` | ✅ Y | — | — |
| `/portal/services/:id` | `portal/service/[id].tsx` | ✅ Y | — | — |
| `/portal/service-reports` | `portal/service-reports.tsx` | ✅ Y | — | — |
| `/portal/service-reports/:id` | `portal/service-report/[id].tsx` | ✅ Y | — | — |
| `/portal/invoices` | `portal/invoices.tsx` | ✅ Y | — | — |
| `/portal/invoices/:id` | `portal/invoices.tsx` → `invoice/[id].tsx` | ✅ Y | Portal nav wired (Iter 18) | — |
| `/portal/estimates` | `portal/estimates.tsx` | ✅ Y | — | — |
| `/portal/estimates/:id` | `portal/estimates.tsx` → `estimate-view/[id].tsx` | ✅ Y | Portal nav wired (Iter 18) | — |
| `/portal/payments` | `portal/payments.tsx` | ✅ Y | — | — |
| `/portal/payment-method` | `portal/payment-method.tsx` | ✅ Y | — | — |
| `/portal/documents` | `portal/documents.tsx` | ✅ Y | — | — |
| `/portal/messages` | `portal/messages.tsx` | ✅ Y | — | — |
| `/portal/chats` | `portal/chats.tsx` | ✅ Y | — | — |
| `/portal/chats/:id` | `portal/chats/[id].tsx` | ✅ Y | — | — |
| `/portal/book` | `portal/book.tsx` | ✅ Y | — | — |
| `/portal/photos` | `portal/photos.tsx` | ✅ Y | — | — |
| `/portal/videos` | `portal/videos.tsx` | ✅ Y | — | — |
| `/portal/profile` | `portal/profile.tsx` | ✅ Y | — | — |
| `/portal/request-service` | `request-service.tsx` | ✅ Y | — | — |
| `/portal/reviews` | `reviews.tsx` | ✅ Y | — | — |
| `/portal/referrals` | `referrals.tsx` | ✅ Y | — | — |
| `/portal/add-card` | `portal/add-card.tsx` | ✅ Y | — | — |
| `/portal/payment-complete` | `payment-complete.tsx` | ✅ Y | — | — |
| `/portal/preferences` | — | ❌ N | Email/SMS preference opt-out (unsubscribe) | LOW |
| `/portal/terms` | — | ❌ N | Terms of service acceptance | LOW |
| `/portal/warranties` | — | ❌ N | Warranty contracts viewer (customer-facing) | LOW |
| `/portal/sign/:token` | — | ❌ N | E-signature magic link | LOW |

## Tech Routes

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/schedule` | `(app)/schedule/calendar.tsx` | ✅ Y | — | — |
| `/tech/time-clock` | `(app)/time-clock.tsx` + `time-clock.tsx` | ✅ Y | — | — |
| `/landscape/time-clock` | `(app)/landscape-time-clock.tsx` | ✅ Y | — | — |
| `/tech/huddle` | `(app)/huddle.tsx` | ✅ Y | — | — |
| `/tech/tools` | `(app)/tools.tsx` | ✅ Y | — | — |
| `/tech/tools/calculators` | `(app)/calculators.tsx` | ✅ Y | — | — |
| `/tech/card` | `card.tsx` | ✅ Y | — | — |
| `/handbook` | `(app)/handbook/index.tsx` | ✅ Y | — | — |
| `/handbook/:code` | `(app)/handbook/[code].tsx` | ✅ Y | — | — |
| `/tests` | `(app)/tests/index.tsx` | ✅ Y | — | — |
| `/tests/:code` | `(app)/tests/[code].tsx` | ✅ Y | — | — |
| `/tests/:code/quiz` | `(app)/tests/[code]/quiz.tsx` | ✅ Y | — | — |
| `/jobs/:id` | `job/[id].tsx` | ✅ Y | — | — |
| `/jobs/:id/service-report` | `(app)/service-report/[id].tsx` | ✅ Y | — | — |
| `/onboarding-checklist` | `(app)/onboarding-checklist/index.tsx` | ✅ Y | — | — |
| `/onboarding/mine` | `(app)/onboarding/mine.tsx` | ✅ Y | — | — |
| `/d2d` | `(app)/d2d.tsx` + `d2d/index.tsx` | ✅ Y | — | — |
| `/d2d/leaderboard` | `d2d/leaderboard.tsx` | ✅ Y | — | — |
| `/d2d/report` | `d2d/report.tsx` | ✅ Y | — | — |
| `/d2d/map` | — | ❌ N | D2D canvassing map view | MEDIUM |
| `/d2d/knocks` | — | ❌ N | D2D knocks log | MEDIUM |
| `/d2d/open-leads` | — | ❌ N | D2D open leads list | MEDIUM |
| `/d2d/sold-leads` | — | ❌ N | D2D sold leads list | MEDIUM |
| `/request-job` | — | ❌ N | Tech job request form | MEDIUM |
| `/notifications` | `notifications.tsx` | ✅ Y | — | — |
| `/chat` | `(app)/chat.tsx` | ✅ Y | File exists (removed from tech nav per cleanup) | — |
| `/customers/:id/chemistry` | `customer/chemistry/[id].tsx` | ✅ Y | Built (Iter 18) | — |

## Admin Routes

### Core Operations (Daily Use)

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/` (Dashboard) | `(app)/index.tsx` | ✅ Y | — | — |
| `/customers` | `(app)/customers.tsx` | ✅ Y | — | — |
| `/customers/new` | `customer/new.tsx` | ✅ Y | — | — |
| `/customers/:id` | `customer/[id].tsx` | ✅ Y | — | — |
| `/customers/:id/edit` | — | ❌ N | Customer edit form (currently inline in web) | MEDIUM |
| `/customers/:id/chemistry` | `customer/chemistry/[id].tsx` | ✅ Y | Built (Iter 18) | — |
| `/customers/:id/chemistry-history` | — | ❌ N | Chemistry readings history | LOW |
| `/customers/:id/credits` | `(app)/credits/index.tsx` | ✅ Y | — | — |
| `/jobs/new` | `job/new.tsx` | ✅ Y | — | — |
| `/jobs/:id` | `job/[id].tsx` | ✅ Y | — | — |
| `/schedule` | `(app)/schedule/calendar.tsx` | ✅ Y | — | — |
| `/dispatch` | `dispatch.tsx` + `(app)/dispatch/board.tsx` | ✅ Y | — | — |
| `/dispatch/map` | — | ❌ N | Google Maps dispatch overlay | MEDIUM |
| `/team` | `team.tsx` | ✅ Y | — | — |
| `/technician/:id` | `technician/[id].tsx` | ✅ Y | — | — |
| `/timesheets` | `timesheets.tsx` | ✅ Y | — | — |
| `/notifications` | `notifications.tsx` | ✅ Y | — | — |
| `/cfo` | `(app)/cfo/index.tsx` | ✅ Y | — | — |
| `/workstream` | `workstream.tsx` | ✅ Y | — | — |
| `/workstream/:id` | `workstream/[id].tsx` | ✅ Y | — | — |

### Quotes / Invoices / Estimator

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/quotes` | `(app)/quotes.tsx` | ✅ Y | — | — |
| `/quotes/new` | `quote/new.tsx` | ✅ Y | — | — |
| `/quotes/:id` | `quote/[id].tsx` | ✅ Y | — | — |
| `/invoices` | `invoices.tsx` | ✅ Y | — | — |
| `/invoices/new` | — | ❌ N | Create new invoice | MEDIUM |
| `/invoices/:id` | `invoice/[id].tsx` | ✅ Y | — | — |
| `/invoices/master` | — | ❌ N | Master invoices list | LOW |
| `/invoices/master/new` | — | ❌ N | Create master invoice | LOW |
| `/invoices/master/:id` | — | ❌ N | Master invoice detail | LOW |
| `/estimator` | `estimator/index.tsx` + `(app)/estimator/index.tsx` | ✅ Y | — | — |
| `/estimator/new` | `estimator/new.tsx` + `(app)/estimator/new.tsx` | ✅ Y | — | — |
| `/estimator/:id` | `estimator/[id].tsx` | ✅ Y | — | — |
| `/estimator/settings` | `estimator/settings.tsx` | ✅ Y | — | — |
| `/estimator/templates` | `estimator/templates.tsx` | ✅ Y | — | — |
| `/ai-estimator` | `(app)/ai-estimator.tsx` | ✅ Y | — | — |

### Marketing & Comms

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/marketing` | `marketing/index.tsx` | ✅ Y | — | — |
| `/marketing/templates` | `marketing/templates.tsx` | ✅ Y | — | — |
| `/marketing/templates/:id` | — | ❌ N | Template detail/editor | MEDIUM |
| `/marketing/brand` | — | ❌ N | Brand memory | LOW |
| `/marketing/campaigns` | `campaigns.tsx` | ✅ Y | — | — |
| `/marketing/campaigns/new` | — | ❌ N | New campaign | MEDIUM |
| `/marketing/campaigns/:id` | — | ❌ N | Campaign detail | MEDIUM |
| `/marketing/posts` | — | ❌ N | Social posts | LOW |
| `/marketing/queue` | — | ❌ N | Approval queue | LOW |
| `/marketing/calendar` | — | ❌ N | Content calendar | LOW |
| `/marketing/broadcasts` | `marketing/broadcasts.tsx` | ✅ Y | — | — |
| `/marketing/segments` | `marketing/segments.tsx` | ✅ Y | — | — |
| `/marketing/sequences` | `marketing/sequences.tsx` | ✅ Y | — | — |
| `/marketing/sequences/new` | — | ❌ N | New sequence | MEDIUM |
| `/marketing/sequences/:id` | — | ❌ N | Sequence detail | MEDIUM |
| `/marketing/reviews` | — | ❌ N | Marketing reviews hub | LOW |
| `/marketing/before-after` | `(app)/before-after.tsx` | ✅ Y | Admin-only | — |
| `/marketing/directories` | `(app)/directories.tsx` | ✅ Y | — | — |
| `/marketing/autopilot` | — | ❌ N | AI autopilot | LOW |
| `/marketing/instaquote` | `(app)/instaquote.tsx` | ✅ Y | — | — |
| `/marketing/instaschedule` | `(app)/instaschedule.tsx` | ✅ Y | — | — |
| `/marketing/gbp-posts` | — | ❌ N | GBP post drafter | LOW |
| `/admin/marketing/analytics` | `marketing/analytics.tsx` | ✅ Y | — | — |
| `/admin/marketing/review-requests` | `marketing/review-requests.tsx` | ✅ Y | — | — |
| `/admin/marketing/suppressions` | `marketing/suppressions.tsx` | ✅ Y | — | — |
| `/admin/marketing/forms` | `forms.tsx` | ✅ Y | — | — |
| `/admin/communications-log` | `communications.tsx` | ✅ Y | — | — |
| `/admin/comms/templates` | `(app)/comms/templates/index.tsx` | ✅ Y | — | — |
| `/admin/comms/templates/:code` | `(app)/comms/templates/[code].tsx` | ✅ Y | — | — |
| `/admin/comms/automations` | `(app)/comms/automations/index.tsx` | ✅ Y | — | — |
| `/admin/comms/sends` | `(app)/comms/sends/index.tsx` | ✅ Y | — | — |

### Reviews

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/admin/reviews` | `(app)/reviews/index.tsx` | ✅ Y | — | — |
| `/admin/reviews/requests` | `(app)/reviews/requests/index.tsx` | ✅ Y | — | — |
| `/admin/reviews/platforms` | `(app)/reviews/platforms.tsx` | ✅ Y | — | — |
| `/admin/reviews/widget` | `(app)/reviews/widget.tsx` | ✅ Y | — | — |

### Leads

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/admin/leads` | `leads/index.tsx` | ✅ Y | — | — |
| `/leads/:id` | `leads/[id].tsx` | ✅ Y | — | — |
| `/leads/request` | — | ❌ N | Lead request distributor | LOW |

### Finance & Reports

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/payments` | `payments.tsx` | ✅ Y | — | — |
| `/auto-billing` | `auto-billing.tsx` | ✅ Y | — | — |
| `/admin/autobilling-runs` | — | ❌ N | Auto-billing runs history | LOW |
| `/admin/finance/stripe-payments` | — | ❌ N | Stripe reconciliation | LOW |
| `/admin/finance/bills` | — | ❌ N | Vendor bills | LOW |
| `/impexp` | — | ❌ N | Import/export | N/A |
| `/income-by-category` | `income-by-category.tsx` | ✅ Y | — | — |
| `/income-categories` | `income-categories.tsx` | ✅ Y | — | — |
| `/reports` | `reports.tsx` | ✅ Y | — | — |
| `/reports/business-summary` | `business-reports.tsx` | ✅ Y | — | — |
| `/reports/forecast` | — | ❌ N | Revenue forecast | LOW |
| `/reports/customer-retention` | — | ❌ N | Customer retention report | LOW |
| `/reports/revenue-by-city` | — | ❌ N | Revenue slices | LOW |
| `/reports/revenue-by-crew` | — | ❌ N | Revenue slices | LOW |
| `/reports/revenue-by-customer` | — | ❌ N | Revenue slices | LOW |
| `/reports/gross-sales` | — | ❌ N | Revenue slices | LOW |
| `/reports/invoiced-items` | — | ❌ N | Revenue slices | LOW |
| `/admin/reports/pool-service` | — | ❌ N | Pool service report | LOW |
| `/admin/reports/job-margins` | — | ❌ N | Job margin leaderboard | LOW |
| `/admin/reports/pricing-insights` | — | ❌ N | Pricing insights | LOW |

### SEO & AI Tools

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/seo` | `seo/index.tsx` | ✅ Y | — | — |
| `/seo/articles` | — | ❌ N | Articles list | LOW |
| `/seo/articles/:id` | — | ❌ N | Article editor | N/A |
| `/seo/keywords` | — | ❌ N | Keyword suggestions | LOW |
| `/seo/audit` | — | ❌ N | Site audit | LOW |
| `/seo/rank-grid` | `rank-grid.tsx` | ✅ Y | — | — |
| `/seo/wordpress` | — | ❌ N | WordPress integration | N/A |
| `/gbp` | `gbp/index.tsx` | ✅ Y | — | — |
| `/admin/seo/audits` | `admin/seo/audits.tsx` | ✅ Y | — | — |
| `/admin/seo/content-scorer` | `admin/seo/content-scorer.tsx` | ✅ Y | — | — |
| `/admin/seo/rank-heatmap` | `admin/seo/rank-heatmap.tsx` | ✅ Y | — | — |
| `/admin/seo/topical-map` | `admin/seo/topical-map.tsx` | ✅ Y | — | — |
| `/admin/seo/llm-visibility` | `admin/seo/llm-visibility.tsx` | ✅ Y | — | — |
| `/admin/seo/atlas` | `admin/seo/atlas.tsx` | ✅ Y | — | — |
| `/admin/seo/studio` | `admin/seo/studio.tsx` | ✅ Y | — | — |
| `/admin/seo/reports` | `admin/seo/reports.tsx` | ✅ Y | — | — |
| `/ai-employees` | `ai-employees.tsx` | ✅ Y | — | — |
| `/ai-employees/:id` | — | ❌ N | AI employee detail | MEDIUM |
| `/ai-chat/:id` | `ai-chat/[id].tsx` | ✅ Y | — | — |
| `/landscape` | `landscape.tsx` | ✅ Y | — | — |
| `/cad` | `cad/index.tsx` | ✅ Y | — | — |
| `/cad/editor/:id` | `cad/editor.tsx` | ✅ Y | — | — |
| `/measure` | `measure.tsx` | ✅ Y | — | — |
| `/virtual-bid` | `virtual-bid.tsx` | ✅ Y | — | — |
| `/card` (admin card manager) | `card.tsx` | ✅ Y | — | — |
| `/weather` | `(app)/dispatch/weather.tsx` | ✅ Y | — | — |

### Settings (Admin)

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/settings/tenant` | `settings/tenant.tsx` | ✅ Y | — | — |
| `/settings/promo-codes` | `settings/promo-codes.tsx` | ✅ Y | — | — |
| `/settings/widgets` | `settings/widgets.tsx` | ✅ Y | — | — |
| `/settings/payment-handles` | — | ❌ N | Stripe account settings | MEDIUM |
| `/settings/billing` | — | ❌ N | Billing settings | MEDIUM |
| `/settings/late-fees` | — | ❌ N | Late fee config | LOW |
| `/settings/terms` | — | ❌ N | Terms of service editor | LOW |
| `/settings/legal` | — | ❌ N | Legal documents list | LOW |
| `/settings/legal/:slug` | — | ❌ N | Legal doc editor | N/A |
| `/settings/integrations` | — | ❌ N | Integrations hub | LOW |
| `/settings/maps` | — | ❌ N | Map settings | LOW |
| `/settings/vanity-slugs` | `settings/vanity-slugs.tsx` | ✅ Y | Built (Iter 18) | — |
| `/settings/marketing/media` | — | ❌ N | Marketing media library | LOW |
| `/settings/business-card` | `settings/business-card.tsx` | ✅ Y | Built (Iter 18) | — |
| `/settings/website-seo` | `settings/website-seo.tsx` | ✅ Y | Built (Iter 18) | — |
| `/settings/local-seo` | — | ❌ N | Local SEO checklist | LOW |
| `/settings/ai-brain` | `settings/ai-brain.tsx` | ✅ Y | Built (Iter 18) | — |
| `/settings/notifications` | — | ❌ N | Notification preferences | MEDIUM |
| `/settings/telephony` | — | ❌ N | RingCentral telephony | N/A |
| `/settings/onboarding` | — | ❌ N | Onboarding setup | LOW |
| `/admin/settings/chemical-costs` | — | ❌ N | Chemical cost settings | LOW |
| `/admin/settings/pricing-defaults` | — | ❌ N | Pricing defaults editor | LOW |
| `/admin/settings/service-templates` | — | ❌ N | Service report templates | LOW |
| `/admin/settings/auto-visit-email` | — | ❌ N | Auto visit email settings | LOW |

### Ops Hub Sub-Pages

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/ops` | — | ❌ N | Unified ops hub (tabs for dispatch, schedule, team, etc.) | MEDIUM |
| `/coverage` | `coverage.tsx` | ✅ Y | — | — |
| `/maintenance` | `maintenance.tsx` | ✅ Y | — | — |
| `/pool-service` | `pool-service.tsx` | ✅ Y | — | — |
| `/equipment` | `equipment.tsx` | ✅ Y | — | — |
| `/price-book` | `price-book.tsx` | ✅ Y | — | — |
| `/log-history` | `log-history.tsx` | ✅ Y | — | — |
| `/job-timers` | `job-timers.tsx` | ✅ Y | — | — |
| `/avg-job-time` | `avg-job-time.tsx` | ✅ Y | — | — |
| `/checkins` | `checkins.tsx` | ✅ Y | — | — |

### Other Admin

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/admin/referrals` | `admin/referrals.tsx` | ✅ Y | — | — |
| `/admin/referrals/settings` | — | ❌ N | Referral tier settings | LOW |
| `/admin/referrals/analytics` | — | ❌ N | Referral analytics V2 | LOW |
| `/admin/ai-credits` | `(app)/credits/index.tsx` | ✅ Y | — | — |
| `/admin/chemicals` | — | ❌ N | Chemicals page | LOW |
| `/admin/copilot` | — | ❌ N | AI copilot chat | LOW |
| `/admin/appointments` | `portal/appointments.tsx` | ✅ Y | — | — |
| `/admin/assets` | `(app)/assets/index.tsx` | ✅ Y | — | — |
| `/admin/onboarding` | — | ❌ N | Admin onboarding dashboard | LOW |
| `/admin/onboarding/templates` | — | ❌ N | Onboarding templates | LOW |
| `/admin/onboarding/queue` | — | ❌ N | Onboarding queue | LOW |
| `/admin/recurring-jobs` | — | ❌ N | Recurring jobs manager | MEDIUM |
| `/admin/cfo/reports` | — | ❌ N | CFO reports | LOW |
| `/admin/job-requests` | — | ❌ N | Admin view of tech job requests | MEDIUM |
| `/admin/portal-inbox` | — | ❌ N | Portal chat inbox (admin) | MEDIUM |
| `/admin/templates` | `(app)/templates/index.tsx` | ✅ Y | — | — |
| `/admin/templates/instances/:id` | `(app)/templates/[id].tsx` | ✅ Y | — | — |
| `/admin/training` | — | ❌ N | Admin training management | LOW |
| `/admin/budget` | — | ❌ N | Budget setup | LOW |
| `/admin/budget/dashboard` | — | ❌ N | Budget dashboard | LOW |
| `/admin/budget/wizard` | — | ❌ N | Budget wizard | LOW |
| `/admin/checks` | `(app)/checks/register.tsx` | ✅ Y | — | — |
| `/admin/checks/*` (new, banks, etc.) | — | ❌ N | Check sub-pages | LOW |
| `/admin/inventory` | `(app)/inventory/index.tsx` | ✅ Y | — | — |
| `/admin/inventory/*` (POs, alerts, etc.) | — | ❌ N | Inventory sub-pages | LOW |
| `/admin/dunning/queue` | `(app)/dunning/queue.tsx` | ✅ Y | — | — |
| `/admin/dunning/settings` | — | ❌ N | Dunning settings | LOW |
| `/admin/dunning/analytics` | — | ❌ N | Dunning analytics | LOW |
| `/admin/warranties/*` | — | ❌ N | Warranty admin pages | LOW |
| `/admin/customer-success/churn` | — | ❌ N | Churn dashboard | LOW |
| `/admin/dispatch` | `dispatch.tsx` | ✅ Y | — | — |
| `/communication/:id` | `communication/[id].tsx` | ✅ Y | — | — |
| `/forms/:id` | — | ❌ N | Form editor | N/A |
| `/deals` | `(app)/deals/index.tsx` | ✅ Y | — | — |
| `/deals/:id` (implied) | `(app)/deals/[id].tsx` | ✅ Y | — | — |
| `/analytics` | — | ❌ N | Analytics dashboard | MEDIUM |
| `/csat` | — | ❌ N | CSAT dashboard | LOW |
| `/tenants` | — | ❌ N | Super-admin tenants page | N/A |

### Social Suite

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/social/composer` | `social.tsx` | ⚠️ Partial | One screen for all social — web has 8 sub-pages | LOW |
| `/social/calendar` | — | ❌ N | Social calendar | LOW |
| `/social/library` | — | ❌ N | Social media library | LOW |
| `/social/drafts` | — | ❌ N | Social drafts | LOW |
| `/social/approvals` | — | ❌ N | Social approvals | LOW |
| `/social/bulk-upload` | — | ❌ N | Social bulk upload | N/A |
| `/social/short-links` | — | ❌ N | Social short links | LOW |
| `/social/brand-kit` | — | ❌ N | Social brand kit | LOW |

### Business OS

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/os` (dashboard, SOPs, roles, etc.) | — | ❌ N | Entire Business OS module (8 sub-pages) | LOW |

### Tracking

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/tracking/filter` | `tracking/index.tsx` | ✅ Y | — | — |
| `/tracking/filter/manage` | — | ❌ N | Filter tracker manage | LOW |
| `/tracking/salt-cell` | — | ❌ N | Salt cell tracker | MEDIUM |
| `/tracking/salt-cell/manage` | — | ❌ N | Salt cell manage | LOW |

### Workforce

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/workforce/timesheets` | `timesheets.tsx` | ✅ Y | — | — |
| `/workforce/crew-map` | — | ❌ N | Crew GPS map | MEDIUM |
| `/workforce/job-costing` | — | ❌ N | Job costing dashboard | LOW |
| `/workforce/mileage` | — | ❌ N | Mileage tracking | LOW |

### D2D Sub-Pages

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/d2d` | `(app)/d2d.tsx` + `d2d/index.tsx` | ✅ Y | — | — |
| `/d2d/map` | — | ❌ N | D2D canvassing map | MEDIUM |
| `/d2d/knocks` | — | ❌ N | D2D knocks log | MEDIUM |
| `/d2d/open-leads` | — | ❌ N | D2D open leads | MEDIUM |
| `/d2d/sold-leads` | — | ❌ N | D2D sold leads | MEDIUM |
| `/d2d/leaderboard` | `d2d/leaderboard.tsx` | ✅ Y | — | — |
| `/d2d/report` | `d2d/report.tsx` | ✅ Y | — | — |

### Public Pages (no auth — web-only marketing pages)

| Web Route | Mobile Screen | Parity | Gap | Priority |
|-----------|--------------|--------|-----|----------|
| `/login` | `login.tsx` | ✅ Y | — | — |
| `/signup` | `signup.tsx` | ✅ Y | — | — |
| `/public/card/:slug` | — | N/A | Public NFC card (web link) | N/A |
| `/nfc/:slug` | — | N/A | NFC review card (web link) | N/A |
| `/reviews/r/:token` | — | N/A | Public review landing | N/A |
| `/reviews/:tenant_slug` | — | N/A | Public reviews widget | N/A |
| `/r/review` | — | N/A | Magic-link review | N/A |
| `/r/preferences` | — | N/A | Magic-link unsubscribe | N/A |
| `/quote/:slug` | — | N/A | Public InstaQuote | N/A |
| `/book/:slug` | — | N/A | Public InstaSchedule | N/A |
| `/pay/invoice/:id` | — | N/A | Public invoice pay | N/A |
| `/f/:slug` | — | N/A | Public form | N/A |
| `/csat/:token` | — | N/A | Public CSAT | N/A |
| `/lead-request/:token` | — | N/A | Public lead request | N/A |
| `/public/leads` | — | N/A | Public lead intake | N/A |

---

## Mobile-Only Screens (no web equivalent)

| Mobile Screen | Purpose |
|---------------|---------|
| `(app)/settings/auto-clockin.tsx` | Auto clock-in toggle (mobile-native GPS feature) |
| `(app)/settings/lidar.tsx` | LiDAR scanner settings (mobile hardware) |
| `(app)/d2d.tsx` | Simplified D2D dashboard (combines web sub-pages) |
| `(app)/today.tsx` | Today's quick-view schedule (mobile shortcut) |
| `portal/appointments.tsx` | Appointment queue (mobile shortcut) |
| `work-stream.tsx` | Alternate workstream entry |

---

## Summary by Priority

| Priority | Count | Description |
|----------|-------|-------------|
| **HIGH** | 0 | ✅ All resolved (service reports list/detail, service detail, broadcasts) |
| **MEDIUM** | ~16 | D2D sub-pages, admin sub-features, remaining settings, campaign CRUD (9 resolved in Iter 18) |
| **LOW** | ~50 | Admin settings, reports slices, social suite, warranties, Business OS |
| **N/A** | ~17 | Public web pages, super-admin-only, desktop-only editors |

### HIGH Priority Gaps (Build First)

All 4 HIGH-priority gaps resolved ✅

### MEDIUM Priority Gaps Resolved in Iteration 18

1. **`/portal/invoices/:id`** — Portal invoice navigation wired
2. **`/portal/estimates/:id`** — Portal estimate navigation wired
3. **`/settings/business-card`** — Business card editor
4. **`/settings/ai-brain`** — AI knowledge base
5. **`/settings/local-seo`** — Local SEO checklist
6. **`/settings/website-seo`** — Website SEO analyzer
7. **`/settings/vanity-slugs`** — Vanity slug editor
8. **`/customers/:id/chemistry`** — Pool chemistry dashboard (tech + admin)
9. **`/customers/:id/chemistry`** — Pool chemistry readings (tech route)
