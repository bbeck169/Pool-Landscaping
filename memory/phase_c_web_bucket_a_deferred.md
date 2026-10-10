# Phase C.web Bucket A — Deferred items (final-state after α.rollback + A2 + Batches 3-6)

> **Updated**: Feb 2026 — Post α.rollback + A2 shared helper + Batches 3-6.
>
> **Commits shipped this dispatch**:
> - α.rollback `824c52950` — reverted K71 `_locked` widening + flipped 2 drifted test files (ack-bypass-aged + silent-bypass) to Phase-#3 narrow invariants. Kept the RecurringJobs save-disable α fix.
> - A2 shared helper `fa95b2756` — `src/test/_helpers/mockAuth.js` + inline `vi.mock("@/auth")` block injected in 6 drifted test files.
> - Batch 3 `37258e41e` — schedule + customer theme (7 files).
> - Batch 4 `2b53405f8` — portal + leads theme (3 files, 3 deferred).
> - Batch 5 `d3fcdbf41` — lazy-import + h1-class + pdf-import prefix match (6 files).
> - Batch 6 `fc084e5b5` — topbar slice-size + fragment-wrap + pt-16 sunset (4 files).
>
> **Statistics**:
> - **Pre-sweep failing**: 58 files
> - **Post α/β/γ (start of this dispatch)**: 51 files
> - **Post Batches 3-6 (now)**: **28 files**
> - **Net reduction this dispatch**: **23 files (-45%)**

---

## Remaining 28 failing files — categorized

### Group A4 — γ-triaged (DO NOT TOUCH) — 7 files
Already documented in `phase_c_web_bucket_c_gamma_verdicts.md` with product-decision verdicts pending. All require human ruling before any fix.
- `chemical-application-form.test.jsx` · TEST-STALE (DecimalInput fixture)
- `phase-mobile-drawer-parity.test.jsx` · TEST-STALE (groups-list refresh)
- `quote-decline-reopen.test.jsx` · NEEDS-HUMAN (Converted filter)
- `rules-of-hooks-guard.test.jsx` · ENV-ISSUE (eslint shell-out)
- `schedule-numbered-reorder.test.jsx` · NEEDS-HUMAN (duplicate-detection UX)
- `settings-sprocket-visibility.test.jsx` · TEST-STALE (widen regex gap)
- `task-a-sidebar-recurring-jobs.test.jsx` · NEEDS-HUMAN (sunset vs. accident)

### Group M — Mobile scope (deferred per rules) — 2 files
Rules state: no mobile edits for web phases.
- `phase30-4-confirm-modal-migration.test.jsx`
- `phase35-mobile-finance-parity.test.jsx`

### Group A2.residual — useAuth-null fixed but testid-drift remains — 5 files
Shared mock installed in `fa95b2756`; residual failures are `qf-line-0-desc` / `qf-line-0-price` / combobox-site testid drift. Not useAuth-null anymore.
- `invoice-line-item-price-editable.test.jsx`
- `invoice-pricebook-writeback.test.jsx`
- `invoice-save-errors-inline.test.jsx`
- `p16-1-1-estimate-combobox-gap.test.jsx`
- `phase40-tab-count-refresh.test.jsx` (timeout; may still be mock-drift)

### Group T — timeout-only — 2 files
Hangs in 5s waitFor. Likely mock-drift (missing resolver for a specific endpoint, or mocked `useAuth` triggers an infinite loading loop in the component).
- `QuoteInvoiceNew.pricebook.test.jsx` (already has useAuth mock)
- `n5-t1-page-header-adoption.test.jsx` (already has useAuth mock)

### Group B3.deferred — Batch 3 skipped — 2 files
Need multi-assertion flipping, not simple regex-widen.
- `customer-first-access-filter.test.jsx` — 3 drift assertions: dep-array adjacency + sibling-count fetch URL refactored.
- `customers-list-waitlist-tab.test.jsx` — `p43Suffix` refactored out of the direct URL fetch pattern; needs test to lock the new helper call-site.

### Group B4.deferred — Batch 4 skipped — 3 files
- `leads-bulk-hard-delete-and-polish.test.jsx` — response shape drift (`{requested, deleted, skipped}` vs test's `{results, summary}` expectation). Needs 3 assertions rewritten against the new shape.
- `lead-row-compose-buttons.test.jsx` — "useLocation() may be used only in Router" — Bucket B pattern (test needs `<MemoryRouter>` wrap for the mounted `LeadsDashboardPage`).
- `k68-customer-status-tab-counts.test.jsx` — "expected null to be truthy" — assertion on an effect-dependency split that the test can't locate. Needs source-walk.

### Group U — unaddressed this dispatch — 7 files
Not surfaced for regex-widen attempt yet; candidate for next dispatch.
- `concierge-avatar-parity.test.jsx` — `<AIAvatar name={e.name}>` import path drift (likely moved file).
- `customer-detail-navy-command-strip.test.jsx` — `expected 42864 to be greater than 60268` — ordering constraint (strip must sit between Portal Access and header card) violated by Phase 28 identity-header reposition. **Likely a Phase-28 regression lock conflict — needs human.**
- `k52-theming.test.js` — `rgba(255,255,255,0.10)` color token drift in a different search block.
- `p47-missed-status-badge.test.jsx` — testid split into `tile-next-service-pool` + `tile-next-service-landscape` (needs test to assert either/both).
- `p49-service-report-restyle.test.jsx` — Portal service-report restyle drift (indexOf null).
- `phase-n2-input-restyle-refinement.test.jsx` — Search-icon color-token drift (same family as k52).
- `task-m-job-reopen-ui.test.jsx` — `locked = !!report.submit...` regex drift.

---

## Recommended next-dispatch shape

### Lane 1 (quick wins, ~45 min, 3-5 files)
- `concierge-avatar-parity` — refresh import path
- `k52-theming` + `phase-n2-input-restyle-refinement` — align color-token regex to current `colors.X` references
- `p47-missed-status-badge` — allow suffixed testids via `(?:-pool|-landscape)?`
- `task-m-job-reopen-ui` — regex-widen for current `locked` form

### Lane 2 (medium, ~1 hr, 5 files)
- Group A2.residual — fix the testid drift (`qf-line-0-desc` → current form).
- Group T timeouts — add missing endpoint mocks that cause loading loops.

### Lane 3 (medium-heavy, ~1 hr, 3 files)
- Group B4.deferred — rewrite response-shape assertions + wrap `MemoryRouter`.

### Lane 4 (human decision required)
- `customer-detail-navy-command-strip` — Phase 28 identity-header-reposition broke this lock's ordering invariant. User ruling needed on whether Phase 28 was correct or the strip should move.
- Group A4 γ-triaged (7 files).

---

## Phase 20/22/23/24/26b/27/28/28b/30/31 regression locks

All verified green via targeted spot-checks during each batch. The α.rollback explicitly restored narrow lock parity on `QuoteInvoiceDetail.jsx` so Phase-26b (category auto-map warnings) and the Phase-27/28/28b CustomerDetail work remained unaffected. No regression-lock drift introduced by any of the 6 commits shipped this dispatch.
