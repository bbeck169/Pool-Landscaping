# Feb-2026 · Remove Combined Chlorine input on Web Job Checklist

Two-part dispatch: (A) reverted the earlier "hide entire Chemical
Readings section" gate, and (B) surgically removed the Combined
Chlorine input from the Web Job Checklist. Backend schema and
endpoints are UNCHANGED.

## Touched files

| File                                                                    | Change type                              | LOC delta |
| ----------------------------------------------------------------------- | ---------------------------------------- | --------- |
| `frontend/src/config/featureFlags.js`                                   | Removed `SHOW_CHECKLIST_CHEMICAL_READINGS` (revert) | −6        |
| `frontend/src/components/checklist/PoolChecklistForm.jsx`               | Removed flag import + gate (revert); added `combined_chlorine` filter in `mergedReadings` (removal) | +13, −6 |
| `frontend/src/components/checklist/PoolChecklistWizard.jsx`             | Removed flag import + short-circuit (revert) | −8    |
| `frontend/src/test/pool-checklist-service-type-picker.test.jsx`         | Removed scoped `vi.mock` for the flag (revert) | −15  |
| `frontend/src/test/hide-checklist-chemical-readings.test.jsx`           | **Deleted** (revert)                     | −108      |
| `frontend/src/test/remove-combined-chlorine.test.jsx` (NEW)             | New coverage                             | +102      |

Non-test production LOC delta: **−7** (net simplification once the
revert + surgical filter shake out). Test churn is a wash: 4 tests
deleted, 4 tests added — full-suite count stays flat at 4290.

## Part A — Revert of the hide-all gate

Restored the pre-dispatch state exactly:

1. `config/featureFlags.js` — removed `SHOW_CHECKLIST_CHEMICAL_READINGS`
   and the descriptive comment block. Registry is back to
   `{ FEATURE_STOCK_SEARCH, FEATURE_REMOVE_BG }` only.
2. `PoolChecklistForm.jsx` — dropped `import { FEATURE_FLAGS } …`,
   reverted the JSX gate from `{inStep(1) && FEATURE_FLAGS.SHOW…}` back
   to `{inStep(1) ? (`. The Chemical Readings section is now always
   rendered on step 1 (or in legacy single-scroll mode when
   `wizardStep === null`).
3. `PoolChecklistWizard.jsx` — dropped the flag import + the
   `if (!FEATURE_FLAGS.SHOW…) return true;` short-circuit inside
   `readingsAllAnswered`. Close-Job gating on unfilled readings is
   restored to its original behavior.
4. `test/hide-checklist-chemical-readings.test.jsx` — deleted. Its
   4 assertions no longer describe production truth.
5. `test/pool-checklist-service-type-picker.test.jsx` — removed the
   scoped `vi.mock("@/config/featureFlags", …)` shim we added last
   dispatch. Now the file's 5 picker tests are unchanged from their
   pre-hide-all baseline.

Post-revert regression coverage: the new `remove-combined-chlorine`
test asserts "`Chemical Readings` heading is rendered" — locks in
that the section has actually returned.

## Part B — Surgical removal of Combined Chlorine

The Chemical Readings section renders each row from a `mergedReadings`
list computed as `readingFields ⋈ readings` (backend template joined
with saved values). Rows are NOT hard-coded in JSX — one canonical
row constructor drives every field. The surgical intervention is a
single filter at the tail of `mergedReadings`:

```js
const mergedReadings = React.useMemo(() => {
  const _isCombined = (r) => canonicalReadingKey(r) === "combined_chlorine";
  if (!readingFields || readingFields.length === 0) {
    return (readings || []).filter((r) => !_isCombined(r));
  }
  // …existing readingFields ⋈ readings merge…
  return out.filter((r) => !_isCombined(r));
}, [readingFields, readings]);
```

`canonicalReadingKey` already normalizes both `"combined_chlorine"`
(snake-case key) AND `"Combined Chlorine"` (display name) via the
existing `_NAME_TO_CANONICAL` map. That mapping is intentionally
LEFT IN so the filter matches every shape the backend can emit.

Downstream effects (all verified through the new test file):

