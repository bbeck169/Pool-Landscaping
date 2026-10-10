# Phase C.web Bucket A — Deferred items (post-Batch-8 residual sweep)

> **Updated**: Feb 2026 — Post α.rollback + A2 shared helper + Batches 3-6 + Residual Batches 7-8.
>
> **Commits shipped this dispatch**:
> - α.rollback `824c52950` — reverted K71 `_locked` widening + flipped 2 drifted test files (ack-bypass-aged + silent-bypass) to Phase-#3 narrow invariants. Kept the RecurringJobs save-disable α fix.
> - A2 shared helper `fa95b2756` — `src/test/_helpers/mockAuth.js` + inline `vi.mock("@/auth")` block injected in 6 drifted test files.
> - Batch 3 `37258e41e` — schedule + customer theme (7 files).
> - Batch 4 `2b53405f8` — portal + leads theme (3 files, 3 deferred).
> - Batch 5 `d3fcdbf41` — lazy-import + h1-class + pdf-import prefix match (6 files).
> - Batch 6 `fc084e5b5` — topbar slice-size + fragment-wrap + pt-16 sunset (4 files).
> - Residual Batch 7 `4689079f3` — Group U quick-win sweep (4 files cleared, 3 deferred).
> - Residual Batch 8 (this commit) — A2.residual PRICEBOOK-UNIFY picker rename + mock widen (3 files cleared, 2 deferred).
>
> **Statistics**:
> - **Pre-sweep failing**: 58 files
> - **Post α/β/γ (start of C.web dispatch)**: 51 files
> - **Post Batches 3-6**: 28 files
> - **Post Residual Batch 7**: 24 files
> - **Post Residual Batch 8 (now)**: **21 files**
> - **Net reduction across all dispatches**: **37 files (-64%)**

---

## Remaining 21 failing files — categorized

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

### Group A2.residual.remaining — 2 files
Original A2.residual bucket had 5 files; Batch 8 cleared 3. Remaining 2 need multi-assertion semantic rewrite:

- `p16-1-1-estimate-combobox-gap.test.jsx` — **PHASE PRICEBOOK-UNIFY COMPONENT SWAP**.
  - Source: `QuoteInvoiceNew.jsx` replaced `MasterServiceCombobox` with `PricebookItemPicker` (Feb-2026 Phase PRICEBOOK-UNIFY).
  - Failures: assertions anchor to `MasterServiceCombobox` import literal + `qf-line-N-desc` wrapper testid (now `qf-line-N-picker-wrapper` on the shared picker), + wrapper-level option testid `qf-line-N-desc-option-{id}` (now `qf-line-N-picker-item-N` on the shared picker).
  - **Needs semantic rewrite**: 5+ assertions need to pivot from the combobox shape to the picker shape. The historical intent "P16.1.1 drop-in combobox is wired to description" is now obsolete; the new intent "PRICEBOOK-UNIFY picker is wired to description + unit_price" is covered by `src/pages/quotes/__tests__/QuoteInvoiceNew.pricebook.test.jsx` already. Candidate for **DELETION** rather than rewrite — the P16.1.1 phase is sunsetted.

- `phase40-tab-count-refresh.test.jsx` — **P40 COUNT-REFETCH REGRESSION**.
  - Failure: After the mute PATCH succeeds, `_countCallsFor(/is_muted=true/) >= 1` fails — the current `CustomersList.jsx` does NOT re-fire `/customers?count_only=true&is_muted=true` after a mute action. P40 fix appears to have regressed OR the current source uses optimistic badge updates without a re-fetch.
  - **Needs source audit**: Determine if the mute flow should re-fetch counts (P40 contract) or if the test is semantically stale (optimistic-update path). Non-mechanical.

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

### Group U.residual — Residual Batch 7 deferred — 3 files
Investigated in Batch 7 but needs multi-source alignment OR a human product ruling.

