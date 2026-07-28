# Iteration 25 — Fix Batch: Header Layout + Next Service Day + Demo Logins

## What was implemented

### FIX 1 — Appointments page Header layout (P0)
- **Root cause**: `Header` component in `widgets.tsx` had `flexDirection: "row"` on the outer container, causing Breadcrumbs to sit as a horizontal sibling of the title row. This squeezed the title's `flex: 1` container to near-zero width when breadcrumbs were present.
- **Fix**: Removed `flexDirection: "row"` from outer `header` style (now defaults to column). Added new `headerRow` style with `flexDirection: "row"` wrapping title+right. Breadcrumbs naturally sit below.
- **Impact**: Affects ALL screens using `Header` — verified both Appointments and Portal Home render correctly.

### FIX 2 — "Next Service Day" tile on Portal Home (P1)
- Added tile below Quick Actions grid in `portal/home.tsx`
- Uses existing `data.next_service` from `GET /api/dashboard` endpoint (already fetched)
- Shows date box (day/month/weekday), service title, tech name, address, chevron
- Empty state: "No upcoming service scheduled" with calendar icon
- Tappable — navigates to `/job/{id}`

### FIX 3 — Demo login buttons for preview builds (P1)
- Added 4 demo login buttons gated on `process.env.EXPO_PUBLIC_ENV === "preview"`
- Accounts: Super Admin, Admin, Customer, Pool Tech with `password123`
- Added `EXPO_PUBLIC_ENV=preview` to `.env`
- When env is not `preview`, renders nothing (fail-safe)

### Tests
- 14 tests across 3 suites, all passing
- `demo-login.test.tsx`: 5 tests (render preview, hide production, hide unset, Super Admin tap, Customer tap)
- `next-service-day.test.tsx`: 4 tests (populated tile, empty state, navigation, tech name)
- `appointments-header.test.tsx`: 5 tests (title/subtitle visible, left prop, full page render, empty state, data rows)

### Jest infrastructure
- Installed: `jest`, `jest-expo`, `@testing-library/react-native@12.9.0`, `@types/jest`, `react-test-renderer`
- Created `jest.config.js` with `jest-expo` preset and module name mapper

## Dependencies installed
- jest, jest-expo, @testing-library/react-native@12.9.0, @types/jest, react-test-renderer (devDependencies)

## Known issues
- None. All fixes verified via screenshot + tests.

## Web-to-mobile mapping decisions
- Next Service Day tile uses `/api/dashboard` endpoint (same as web frontend), not a dedicated endpoint
- Demo login section mirrors web's prior demo accounts UI pattern, re-gated on EXPO_PUBLIC_ENV
