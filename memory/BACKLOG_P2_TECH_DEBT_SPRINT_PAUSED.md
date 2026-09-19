# P2 Tech-Debt Sprint · PAUSED (Feb-2026)

Sprint kicked off 2026-Feb, one item shipped (A1), rest paused mid-flight
so we could pivot to **Phase: Proposal Analytics — Flipbook Estimate
Tracking + Admin Dashboard**. Do NOT resume these unless the user
explicitly re-opens the sprint.

## A1 — SHIPPED ✅
- `backend/tests/test_i17b_fallback_platform_messaging.py` migrated to the
  canonical `run_test(coro_factory)` + `tests._f7_loop_fixture` pattern.
  Collection no longer hangs; `4 passed, 5.89s`. No product-code changes.

## A2 — pymongo pool exhaustion (capture-first-then-fix) · P2
- Symptom: 3 unnamed test files hit `pymongo.ServerSelectionTimeoutError`
  during a full backend sweep. Names never captured in-repo.
- Trigger: only touch when someone re-runs the full backend suite and
  pastes the actual traceback with file names. Do NOT proactively rewrite
  ~300 test files by judgment call — the pattern is codebase-wide and
  the failure rate is unknown.
- Reference pattern for the eventual fix: convert the module-level
  `MongoClient(...)` in the flagged files to a fixture-scoped instance,
  same shape as `tests._f7_loop_fixture.run_test` for the async side.

## A3 — PYTEST_SEED_SUNBELT bootstrap fixture · P2
- Design (pre-agreed opt-1):
    * Env-flag gated (`PYTEST_SEED_SUNBELT=1`), default OFF.
    * Fixture in `backend/tests/conftest.py`.
    * Seeds one `tenants` row (`slug="sunbelt"`, `name="Sunbelt Test"`,
      random `id`) + one `admin@sunbelt.com` user with `role="admin"`,
      bcrypted `password123`, `must_reset_password=false`.
    * Tests referencing `admin@sunbelt.com` / `db.tenants.find_one({
      "slug": "sunbelt"})` (`test_seo_phase17b.py`, `test_phase32_cfo.py`,
      `test_schedule.py`) currently `pytest.skip("no sunbelt admin")` OR
      take the mocked branch — post-fix they'll run cleanly.
- No blockers; ~30 min work when picked back up.

## B1 — schedule-numbered-reorder.test.jsx 7 failures · P2
- Root cause diagnosed: **case (b)** — the tests assert against the
  pre-Sprint-3d component contract. Post-Sprint-3d changes:
    * Duplicates NO LONGER trigger validation errors — backend
      `insert-and-shift` semantics handle collisions server-side.
    * `POST /jobs/reorder` (bulk) replaced by `POST /jobs/reorder-day-route`
      (per-input touched) with `{date, technician_id, job_id, new_position}`.
    * Banner message strings dropped the word "unique".
- Concrete fixes (test-side only, no product-code touch):
    * Lines 107 + 210: rewrite "duplicate → banner + POST NOT fired" as
      "duplicate → insert-shift fires against `/jobs/reorder-day-route`".
    * Lines 138 + 151: change regex from `/unique positive integers …/`
      to `/positive integers …/`.
    * Lines 180 + 222: change endpoint assertion from `/jobs/reorder`
      to `/jobs/reorder-day-route` and update payload shape.
    * Line 246: trigger `validation.valid=false` via blank/out-of-range
      instead of a duplicate.
- All 7 are pure test rewrites; product code stays untouched.

## C1 — react-hooks/exhaustive-deps warnings · P2
- Current warning count (from `yarn build`): **12** distinct files, not
  the 8 originally listed. Full list:
    * `components/checklist/IndustryChecklistForm.jsx` (line 82)
    * `components/settings/TenantIntegrationsCard.jsx` (line 1631, 1635)
    * `pages/customers/CustomersList.jsx` (line 514)
    * `pages/dispatch/DispatchBoardPage.jsx` (line 357)
    * `pages/reports/AttritionReport.jsx` (line 91)
    * `pages/reports/BookedOutCapacityReport.jsx` (line 64)
    * `pages/reports/ClientLifetimeValueReport.jsx` (line 83)
    * `pages/reports/CloseRatioReport.jsx` (line 61)
    * `pages/reports/LaborEfficiencyReport.jsx` (line 70)
    * `pages/reports/RecurringVsProjectReport.jsx` (line 68)
    * `pages/reports/TimeToCloseReport.jsx` (line 70)
    * `pages/reports/TimeToGetPaidReport.jsx` (line 85)
- Pattern is uniform: `const foo = data && …` computed OUTSIDE a
  `useMemo`, then used INSIDE it. Fix = wrap the initialisation in its
  own `useMemo`. Mechanical.

## C2 — bundle code-split · P2
- Baseline captured (2026-Feb sprint pause):
    * `build/static/js/main.0fb3c116.js` — **2.16 MB gzipped**
    * 1 async chunk (`689.9cdfd615.chunk.js`, 726 B)
    * CRA emitted the "bundle size is significantly larger than
      recommended" warning.
- Plan for the eventual code-split:
    * `React.lazy` + `Suspense` around: `EstimateFlipbook.jsx` (629
      lines), the reports family, PDF views, portal pages.
    * Use existing loading skeleton where present; fall back to a
      minimal spinner.
    * Target: main bundle < 1.6 MB, ≥ 5 async chunks.
- **Do NOT ship code-split concurrently with any big feature phase** —
  it risks Suspense-related runtime regressions and needs its own
  focused Vitest sweep after.
