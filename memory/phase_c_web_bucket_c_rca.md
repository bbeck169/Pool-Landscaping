# Phase C.web — Bucket C RCA (potential source regressions)

> **Produced**: Feb 2026 — Phase C.web Frontend Baseline Drift Sweep
> **Scope**: 8 originally-flagged Bucket C files + 4 Bucket E files that re-triaged to Bucket C after live inspection
> **Status**: READ-ONLY — awaiting human review before any source or test fix

For each file: failing assertion, current source behavior, verdict, reasoning, suggested action.

---

## 1 · `src/test/chemical-application-form.test.jsx`

**Failing assertion**:
```jsx
// test:  "POST /chemical-applications with correct payload + navigate on success"
expect(submittedPayload.ph).toBe(2.5);   // expected 2.5, got +0
```

**Current source behavior**: `ChemicalApplicationForm` submit handler reads `ph` from form state. The `+0` return value suggests the form's `ph` field is being coerced via `Number(stringValue)` where the stringValue is empty / "0" at submit time. Needs manual mount + fireEvent inspection to confirm whether the user-input is reaching state.

**Verdict**: `ambiguous`

**Reasoning**: Could be either (a) a legitimate submit-pipeline regression where numeric form fields default to 0 instead of carrying the user-typed value, or (b) a test-fixture that forgot to type the value before clicking Submit (missing `fireEvent.change` on the ph input). Need to open the test + run it with a debug line to see whether the value is in form state at submit time.

**Suggested action**: `NEEDS HUMAN REVIEW` — if submit-pipeline is confirmed broken, this is a P1 field-coercion bug. If test fixture forgot the fireEvent, it's a 1-line test fix.

---

## 2 · `src/test/phase-k62-customers-page-size.test.jsx`

**Failing assertion**:
```jsx
// test: "defaults to page_size=25 when no URL param / localStorage"
expect(someCondition).toBe(true);   // expected false, got true (inverted)
```

**Current source behavior** (`frontend/src/pages/customers/CustomersList.jsx:222`):
```jsx
const _K62_DEFAULT_PAGE_SIZE = 50;   // ← was 25 at test-write time
```

**Verdict**: `test-stale`

**Reasoning**: The default page size was bumped from 25 → 50 at some point post-K62. The test literal `25` is now stale. No source regression — the config value is explicitly set in the component.

**Suggested action**: `fix test` — update expected default from 25 to 50 (or make the test read `_K62_DEFAULT_PAGE_SIZE` from the source to be drift-resistant).

---

## 3 · `src/test/quote-invoice-detail-ack-bypass-aged.test.jsx`

**Failing assertion**:
```jsx
// test: "K71 line-items save uses the widened _locked array"
expect(SRC.includes('"sent"')).toBe(true);   // expected true, got false
// (actual message: "K71 _locked block missing 'sent'")
```

**Current source behavior**: K71LineItemsEditor save-path `_locked` array (which controls which doc statuses prohibit line-item edits). Phase 26b edited this editor to add `category_auto_mapped` soft-pass handling. The `_locked` array composition may have been reshuffled.

**Verdict**: `source-regression` (suspected)

**Reasoning**: The test was written specifically to lock the `"sent"` value in the `_locked` tuple. If `"sent"` is no longer there, send-state invoices are now editable — likely unintended behavior change. Need to inspect commit `fd2977889` (Phase 26b) + any earlier K71 edit to see whether `_locked` was intentionally narrowed. If intentional, test is stale; if accidental, source needs the status re-added.

**Suggested action**: `NEEDS HUMAN REVIEW` — surface-level implication is "sent invoices became editable" which is likely a user-visible behavior change. Confirm policy intent before fixing either side.

---

## 4 · `src/test/recurring-job-edit-modal.test.jsx`

**Failing assertion**:
```jsx
// test: "invalid price shows inline error and disables Save"
expect(saveBtn.disabled).toBe(false);   // expected false, got true (inverted)
```

