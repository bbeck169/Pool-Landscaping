# Hotfix #4 · Feb-2026 — Trainings designation visibility

## Symptom
Cross-trained technicians (department = `"both"`, i.e. both pool
and landscaping designations) only saw a subset of training
modules on the `Trainings / Tests` page. Pool-only and
landscaping-only trainings were silently filtered out.

## Rule (post-fix)
```
admin / super_admin          → every module in the tenant
technician whose designations cover EVERY tenant designation
                              → every module (superset rule)
technician with one designation
                              → that designation + universal ("both")
technician with zero designations
                              → universal-only ("both")
customer                     → 403 (unchanged)
```

The "superset rule" is future-proof: adding an `"irrigation"`
designation later is a **one-line** change to
`_TENANT_DESIGNATIONS` in `backend/routers/training.py`. Any tech
carrying *every* recognised designation continues to see
everything without any additional visibility code.

## Where the rule lives
`backend/routers/training.py`:
- `_TENANT_DESIGNATIONS = ("pool", "landscaping")` — extendable.
- `_UNIVERSAL_MODULE_TAG = "both"`.
- `_DEPT_ALIASES` — normalises the seed-drift naming
  (`pool_tech` → `pool`, `landscape_tech` → `landscaping`,
  `landscaper` → `landscaping`) so both the canonical short
  form and the modern `_tech`-suffix form work.
- `_user_designations(user)` — returns the *set* the tech
  carries; `"both"` expands to every tenant designation.
- `_visible_departments(user)` — returns the list of module
  `department` tags visible to this caller, or `None` for
  "all". The route uses `None` to skip the Mongo `$in` filter.

The list route (`GET /api/training/modules`) and the detail
route (`GET /api/training/modules/{code}`) both consult the
helper. `_module_visible_to(mod, user)` (used by detail /
progress / quiz endpoints) shares the same source of truth.

## Fixture drift discovered while writing tests
`backend/seed.py` intentionally seeds `mike@aquaterra.com` as
`department = "pool_tech"` and `landscaper@aquaterra.com` as
`department = "landscape_tech"` (phase 41.1b naming refactor).
The training router previously only recognised the canonical
short forms `pool` / `landscaping`. The pre-existing baseline
test `TestDepartmentFilter::test_pool_tech_hidden_from_landscaping_module`
had been red for this exact reason — the landscaping tech
couldn't see any landscaping module.

**Fix**: added `_DEPT_ALIASES` to normalise on read. Both
naming conventions now work everywhere the training router
looks at `user.department`. The seed remains authoritative and
untouched.

## Tests
### Backend (`backend/tests/test_trainings_designation_visibility_hotfix.py`)
14 tests, all green:

Helper unit tests (no HTTP):
- `test_helper_pool_only_returns_pool_plus_universal`
- `test_helper_landscaping_only_returns_landscaping_plus_universal`
- `test_helper_both_returns_none_meaning_all`
- `test_helper_zero_designations_returns_universal_only`
- `test_helper_admin_returns_none_meaning_all`
- `test_helper_superset_rule_future_proof` — proves the
  irrigation-added scenario auto-includes cross-trained techs.

HTTP integration tests (real backend + Mongo seed):
- `test_tech_with_pool_only_sees_pool_trainings`
- `test_tech_with_landscaping_only_sees_landscaping_trainings`
- `test_tech_with_pool_only_does_not_see_landscaping_only_training`
- `test_tech_with_both_pool_and_landscaping_sees_all_trainings`
- `test_tech_with_both_designations_sees_new_landscaping_only_training`
  (regression guard for late-added modules)
- `test_admin_sees_all_trainings_regardless_of_designation`
- `test_tech_with_zero_designations_sees_only_untagged_trainings`
- `test_tech_with_every_tenant_designation_sees_all_trainings_even_new_types`

### Baseline (`backend/tests/test_training.py`)
`23 passed, 1 skipped` (the skipped test is `TestTenantIsolation`
— `admin@sunbelt.com` is not seeded in this environment, which
the test explicitly `pytest.skip`s on). No regressions.

### Frontend (`frontend/src/test/trainings-designation-visibility-hotfix.test.jsx`)
3 vitest tests, all green:
- Renders every module the API returns (proves no client-side
  department filter was silently dropping trainings).
- Renders a single card when the API returns one — no phantom
  entries added by the FE.
- Empty state renders when the API returns `[]`.

The `TrainingList` page groups modules by department for
presentation only; it does NOT filter the API response. The
tests are the guard against a future well-intentioned
"filter to my department" regression.

## Mobile (Expo) parity
The visibility rule is server-side, so the mobile client
inherits it as long as it calls `/api/training/modules`
unmodified. Mobile screens that render trainings for the
current user:

- `/app/mobile/app/(app)/tests/index.tsx` — list.
- `/app/mobile/app/(app)/tests/[code].tsx` — module detail.
- `/app/mobile/app/(app)/tests/[code]/quiz.tsx` — quiz.

Handoff to `e1_expo_frontend_dev`:
1. Confirm the list screen has no `department`-based filter.
2. Add an Expo test matching the web vitest above (three
   modules from the API → three cards rendered).

## API contract unchanged
- `GET /api/training/modules` — unchanged shape; the list
  simply includes more rows for cross-trained techs.
- `GET /api/training/modules/{code}` — 403 still fires for
  modules outside the caller's visibility set.

## Follow-ups (not blocking)
- `designations: str[]` schema on `users` (currently scalar
  `department`) would let a tenant author truly independent
  designation sets per tech. Today `"both"` is our way of
  expressing "every designation the tenant has".
- `TestTenantIsolation` in `test_training.py` will start
  running once `admin@sunbelt.com` is seeded — no change to
  the training router needed.
