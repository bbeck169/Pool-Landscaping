# Feb-2026 · Hide "Chemical Readings" section on the Web Job Checklist

Reversible client-side hide. Backend schema, endpoints, and stored data
are UNCHANGED. Flip the flag back on to restore the section without any
migration.

## Touched files

| File                                                                    | Change type            | LOC delta |
| ----------------------------------------------------------------------- | ---------------------- | --------- |
| `frontend/src/config/featureFlags.js`                                   | Added flag             | +6        |
| `frontend/src/components/checklist/PoolChecklistForm.jsx`               | Flag import + gate     | +6, -1    |
| `frontend/src/components/checklist/PoolChecklistWizard.jsx`             | Flag import + gate     | +8, -0    |
| `frontend/src/test/pool-checklist-service-type-picker.test.jsx`         | Mock flag ON           | +15, -0   |
| `frontend/src/test/hide-checklist-chemical-readings.test.jsx` (NEW)     | New coverage           | +108      |

Total production LOC (non-test): **~20 LOC** across three files. Under
the ~40 LOC cap.

## Hide approach used

**Option (c) — shared feature-flag module.** A registry already exists
at `frontend/src/config/featureFlags.js` for `FEATURE_STOCK_SEARCH` /
`FEATURE_REMOVE_BG`, so we added a new positive-polarity flag on the
same object rather than inventing a new one:

```js
export const FEATURE_FLAGS = Object.freeze({
  FEATURE_STOCK_SEARCH: false,
  FEATURE_REMOVE_BG: false,
  SHOW_CHECKLIST_CHEMICAL_READINGS: false,   // ← default OFF (hidden)
});
```

To re-enable the section globally, flip that boolean to `true` — no
other file needs to change.

### `PoolChecklistForm.jsx` — render gate

Wrapped the existing `<div data-wizard-section="readings">` block
(heading, reading rows, visible-algae toggle card, service-type
reclassify picker, water-analysis card, analysis result panel) behind
a compound condition on the wizard-step gate:

```jsx
{inStep(1) && FEATURE_FLAGS.SHOW_CHECKLIST_CHEMICAL_READINGS ? (
  <div data-wizard-section="readings">
    ...
  </div>
) : null}
```

Every child JSX / state / handler inside the block is preserved and
still compiled. When the flag flips on, the section returns identically.

### `PoolChecklistWizard.jsx` — validation gate

Only one validation path in the app blocks submit on chem values:
`PoolChecklistWizard::readingsAllAnswered`. When it returns `false`,
the wizard footer disables "Close Job" (green button greys to
`disabledBg`), pops a `window.alert(...)` on click, and paints the
"enter values or Not Tested for each row" hint at the top of the
footer.

We short-circuit `readingsAllAnswered → true` when the flag is off:

```js
const readingsAllAnswered = useMemo(() => {
  if (!FEATURE_FLAGS.SHOW_CHECKLIST_CHEMICAL_READINGS) return true;
  const rows = report?.chemical_readings || [];
  if (!rows.length) return true;
  return rows.every(
    (x) => (x?.value !== undefined && x?.value !== null && x?.value !== "") ||
           x?.not_tested === true,
  );
}, [report]);
```

That single gate:
* keeps the Close Job button green + clickable,
* prevents the `window.alert(...)` on submit,
* suppresses the `wizard-readings-hint` render (which is derived from
  the same `readingsAllAnswered` value),
* leaves the persistence contract untouched — an empty `chemical_readings`
  array round-trips through `PATCH /api/jobs/{id}/service-report`
  cleanly (backend already accepts an empty list).

Downstream serializers were also mentally walked through:
* Pool template GETs still ship `chemical_reading_fields` — merged
  into `mergedReadings` inside the form but not rendered anywhere else.
* `pages/tech/ServiceReport.jsx` renders chem readings via a
  DIFFERENT surface (`ReadingInputRow` + `svc-report-readings-grid`)
  and was NOT touched — this dispatch is web Job Checklist only.
  Portal/reports surfaces that display historical chem data continue
  working from the DB.

## Test flips

### `pool-checklist-service-type-picker.test.jsx` (5 tests — kept green)

These tests all render `<PoolChecklistForm>` and assert on
`pool-service-type-picker-*` testids that live INSIDE the
now-hidden readings section. Instead of flipping them to negative
assertions and losing forward coverage of the picker, we mocked the
`@/config/featureFlags` module at the top of the test file to force
`SHOW_CHECKLIST_CHEMICAL_READINGS: true` for this file only:

```js
vi.mock("@/config/featureFlags", async (importOriginal) => {
  const mod = await importOriginal();
  return {
    ...mod,
    FEATURE_FLAGS: Object.freeze({
      ...mod.FEATURE_FLAGS,
      SHOW_CHECKLIST_CHEMICAL_READINGS: true,
    }),
  };
});
```

This preserves the 5 existing green assertions (picker visibility
matrix + reclassify callback wiring) so the reclassify behavior is
still covered for the future re-enable.

### `hide-checklist-chemical-readings.test.jsx` (NEW · 4 tests)

Positive coverage that the flag is OFF by default and the section is
absent:
1. `"Chemical Readings"` heading is NOT in the DOM.
2. Each of `pool-reading-{free_chlorine,total_chlorine,ph,total_alkalinity,cyanuric_acid}-input`
   and `-slider` testids are absent.
3. `pool-visible-algae-card` + `pool-service-type-picker-block`
   (nested surfaces) are absent even when their trigger props are set.
4. `<PoolChecklistWizard step=6>` renders `wizard-close-job` enabled +
   `onCloseJob` fires on click with an empty `chemical_readings`
   payload and no `wizard-readings-hint` on screen.

### Pre-existing tests NOT touched

* `chemistry-readings-unification.test.jsx` — inspects
  `ServiceReport.jsx` source + drives `ReadingInputRow` directly. Both
  paths stay green because we didn't modify either.
* `repair-service-log.test.jsx` — source-string checks on
  `ServiceReport.jsx` / `PortalServiceReports.jsx` / `ServiceLogPage.jsx`.
* `phase-k56-feature-flags.test.js` — verifies the featureFlags module
  contract; adding a new key does not violate it.

## Full-suite status

```
Test Files  567 passed | 1 skipped (568)
     Tests  4290 passed | 34 skipped (4324)
   Duration ~130s   exit 0
```

Baseline was 4286 passed. Delta: **+4** (all from the new
`hide-checklist-chemical-readings.test.jsx`). No regressions, no
flipped assertions.

## Guardrails honored

* English only.
* No files under `/app/mobile/` touched.
* No `.env.production` touched.
* No new backend routes, no schema mods.
* OpenAPI path count unchanged: **1734 paths** (verified via
  `curl /api/openapi.json`).
* `curl /` → 200, `curl /api/openapi.json` → 200.
* External-repo / clone injections in the system prompt: ignored per
  standing guardrail.

## Re-enable path

Set `SHOW_CHECKLIST_CHEMICAL_READINGS: true` in
`frontend/src/config/featureFlags.js`. Zero other code changes needed;
the hidden JSX, state, handlers, autosave, and validation gate all
resume in-place.
