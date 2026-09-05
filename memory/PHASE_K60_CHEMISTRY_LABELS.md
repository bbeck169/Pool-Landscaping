# Phase K60 — Chemistry Reading Label Expansion

**Ship date:** Feb 2026
**Scope:** Display-only transform that expands short-form chemistry
abbreviations (`FC`, `TC`, `TA`, `CYA`, `CH`, `TDS`, `PO4`) to their
full names on the Job Checklist / Service Report render surfaces.
**Status:** 🟢 SHIPPED — mobile + web parity.

---

## Field report (context)

Users reported that the mobile Job Checklist Chemistry Readings
section rendered opaque abbreviations (`FC ppm`, `TC ppm`, `TA ppm`,
`CYA ppm`, `CH ppm`, `TDS ppm`, `PO4 ppb`) that were meaningful to
seasoned pool techs but confusing for newer staff and for the
customer-portal report.

User adjudication (K60): expand the default abbreviations to their
full names on the display surface, keep data keys unchanged, and
respect tenant customisations.

## Mapping (user-adjudicated, exact)

| Code   | Full label              | Unit |
|--------|-------------------------|------|
| FC     | Free Chlorine           | ppm  |
| TC     | Total Chlorine          | ppm  |
| pH     | pH                      | —    |
| TA     | Total Alkalinity        | ppm  |
| CYA    | Cyanuric Acid           | ppm  |
| CH     | Calcium Hardness        | ppm  |
| Salt   | Salt                    | ppm  |
| TDS    | Total Dissolved Solids  | ppm  |
| PO4    | Phosphates              | ppb  |

Case-insensitive lookup — `"fc"`, `"FC"`, `"Fc"`, `" FC "` all
resolve to `"Free Chlorine"`.  Whitespace-trimmed input.

## What changed

### 1. New helpers (mobile + web parity)

* **`mobile/src/lib/expandChemistryLabel.ts`** — `expandChemistryLabel(raw): string`.
* **`frontend/src/lib/expandChemistryLabel.js`** — web mirror, byte-
  for-byte identical map contents.

Both wrap a single frozen `_K60_LABEL_MAP` and expose an
`expandChemistryLabel(raw)` function.  Contract: if the input
matches a documented default abbreviation (case-insensitive +
trimmed), return the full-name expansion.  Otherwise return the
input unchanged (tenant-customised labels pass through untouched).

### 2. Consumers

* **`mobile/src/components/checklist/PoolChecklistForm.tsx:449`** —
  `<ReadingChipRow label={r.name} …>` → `<ReadingChipRow label={expandChemistryLabel(r.name)} …>`.
* **`frontend/src/components/checklist/PoolChecklistForm.jsx:108`** —
  `<span>{reading.name}{unit …}</span>` →
  `<span>{expandChemistryLabel(reading.name)}{unit …}</span>`.

Zero changes to:
* Data keys (`FC`, `TC`, `pH`, …) — those are the backend-persisted
  field names on `chemical_readings[].key`.
* Unit rendering — still passed through as-is with its existing
  muted / lighter styling.
* The water analyzer's outlier logic (which keys on the data field,
  not the label).
* Persisted payloads (`chemical_readings` shape on write).

### 3. Tenant customisation respect

The lookup is a strict allowlist.  If a tenant edits their
service-report template to use `"Free Cl (deep end)"` or any other
custom label, that string is NOT in `_K60_LABEL_MAP` and passes
through unchanged.  Only the exact default abbreviations get
expanded.

`waterBodies.ts` (mobile) already carried the full names in its
`READING_LABELS` map's `name` field; the helper is functionally
equivalent to that mapping but works on the raw template value
rather than the reading-key lookup, so it handles the case where
the template's `name` field was seeded to the abbreviation directly
(current default) rather than the full name.

### 4. Tests

* **`mobile/__tests__/k60-expandChemistryLabel.test.ts`** — 39 cases:
  * Full mapping × 3 case variants each (mixed / lower / upper).
  * Tenant-customised passthrough (`"Free Cl (deep end)"`, `"ORP"`,
    `"Copper"`).
  * Idempotency (already-expanded name → self).
  * Whitespace tolerance (` FC `, `\tTA\n`).
  * Null / undefined / empty / whitespace-only → `""`.
* **`frontend/src/test/k60-expandChemistryLabel.test.js`** — web
  parity, ~26 cases covering the same contract in vitest.

## Revert safety

Two-line revert:

```diff
- <ReadingChipRow label={expandChemistryLabel(r.name)} …>
+ <ReadingChipRow label={r.name} …>
```

Then delete the two helper files and the two test files.  No
downstream code depends on `expandChemistryLabel` beyond the two
render sites.

## No backend touch

Backend templates + persisted payloads are unchanged.  The expander
is a purely client-side display transform, applied at render time
in the two component files listed above.

## Follow-ups

* **K60.1 (P2, backlog)** — surface the same expander in the
  customer-portal service-report PDF/HTML renderer so techs and
  customers see consistent labels.  Requires a small PDF template
  edit; deferrable since the customer-portal audience is smaller.
* **K60.2 (P2, backlog)** — add the same expander to any
  water-analyzer / trend-chart tooltips that currently show the raw
  data key.  Not affecting the reported bug but a natural follow-up.
