# Phase 41.5c · T2 mobile-drawer stub audit  (Feb 2026)

**Audit-only report — no code changes.** Read-only enumeration of
Tier-2 mobile drawer entries and their current wiring state so a
future Phase B follow-up can prioritise which stubs to convert into
real screens.

## Method

- Source of truth for the drawer tree: `mobile/src/nav/adminNav.ts`.
- Route-to-file resolution: Expo Router convention — `mobile/app{route}.tsx` or `mobile/app{route}/index.tsx`.
- Each screen file was inspected for line count + api usage
  (`api.get/post/put/patch/delete` and `fetch(`) + stub-marker strings
  (`Coming Soon` / `TODO wire`).
- Web equivalent inferred via filename similarity in
  `frontend/src/pages/**/*.{jsx,tsx}` (best-effort match; low-signal
  fits flagged in the notes column).

## Sizing note

The prior handoff called this a "44 T2 entries" audit — the actual
current drawer tree in `mobile/src/nav/adminNav.ts` exposes **29
unique Tier-2 routes**. The 44 figure predates the Phase 51d + 54g
nav consolidations that folded several T2 rows into T1 or removed
them entirely; the corresponding stub files were left behind in
`mobile/app/**` but no longer surface in the drawer.

## Summary table

| Label | Route | Screen file | Classification | Notes |
|-------|-------|-------------|----------------|-------|
| Income Categories | `/settings/income-categories` | `app/settings/income-categories.tsx` | **STUB** | Re-exports `ComingSoonPage`. No web equivalent. |
| Service Categories | `/settings/service-categories` | `app/settings/service-categories.tsx` | **STUB** | Re-exports `ComingSoonPage`. No web equivalent found. |
| Notification Prefs | `/settings/notifications` | `app/settings/notifications.tsx` | **STUB** | Re-exports `ComingSoonPage`. Mature web at `NotificationsPage.jsx`. |
| Referral Analytics | `/admin/referrals/analytics` | `app/admin/referrals/analytics.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web candidate: `WidgetAnalyticsPage.jsx` (loose fit — verify before wiring). |
| Referral Tiers | `/admin/referrals/settings` | `app/admin/referrals/settings.tsx` | **STUB** | Re-exports `ComingSoonPage`. |
| Crews | `/crews` | `app/crews.tsx` | **STUB** | Re-exports `ComingSoonPage`. |
| Time Off Approvals | `/admin/time-off` | `app/admin/time-off.tsx` | **LIVE** | 153-line native screen · 6 API calls · full approve/reject flow · reads `api.timeOff.*`. |
| Weather | `/weather` | `app/weather.tsx` | **STUB** | Re-exports `ComingSoonPage`. Mature web at `WeatherWidget5Day.jsx`. |
| Terms | `/settings/terms` | `app/settings/terms.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `Terms.jsx`. |
| Legal Docs | `/settings/legal` | `app/settings/legal.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `LegalDocs.jsx`. |
| Maps | `/settings/maps` | `app/settings/maps.tsx` | **STUB** | Re-exports `ComingSoonPage`. No direct web equivalent. |
| RingCentral | `/settings/ringcentral` | `app/settings/ringcentral.tsx` | **STUB** | Re-exports `ComingSoonPage`. Mature web at `RingCentralAdmin.jsx`. |
| Chemical Products | `/admin/chemicals` | `app/admin/chemicals.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `ChemicalsPage.jsx`. |
| Appointments | `/admin/appointments` | `app/admin/appointments.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `AppointmentsQueue.jsx`. |
| Tenants (super) | `/tenants` | `app/tenants.tsx` | **STUB** (HIDDEN for non-super) | Re-exports `ComingSoonPage`. Web: `TenantsAdminPage.jsx`. Drawer row gated to `roles: ["super_admin"]`. |
| Customer Tags | `/admin/tags` | `app/admin/tags.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `AdminTagsList.jsx`. |
| Service Reports | `/admin/service-reports` | `app/admin/service-reports.tsx` | **STUB** | Re-exports `ComingSoonPage`. No direct web filename match. |
| Check-in Moderation | `/admin/moderation/checkins` | `app/admin/moderation/checkins.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `ModerationCheckinsPage.jsx`. |
| Client Errors | `/admin/diagnostics/errors` | `app/admin/diagnostics/errors.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `AdminDiagnosticsErrorsPage.jsx`. |
| Supplier Syncs | `/settings/suppliers` | `app/settings/suppliers.tsx` | **DEEP-LINK** | Just-added drawer row deep-links to the existing `/settings/suppliers` scaffold. Screen file is **LIVE** (191 lines · 2 API calls) but no dedicated `/reports/supplier-syncs` mobile page exists yet — `TODO(Phase 54g-B)` comment in `adminNav.ts` marks the wire-up. |
| Email Builder | `/admin/comms/email` | `app/admin/comms/email.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web candidate: `AutoVisitEmailSettings.jsx` (loose fit). |
| SMS Builder | `/admin/comms/sms` | `app/admin/comms/sms.tsx` | **STUB** | Re-exports `ComingSoonPage`. |
| Templates | `/admin/comms/templates` | `app/admin/comms/templates.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `TemplatesLibraryPage.jsx`. |
| Automations | `/admin/comms/automations` | `app/admin/comms/automations.tsx` | **STUB** | Re-exports `ComingSoonPage`. |
| Sends History | `/admin/comms/sends` | `app/admin/comms/sends.tsx` | **STUB** | Re-exports `ComingSoonPage`. |
| Reviews · Dashboard | `/admin/reviews` | `app/admin/reviews.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web candidate: `GoogleReviewSettings.jsx` (loose fit). |
| Reviews · Requests | `/admin/reviews/requests` | `app/admin/reviews/requests.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web candidate: `JobRequestsPages.jsx` (loose fit). |
| Reviews · Platforms | `/admin/reviews/platforms` | `app/admin/reviews/platforms.tsx` | **STUB** | Re-exports `ComingSoonPage`. No web filename match. |
| Reviews · Widget | `/admin/reviews/widget` | `app/admin/reviews/widget.tsx` | **STUB** | Re-exports `ComingSoonPage`. Web: `WidgetEmbedPage.jsx`. |

