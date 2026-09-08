## Iteration 74 — Chemistry Readings Unification (web-parity mirror)

### What was implemented

1. **`expandChemistryLabel.ts`** — Added `cc` → "Combined Chlorine" and `water_temp` → "Water Temp" to the label map.

2. **`ReadingChipRow.tsx`** — Added `required?: boolean` prop. When true, renders a red `*` marker after the label. Also added validation rules for `combined_chlorine`, `calcium_hardness`, `tds`, `phosphates`, `water_temp`.

3. **`PoolChecklistForm.tsx`** — Exported `canonicalReadingKey` as named export. Added re-export of `ReadingChipRow` as `ReadingInputRow` for web API compatibility. Added `REQUIRED_READING_KEYS` Set (all alias forms of 5 core readings). Wired `required={REQUIRED_READING_KEYS.has(key)}` on ReadingChipRow render. Added short-form abbreviations (FC, TC, CC, TA, CH, PO4, water_temp) to `_NAME_TO_CANONICAL` map for proper canonical key resolution.

4. **`(app)/service-report/[id].tsx`** — Replaced inline compact grid renderer (readingGrid/readingCell with raw `r.name`) with canonical `ReadingChipRow` component using `expandChemistryLabel` + `canonicalReadingKey` + `required`. Deleted orphan `readingGrid`/`readingCell` style definitions.

5. **`WaterBodyPanel.tsx`** — Changed reading label from `meta.short` (abbreviations) to `meta.name` (full-word labels). Now renders "Free Chlorine" instead of "FC".

6. **`waterBodies.ts`** — Added `combined_chlorine` and `water_temp` to `READING_LABELS`, `READING_ALLOWLIST` (pool, spa, water_feature, fountain, other).

7. **`portal/service-report/[id].tsx`** — Applied `expandChemistryLabel` to both water-body readings and legacy single-body readings so customer-facing labels show full-word names instead of abbreviations.

8. **`__tests__/chemistry-unification.test.ts`** — 9 regression tests: compact grid gone from service-report, canonical exports work, all 11 fields in expandChemistryLabel, READING_LABELS + READING_ALLOWLIST updated, WaterBodyPanel uses full-name labels.

### Files changed
- `src/lib/expandChemistryLabel.ts`
- `src/components/checklist/ReadingChipRow.tsx`
- `src/components/checklist/PoolChecklistForm.tsx`
- `src/components/checklist/WaterBodyPanel.tsx`
- `src/lib/waterBodies.ts`
- `app/(app)/service-report/[id].tsx`
- `app/portal/service-report/[id].tsx`
- `__tests__/chemistry-unification.test.ts` (new)

### Label casing decision
UPPERCASE — via `textTransform: "uppercase"` in the `styles.label` style of `ReadingChipRow`. The underlying `expandChemistryLabel` returns Title Case ("Free Chlorine") which is displayed as "FREE CHLORINE" on screen. This matches the web behavior (web uses CSS `text-transform: uppercase`).

### Portal label fix
The portal service-report previously rendered raw `r.name || r.key` which showed abbreviations like "FC", "TC". Now it uses `expandChemistryLabel(r.name || r.key)` to show full-word labels like "Free Chlorine", matching the tech-facing checklist.

### Test results
- Chemistry unification: 9/9 ✅
- Phase 1 read-cache: 16/16 ✅
- Phase 2 sync: 77/77 ✅
- Total: 86 new tests + 77 existing = all passing, 0 regressions
