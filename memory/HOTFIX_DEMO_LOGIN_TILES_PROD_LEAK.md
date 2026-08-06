# P0 Hotfix — Demo Login Tiles Leaking Into Production

**Date:** 2026-02 (interrupt of Phase 41.1d)
**Severity:** P0 — demo credentials rendered on the customer-facing production login page.
**Status:** LANDED. Preview still shows tiles; production and fail-closed paths verified hidden.

---

## 1. Root Cause (one paragraph)

The demo-tiles env gate on both the web login (`frontend/src/pages/Login.jsx`) and the mobile login (`mobile/app/login.tsx`) was written as a **build-time** predicate: `process.env.REACT_APP_PUBLIC_ENV === "preview"` on web and `process.env.EXPO_PUBLIC_ENV === "preview"` on mobile. React/Vite and Expo bake `process.env.*` values into the JS/Metro bundle at *build* time by inlining them as string literals. When a build was produced with the preview `.env` present (which both `/app/frontend/.env` and `/app/mobile/.env` contain — `REACT_APP_PUBLIC_ENV=preview` / `EXPO_PUBLIC_ENV=preview`), those literals were frozen into the bundle. Any subsequent production deploy that re-used that bundle shipped `if ("preview" === "preview")` to prod — which is trivially true, so the tiles rendered. The gate expression itself was written safely (case-insensitive strict equality), but the *value* it consulted was chosen at the wrong time (build) instead of the right time (runtime). Fix: introduce a runtime source of truth — extend the existing `GET /api/config/public` endpoint to include `app_env` (server-side `os.getenv("APP_ENV")`, with a whitelist that falls back to `"production"` for missing/unknown values), and gate the tiles on `appEnv !== null && appEnv !== "production"`. Default `appEnv` is `null` during initial render, and any fetch failure sets it to `"production"` — both branches hide the tiles. Fail-closed by design.

## 2. Env Source Used

- **Endpoint:** `GET /api/config/public` (existing, reused per brief — no new endpoint introduced).
- **Backend env var:** `APP_ENV` (already present in `backend/.env` for preview; must be set to `production` in the production deploy). Whitelist accepts: `production`, `preview`, `development`, `staging`, `local`, `test`. Anything else coerces to `production`.
- **Response payload (post-hotfix):**
  ```json
  { "show_demo_logins": <bool>, "app_env": "<production|preview|...>" }
  ```
- **Frontend consumers:** `frontend/src/pages/Login.jsx` and `mobile/app/login.tsx` — both fetch on mount, both fail-closed on error / missing value.

## 3. Files Touched

| File | Purpose |
|---|---|
| `backend/routers/config.py` | Extended `GET /api/config/public` payload with `app_env`. Whitelist coerces unknown values → `"production"`. Existing `show_demo_logins` field untouched. |
| `frontend/src/pages/Login.jsx` | Replaced build-time `process.env.REACT_APP_PUBLIC_ENV === "preview"` gate with runtime `useEffect` fetching `/config/public`. `appEnv` state defaults to `null`; render predicate is `appEnv !== null && appEnv !== "production"`. Fetch failure sets `appEnv="production"` → hide. |
| `mobile/app/login.tsx` | Same pattern for mobile — replaced `process.env.EXPO_PUBLIC_ENV === "preview"` with runtime fetch of `/config/public` via `api.get()`. |
| `backend/tests/test_config_public_show_demo_logins_default.py` | +6 new tests locking the `app_env` contract (default=production, reports the current APP_ENV verbatim, lower-cased, whitelist coerces unknown → production). Also fixed the batch-unsafe `_call_public()` helper that used `asyncio.get_event_loop()` to use `asyncio.new_event_loop()` (order-independent). |
| `frontend/src/test/preview-demo-logins.test.jsx` | Rewrote the predicate suite to test `isPreviewGateOn(appEnv)` — the new runtime predicate — with `null`/`undefined`/`"production"`/`"preview"`/`"development"`/`"staging"`/`"local"` cases. Source-grep guardrail: asserts `/config/public` fetch call and `!== "production"` gate literal are present, and the old `process.env.REACT_APP_PUBLIC_ENV` / `=== "preview"` gate expressions are gone from executable code. |
| `frontend/src/test/phase30-login-tweaks.test.jsx` | Inverted the anti-test (`does NOT read /config/public`) that was blocking this hotfix. New assertion locks the runtime fetch — future refactors cannot silently regress back to a build-time gate. |
| `frontend/src/test/login-welcome.test.jsx` | Updated the `api` mock so `api.get` returns a resolved Promise (previous `vi.fn()` returned `undefined`, which broke the new `.then()` in `Login.jsx`). No behavior change — mock hygiene only. |
| `mobile/__tests__/demo-login.test.tsx` | Rewrote from process-env toggle → `api.get` mock. +3 new tests: renders on `preview`+`development`, hides on `production`/missing/reject/initial-render. Existing 2 credential-tap tests preserved (now updated to await the runtime fetch). |

No runtime code touched outside `backend/routers/config.py`, `frontend/src/pages/Login.jsx`, and `mobile/app/login.tsx`.

## 4. DOM Assertions (Production / Preview / Fail-Closed)

