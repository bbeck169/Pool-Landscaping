# Iteration 17 — HIGH-Priority Parity Gap Build (STEP 2)

## What was implemented

### New Screens (4)

1. **`/portal/service-reports`** (portal/service-reports.tsx)
   - Customer service reports list
   - Kind chips: Pool service (blue), Landscape service (green), Service (neutral)
   - Date formatting, tech name display
   - Loading skeleton (4 shimmer cards), empty state, error banner
   - Pull-to-refresh via RefreshControl
   - Taps navigate to `/portal/service-report/{id}`

2. **`/portal/service-report/{id}`** (portal/service-report/[id].tsx)
   - Rich detail view matching web's PortalServiceReportDetail
   - Header card: kind icon, kind chip, status pill, title, date, tech, address
   - Algae observation banner (yellow, pool-only)
   - Water chemistry readings grid with qualitative band chips (Below=blue, Average=green, Above Avg=amber, Elevated=red)
   - Chemicals added list with name + amount + unit
   - Service checklist with check/uncheck visual indicators
   - Customer notes section
   - Visit photos in 2-column grid
   - Pull-to-refresh, loading skeleton, error state

3. **`/portal/service/{id}`** (portal/service/[id].tsx)
   - Customer-facing job detail (simpler than admin /job/{id})
   - Status pill, title, scheduled date, technician name, address
   - Service checklist with done/undone icons
   - Water reading chips
   - Photos grid (3-column)
   - Notes section
   - Pull-to-refresh, loading skeleton

4. **`/marketing/broadcasts`** (marketing/broadcasts.tsx)
   - Admin-only broadcasts page (role gate: admin/super_admin)
   - Batch list with expandable rows
   - Stat pills per batch: sent (green), failed (red), suppressed (amber), no-contact (gray)
   - Relative time display (Xs/Xm/Xh/Xd ago)
   - Expandable detail: recipients list with channel badge + recipient + delivery status
   - Compose bottom sheet (full modal):
     - Channel selection: Email/SMS toggles
     - Subject (email-only), Body with merge tag support
     - Live preview: estimated recipients, suppressed counts, cost hint
     - Send confirmation modal with "can't be undone" warning
   - Refresh button, pull-to-refresh, loading skeleton, empty state

### Navigation Wiring

- **Portal Home**: Added "Service Reports" card to Explore grid (between Service Records and Book Service)
- **Portal Services**: Rewrote to use inline card UI (was using JobCard → admin `/job/{id}`). Now navigates to customer-scoped `/portal/service/{id}`
- **Admin More**: Added "Broadcasts" link in admin links section

## Web-to-Mobile Mapping

| Web Route | Mobile Screen | Status |
|-----------|--------------|--------|
| `/portal/service-reports` | `portal/service-reports.tsx` | ✅ Built |
| `/portal/service-reports/:id` | `portal/service-report/[id].tsx` | ✅ Built |
| `/portal/services/:id` | `portal/service/[id].tsx` | ✅ Built |
| `/marketing/broadcasts` | `marketing/broadcasts.tsx` | ✅ Built |

## API Endpoints Used

- `GET /api/customers/me/service-reports` — Service reports list
- `GET /api/customers/me/service-reports/{id}` — Service report detail
- `GET /api/jobs/{id}` — Job detail (customer perspective)
- `GET /api/mass-messaging/batches` — Broadcast batches list
- `GET /api/mass-messaging/batches/{id}` — Batch detail with recipients
- `POST /api/mass-messaging/preview` — Live preview with estimated counts
- `POST /api/mass-messaging/send` — Send broadcast with confirm token

## Known Issues

- Mobile tunnel CDN is serving cached "Preview Unavailable" page — platform-level issue
- Screenshots could not be captured due to tunnel CDN cache
- Local service runs fine (port 3001, 200 response, 1897 modules bundled)

## Dependencies Installed

None — all dependencies already present in existing setup.

## Remaining HIGH-priority Gaps

All 4 HIGH-priority gaps from MOBILE_PARITY_GAP.md are now resolved. ✅
