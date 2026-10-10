# Phase C.web.γ — Bucket C ambiguous-items quick verdicts

> **Produced**: Feb 2026 — Phase C.web Frontend Baseline Drift Sweep, follow-on to
> `/app/memory/phase_c_web_bucket_c_rca.md` after α (source fixes shipped at `2878a6be9`)
> and β (test-stale flips shipped at `ac341143b`).
>
> **Scope**: 7 remaining Bucket C files that the RCA marked `ambiguous` or `NEEDS HUMAN REVIEW`.
> One-line verdicts per file + proposed action, awaiting human green-light per item.
> **Status**: READ-ONLY — no code or test touched here.

---

## chemical-application-form.test.jsx
- **Current source behavior** (1 line): `ChemicalApplicationForm.jsx` line 693 wraps `amount_sprayed_gal` in `<DecimalInput onChange={(n) => patch({ amount_sprayed_gal: n == null ? "" : String(n) })} />`; `DecimalInput` is a controlled wrapper that only propagates numeric values via its own `onChange(n)` after internal parse.
- **Test's current assertion** (1 line): Line 511 fires a vanilla `fireEvent.change(screen.getByTestId("chem-app-form-amount-sprayed-gal"), { target: { value: "2.5" } })` directly on the inner input, expecting `body.amount_sprayed_gal` to equal `2.5` after submit.
- **Verdict**: **TEST-STALE** (test fixture pre-dates the DecimalInput wrapper migration).
- **Proposed action** (1 line): Replace the direct `fireEvent.change` with a `DecimalInput`-aware helper (either `fireEvent.input` with the exact typed stream the wrapper expects, or import a `_decimalInputSet(testId, "2.5")` helper from `src/test/_helpers` if one exists) — same pattern the `wind_mph`/`temp_f` passing cases use elsewhere in this file.

---

## schedule-numbered-reorder.test.jsx
- **Current source behavior** (1 line): `useRouteOrderController` runs `_validate` on every draft change — the error banner surfaces when `validation.message` is non-null AND there's a `banner.kind === "err"`; the save POST is gated by `validation.valid`.
- **Test's current assertion** (1 line): Types duplicate numbers into two inputs, blurs both, then expects `screen.getByTestId("route-order-error-banner").textContent` to match `/must be unique/i` AND `_h.post` to NOT have been called.
- **Verdict**: **NEEDS-HUMAN** (duplicate-detection logic has evolved — the test's "must be unique" wording doesn't appear in the current `validation.message` strings, which read `"Only whole numbers are allowed."` / `"Numbers must be positive integers (1–50)."` / `"Every job needs a number."`).
- **Proposed action** (1 line): Confirm whether a dedicated duplicate-detection message is still a product requirement — if yes, add it to source `_validate` + wire the banner (SOURCE restore); if duplicates fall through to backend 422 by design, flip the test's expected message to the current validation copy (TEST-STALE flip).

---

## settings-sprocket-visibility.test.jsx
- **Current source behavior** (1 line): `AdminTopBar.jsx` has 3 `<SettingsSprocket />` sites at lines 501, 570, 603 — each inside a distinct responsive wrap (`admin-topbar-tech-wrap`, `admin-topbar-narrow-wrap`, `admin-topbar-wide-wrap`), each followed by `<SignOutButton />`.
- **Test's current assertion** (1 line): Line 70 regex `<SettingsSprocket\s*\/>(?:\s*<[A-Z][A-Za-z]*(?:\s+[^>/]*)?\s*\/>)?\s*<SignOutButton\s*\/>` allows at most ONE intermediate self-closing JSX element between sprocket and signout, expecting `>=3` matches.
- **Verdict**: **TEST-STALE** (one of the three wraps now has `<SettingsSprocket /> <LanguageSelector /> <NotificationBell /> <SignOutButton />` — two intermediate elements, not one; regex fails that branch, so the count drops to 2).
- **Proposed action** (1 line): Widen the inner non-capturing group from `(?:\s*<...>)?` (0 or 1 element) to `(?:\s*<...>){0,3}` (0-3 intermediate elements), keeping the sprocket-before-signout invariant intact.

---

