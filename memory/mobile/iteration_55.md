# Iteration 55 — Phase J2: Mobile Parity Sweep (4 features)

## What was implemented

### Feature 1: H4 Waitlist Tab (customers.tsx)
- Extended `statusFilter` type from `"active"|"inactive"|"all"` to include `"waitlist"`
- Added "Waitlist" as 4th segment in the customer list segmented control
- When selected, passes `?waitlisted=true` on the fetch (matches web CustomersList.jsx)
- Stacks with Portal Activation filter (G4b) as intersection
- Persisted via same AsyncStorage key `customerListFilter.status` — accepts `"waitlist"` value
- LOC delta: ~15 lines in customers.tsx

### Feature 2: H10 Revenue Forecast Tile (RevenueForecastTile.tsx)
- Created inline dashboard tile with 5 quick-view tabs: Today · Tomorrow · This Week · This Month · Next Month
- Hits `GET /api/admin/dashboard/revenue-forecast?start=...&end=...` (same endpoint as web)
- Date range helpers mirror web RevenueForecastTile.jsx (isoDay, startOfDay, todayRange, etc.)
- Mounted on dashboard between EBIT tile and weather/hero, admin+ only
- LOC: ~170 lines (new file)

### Feature 3: I5 Payment Method Tiles (PaymentMethodTiles.tsx)
- Green on-file tiles (solid green bg, white text, padlock fields) matching web I5 Wave C
- Dark-red empty state tiles
- Two subsections: Credit/Debit Cards + Bank Accounts
- Delete: TypedDeleteModal with last4 typed input (case-sensitive), uses `delete-typed` endpoint
- Set-default: J1 "Set default" button on non-default cards/banks, uses `set-default` endpoint
- Expires-soon: J1 amber chip (expires soon) and dark-red chip (expired / expires this month)
- Edit: alert explaining immutable PMs + redirects to add-PM screen
- Mounted on customer profile between contact info area and card-required toggle
- LOC: ~340 lines (new file)

### Feature 4: I7 Communication Timeline (CommunicationTimeline.tsx)
- Vertical timeline with dashed left border, colored markers (red=SMS, green=Email)
- TypePill (SMS red, Email green), StatusPill (delivered/sent/queued/failed), relative time
- Admin mount: bottom of customer profile screen (always visible, not tab-gated)
- Portal mount: bottom of portal Messages screen (below chat thread)
- Server strips `actor_user_id` + `delivery_error` for portal variant (component also hides them)
- Load-more via cursor pagination (`before` parameter)
- LOC: ~245 lines (new file)

## API Endpoints Used
- `GET /api/customers?waitlisted=true` (H4)
- `GET /api/admin/dashboard/revenue-forecast?start=...&end=...` (H10)
- `GET /api/payments/stripe/payment-methods/{customerId}` (I5)
- `POST /api/payments/stripe/payment-methods/{pm_id}/delete-typed` (I5)
- `POST /api/payments/stripe/payment-methods/{pm_id}/set-default` (I5/J1)
- `GET /api/customers/{id}/communication-timeline` (I7)

## Files Modified
- `app/(app)/customers.tsx` — Waitlist segment added
- `app/(app)/index.tsx` — RevenueForecastTile mounted on dashboard
- `app/customer/[id].tsx` — PaymentMethodTiles + CommunicationTimeline mounted
- `app/portal/messages.tsx` — CommunicationTimeline (portal variant) mounted

## Files Created
- `src/components/dashboard/RevenueForecastTile.tsx` (170 LOC)
- `src/components/customers/PaymentMethodTiles.tsx` (340 LOC)
- `src/components/customers/CommunicationTimeline.tsx` (245 LOC)

## Build Verification
- Metro: 2166 modules bundled, 0 errors
- Lint: All 7 files clean (0 new issues)
- Screenshot: Waitlist tab visible in customer list segmented control
- Dashboard loading state renders (backend 403 from tunnel — not code issue)
