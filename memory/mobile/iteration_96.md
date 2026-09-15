# Iteration 96 — Phase CHEM5: Unify all water-body forms + remove duplicate

## What was implemented
- Completed Phase CHEM5: Reversed CHEM4's `isPrimary` gating so that Chemistry Readings and Chemicals Used sections render on ALL bodies, including the primary pool (body 0).
- Removed the standalone "Chemicals Added" top-level block from `PoolChecklistForm.tsx` (section title, `ChemicalDropdownStack`, quick-add button, and `ChemicalPickerSheet`).
- Updated `chem4-isprimary-suppression.test.tsx` to assert that body 0 (`isPrimary=true`) NOW renders both Chemistry Readings AND Chemicals Used sections with header "Pool".

## Web-to-mobile mapping decisions
- All chemistry and chemical data is now centralized per-body inside `WaterBodyPanel`, matching the unified web form.
- The `isPrimary` prop is retained solely for header label differentiation: `isPrimary=true` → "Pool", `isPrimary=false` → "Additional Body of Water Chemicals".

## Files modified
- `/app/mobile/src/components/checklist/PoolChecklistForm.tsx` — Removed standalone Chemicals Added block (lines 629-661), `ChemicalPickerSheet` import, and `pickerOpen` state.
- `/app/mobile/__tests__/chem4-isprimary-suppression.test.tsx` — Flipped assertions for tests 1 & 2; updated test descriptions to reflect CHEM5.

## Dependencies installed
- None

## Known issues
- Pre-existing lint warnings in PoolChecklistForm.tsx (unused vars: customerId, chemicalsCatalog, internalNotes, inStep, analyzing, addChem, updChem, rmChem, analyzeWater) — all pre-date CHEM5.
- Pre-existing `act()` warnings in Jest from `@expo/vector-icons`.

## Verification
- Jest: 6/6 tests pass in `chem4-isprimary-suppression.test.tsx`
- Screenshot testID checks: `water-body-panel-0` ✅, `water-body-chem-header-0` ✅, `chem-picker-open` = 0 ✅, `water-body-type-badge-0` = "Pool" ✅