**Current source behavior**: `RecurringJobEditModal` save button disabled logic. The invalid-price path currently keeps Save enabled instead of disabling.

**Verdict**: `source-regression` (suspected)

**Reasoning**: Opposite of the invariant — the test says "invalid price → Save disabled" but current source leaves Save enabled. Either (a) the component used to disable but a refactor removed the guard, or (b) the policy intentionally changed to show inline error + allow save-attempt-then-422. Need to check `git blame` on the Save button's `disabled` prop.

**Suggested action**: `NEEDS HUMAN REVIEW` — user-facing: invalid prices CAN be submitted now. If that's intentional (optimistic save), test is stale. If accidental, Save gate needs restoring.

---

## 5 · `src/test/schedule-numbered-reorder.test.jsx`

**Failing assertion**:
```jsx
// test: "duplicate numbers → red border on both inputs + banner + POST NOT fired"
expect(postCalledOnDupInput).toBe('true');   // got 'false'
```

**Current source behavior**: `NumberedReorder` component — duplicate-number guard. The test expects that typing the same number into two rows causes (a) both inputs to get a red border, (b) a banner, (c) NO save POST. Currently the POST appears to NOT be gated, OR the state-string serialization in the test is mismatched.

**Verdict**: `ambiguous`

**Reasoning**: The assertion checks a string `'true'` vs `'false'` — looks like a stringified boolean compare. If the UI's duplicate-detection is firing but the test is reading from a stale DOM attribute, this could be a test harness race. Need to re-run with `await waitFor` to confirm whether the UI state settles.

**Suggested action**: `NEEDS HUMAN REVIEW` — if dup-reorder-save-gate is broken, that's user-impacting (bad schedule data). Fix source. Otherwise widen the test's wait condition.

---

## 6 · `src/test/settings-sprocket-visibility.test.jsx`

**Failing assertion**:
```jsx
// test: "sprocket sits BEFORE SignOutButton in every responsive variant"
expect(wrapBranchCount).toBeGreaterThanOrEqual(3);   // got 2
```

**Current source behavior**: `AdminTopBar` component's responsive wrap branches. The test expects 3 responsive wrap-breakpoints each hosting a `SettingsSprocket → SignOutButton` ordering. Currently only 2 wrap branches exist.

**Verdict**: `test-stale` (likely)

**Reasoning**: Phase 24-ish simplified `AdminTopBar` responsive breakpoints — likely consolidated from 3 wrap variants to 2. The sprocket-before-signout invariant is probably still honored in the 2 remaining branches; the test's count is just out of date.

**Suggested action**: `fix test` — change `.toBeGreaterThanOrEqual(3)` to `.toBeGreaterThanOrEqual(2)` and verify the sprocket-before-signout assertion still passes on each of the 2 branches. If it does, no source regression.

---

## 7 · `src/test/job-count-pill.test.jsx` (re-triaged from Bucket E)

**Failing assertion**:
```jsx
// test: "empty / missing service_type stays null even when completed (no bucket leak)"
expect(classifyJob({ service_type: "", status: "completed" })).toBeNull();
// expected: null, got: 'service'
```

**Current source behavior** (`frontend/src/lib/jobCategory.js:57-78`):
```jsx
export function classifyJob(job) {
  const st = String((job && job.service_type) || "");
  if (_REPAIRS_RX.test(st)) return "repair";
  if (_SERVICES_RX.test(st)) return "service";
  // Phase P27 · the completed-fallback check runs BEFORE the empty-string
  // skip so a completed job whose service_type was mistakenly left blank
  // still lands in Services.
  if (_isCompleted(job)) return "service";   // ← empty+completed = "service"
  if (!st) return null;
  return null;
}
```

**Verdict**: `test-stale` — **intentional policy change in commit `b1fe56b39` (Phase P27 Complete)**

