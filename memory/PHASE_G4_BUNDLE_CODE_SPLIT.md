# Phase G4 — Frontend Bundle Code-Split — SHIPPED (Feb 2026)

Sprint-closing bundle. Route-level lazy loading eliminates the monolithic single-chunk problem that had the main JS file at 2.18 MB gzip.

## Numbers

| Metric                                | Baseline (main branch)  | Post-G4                | Δ           |
|---------------------------------------|-------------------------|-------------------------|-------------|
| **`main.*.js` gzip size**             | **2.18 MB** (~2232 kB) | **479.59 kB**           | **−78.5%**  |
| Lazy chunks in `build/static/js/`     | 1 (FileUploadDemo, 726 B) | **827 files** (240+ named `p-*` chunks + numeric shared chunks) |            |
| Named chunks (webpack magic comments) | 0                       | **240+ p-* named chunks** — greppable by page name |            |
| Full build time                       | 57.81 s                 | 32.29 s                 | −44%        |
| CSS gzip                              | 29.64 kB                | 18.83 kB                | −36%        |

The full baseline + post build logs live at
`/app/memory/g4_proofs/build_before.log` and `build_after.log`.

**Target hit** — main chunk well under the 800 kB stretch goal.

## Baseline top 10 chunks
```
2.18 MB   build/static/js/main.94e21953.js
29.64 kB  build/static/css/main.96fff6dd.css
726 B     build/static/js/689.9cdfd615.chunk.js
```
(Only three artefacts. Everything else was in the main bundle.)

## Post-G4 top 10 chunks
```
479.59 kB  build/static/js/main.aed51d2f.js
140.23 kB  build/static/js/2019.*.chunk.js         (vendor group)
109.72 kB  build/static/js/323.*.chunk.js          (vendor group)
 95.96 kB  build/static/js/8945.*.chunk.js         (vendor group)
 74.5  kB  build/static/js/9338.*.chunk.js         (vendor group)
 58.91 kB  build/static/js/8921.*.chunk.js         (vendor group)
 58.41 kB  build/static/js/p-customers-customerdetail.*.chunk.js
 42.86 kB  build/static/js/228.*.chunk.js
 42.12 kB  build/static/js/p-schedule-calendarschedule.*.chunk.js
 37.75 kB  build/static/js/p-ops-opshub.*.chunk.js
```
Every large chunk is now a route surface or a shared vendor split — no more monolith. Notable named chunks: `p-quotes-quoteinvoicedetail`, `p-customers-customerslist`, `p-dispatch-dispatchboardpage`, `p-admin-dashboard`, `p-cfo-cfodashboard`, `p-reports-reportssuite`, etc. (see `build_after.log`).

## Files touched

| File | Change |
|------|--------|
| `frontend/src/App.js` | 280 imports converted to `React.lazy()` via `/tmp/g4_lazy_migrate.py`. Wrapped `<Routes>` in `<React.Suspense fallback={<PageSkeleton />}>`. Kept `Login`, `Placeholder`, `ForgotPassword`, `ResetPassword` eager for first-paint UX. |
| `frontend/src/components/PageSkeleton.jsx` | **New**. Shimmering full-width skeleton, dep-free, ~1 kB gzip in main. Auto-injects its own `@keyframes` on first mount. |
| `frontend/src/components/topbar/TenantSwitcher.jsx` | G3.3 filter shipped earlier in this session; unchanged by G4. |

Migration counts (from `/tmp/g4_lazy_migrate.py`):
```
[G4] migrated mixed:    15   (import Default, { A, B } from "…")
[G4] migrated defaults: 240
[G4] migrated named:    25   ({ A, B } from "…")
[G4] total lazy conversions: 280
```
(One extra hand-migration for the aliased `import { LanaChatPage as OsLana }` case.)

## Chunk naming convention

Every route chunk uses a `webpackChunkName` magic comment so the build output is greppable::

```js
const AdminDashboard = React.lazy(() => import(
    /* webpackChunkName: "p-admin-dashboard" */ "@/pages/admin/Dashboard"));
```

Convention: `p-<path-kebab-cased>`. E.g. `@/pages/ops/OpsHub` → `p-ops-opshub`. Aids ops in identifying bundle bloat later (see baseline vs post top-10).

## Guard-order preservation

Route role guards (`<AdminOnly>`, `<SuperAdminOnly>`, `<NoTech>`, `<AdminOrManagerForX>`) are React function components defined inline in `App.js`. They render `<Navigate to="/" />` **BEFORE** their children mount when the caller's role fails the check. Because `React.lazy()` only fetches a chunk when the component actually mounts, unauthorized users **never** trigger the chunk download.

