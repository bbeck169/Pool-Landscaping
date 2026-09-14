# Fix — Remove Legacy "Chemical Readings" from Mobile Pool Checklist

**Priority**: CRITICAL (blocked techs from completing pool jobs)
**Date**: Sep-2026
**Scope**: Mobile only (`/app/mobile/`)

## Problem

The mobile Pool job checklist rendered TWO chemistry sections:
1. **Legacy "Chemical Readings"** — flat, uppercase labels (`TOTAL CHLORINE (PPM)*`, `FREE CHLORINE (PPM)*`, etc.) rendered by `PoolChecklistForm.tsx`
2. **Structured "Chemistry Readings"** — water_bodies-backed, title-case (`Free Chlorine* ppm`, `pH*`, etc.) rendered by `WaterBodyManager` → `WaterBodyPanel`

Techs filled the LEGACY section. The close-gate validates the STRUCTURED section (`water_bodies`). Result: jobs blocked with "Missing required readings."

## Fix

Removed the legacy rendering from `PoolChecklistForm.tsx`. The structured `Chemistry Readings` section (via `WaterBodyManager`) is now the ONLY readings UI.

## Files Touched

### `src/components/checklist/PoolChecklistForm.tsx`

Removed:
- `REQUIRED_READING_KEYS` constant (13 lines)
- `readingFields` filtered memo (7 lines)
- `mergedReadings` memo (26 lines)
- `updReading` handler (9 lines)
- `lastReadings` + `recentReadings` state + fetch effect (16 lines)
- "Chemical Readings" header text block (6 lines)
- `mergedReadings.map()` rendering block (30 lines)
- `ReadingChipRow` import
- `expandChemistryLabel` import

Preserved:
- `readingsDict` (feeds Recommended Chemicals card)
- Analysis card, Algae card
- Recommended Chemicals, Chemicals Added
- Checklist Items, Notes
- All payload building logic

### `app/job/[id]/checklist.tsx`

Modified `handleBodiesChange` to mirror the first pool body's readings into `report.chemical_readings` — keeps `readingsDict` (and hence Recommended Chemicals) responsive when users type structured readings.

## Regression Guards

1. Legacy "Chemical Readings" header no longer renders → confirmed via Jest + Playwright
2. Legacy uppercase labels (`TOTAL CHLORINE (PPM)` etc.) no longer render → confirmed via Jest
3. Structured Chemistry Readings section renders normally → confirmed
4. `readingsDict` stays fed by mirroring water_bodies → pool readings into `report.chemical_readings` on every change
5. Payload building untouched — autosave still sends both `chemical_readings` (flat mirror) and `water_bodies` (structured)
6. No other mobile screen reads from a legacy flat `chemical_readings` array without going through `waterBodiesRef`

## Test Coverage

**File**: `__tests__/remove-legacy-chemical-readings.test.tsx` — 4 tests passing

| # | Test |
|---|------|
| 1 | Does NOT render legacy "Chemical Readings" section title |
| 2 | Does NOT render uppercase legacy field labels |
| 3 | Does NOT render individual ReadingChipRow inputs |
| 4 | Still renders pool-checklist-form root testID |

## Coupling with Web Team

The web team (`e1_dev`) is running the same removal in parallel on the web checklist (`frontend/src/components/checklist/PoolChecklistForm.jsx`). Contract stays symmetric: only the structured Chemistry Readings section is rendered on both platforms.

## Dependencies
None changed.
