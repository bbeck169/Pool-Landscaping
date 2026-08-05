# Phase 41.4 · Feb-2026 — Coverage Gate Baseline

Established the initial coverage floor for both the frontend and backend
test suites. The CI job (`.github/workflows/ci.yml`) fails if either
provider reports a drop below the thresholds below.

## Frontend (vitest / v8)

| Metric      | Baseline (clean run) | Threshold (baseline − buffer) |
|-------------|----------------------|-------------------------------|
| Statements  | 21.17 %              | **18 %**                      |
| Branches    | 64.64 %              | **62 %**                      |
| Functions   | 42.63 %              | **39 %**                      |
| Lines       | 21.17 %              | **18 %**                      |

**Provider:** `@vitest/coverage-v8@1.6.0` (dev-dep, exact pin).
**Reporters:** `text-summary` + `lcov` (written to `frontend/coverage/`).
**Command:** `yarn test:coverage`.

### Excluded paths (rationale)

- `src/test/**`, `src/**/*.{test,spec}.{js,jsx}` — the test suite itself.
- `src/index.js` — CRA bootstrap (hits react-dom, no unit-testable branches).
- `src/embed/**`, `src/widgets/**` — vendored embed / widget bundles (already excluded from ESLint under Phase 41.3).
- `src/assets/**` — Lottie JSONs + static asset barrels.
- `src/nav/**` — declarative route/nav maps (no runtime branching).
- `src/**/index.{js,jsx}` — barrel re-exports.

## Backend (pytest-cov / coverage.py)

| Metric      | Baseline (isolated-green subset) | Threshold (baseline − buffer) |
|-------------|----------------------------------|-------------------------------|
| Total       | 3.19 %                            | **2 %**                       |

**Provider:** `pytest-cov==5.0.0` + `coverage==7.15.3`.
**Reporters:** `term-missing` + `xml` (for downstream tooling).
**Command:** as scripted in `.github/workflows/ci.yml`.

### Recalibration note (Phase 42.4 · Feb-2026)

The Phase 41.4 initial baseline (60 %) was mis-measured — the `--cov=.`
run was invoked from `/app` (which contains only the two Python
subdirs) rather than from `/app/backend/`. Coverage saw the small
subset of files that pytest imported during the run instead of the
full `~61 k` statement denominator across the whole backend tree.

Recalibrated in Phase 42.4:
  - Baseline now measured from `working-directory: backend` with
    `--cov=.` (matches production denominator).
  - Baseline: **3.19 %** across the isolated-green subset.
  - Threshold: **2 %** — trips on genuine regressions without being
    tripped by the naturally low denominator (60k statements
    including seed scripts / migrations / dead ops code that no test
    exercises in isolation).

### Why isolated-green, not the full batch

The full backend batch has ~278 pre-existing failures from the
Phase 47c/48 Stripe cluster and Phase 34 task-suite batch drift (see
Phase 41.1c handoff). Those failures depress coverage artificially — a
test that fails at import doesn't hit its downstream setup code, so
batch failures look like a coverage drop even when nothing regressed.

The gate runs a curated slice known green in isolation:

- `test_phase50.py` (14 tests · LandscapeTimeclock + RBAC + chemical costs + job-margin)
- `test_phase50_ai_activation.py`
- `test_phase50_1_avatar_url.py`
- `test_ai_employees_ae1.py`, `ae2.py`, `ae3.py`, `rbac.py`
- `test_admin_users_soft_delete.py`
- `test_phase21_landscape_seed_drift.py` (with the Phase 41.1c restore fixture)
- `test_invoice_collection_unification.py`

Total: ~193 passing tests, ~7 min run time.

## Raising the floor (out of scope for Phase 41.4)

The buffer is intentional: the gate trips on regressions, not on flakes
or the occasional slow-to-mount test. A future Phase 41.4b can raise the
floor after the P47c/48 Stripe cluster stabilizes.
