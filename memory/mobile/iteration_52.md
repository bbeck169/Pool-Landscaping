# Iteration 52 — Phase F6b: Mobile Filter Bundle (Crew + Customer Status)

## Date: 2026-08-31

## Two deliverables shipped

### 1. Schedule "All Crews" Filter
- **New**: `src/components/schedule/CrewFilterBar.tsx` (222 LOC)
  - Single-select dropdown: "All crews" + each crew option
  - When crew selected: pill turns brand color, member chips appear below
  - Crew picker modal with color dots, checkmarks, empty state
  - Selecting "All crews" clears filter
- **Modified**: `app/(app)/schedule/calendar.tsx`
  - Added state: `crews`, `crewFilter`, `crewMembers`, `allTechs`
  - Fetches `GET /api/crews` + `GET /api/users?role=tech` on mount
  - `load()` appends `&crew_id=X` when crew selected
  - Crew-filtered fetches skip write-through cache (prevents overwriting full cache with subset)
  - `handleCrewSelect()` resolves member names from crew.members or allTechs lookup
  - CrewFilterBar mounted in GridView filter row alongside NavigateRouteButton

### 2. Customer List Active/Inactive Filter
- **Modified**: `app/(app)/customers.tsx`
  - Three-state segmented control: **Active | Inactive | All**
  - Default: Active (matches daily workflow)
  - `load()` appends `?is_active=true|false` or omits param for "All"
  - Persists selection to AsyncStorage (key: `customerListFilter.status`)
  - Loads persisted value on mount
  - Styled as iOS-style segmented control with shadow on active tab

## Backend extension needed?
- **Crews**: NO — `GET /api/crews` and `GET /api/jobs?crew_id=X` already live from F6a.
- **Customer is_active**: AUDIT NEEDED — The `is_active` param is being sent. If the backend doesn't filter on it, a backend change is required. Flag for `e1_dev` to verify.
- **Web missing Active/Inactive filter**: The web customer list does NOT appear to have this specific segmented filter. Flag as web follow-up.

## Files
| File | Type | LOC |
|------|------|-----|
| `src/components/schedule/CrewFilterBar.tsx` | New | 222 |
| `app/(app)/schedule/calendar.tsx` | Modified | +30 lines (state, fetch, load, mount) |
| `app/(app)/customers.tsx` | Modified | +35 lines (state, filter, segmented control, styles) |
| `__tests__/mobile-crew-filter.test.tsx` | New | 141 |
| `__tests__/mobile-customer-status-filter.test.tsx` | New | 157 |

## Test Results
| Suite | Tests | Status |
|-------|-------|--------|
| mobile-crew-filter | 7/7 | ✅ |
| mobile-customer-status-filter | 5/5 | ✅ |
| **Phase F6b total** | **12/12** | ✅ |

## Regression check
- subscriptions-mobile: 15/15 ✅
- mobile-line-items (all 5 suites): 16/16 ✅
- mobile-navigate-route: 7/7 ✅
- mobile-reorder-route: 5/5 ✅
- **Total regression: 43/43** ✅

## Known Issues
- Expo preview tunnel sleeping (known recurring, not code)
- `customers.tsx` has 1 pre-existing unused `formatCustomerName` import
- `calendar.tsx` has 1 pre-existing stale eslint-disable directive