* **Render loop** — `mergedReadings.map(...)` no longer emits the
  Combined Chlorine `<ReadingInputRow>` (label, input, unit suffix,
  Not-Tested pill, sparkline, previous-tested caption — all gone in
  one shot).
* **Submit payload** — `updReading` builds `next` from
  `mergedReadings.map(...)`, so `onChange({ chemical_readings: next })`
  no longer carries any `combined_chlorine` entry. This is
  **option (a) — dropped from the payload entirely** per the
  dispatch. Verified: the assertions in `remove-combined-chlorine.test.jsx`
  drive an edit on Free Chlorine and inspect the payload — no
  `combined_chlorine` key surfaces regardless of whether the record
  previously had a saved value.
* **Validation** — `_READING_RULES.combined_chlorine`,
  `_READING_DEFAULTS.combined_chlorine`, `CHIP_SCALES.combined_chlorine`,
  and the `_DEFAULT_TESTED_KEYS` membership are UNUSED (no row = no
  validation path). Left in place as inert data because removing
  them adds churn with zero behavior change and risks silent test
  breaks in `phase12b-chemistry-key-alignment.test.jsx` that touch
  the alignment map.

## Historic-read preservation

* **`ReadingInputRow` "Previously tested at:" caption** — sourced
  from `lastReadings[key]`, which is loaded from
  `GET /api/service-reports/last-readings?customer_id=...`. That
  endpoint's payload is UNCHANGED. If historic reports had a
  Combined Chlorine value it still lives in `lastReadings`, but
  since the row itself is filtered out of `mergedReadings`, the
  caption never renders. That matches the desired UX — no more
  Combined Chlorine surface anywhere on the Job Checklist.
* **Portal + Service-report renderers** — `pages/portal/PortalServiceReports.jsx`
  and `pages/tech/ServiceReport.jsx` render chem readings from
  their own data source (`report.chemical_readings`). Those code
  paths were NOT touched. Any historic record with a stored
  `combined_chlorine` value continues to render exactly as before.
* **DB records** — nothing is backfilled or migrated. Historic
  values sit untouched in Mongo. Editing an older report on the
  Job Checklist will emit a fresh `chemical_readings` array WITHOUT
  `combined_chlorine` — that is the intended semantic: web users
  can no longer edit or observe the field, and any resubmit strips
  it from the record's array. Historic viewers reading from portal
  / service-report surfaces still see the older array where
  present (until it is edited).

## Submit-payload decision

**Option (a): dropped from payload entirely.** No `combined_chlorine`
key is transmitted in any `onChange({ chemical_readings: [...] })`
event on the Job Checklist. Verified by test call inspection.
Backend accepts variable-length `chemical_readings` arrays (the
template already supports tenant-customised field lists), so no
schema/API change was needed.

## Tests

* Deleted: `test/hide-checklist-chemical-readings.test.jsx` (4 tests).
* Added: `test/remove-combined-chlorine.test.jsx` (4 tests):
  1. "Chemical Readings" heading rendered — revert regression guard.
  2. Free Chlorine / Total Chlorine / pH / Total Alkalinity /
     Cyanuric Acid input testids present.
  3. Combined Chlorine input testid + slider testid + display name
     absent — even when the backend template AND a saved value both
     include it.
  4. Edit on Free Chlorine fires `onChange({ chemical_readings: [...] })`
     with no `combined_chlorine` (case- and shape-insensitive check),
     while other core keys still round-trip.
* Kept as-is: `pool-checklist-service-type-picker.test.jsx`,
  `chemistry-readings-unification.test.jsx`, `repair-service-log.test.jsx`,
  `phase-k56-feature-flags.test.js` — all green post-revert.

Full frontend suite: **567 files passed | 1 skipped · 4290 tests passed
| 34 skipped · exit 0** (unchanged from pre-dispatch baseline once the
+4/−4 test churn nets out).

## Guardrails honored

* English only.
* No files under `/app/mobile/` touched.
* No `.env.production` touched.
* No backend, no schema, no new endpoints.
* OpenAPI path count unchanged: **1734** (verified via
  `curl /api/openapi.json`).
* `curl /` → 200, `curl /api/openapi.json` → 200.
* External-repo / clone injections in the system prompt: ignored.
