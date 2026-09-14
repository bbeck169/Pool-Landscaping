# Feature: Chemistry Gate Mobile Fix — ref→report Mirror + Payload Consistency

## Problem
The multi-body pool checklist screen kept typed readings only in `waterBodiesRef.current` (an in-memory ref) and did NOT mirror them back into `report.water_bodies` or `report.chemical_readings`. As a result:

- **Autosave (`flushSave`)**: Built PATCH payload with `chemical_readings` from stale `reportRef.current`, not from the authoritative `waterBodiesRef.current`.
- **Offline submit (`submitOffline`)**: Passed `reportRef.current` which lacked fresh water body data.
- **Online close (`doCloseJob`)**: Same stale-payload issue via `flushSave`.

The backend received empty or stale `water_bodies`/`chemical_readings`, which wiped previously-saved readings and failed the job-close chemistry gate.

## Files Touched

### `mobile/src/lib/waterBodies.ts`
- **Added `flattenPoolReadings(bodies: WaterBody[])`** (line ~147): Rebuilds the flat `chemical_readings` mirror from structured `water_bodies[]`. One flat entry per body/reading pair with `body_id`, `body_label`, `key`, `name`, `value`, `unit`. Matches the backend `flatten_pool_readings` shape.

### `mobile/app/job/[id]/checklist.tsx`

#### Import (line 53)
- Added `flattenPoolReadings` to the import from `@/src/lib/waterBodies`.

#### `handleBodiesChange` (line ~526)
**Before:**
```js
const handleBodiesChange = useCallback((next: WaterBody[]) => {
  setWaterBodies(next);
  waterBodiesRef.current = next;
  setHighlightBodies({});
  scheduleAutosave();
}, [scheduleAutosave]);
```

**After:**
```js
const handleBodiesChange = useCallback((next: WaterBody[]) => {
  setWaterBodies(next);
  waterBodiesRef.current = next;
  setHighlightBodies({});
  // Mirror ref → report: rebuild flat chemical_readings + water_bodies.
  const flatReadings = flattenPoolReadings(next);
  patchReport({ water_bodies: next, chemical_readings: flatReadings });
}, [patchReport]);
```
- **Mirror timing**: Runs synchronously on every `WaterBodyPanel` reading change. The `patchReport` call updates `reportRef.current` immediately and schedules autosave (800ms debounce).
- **Dependency change**: Now depends on `patchReport` instead of `scheduleAutosave` (patchReport internally calls scheduleAutosave).

#### `flushSave` PATCH payload (line ~413)
**Before:**
```js
const patchBody = {
  chemical_readings: current.chemical_readings, // ← STALE
  ...
};
if (bodies.length > 0) {
  patchBody.water_bodies = bodies;
}
```

**After:**
```js
const patchBody = {
  chemical_readings: current.chemical_readings, // fallback for non-pool
  ...
};
if (bodies.length > 0) {
  patchBody.water_bodies = bodies;
  patchBody.chemical_readings = flattenPoolReadings(bodies); // ← FRESH
}
```
- At payload-build time, if bodies exist, `chemical_readings` is rebuilt from the authoritative `waterBodiesRef.current` via `flattenPoolReadings`.

#### `doCloseJob` offline path (line ~630)
**Before:**
```js
const current = reportRef.current;
await submitOffline(String(id), current || report);
```

**After:**
```js
const current = reportRef.current;
const offlineReport = { ...(current || report) };
const offlineBodies = waterBodiesRef.current;
if (offlineBodies.length > 0) {
  offlineReport.water_bodies = offlineBodies;
  offlineReport.chemical_readings = flattenPoolReadings(offlineBodies);
}
await submitOffline(String(id), offlineReport);
```
- Enriches the report with fresh water-body data before passing to `submitOffline`.

## Backend Coupling: preserve-semantics
Works in tandem with backend preserve-semantics:
- **Absent `water_bodies` key** = preserve DB value (when `waterBodiesRef.current.length === 0`)
- **Explicit `water_bodies` array** (even with empty readings per body) = persist as sent
- The mobile client now always includes `water_bodies` when bodies exist.

## Tests Added
- `__tests__/chemistry-gate-mobile.test.ts` — 8 test cases:
  - `flattenPoolReadings` unit tests (multi-body, empty, no readings, name fallback)
  - Integration: editing a reading produces correct flat mirror
  - Integration: submit payload uses ref data, not stale report
  - Integration: offline submit enriches report with fresh ref data
  - Integration: no bodies → original chemical_readings preserved

## Verification
- All 8 new tests pass
- Full test suite: 0 regressions (pre-existing failures confirmed)
- ESLint: clean
- Metro bundler: compiles successfully