## rules-of-hooks-guard.test.jsx
- **Current source behavior** (1 line): The test shells out to `npx eslint --max-warnings=0 src/layouts/AdminTopBar.jsx src/layouts/AppLayout.jsx` and expects exit=0.
- **Test's current assertion** (1 line): `expect(eslintExit).toBe(0)` — fails when eslint returns 1 (lint errors present).
- **Verdict**: **ENV-ISSUE** (test is a lint-gate — the eslint exit code depends on the preview container's eslint config + plugin resolution; a jsdom-only vitest run against a fresh `npx eslint` subprocess likely resolves plugins differently than the CI harness that originally wrote this test).
- **Proposed action** (1 line): Move to Bucket D (environment) — either (a) run `npx eslint …` manually to confirm whether there are REAL hook-rule violations in `AdminTopBar.jsx` / `AppLayout.jsx` (if yes, that's a P0 source fix; if no, the test's `npx` shell-out is the issue), or (b) replace the shell-out with an in-process `@eslint/js` call so the test is self-contained.

---

## quote-decline-reopen.test.jsx
- **Current source behavior** (1 line): `QuotesList.jsx:41` → `const LIFECYCLE_VIEWS = ["open", "accepted", "declined", "all"];` — the lifecycle filter row renders exactly 4 buttons with testids `quotes-list-filter-open|accepted|declined|all`.
- **Test's current assertion** (1 line): Line 263 + 271 + 274 reference `quotes-list-filter-converted` which does not exist in source.
- **Verdict**: **NEEDS-HUMAN** (either the Converted filter was intentionally sunset and merged into Accepted, or the testid was renamed from `converted` → `accepted` as part of a product rename, OR a 5th view was planned but never shipped).
- **Proposed action** (1 line): If product intent is "Converted = Accepted" rename: swap `converted` → `accepted` in the 3 failing lines. If the Converted filter was fully sunset: delete the test block. If it should exist: restore the view key + the test can stay.

---

## phase-mobile-drawer-parity.test.jsx
- **Current source behavior** (1 line): `mobile/src/nav/adminNav.ts:262` declares `key: "business_os"` instead of `reviews`; web `frontend/src/nav/adminNav.js` canonical keys are `finance, ai_employees, marketing, operations, specialty_services, customers, reports, communications` — **neither** surface has a `reviews` group.
- **Test's current assertion** (1 line): Line 29-37 expects both surfaces to contain `["finance", "ai_employees", "marketing", "operations", "customers", "reports", "communications", "reviews"]` in order.
- **Verdict**: **TEST-STALE** (both web + mobile independently moved on from `reviews` as a top-level group key; test array is the only remnant).
- **Proposed action** (1 line): Replace `"reviews"` with `"business_os"` in the expected-groups array AND add `"specialty_services"` to match the web list ordering, OR narrow the test to the subset of groups both surfaces still share (`finance, ai_employees, marketing, operations, customers, reports, communications`).

---

## task-a-sidebar-recurring-jobs.test.jsx
- **Current source behavior** (1 line): `nav/adminNav.js:382` has `{ to: "/admin/recurring-jobs", label: "Recurring Jobs", icon: CalendarClock, feature: "scheduling", subsection: "Reports" }` inside the Reports group — the entry EXISTS but **carries a `subsection: "Reports"` string**.
- **Test's current assertion** (1 line): Line 164-167 does `const reports = reportsGroup?.entries?.find((e) => e.to === RECURRING_TO && !e.subsection)` and `expect(reports).toBeTruthy()` — it demands a Reports-group entry **without** a subsection.
- **Verdict**: **NEEDS-HUMAN** (the backwards-compat invariant was "an entry WITHOUT subsection exists so legacy bookmarks keep rendering as a top-level Reports link"; the source added a subsection, which converts the entry into a subsection header — this may be intentional nav-tree consolidation or an accidental over-tagging).
- **Proposed action** (1 line): If the subsection addition was intentional: delete this test block (backwards-compat sunset). If accidental: either drop `subsection` from line 382 (source fix) OR add a sibling entry at line 383 without a subsection (dual-anchor fix).

---

## Summary table

| # | File | γ Verdict | Fix side |
|---|---|---|---|
| 1 | `chemical-application-form.test.jsx` | TEST-STALE | test (DecimalInput-aware fixture) |
| 2 | `schedule-numbered-reorder.test.jsx` | NEEDS-HUMAN | needs product-UX decision |
| 3 | `settings-sprocket-visibility.test.jsx` | TEST-STALE | test (widen regex gap `{0,1}` → `{0,3}`) |
| 4 | `rules-of-hooks-guard.test.jsx` | ENV-ISSUE | move to Bucket D (or in-process eslint) |
| 5 | `quote-decline-reopen.test.jsx` | NEEDS-HUMAN | product decision on Converted filter |
| 6 | `phase-mobile-drawer-parity.test.jsx` | TEST-STALE | test (groups-list refresh) |
| 7 | `task-a-sidebar-recurring-jobs.test.jsx` | NEEDS-HUMAN | product decision on sunset vs. accident |

**Statistics**: 3 `TEST-STALE` (safe to fix) · 1 `ENV-ISSUE` (bucket-move) · 3 `NEEDS-HUMAN` (product/UX decisions pending).