All three branches verified end-to-end against `https://poolscape-audit.preview.emergentagent.com/login` with the backend running under `APP_ENV=preview`:

| Branch | `app_env` from `/api/config/public` | `[data-testid^="demo-login-"]` count | `[data-testid="demo-logins-block"]` present | Screenshot |
|---|---|---:|:---:|---|
| Preview (unmocked) | `"preview"` | **4** | ✅ Yes | Shows Super Admin / Admin / Customer / Landscape Tech tiles under "DEMO LOGINS (Preview Only)" |
| Production (mocked via `page.route`) | `"production"` | **0** | ❌ No | Login form only — no demo section at all |
| Fail-closed (`page.route` returns `abort("failed")`) | (fetch fails) | **0** | ❌ No | Login form only — no demo section at all |

## 5. Tests Added / Updated

- **Backend (`test_config_public_show_demo_logins_default.py`):** +6 tests for the `app_env` contract + 1 helper fix. Now 12 passed (was 6).
- **Frontend (`preview-demo-logins.test.jsx`):** predicate suite rewritten for the runtime `null`/production/preview matrix + source-grep guardrail (locks in the new gate, forbids the old one). +1 test in the file (12 → 13 was rejected — final count 12 pass with two-branch grep).
- **Frontend (`phase30-login-tweaks.test.jsx`):** anti-test inverted. Now asserts `/config/public` IS fetched at mount.
- **Mobile (`demo-login.test.tsx`):** rewrote to mock `api.get` with 6 cases: preview, development, production, missing value, fetch-reject, never-resolves. Existing 2 credential-tap tests preserved (129 → 132 total).

## 6. Invariants Held Green (Post-Hotfix)

| Gate | Result |
|---|---|
| Frontend Vitest | **1258 / 1258 passed** ✅ (was 1257 — added +1 predicate test) |
| Mobile Jest | **132 / 132 passed** ✅ (was 129 — added +3 tests for the runtime gate) |
| Frontend ESLint `--max-warnings=0` | exit **0** ✅ |
| Backend curated coverage gate | **149 passed, 2.45%** ✅ (floor: 2%; was 137/2.27% — added the new `app_env` tests) |
| Preview login DOM (unmocked) | 4 tiles rendered ✅ |
| Production login DOM (mocked) | 0 tiles rendered ✅ |
| Fail-closed login DOM (fetch rejects) | 0 tiles rendered ✅ |

## 7. Production Deployment Note

**The frontend/mobile hotfix does the correct thing regardless of what production sets `APP_ENV` to.** However, for the tiles to properly hide in production, the production deploy environment must have `APP_ENV=production` (or unset — the whitelist coerces to `production` by default). The current preview environment (`/app/backend/.env`) has `APP_ENV=preview` which is correct for preview.

- ❌ **NOT flipped:** we did **not** touch any production env vars from this session (per guardrail).
- ✅ **Safe default:** the whitelist ensures that if the production `APP_ENV` is unset, missing, or misspelled, the endpoint returns `"production"` → tiles hidden.
- ✅ **Fail-safe:** if the production backend can't be reached at all, the frontend fetch fails → `appEnv` set to `"production"` → tiles hidden.

**Recommended production check (surface to operator, do NOT auto-execute):**
```bash
curl -sS https://<prod-domain>/api/config/public
# Expected: {"show_demo_logins":false,"app_env":"production"}
```

## 8. Phase 41.1d Stash Confirmation

- Stashed to `stash@{0}: On main: phase-41.1d-wip-tenant-tasks-async-batch` — `git stash list` shows it.
- Stashed files: 7 (six `test_phase34_task_*.py` + the new `backend/tests/_phase34_asyncio.py`). Verified via `git status --short` — no phase34_task or _phase34_asyncio files in working tree post-stash.
- Post-hotfix working tree is clean of Phase 41.1d WIP; resume with `git stash pop stash@{0}` (or `git stash apply` if you want to inspect first).
- **Important context for the 41.1d resume:** the working hypothesis at pause time (`asyncio.get_event_loop()` returning a closed loop) was correct for solo-run and small-batch reproduction, but the same 60 phase34_task failures persisted in the full batch even after installing the `batch_safe_run` helper. Root cause is *deeper than the `_run` helper* — most likely the Motor client's `_io_loop` is bound at import time to a loop that a later batch test closes, and the helper's rebind runs too late for existing collection references planted by the module-scoped `db` fixture. Next-step suggestion: move the Motor client rebind to `pytest_collection_modifyitems` or a session-scoped autouse fixture that runs BEFORE any module's `db` fixture resolves.

## 9. Guardrail Confirmation

- ✅ No test credentials changed (`memory/test_credentials.md` untouched).
- ✅ Demo tiles still work in preview/development (verified with unmocked fetch → 4 tiles).
- ✅ Phase 41.1d work stashed before this hotfix landed.
- ✅ Vitest 1258/1258, Mobile Jest 132/132, `yarn lint` exit 0, coverage gate 149 passed / 2.45% (floor 2%).
- ✅ No production env vars flipped from this session.
- ✅ `PreviewDemoLogins` unchanged (its parent gate was the bug, not the component itself).

**End of P0 Demo-Login Hotfix.**
