# Phase K57 — Mobile Schedule `pending` alias → `open` bucket

**Ship date:** Feb 2026
**Scope:** Slice-B (K50) job-card status background helper — add a
single alias entry so real-world jobs with `status = "pending"`
render on the same light-teal-green as the `open` bucket.
**Status:** 🟢 SHIPPED — Step 3 only (alias + tests + docs).

---

## Field report (context)

Users reported the mobile Schedule surface rendering **white** card
backgrounds on jobs displayed in the "Pending" filter bucket, while
the neighbouring "Open" / "Scheduled" cards rendered the K50 light
teal green (`#D6F5EE`).

Root cause: the K50 map (`K50_JOB_STATUS_BG` in
`frontend/src/lib/jobStatus.js` + `mobile/src/lib/jobStatus.ts`) had
no entry for `pending`, and the alias table did not translate
`pending → open`.  `jobStatusColor("pending")` therefore returned
`null`, and the caller correctly fell back to its default
(`colors.surface` / white).  The K50 helper is deliberately
narrow — only the five brief-called-out statuses are mapped — so the
fix is to add the alias, not to expand the frozen bucket map.

## Step-1 enumeration (recap)

DB distinct `status` values (jobs collection) at K57 Step-1 time:
`open`, `scheduled`, `in_progress`, `completed`, `cancelled`,
`skipped`, `pending`.  Only `pending` was unmapped.

## Step-2 adjudication (recap)

User adjudicated `pending → open` (same real-world semantics —
"on the schedule, not yet started"), reusing `#D6F5EE`.  No new
bucket colour introduced.

## Step-3 ship — what changed

| File | Change |
|---|---|
| `frontend/src/lib/jobStatus.js` | Added `pending: "open"` to the inline alias table inside `jobStatusColor()`.  Comment references this ship report. |
| `mobile/src/lib/jobStatus.ts` | Added `pending: "open"` to the `_ALIAS` frozen table.  Mirrors the web helper byte-for-byte at the alias-entry level. |
| `frontend/src/test/k50-theming.test.js` | New assertion block — `jobStatusColor("pending")` / `"Pending"` / `"PENDING"` all resolve to `#D6F5EE`.  Case-insensitivity is already covered generically for the K50 five; the K57 block re-asserts it for `pending` specifically because upstream write paths do not normalise the status field. |
| `mobile/__tests__/k50-job-status-color.test.ts` | Same three assertions on the mobile side (primary regression gate — mobile is where the bug was reported). |
| `memory/PHASE_K50_THEMING.md` | Alias-table section updated to include `pending → open (#D6F5EE)` with a back-pointer to this ship report. |
| `memory/PHASE_K57_MOBILE_SCHEDULE_PENDING_ALIAS.md` (this file) | Ship report. |

### Parity note

The alias entries in `frontend/src/lib/jobStatus.js` (`alias` object,
lines ~52-60) and `mobile/src/lib/jobStatus.ts` (`_ALIAS` object,
lines ~19-27) share the **exact same key/value ordering** so a diff
between the two tables stays a single-line difference (the const
name / Object.freeze wrapper) rather than an entry-order shuffle
that would obscure real drift in code review.

### Case-sensitivity — confirmed by design

The K57 test additions include a `"PENDING"` (all-caps) assertion.
This works because both helpers call `String(status || "").toLowerCase().trim()`
before hitting the alias table.  If a future refactor removes that
normalisation the K57 assertion will fail and flag the regression.
No expansion of scope needed (K57.1 is unnecessary — the case-
insensitivity contract is already locked in).

## Tests

* Web (vitest): `frontend/src/test/k50-theming.test.js` — the existing
  Slice-B suite (13 checks) grew by 1 new `it` block asserting the
  `pending` alias + case variants.
* Mobile (jest): `mobile/__tests__/k50-job-status-color.test.ts` —
  the existing 6-check suite grew by 1 new `it` block covering the
  same contract on the mobile side.
* No changes to any other test file.  Suites remain isolated to their
  respective helpers.

### Test run
Test evidence is captured in the Testing subagent report referenced
alongside this ship.  Green on both surfaces confirms:
* `jobStatusColor("pending") === "#D6F5EE"` (web + mobile).
* `jobStatusColor("Pending") === "#D6F5EE"` (web + mobile).
* `jobStatusColor("PENDING") === "#D6F5EE"` (web + mobile).
* All pre-K57 assertions from the K50 suite still pass — no
  regressions to the frozen map, alias resolution for existing
  aliases (`active`, `closed`, `done`, `canceled`), null-fallback
  contract for unmapped statuses (`on_hold`, `requested`,
  `reopened`), or `Object.isFrozen(K50_JOB_STATUS_BG)`.

## Out of scope (deliberate)

* **No expansion of the frozen `K50_JOB_STATUS_BG` map** — `pending`
  reuses the `open` hex via the alias table.  This preserves the K50
  invariant that the bucket map is the five brief-called-out statuses
  and nothing else.
* **No fallback default paint** — the K50 helper still returns `null`
  for genuinely unmapped statuses (`on_hold`, `requested`, `reopened`,
  future statuses).  Callers keep their `colors.surface` fallback.
* **No status-write-path normalisation** — this ship does not touch
  the backend or any write path that persists `status`.  If a
  specific write path is emitting `"Pending"` (mixed case) or
  `" pending "` (whitespace), the helper handles it — but if a
  future audit wants to normalise-at-write for cleaner DB values,
  that is a separate ticket.

## Revert safety

Trivially revertable — the alias entry is one line in each file, and
the test blocks are self-contained `it()` blocks.  Reverting removes
the alias and callers immediately fall back to `colors.surface`
(the pre-K57 behaviour).  No downstream code depends on `pending`
resolving to a specific hex — the helper is the only path to the
K50 background paint.

## Follow-ups

* **K58** — separate ship line.  Mobile Schedule *map* shows
  "No mapped stops today" even when jobs exist for the day.  Six-point
  diagnosis follows this K57 ship in the next turn (report only —
  no code fix pending user adjudication).
* **K57.1 (not needed)** — case-insensitivity is already contract-
  guaranteed by the `.toLowerCase().trim()` normalisation and locked
  in by the new `"PENDING"` assertion.  No follow-up work required.