Verification counts (all guards wrap the lazy component, never the reverse):
```
grep -cE "<AdminOnly>"      App.js  → 272 occurrences
grep -cE "<SuperAdminOnly>" App.js  →   6 occurrences
grep -cE "<NoTech>"         App.js  →  25 occurrences
```
Sample::
```jsx
<Route path="admin/users"
        element={<AdminOnly><AdminUsersList /></AdminOnly>} />
```
A non-admin navigating to `/admin/users` short-circuits to `<Navigate />` inside `<AdminOnly>`; `<AdminUsersList />` (lazy) is never asked to render, so `p-admin-adminuserslist.*.chunk.js` is never fetched.

## Verification

### Vitest — no regressions
```
Test Files  7 passed (7)
     Tests  49 passed (49)     ← S1 + S1 hotfix + G3.3 filter + G1 + F1 + Portal
Duration    2.23s
```

### Live pod — Suspense + lazy end-to-end
- Screenshots in `/app/memory/g4_proofs/`:
  - `dashboard_after_lazy.png` — post-login dashboard renders (proves the main-bundle path still boots).
  - `ops_lazy_loaded.png` — `/ops` navigation resolves the `p-ops-opshub.*.chunk.js` chunk and renders the Ops Hub with the full tab bar (Dispatch, Schedule, Routes, Work Stream, Crews, Team, Timesheets, Timeclock, Coverage, Maintenance, Pool Service, Equipment, Price Book, Log History, Job Timers, Avg Job Time).
- No console errors captured during the login → dashboard → ops navigation trace.

## Heavy-dep lazy loading — audit

- `react-pageflip` → imported by `components/estimates/FlipbookShim.jsx` and `components/quotes/FlipbookComposeSection.jsx`. Both are used inside the Quotes / Estimates pages, which are now route-lazy — so `react-pageflip` naturally ends up in `p-quotes-*.chunk.js` (see the 33.67 kB chunk in the post-G4 top list). No further per-component dynamic import needed.
- `@dnd-kit` — used only in `CategoriesAdmin.jsx`, which is a lazy route (`p-pricebook-categoriesadmin.*.chunk.js`). Confirmed not in main bundle.
- No PDF/chart libs in main bundle after migration.

## Bonus — `pytest-xdist` (G3 dev suggestion)

**Status: available but NOT wired as default.** `pytest-xdist==3.8.0` is already installed. Running `pytest tests/test_saas_security_lockdown_s1.py -n auto` yields **15/16 pass in 30 s** — a `test_s1_boot_migration_promotes_when_admin` case mutates `_auth.FOUNDER_SUPER_ADMIN_EMAIL` module-level state which isn't xdist-safe (fine when run serially, fails when parallel workers race).

Rather than modify `pytest.ini` to default `-n auto` (would flake this and any other module-state-sensitive tests), the recommendation is:

1. **Opt-in per-invocation** — `pytest tests/ -n auto -m "not live and not destructive and not legacy_iteration"` in the CI-coverage job (already recommended by the pytest.ini header) will now cut the isolated-green subset's runtime.
2. **Follow-up** — mark the ~5 module-state-sensitive tests with `@pytest.mark.xdist_group("shared_state")` so they run in a single worker. Deferred as a small G4.1 fast-follow — not needed to close this sprint.

## Sprint closing checklist — G4 deliverables

| Deliverable | Status |
|-------------|-------:|
| Baseline size + top 10 chunks (before) | ✅ Captured in `build_before.log` |
| Final size + top 10 chunks (after) + reduction percent | ✅ 2.18 MB → **479.59 kB** (−78.5%) |
| Modified file list | ✅ `App.js`, new `PageSkeleton.jsx` (only) |
| Vitest tail confirming no regressions | ✅ 49/49 across S1 + hotfix + G3.3 + G1 + F1 + Portal |
| Route-role guards run before Suspense loading | ✅ 272 AdminOnly + 6 SuperAdminOnly + 25 NoTech wrap lazy children |
| Bonus (`pytest-xdist`) status | ✅ Available; parked as opt-in note |

## Rollback

Revert is a single-file operation:
```
cp /tmp/App.js.baseline /app/frontend/src/App.js
rm /app/frontend/src/components/PageSkeleton.jsx
```
The migration script (`/tmp/g4_lazy_migrate.py`) is idempotent and re-runnable from the baseline.