**Reasoning**: The source file explicitly documents this behavior change in a comment block (lines 67-74): "Phase P27 — the completed-fallback check runs BEFORE the empty-string skip so a completed job whose service_type was mistakenly left blank (legacy CSV import, hand-created work order) still lands in Services. Pre-P27 the `if (!st) return null;` guard at the top short-circuited that path and silently dropped those rows from the pill total — the reported 'some completed rows never make it into the tile total' symptom." The test is locking the PRE-P27 invariant that was explicitly reversed to fix a bug.

**Suggested action**: `fix test` — invert the assertion: `.toBeNull()` → `.toBe("service")` + update the test description to match the P27 policy. Add a comment pointing at commit `b1fe56b39`.

---

## 8 · `src/test/rules-of-hooks-guard.test.jsx` (re-triaged from Bucket E)

**Failing assertion**:
```jsx
// test: "AdminTopBar.jsx + AppLayout.jsx have zero eslint errors"
expect(eslintExit).toBe(0);   // got 1
```

**Current source behavior**: eslint runs on `AdminTopBar.jsx` + `AppLayout.jsx` and currently exits with code 1 (= has errors).

**Verdict**: `ambiguous`

**Reasoning**: The test is a lint-gate — if lint errors are real, source needs the fix; if lint rules changed, lint config needs the fix; if the test's eslint invocation is passing wrong args, test needs the fix. Can't tell without running `eslint AdminTopBar.jsx AppLayout.jsx` directly.

**Suggested action**: `NEEDS HUMAN REVIEW` — run eslint on both files; if there are REAL hook-rule violations, fix the source (highest priority — hooks violations are runtime crashes). If config drift, bump lint config.

---

## 9 · `src/test/p16-1-combobox-sweep.test.jsx` (re-triaged from Bucket E)

**Failing assertion**:
```jsx
// test: "K71LineItemsEditor.jsx source imports MasterServiceCombobox + loadCategories"
expect(src).toMatch(/import MasterServiceCombobox from "@\/components\/services\/MasterServiceCombobox"/);
```

**Current source behavior** (`frontend/src/components/quotes/K71LineItemsEditor.jsx:41`):
```jsx
// Replaces the P16.1 ``MasterServiceCombobox`` (which read from the
// legacy master-service-types collection) with a direct pricebook
// lookup via the K71.5 ``PricebookItemPicker``.
```

**Verdict**: `test-stale` — **intentional component replacement**

**Reasoning**: The source file explicitly documents that `MasterServiceCombobox` was REPLACED by `PricebookItemPicker` as part of K71.5. The test is locking the pre-K71.5 import that no longer exists. The replacement is a feature upgrade (direct pricebook lookup replaces legacy collection read), not a regression.

**Suggested action**: `fix test` — update the test's imports regex to point at `PricebookItemPicker` instead of `MasterServiceCombobox`. The related DOM-mount tests (`k71-input-item-1-option-svc-2`) may also need their fixture rewired to the new picker's testid shape.

---

## 10 · `src/test/quote-decline-reopen.test.jsx` (re-triaged from Bucket E)

**Failing assertion**:
```jsx
// test: "filter control renders all 4 stable testids" + "clicking the Converted filter re-fetches with ?view=converted"
expect(screen.getByTestId("quotes-list-filter-converted")).toBeInTheDocument();
// error: Unable to find element [data-testid="quotes-list-filter-converted"]
```

**Current source behavior**: `QuotesList` lifecycle filter UI. The `quotes-list-filter-converted` testid is absent from current source.

**Verdict**: `ambiguous`

**Reasoning**: Either (a) the Converted filter was intentionally removed (feature regression / scope cut), or (b) the testid was renamed in a refactor without updating this test. Need to grep the current `QuotesList.jsx` for the Converted filter button's current testid.

**Suggested action**: `NEEDS HUMAN REVIEW` — if filter removed, test is obsolete. If testid renamed, 4-line regex update.

---

