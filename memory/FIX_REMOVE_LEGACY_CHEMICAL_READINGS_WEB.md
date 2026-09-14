# Fix — Remove legacy "Chemical Readings" heading from Pool checklist (web)

**Phase**: Feb-2026 · URGENT bugfix  
**Scope**: web only (mobile team running the same change in parallel).  
**Problem reported**: user video showed a Pool job checklist
rendering the flat "**CHEMICAL READINGS**" section (uppercase
labels via CSS) alongside the structured multi-body "Chemistry"
section. The uppercase legacy header diverged from the new
`water_bodies`-based taxonomy, and techs were reporting
"Missing required readings" close-gate hits even after typing
values into what looked like the correct fields.

## Root-cause analysis

### The primary readings block

`PoolChecklistForm.jsx` renders a single readings block gated by
`inStep(1)`. Rendered inside the wizard for the primary body of
every pool job. Labels were formatted with
`text-[11px] font-bold uppercase tracking-wider` in
`ReadingInputRow`, producing the "TOTAL CHLORINE (PPM)*" look.
The section header text was "Chemical Readings".

`WaterBodyPanel.jsx` — used only for **extra** water bodies —
renders a title-case "Chemistry" section with a different
visual weight and taxonomy. On a multi-body pool (Pool + Spa),
both surfaces would be visible on the same page, giving the
impression of a "duplicated" section.

### Writeback + close-gate

Data-side, both flow through the same pipeline:

- Primary: `PoolChecklistForm.updReading` →
  `onChange({chemical_readings: [...]})` →
  `WaterBodyManager.onPrimaryChange` **mirrors** the write to
  `water_bodies[0].readings` in the SAME patch.
- Backend `services/water_bodies.apply_water_bodies_writes()`
  runs `flatten_pool_readings(bodies)` so the top-level
  `chemical_readings` mirror is rebuilt on every write regardless
  of which surface produced the patch.
- `services/chemistry_gate.assert_core_readings_present()`
  accepts EITHER shape (dict OR list-of-dicts) via
  `normalize_readings()`.

The close-gate therefore already tolerates both shapes; the bug
was purely visual — the two sections rendering with divergent
labels made techs believe they'd filled the wrong one.

## Fix

Minimum-invasive rename + label re-style:

- **`components/checklist/PoolChecklistForm.jsx`**
  - Section header text: `"Chemical Readings"` → `"Chemistry Readings"`.
  - `data-testid="pool-chemistry-readings"` added to the section
    wrapper so tests + Playwright flows have a stable hook.
  - `ReadingInputRow` label styling:
    - `text-[11px] font-bold uppercase tracking-wider` →
      `text-sm font-semibold` (title-case, matches
      WaterBodyPanel's Chemistry rows).
    - Unit render: ` (${reading.unit})` → ` ${reading.unit}`
      (title-case "Free Chlorine ppm" not "FREE CHLORINE (PPM)").

- **`pages/tech/ServiceReport.jsx`** — read-only Section title
  in the legacy tech ServiceReport page (`isPool && !isRepair`):
  `"Chemical Readings"` → `"Chemistry Readings"`. Regex test
  updated in lockstep.

- **No backend changes** — the flatten helper + close-gate
  already tolerate both shapes.

## Files touched

| File | Change | LOC delta |
|---|---|---|
| `components/checklist/PoolChecklistForm.jsx` | 2 label/testid edits | ~10 lines |
| `pages/tech/ServiceReport.jsx` | 1 header string | ~2 lines |
| `test/repair-service-log.test.jsx` | regex + comment | ~4 lines |
| `test/remove-combined-chlorine.test.jsx` | asserts new header + rejects legacy | ~4 lines |
| `test/remove-legacy-chemical-readings-web.test.jsx` | **NEW** 5-test regression guard | +105 lines |

## Regression guards

New Vitest `test/remove-legacy-chemical-readings-web.test.jsx`:

1. Renders "Chemistry Readings" header exactly once.
2. **Never** renders the legacy "Chemical Readings" header.
3. Carries `data-testid="pool-chemistry-readings"` on the wrapper.
4. Still renders every reading input (free_chlorine,
   total_chlorine, ph, total_alkalinity, cyanuric_acid) — no
   accidental key drift.
5. Writeback continues to bubble through
   `onChange({chemical_readings: [...]})` so the
   `WaterBodyManager` mirror to `water_bodies[0].readings`
   is preserved and the close-gate keeps seeing populated
   readings.

## Not-in-scope surfaces (intentional)

The read-only display surfaces below still use the "Chemical
Readings" label because they render pre-existing report data
where the section name is part of the historical presentation:

- `pages/ops/WorkstreamJobDrawer.jsx` line 151
  (`<Section title="Chemical Readings">`)
- `pages/public/ServiceImagesPortalPage.jsx` line 173
  (`<PortalSection title="Chemical Readings">`)

These are admin/portal RETROSPECTIVE views, not the tech
capture form. Renaming them is a low-risk consistency polish
that can happen in a follow-up phase alongside any
mobile-parity work — the user's scope was explicitly the "Pool
checklist form" the tech fills.

## Mobile parity coupling

Mobile team is running the same rename in parallel on
`mobile/src/components/checklist/PoolChecklistForm.tsx`. Both
surfaces already share `expandChemistryLabel.ts` for label
text; the only divergence was the CSS `uppercase` transform on
web, which is now gone. When the mobile edit lands, the two
platforms will match byte-for-byte on both the section header
and the row labels.

Main-agent guardrail: `/app/mobile/` is not touched from this
job (owned by `e1_expo_frontend_dev`).

## Test totals

- **Backend**: `pytest tests/test_chemistry_gate_backend.py
  tests/test_chemistry.py tests/test_chemistry_bands.py` → **53
  passed**, no regressions. No backend files modified.
- **Frontend**: `yarn test:unit` full suite green with the
  updated + new coverage.
- **OpenAPI paths**: **1749 (unchanged)** — no backend
  endpoint touched.