## Counts breakdown

| Class | Count |
|-------|------:|
| **LIVE** | **1** (`/admin/time-off`) |
| **STUB** | **26** (all re-export the shared `ComingSoonPage`) |
| **DEEP-LINK** | **1** (`/settings/suppliers` via the new "Supplier Syncs" drawer row; underlying screen file is itself LIVE) |
| **DEAD** | **0** — every drawer route resolves to a file, no orphaned routes |
| **HIDDEN** | **1** (`/tenants` is `roles: ["super_admin"]` — technically STUB + role-gated) |
| **Total unique T2 routes** | **29** |

Effective ready-for-production T2 entries: **1 LIVE + 1 DEEP-LINK = 2 of 29 (7%)**. The `ComingSoonPage` shared component was the intentional bridging strategy — it renders a "Coming soon on mobile" screen with an "Open on web" escape hatch that respects `?title=&webPath=` search params, so testers aren't blocked by a broken drawer route.

## Recommended next actions

The mature-web-equivalent column is the sort key — items where a full web page ALREADY exists tend to be the cheapest to bring to mobile parity (backend already returns the data shape, only the RN screen needs building).

### Top 5 "quickest wins" for the next wiring phase

Ranked by (a) presence of a mature web page (b) small API surface (c) high daily-use frequency:

1. **RingCentral · `/settings/ringcentral`** — web `RingCentralAdmin.jsx` is a single-form settings screen (~200 lines), 3 API endpoints (`/api/ringcentral/config` get/patch, `/api/ringcentral/test-call`). Ports cleanly to a `TextInput`-heavy native form. **Estimated: 1 day.**
2. **Chemical Products · `/admin/chemicals`** — web `ChemicalsPage.jsx` is a list + edit form. Techs on the road need to look up SDS/dosage info offline-ish, so mobile parity is high-value. **Estimated: 1-1.5 days.**
3. **Notification Prefs · `/settings/notifications`** — web `NotificationsPage.jsx` is a toggle grid. Small state surface, very used. **Estimated: 0.5-1 day.**
4. **Client Errors · `/admin/diagnostics/errors`** — read-only list. Web `AdminDiagnosticsErrorsPage.jsx` is a table with filters. A collapsed mobile list-view is a couple hundred lines and instantly unblocks admin-on-mobile support workflows. **Estimated: 1 day.**
5. **Weather · `/weather`** — web `WeatherWidget5Day.jsx` is a 5-day forecast tile. Already relevant to the existing mobile dashboard weather widget (`mobile/src/components/weather/WeatherWidget.tsx`) — extend that widget into a full page. **Estimated: 0.5 day.**

### Deferred / lower priority

- **Reviews cluster** (4 T2 entries) — web equivalents are early-stage; wire mobile in the same phase that finalises the web dashboard.
- **Comms cluster** (5 T2 entries) — same story; heavy editor UI on web is expensive to port and low-frequency for on-the-road users.
- **Tenants** — super-admin-only + rarely used; keep as stub with `?title=&webPath=` deep-link.
- **Referrals cluster** (2 T2 entries) — web pages don't fully exist yet; block on Phase-42-referrals.

### Egregious findings — none

Every drawer route resolves to a file. No orphaned entries would crash on click; every stub gracefully lands on `ComingSoonPage` with a working "Open on web" button. **No hotfix needed as a follow-up to this audit.**

## Non-goals honored

- **No code changes.** Every screen file, every drawer entry, every test left exactly as-is.
- **No API/DB writes** — the audit only reads the filesystem + greps.
- **No scraper runs.** No external calls at all.
