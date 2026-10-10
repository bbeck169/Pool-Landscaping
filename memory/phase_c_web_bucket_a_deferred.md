# Phase C.web Bucket A — Deferred items (post-residual-sweep)

> **Updated**: Feb 2026 — Post α.rollback + A2 shared helper + Batches 3-6 + Residual Batch 7.
>
> **Commits shipped this dispatch**:
> - α.rollback `824c52950` — reverted K71 `_locked` widening + flipped 2 drifted test files (ack-bypass-aged + silent-bypass) to Phase-#3 narrow invariants. Kept the RecurringJobs save-disable α fix.
> - A2 shared helper `fa95b2756` — `src/test/_helpers/mockAuth.js` + inline `vi.mock("@/auth")` block injected in 6 drifted test files.
> - Batch 3 `37258e41e` — schedule + customer theme (7 files).
> - Batch 4 `2b53405f8` — portal + leads theme (3 files, 3 deferred).
> - Batch 5 `d3fcdbf41` — lazy-import + h1-class + pdf-import prefix match (6 files).
> - Batch 6 `fc084e5b5` — topbar slice-size + fragment-wrap + pt-16 sunset (4 files).
> - Residual Batch 7 (this commit) — Group U quick-win sweep (4 files cleared).
>
> **Statistics**:
> - **Pre-sweep failing**: 58 files
> - **Post α/β/γ (start of C.web dispatch)**: 51 files
> - **Post Batches 3-6**: 28 files
> - **Post Residual Batch 7 (now)**: **24 files**
> - **Net reduction across all dispatches**: **34 files (-59%)**

---

## Remaining 24 failing files — categorized

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

### Group U.residual — Residual Batch 7 deferred — 3 files
Investigated in this dispatch but needs multi-source alignment OR a human product ruling. Each deferred with specific rationale:

- `customer-detail-navy-command-strip.test.jsx` — **PHASE 28 REGRESSION LOCK CONFLICT**.
  - Failure: `expected 42864 to be greater than 60268` (strip's `indexOf` fails the "sits below Portal Access and above the header card" ordering invariant).
  - Root cause: Phase 28 identity-header reposition changed the Customer Detail layout order — the navy command strip now mounts ABOVE Portal Access, not between it and the header card.
  - **Needs human**: Which ordering is canonical? Phase 28 shipped the current ordering intentionally; the K71 test's ordering invariant was defined pre-Phase-28. User must rule: (a) revert Phase 28 identity-header position, or (b) rewrite the K71 ordering invariant to match the new layout, or (c) drop the ordering invariant entirely.

- `k52-theming.test.js` — **PHASE N1 UNIVERSAL INPUT RESTYLE DRIFT**.
  - Failures:
    - `calendar-filters` strip Search block expects `background: "rgba(255,255,255,0.10)"` + `color: colors.nav.fgMuted` on the search input. Source (CalendarSchedule.jsx:1776) now uses `className="... bg-white ..."` + `text-[#0284C7]` per Phase N1 ("solid-white bg + navy text + blue focus ring").
    - `quotes-filters` strip asserts `colors.onSurfaceSecondary` NOT in the strip; source has legitimate `onSurfaceSecondary` on inactive lifecycle tab text (QuotesList.jsx:443).
  - **Needs multi-assertion rewrite**: 2–3 K52.1 assertions need to acknowledge the N1 "nested white card on navy strip" pattern instead of the pre-N1 "white/10 translucent overlay" pattern. Not a simple regex-widen — the assertions are structured as block scans against the whole strip.

- `phase-n2-input-restyle-refinement.test.jsx` — **SOURCE-WIDE SEARCHICON DRIFT (9 files)**.
  - Failure: D1 scans every `<Search>` in `frontend/src/` and asserts each uses `colors.searchIcon` or `#0284C7`. 24 files use `colors.searchIcon`; 9 outlier files remain on stale tokens (`colors.muted`, `colors.nav.fgMuted`, or missing style entirely):
    - `components/GlobalSearch.jsx:261`
    - `components/GlobalSearchBar.jsx:210, 241`
    - `components/pricebook/PricebookItemPicker.jsx:179` (`colors.muted` stale)
    - `components/services/MasterServiceCombobox.jsx:337` (`colors.muted` stale)
    - `components/ui/NavyFilterBar.jsx:146`
    - `pages/admin/FleetMembership.jsx:125`
    - `pages/settings/AIBrainPage.jsx:144, 173`
    - `pages/settings/MasterServicesSettings.jsx:426` (`colors.muted` stale — attempted fix in this dispatch; reverted to keep scope clean)
  - **Needs theme-sweep commit**: 1-char source alignment per file × 9 files. Theme-token sweep is a legitimate standalone commit — not a test-regex-widen candidate. Flag for a dedicated "N2 search-icon theme sweep" dispatch.

### Group U.cleared — Residual Batch 7 fixed — 4 files
Cleared in `<SHA>` via regex widen / baseline additions (test-only edits).
- `concierge-avatar-parity.test.jsx` — widened `name={e.name}` regex to accept `name={e.human_name || e.name}` display-name fallback.
- `p47-missed-status-badge.test.jsx` — widened 4 assertions to accept Phase 3d-portal pool/landscape split (`tile-next-service(?:-(?:pool|landscape))?`, `summary.next_(pool|landscape)_service.*`, both the legacy "None scheduled" fallback literal + the conditional-hide empty-state pattern).
- `p49-service-report-restyle.test.jsx` — widened `function Section()` destructure signature to accept the new `templateFieldId` fifth arg; added `portal-service-report-superseded-banner` + `portal-service-report-superseded-original-at` to `P49_TESTIDS_ADDED` allowlist.
- `task-m-job-reopen-ui.test.jsx` — widened `const locked = !!report.submitted_at;` regex to accept the optional PS-A `&& !techPostSubmitEdit` guard tail.

---

## Recommended next-dispatch shape

### Lane 1 (quick wins, ~45 min, 5 files)
- Group A2.residual — testid drift (`qf-line-0-desc` → current form).
- Group T timeouts — add missing endpoint mocks that cause loading loops.

### Lane 2 (medium, ~1 hr, 3 files)
- Group B4.deferred — rewrite response-shape assertions + wrap `MemoryRouter`.

### Lane 3 (theme-token sweep, ~30 min, 9 source files)
- Phase N2 search-icon alignment: change `colors.muted` → `colors.searchIcon` (and equivalents) on the 9 outlier `<Search>` sites listed above. Expected to clear `phase-n2-input-restyle-refinement.test.jsx` + possibly adjacent k52 search-input assertions.

### Lane 4 (K52.1 N1-reconciliation, ~45 min, 1 file)
- `k52-theming.test.js` — rewrite the 2–3 K52.1 Slice-A assertions to accept the N1 "nested white card on navy strip" pattern.

### Lane 5 (human decision required)
- `customer-detail-navy-command-strip` — Phase 28 identity-header-reposition conflict. User ruling needed on whether Phase 28 was correct or the strip should move.
- Group A4 γ-triaged (7 files).

---

## Phase 20/22/23/24/26b/27/28/28b/30/31/33/34 regression locks

All verified green via targeted spot-checks during each batch. Residual Batch 7 ran the Phase 33 (`pdfImportUnifiedUI` + `pdfi-upload-sidepanel`) and Phase 34 (`revenue-date-range-year-presets`) suites as a sanity gate — 54/54 green post-sweep. No regression-lock drift introduced by any of the 7 commits shipped across this + prior dispatches.
