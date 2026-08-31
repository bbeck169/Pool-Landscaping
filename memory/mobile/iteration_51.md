# Iteration 51 — Phase E: Mobile Parity Sweep (Navigate + Line Items + Reorder)

## Date: 2026-08-31

## Three parity items shipped

### 1. Schedule "Navigate" Button (Google Maps deep-link)
- **New**: `src/components/schedule/NavigateRouteButton.tsx` (135 LOC)
- Builds multi-stop Google Maps URL: `https://www.google.com/maps/dir/?api=1&destination=<last>&waypoints=<mid1|mid2>&travelmode=driving`
- Origin blank (Google uses current location), destination = last non-terminal job's address
- Sorts stops by `route_index` / `route_order`, filters out terminal statuses (completed/cancelled/skipped)
- Supports both address strings and lat/lng coordinates
- Disabled (greyed out) when 0 addressable jobs
- Fallback: Alert with App Store / Play Store link if Google Maps not installed
- **Mounted** in GridView day header between day nav and actions row

### 2. F7 Line Items on Scheduled Jobs
- **Modified**: `src/components/schedule/ScheduleJobEditSheet.tsx`
- Mounted existing `LineItemsSection` component inside the schedule edit sheet
- Appears between Notes block and error text area
- Uses K2 endpoints (same as job detail page) — fully independent CRUD
- Admin: pricebook picker, category, unit price, writeback, totals
- Tech: quantity + description (read-only pricing per RBAC)
- Offline: banner + disabled add/edit/delete

### 3. Reorder Route Drag-and-Drop Parity
- **Modified**: `app/(app)/schedule/calendar.tsx`
- Drag handle moved from LEFT to RIGHT (mobile convention)
- Position badge restyled as green circle (matching web's visual)
- Added header copy: "Reorder route — Drag jobs to reorder. Position updates automatically."
- Added visible Save/Cancel bar when in rearrange mode
- Fixed reorder payload: `ordered_job_ids` (was `job_ids`) + `tech_user_id` + `date` — matches web contract
- Fixed auto-save-on-drag payload to match same shape
- Up/down arrow buttons retained as fallback, properly disabled at boundaries

## Files modified
| File | Type | LOC |
|------|------|-----|
| `src/components/schedule/NavigateRouteButton.tsx` | New | 135 |
| `src/components/schedule/ScheduleJobEditSheet.tsx` | Modified | +4 lines |
| `app/(app)/schedule/calendar.tsx` | Modified | +95 lines (nav btn mount, reorder UI, styles) |
| `__tests__/mobile-navigate-route.test.tsx` | New | 110 |
| `__tests__/mobile-schedule-lineitems.test.tsx` | New | 81 |
| `__tests__/mobile-reorder-route.test.tsx` | New | 78 |

## Test Results
| Suite | Tests | Status |
|-------|-------|--------|
| mobile-navigate-route | 7/7 | ✅ |
| mobile-schedule-lineitems | 2/2 | ✅ |
| mobile-reorder-route | 5/5 | ✅ |
| mobile-line-items-list | 5/5 | ✅ |
| mobile-line-items-add | 4/4 | ✅ |
| mobile-line-items-edit | 3/3 | ✅ |
| mobile-line-items-error-inline | 2/2 | ✅ |
| mobile-line-items-offline | 2/2 | ✅ |
| **Total Phase E** | **30/30** | ✅ |

## Regression check
- subscriptions-mobile: 15/15 ✅
- Metro: Bundled 2226 modules, no errors

## Mobile Primitives Reused
| Primitive | Source |
|-----------|--------|
| `useAuth` | `@/src/auth` |
| `useOnline` | `@/src/offline` |
| `api` | `@/src/api` |
| `Linking` | `react-native` |
| `LineItemsSection` | `@/src/components/jobs/LineItemsSection` (iteration 50) |
| `react-native-draggable-flatlist` | Already installed (v4.0.3) |
| Design tokens | `@/src/theme` |

## Known Issues
- Expo preview tunnel sleeping (known recurring issue, not code)
- calendar.tsx has 1 harmless stale eslint-disable-directive warning (pre-existing)
- ScheduleJobEditSheet has 1 pre-existing unused ActivityIndicator import

## API Endpoints Used
- `GET /api/jobs/{jid}/line-items` — line items list
- `POST /api/jobs/{jid}/line-items` — add line item
- `PATCH /api/jobs/{jid}/line-items/{lid}` — edit line item
- `DELETE /api/jobs/{jid}/line-items/{lid}` — remove line item
- `GET /api/pricebook-items?q=...` — pricebook search
- `GET /api/pricebook/categories?active=true` — category list
- `POST /api/jobs/reorder` — reorder route (payload: `{ ordered_job_ids, tech_user_id, date }`)
- Google Maps deep-link (not API, just URL opening)

## No backend changes required ✅
