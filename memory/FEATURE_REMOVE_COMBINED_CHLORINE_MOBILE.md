# Mobile — Revert Hide-All Chemical Readings + Remove Combined Chlorine

## Status: COMPLETE
**Date**: 2026-09-13

---

## Step 1 — Revert hide-all feature flag

| Action | Detail |
|--------|--------|
| Deleted | `src/config/featureFlags.ts` (entire file — only contained `SHOW_CHECKLIST_CHEMICAL_READINGS`) |
| Deleted | `__tests__/hide-checklist-chemical-readings.test.tsx` (4 tests that asserted flag behavior) |
| Reverted | `PoolChecklistForm.tsx`: removed `FEATURE_FLAGS` import + `SHOW_CHECKLIST_CHEMICAL_READINGS ? <>...</> : null` gate. Section now always renders. |

## Step 2 — Broken legacy test recovery

| Test file | Tests | Status after revert |
|-----------|-------|---------------------|
| `__tests__/chemistry-ui-trim.test.tsx` | 6 | ✅ All pass |
| `__tests__/checklist-service-type-picker.test.tsx` | 4 | ✅ All pass |

Both suites were broken because they asserted on elements the hide-all flag was hiding. After reverting the flag gate, the section renders again and all 10 legacy tests pass with zero changes to the test files.

## Step 3 — Surgical removal of Combined Chlorine

### Changes

| File | Change | LOC |
|------|--------|-----|
| `PoolChecklistForm.tsx` | Filter `combined_chlorine` out of `readingFields` useMemo via `canonicalReadingKey` check. Kept canonical key mapping entries for historic data reads. | +3 |
| `src/lib/waterBodies.ts` | Removed `combined_chlorine` from `READING_ALLOWLIST.pool` and `READING_ALLOWLIST.other`. | -2 |

### Preserved for historic reads

| Item | Kept? | Reason |
|------|-------|--------|
| `_NAME_TO_CANONICAL["combined chlorine"]` | ✅ Yes | Historic readings may carry this key; canonical mapping needed for display |
| `_NAME_TO_CANONICAL["cc"]` | ✅ Yes | Same |
| `READING_LABELS.combined_chlorine` | ✅ Yes | Historic display label |

### Submit payload decision

**Option A (matching web)**: `combined_chlorine` is dropped from the outbound payload entirely. The `readingFields` filter ensures it's never in the merged readings array, so it's never included in the save/close-job payload. Backend accepts variable-length reading arrays.

## Files Modified

| File | Change |
|------|--------|
| `src/components/checklist/PoolChecklistForm.tsx` | Removed flag import + gate (revert), added CC filter in `readingFields` useMemo |
| `src/lib/waterBodies.ts` | Removed `combined_chlorine` from pool + other allowlists |

## Files Deleted

| File | Reason |
|------|--------|
| `src/config/featureFlags.ts` | Only contained the now-reverted flag |
| `__tests__/hide-checklist-chemical-readings.test.tsx` | Tested the now-reverted flag |

## Files Created

| File | Tests | Purpose |
|------|-------|---------|
| `__tests__/remove-combined-chlorine.test.tsx` | 4 | Post-revert guard + CC removal contract |

## Test Coverage (4 new tests)

1. Chemistry Readings section IS rendered (post-revert guard) ✅
2. Combined Chlorine input NOT rendered even if backend sends it ✅
3. Core fields (FC, TC, pH, TA, CYA) ARE rendered ✅
4. `readingFields` filter strips `combined_chlorine` from merged list ✅

## Full suite

- Dispatch A (Chase + Onboarding): 14 ✅
- Dispatch B (Portal Access): 11 ✅
- Send to Customer: 6 ✅
- Route-entry classifier: 6 ✅
- Legacy checklist tests: 10 ✅ (recovered)
- Combined Chlorine removal: 4 ✅
- **Total: 51 tests all green**
