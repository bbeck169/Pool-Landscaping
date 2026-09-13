# Mobile — Hide Checklist Chemical Readings

## Status: COMPLETE
**Date**: 2026-09-13

---

## Summary

Mirrored the web's Chemical Readings hide behind a feature flag on the mobile
checklist. The section (heading, reading inputs, reclassify picker, water
analysis card, visible algae toggle) is fully gated by a boolean flag — flip
to `true` to re-enable without touching any other file.

## Flag Approach

**New module created**: `src/config/featureFlags.ts` (9 LOC)

No existing flags module existed in mobile. Created one mirroring the web's
`frontend/src/config/featureFlags.js` pattern with positive polarity.

```ts
export const FEATURE_FLAGS = Object.freeze({
  SHOW_CHECKLIST_CHEMICAL_READINGS: false,
});
```

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `src/config/featureFlags.ts` | 9 | Feature flag module |
| `__tests__/hide-checklist-chemical-readings.test.tsx` | 130 (4 tests) | Flag OFF hides readings; flag ON renders them |

## Files Modified

| File | Change | LOC delta |
|------|--------|-----------|
| `src/components/checklist/PoolChecklistForm.tsx` | Import flag + wrap lines 410-594 in `FEATURE_FLAGS.SHOW_CHECKLIST_CHEMICAL_READINGS ? <>..</> : null` | +8 LOC |

## What is gated

When flag is `false`, the following are hidden:
- "Chemical Readings" section heading
- Service-type reclassify picker (the "wrong template" inline picker)
- All reading input rows (Free Cl, Total Cl, pH, Total Alkalinity, Cyanuric Acid)
- Water analysis AI card
- Visible Algae toggle card

When flag is `true`, all of the above render normally (verified by test 4).

## Submit / Close-job logic

No client-side `readingsAllAnswered` gate exists on mobile (unlike web). The
mobile checklist relies on the backend for validation. Since the web has
already verified the backend accepts empty readings, no additional mobile
close-job gating was needed.

## Test Coverage (4 tests)

1. "Chemical Readings" heading is NOT rendered (flag OFF) ✅
2. Reading input fields (free_chlorine, ph, etc.) are NOT rendered (flag OFF) ✅
3. Visible algae toggle is NOT rendered (flag OFF) ✅
4. Reading fields + algae toggle DO render when flag is ON (contract lock) ✅

## LOC Budget

| Component | LOC |
|-----------|-----|
| Feature flag module | 9 |
| PoolChecklistForm gate | 8 |
| Test file | 130 |
| **Total (excluding tests)** | **17 LOC** (well under 50 cap) |

## Deviations from spec

None.

## Prior dispatches — UNTOUCHED

- Dispatch A (Chase + Onboarding): 14 tests ✅
- Dispatch B (Portal Access): 11 tests ✅
- Send to Customer: 6 tests ✅
- Route-entry classifier: 6 tests ✅
- Chemical readings hide: 4 tests ✅
- **Total: 41 parity tests all green**