- `customer-detail-navy-command-strip.test.jsx` — **PHASE 28 REGRESSION LOCK CONFLICT**. Needs human ruling on canonical ordering.
- `k52-theming.test.js` — **PHASE N1 UNIVERSAL INPUT RESTYLE DRIFT**. Needs multi-assertion rewrite to accept the N1 "nested white card on navy strip" pattern.
- `phase-n2-input-restyle-refinement.test.jsx` — **SOURCE-WIDE SEARCHICON DRIFT (9 outlier source files)**. Needs a dedicated theme-sweep dispatch (1-char-per-file × 9 files).

### Group U.cleared — Residual Batches 7-8 fixed — 7 files
Cleared via regex widen / mock widen / baseline additions (test-only edits).

**Batch 7 `4689079f3`** (4):
- `concierge-avatar-parity.test.jsx` — widened `name={e.name}` regex to accept `name={e.human_name || e.name}` display-name fallback.
- `p47-missed-status-badge.test.jsx` — widened 4 assertions to accept Phase 3d-portal pool/landscape split.
- `p49-service-report-restyle.test.jsx` — widened `function Section()` destructure signature + added 2 superseded-banner testids to allowlist.
- `task-m-job-reopen-ui.test.jsx` — widened `locked` regex to accept the optional PS-A `&& !techPostSubmitEdit` guard tail.

**Batch 8 (this commit)** (3):
- `invoice-line-item-price-editable.test.jsx` — renamed `qf-line-0-desc` → `qf-line-0-desc-input` (PRICEBOOK-UNIFY picker exposes input via `inputTestid`), widened `/items` mock to `.startsWith("/items")` for the picker's debounced search params, added dropdown-click flow (`qf-line-0-picker-item-0`) to actually SELECT a pricebook item (picker is not auto-select-on-type like the old combobox).
- `invoice-pricebook-writeback.test.jsx` — same testid rename + mock widen + dropdown-click flow in the "label flips after selecting a pricebook item" test. The checkbox-send-payload test only needs the testid rename.
- `invoice-save-errors-inline.test.jsx` — testid rename only in the shared `fillLineAndSubmit()` helper (the inline error path doesn't depend on an actual pricebook pick, just typing).

---

## Recommended next-dispatch shape

### Lane 1 (medium, ~1 hr, 3 files) — RECOMMENDED NEXT
- Group B4.deferred — rewrite response-shape assertions + wrap `MemoryRouter`.

### Lane 2 (theme-token sweep, ~30 min, 9 source files)
- Phase N2 search-icon alignment: change `colors.muted` → `colors.searchIcon` (and equivalents) on the 9 outlier `<Search>` sites. Expected to clear `phase-n2-input-restyle-refinement.test.jsx` + possibly adjacent k52 search-input assertions.

### Lane 3 (medium, ~45 min, 2 files)
- Group B3.deferred — rewrite 3 drift assertions each.

### Lane 4 (K52.1 N1-reconciliation, ~45 min, 1 file)
- `k52-theming.test.js` — rewrite the 2–3 K52.1 Slice-A assertions to accept the N1 "nested white card on navy strip" pattern.

### Lane 5 (delete-vs-rewrite decision)
- `p16-1-1-estimate-combobox-gap.test.jsx` — P16.1.1 is sunsetted by PRICEBOOK-UNIFY. The newer `QuoteInvoiceNew.pricebook.test.jsx` already covers the picker. **Candidate for deletion with a line in the doc rather than a semantic rewrite.** Needs human ruling.

### Lane 6 (feature-regression investigation)
- `phase40-tab-count-refresh.test.jsx` — determine canonical mute-flow count-refetch behavior. If P40 regressed in source, this is a bug not a test fix.

### Lane 7 (human decision required)
- `customer-detail-navy-command-strip` — Phase 28 identity-header-reposition conflict.
- Group A4 γ-triaged (7 files).

---

## Phase 20/22/23/24/26b/27/28/28b/30/31/32/33/34/35 regression locks

All verified green via targeted spot-checks during each batch. Residual Batches 7-8 ran the Phase 33 (`pdfImportUnifiedUI` + `pdfi-upload-sidepanel`) and Phase 34 (`revenue-date-range-year-presets`) suites as a sanity gate — green post-sweep. No regression-lock drift introduced by any of the 8 commits shipped across this + prior dispatches.
