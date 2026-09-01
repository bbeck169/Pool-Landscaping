# Iteration 53 — Phase G4b: Portal Activation Filter (Expo Mobile)

## Date: 2026-08-31

## What was shipped

### Portal Activation Filter on Customer List
- **Modified**: `app/(app)/customers.tsx`
  - Added `portalFilter` state: `"all" | "activated" | "not_activated"`, default "all"
  - AsyncStorage persistence via key `customerListFilter.portalStatus` (matches F6b convention)
  - `load()` appends `&portal_status=<value>` when not "all"
  - `portalFilter` added to `load`'s dependency array → refetch on change, page reset to 1
  - Horizontal chip row UI with key icon prefix: `[All] [Activated] [Not activated]`
  - Active chip styled teal (#0D9488), visually distinct from F6b's grey/white segmented control
  - Stacks with F6b Active/Inactive as intersection query (both params compose on the URL)

### Test file
- **New**: `__tests__/mobile-portal-filter.test.tsx` (178 LOC, 7 tests)

## Files
| File | Type | Change |
|------|------|--------|
| `app/(app)/customers.tsx` | Modified | +28 lines (state, URL param, UI, styles) |
| `__tests__/mobile-portal-filter.test.tsx` | New | 178 LOC |

## Test Results
| Suite | Tests | Status |
|-------|-------|--------|
| mobile-portal-filter | 7/7 | ✅ |

## Regression
- mobile-customer-status-filter: 5/5 ✅
- mobile-crew-filter: 7/7 ✅
- subscriptions-mobile: 15/15 ✅
- mobile-line-items (5 suites): 16/16 ✅
- **Total regression: 43/43** ✅

## F6b persistence layer
- Extended independently — added `portalFilter` state and `PORTAL_KEY` alongside existing `statusFilter` and `STATUS_KEY`. Both use the same `storage` import from `@/src/utils/storage`. No refactoring of F6b needed.

## Surprises
- None. The change was surgical — 28 lines of production code in customers.tsx.
- The `useEffect` for storage reads both keys in one effect (consolidated from F6b's separate effect).
- Metro bundled clean at 2134 modules.