## 11 · `src/test/phase-mobile-drawer-parity.test.jsx` (re-triaged from Bucket E)

**Failing assertion**:
```jsx
// test: "mirrors the eight canonical web groups in order"
const groups = ["finance", "ai_employees", "marketing", "operations",
                 "customers", "reports", "communications", "reviews"];
// expected mobile source to contain each key in order; "reviews" is absent
```

**Current source behavior** (`mobile/src/nav/adminNav.ts`):
```ts
key: "quick_access",  key: "finance",         key: "ai_employees",
key: "marketing",     key: "operations",      key: "customers",
key: "reports",       key: "communications",  key: "business_os"   // ← "reviews" is gone
```

**Verdict**: `ambiguous` — **cross-surface parity gap**

**Reasoning**: Mobile source has `business_os` where test expects `reviews`. If web still has `reviews` as a canonical group, mobile is out of parity → mobile source regression. If web ALSO adopted `business_os`, test is stale. The test file is in `/app/frontend/src/test/` so I can touch it, but the authoritative decision needs the web nav source confirmed.

**Suggested action**: `NEEDS HUMAN REVIEW` — confirm current web admin-nav canonical group list. If `reviews` is still canonical, this is a mobile parity gap (file a mobile-dev ticket). If `business_os` replaced it on both sides, update the test array.

---

## 12 · `src/test/task-a-sidebar-recurring-jobs.test.jsx` (re-triaged from Bucket E)

**Failing assertion**:
```jsx
// test: "keeps existing Reports-group Recurring Jobs entry available for backwards compat"
const reports = reportsGroup?.entries?.find(
  (e) => e.to === RECURRING_TO && !e.subsection,
);
expect(reports).toBeTruthy();   // expected truthy, got undefined
```

**Current source behavior**: `ADMIN_NAV_V2` — the Reports-group's `Recurring Jobs` entry (the backwards-compat one with no `subsection` field) is no longer present.

**Verdict**: `ambiguous`

**Reasoning**: The test explicitly flags itself as a "backwards compat" guard. If the backwards-compat entry was INTENTIONALLY cleaned up (deprecation sunset), the test is obsolete. If it was accidentally removed in a refactor, users who had bookmarked the old route lose their shortcut. Low user impact either way (the primary entry still works under Schedule & Dispatch), but worth confirming the removal was intentional.

**Suggested action**: `NEEDS HUMAN REVIEW` — if intentional sunset: delete this test block entirely. If accidental: restore the backwards-compat entry in `ADMIN_NAV_V2`.

---

## Summary table

| # | File | Verdict | Suggested action |
|---|---|---|---|
| 1 | chemical-application-form | ambiguous | NEEDS HUMAN REVIEW |
| 2 | phase-k62-customers-page-size | test-stale | fix test (25 → 50) |
| 3 | quote-invoice-detail-ack-bypass-aged | source-regression (suspected) | NEEDS HUMAN REVIEW |
| 4 | recurring-job-edit-modal | source-regression (suspected) | NEEDS HUMAN REVIEW |
| 5 | schedule-numbered-reorder | ambiguous | NEEDS HUMAN REVIEW |
| 6 | settings-sprocket-visibility | test-stale (likely) | fix test (3 → 2) |
| 7 | job-count-pill | test-stale (intentional P27) | fix test (invert assertion) |
| 8 | rules-of-hooks-guard | ambiguous | NEEDS HUMAN REVIEW |
| 9 | p16-1-combobox-sweep | test-stale (intentional K71.5) | fix test (update import) |
| 10 | quote-decline-reopen | ambiguous | NEEDS HUMAN REVIEW |
| 11 | phase-mobile-drawer-parity | ambiguous | NEEDS HUMAN REVIEW |
| 12 | task-a-sidebar-recurring-jobs | ambiguous | NEEDS HUMAN REVIEW |

**Statistics**: 3 clear test-stale (safe to fix) · 2 suspected source regressions · 7 need human review.
