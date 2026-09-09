# Iteration 78 — Trim Chemistry UI Elements on Expo Web Checklist

## What was implemented
- **Removed "Chemicals Used" block on Expo Web**: In `WaterBodyPanel.tsx`, wrapped the entire "Chemicals Used" section (label + chemical rows + "Add chemical" button) in a `Platform.OS !== "web"` guard so it's hidden on Expo Web but preserved on native iOS/Android.
- **Removed "Chemical Readings" heading on Expo Web**: In `PoolChecklistForm.tsx`, wrapped the `<Text>Chemical Readings</Text>` heading in a `Platform.OS !== "web"` guard. The yellow classify prompt below it (with Pool Service / Landscape Service / Other pills) is untouched and fully functional.
- **Guard test added**: `__tests__/chemistry-ui-trim.test.tsx` with 6 assertions covering both web removal and native preservation.

## Files modified
- `/app/mobile/src/components/checklist/WaterBodyPanel.tsx` — Added `Platform` import, wrapped chemicals block in Platform gate
- `/app/mobile/src/components/checklist/PoolChecklistForm.tsx` — Wrapped "Chemical Readings" heading in Platform gate
- `/app/mobile/__tests__/chemistry-ui-trim.test.tsx` — New test file (6 tests)

## What was NOT changed
- Notes block, "Add body of water" CTA, "Visible algae on walls" toggle, footer buttons — all untouched
- "Chemistry Readings" sub-heading inside WaterBodyPanel (per-body readings inputs) — untouched
- "Chemicals Added" / "Recommended Chemicals" in PoolChecklistForm — untouched
- Native iOS/Android surface — both sections preserved via Platform.OS gate
- No backend, no frontend, no estimator files changed

## Verification
- DOM text check: "Chemicals Used" count=0, "Chemical Readings" heading count=0
- "CHEMISTRY READINGS" (per-body sub-heading) and "Notes" still present
- 6/6 RTL tests passing, no regressions in existing suite
