# Mobile Route-Entry Classifier Gap Fix

## Status: COMPLETE
**Date**: 2026-09-13

---

## Audit Report

### Screens assessed for route-entry classifier gap

| Screen | Had `mapApiError`? | Error behavior before fix | Gap? |
|--------|-------------------|---------------------------|------|
| `app/job/[id].tsx` | ✅ YES | Full classified error state with retry | **NO** — already fixed |
| `app/quote/[id].tsx` | NO (only via child) | Silent catch → cache fallback → blank `null` screen on 403 | **YES** |
| `app/customer/[id].tsx` | NO | Silent catch → cache fallback → blank `null` screen on 403 | **YES** |
| `app/invoice/[id].tsx` | NO | Catch sets generic message → renders "Failed to load invoice" with generic icon | **YES** |

### Root cause confirmed

The screens' `load()` catch blocks either:
1. Swallowed errors silently (quote, customer) — resulting in blank screen on 403
2. Used `e?.message` directly without classification (invoice) — resulting in raw API error text

In all three cases, `mapApiError` was not invoked, so a 403 was never classified as "Not authorized".

## Implementation

### Pattern applied (matching `job/[id].tsx` reference)

Each affected screen now:
1. Stores `rawLoadError` (the caught error object) alongside the existing error state
2. On render, passes `rawLoadError` through `mapApiError()` to get classified `{ title, message, kind }`
3. Uses `errorKindIcon(kind)` for the correct icon (lock for 403, cloud-offline for network)
4. Shows retry button
5. Preserves cache fallback — if a cached version exists, it still renders (no regression)

### LOC per screen

| Screen | Lines added | Lines modified |
|--------|-------------|----------------|
| `app/quote/[id].tsx` | 27 (error state block) | 8 (catch block, imports, state) |
| `app/customer/[id].tsx` | 27 (error state block) | 10 (catch block, imports, state) |
| `app/invoice/[id].tsx` | 5 (extra lines in existing error block) | 5 (catch block, imports, state) |
| **Total** | **~82 LOC** | Under 100 LOC cap ✅ |

## Files Modified

| File | Change |
|------|--------|
| `app/quote/[id].tsx` | Added `loadError`/`rawLoadError` state, error classification in catch, classified error render block |
| `app/customer/[id].tsx` | Same pattern as quote |
| `app/invoice/[id].tsx` | Added `rawLoadError` state, store in catch, use `mapApiError` in existing error block |

## Files Created

| File | Tests | Purpose |
|------|-------|---------|
| `__tests__/route-entry-classifier.test.tsx` | 6 | 403 → "Not authorized" + network → "You're offline" for all 3 screens |

## Test Coverage (6 tests)

1. Quote detail 403 → renders "Not authorized" ✅
2. Quote detail network error → renders "You're offline" ✅
3. Customer detail 403 → renders "Not authorized" ✅
4. Customer detail network error → renders "You're offline" ✅
5. Invoice detail 403 → renders "Not authorized" ✅
6. Invoice detail network error → renders "You're offline" ✅

## Deviations

None — all three screens identified in the audit were fixed with the same pattern.

## Prior Dispatches — UNTOUCHED

- Dispatch A (Chase + Onboarding Tile): 14 tests ✅
- Dispatch B (Portal Access Panel): 11 tests ✅
- Send to Customer: 6 tests ✅
- Route-entry classifier: 6 tests ✅
- **Total: 37 parity tests all green**
