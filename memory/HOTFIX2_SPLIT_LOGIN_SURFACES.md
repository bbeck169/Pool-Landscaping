# P0 Hotfix #2 — Split Login Surfaces (Option C)

**Date:** 2026-02
**Severity:** P0 follow-up — customer-facing surface must never render demo tiles.
**Status:** LANDED. Both routes verified end-to-end via Playwright DOM assertions.

---

## 1. Chosen Route

**`/portal/login`** — path is free (no clash with existing `/portal/review/submit`, `/portal/sign/:token`, `/portal/service/:uuid`, `/portal/add-card`). No fallback needed.

## 2. Implementation Approach

Rather than duplicate the ~320-line `Login.jsx` into a second page, added a **`variant` prop** (`"staff" | "customer"`, default `"staff"`) to the existing component. The customer variant:

- **Never renders `<PreviewDemoLogins>`** — the `showDemoTiles` computation short-circuits to `false` unconditionally.
- **Never fetches `/api/config/public`** — the `useEffect` bails on the first line for the customer variant, so no network call is made.
- **Marks the DOM** — root element carries `data-testid="portal-login-page"` and `data-login-variant="customer"` so tests / debug tooling can distinguish.

Route wiring:

```jsx
<Route path="/login" element={<Login />} />               {/* variant defaults to "staff" */}
<Route path="/portal/login" element={<Login variant="customer" />} />
```

The `<PreviewDemoLogins>` component is **unchanged and still exported** — it just isn't imported/rendered on the customer route.

## 3. Files Touched

| File | Purpose |
|---|---|
| `frontend/src/pages/Login.jsx` | Added `variant` prop (defaults to `"staff"`). Customer variant skips both `/config/public` fetch and the demo-tiles JSX. Root `data-testid` split between `login-page` (staff) / `portal-login-page` (customer). Added `data-login-variant` marker. |
| `frontend/src/App.js` | Added `<Route path="/portal/login" element={<Login variant="customer" />} />` next to the existing `/login` route. |
| `frontend/src/pages/ResetPassword.jsx` | Post-reset navigate + "Back to sign in" link → `/portal/login` (ambiguous, safer default). |
| `frontend/src/pages/Signup.jsx` | "Already have an account? Sign in" link → `/portal/login` (customer-facing page). |
| `frontend/src/pages/ForgotPassword.jsx` | "Back to sign in" link → `/portal/login` (ambiguous, safer default). |
| `frontend/src/test/portal-login-hides-demo-tiles.test.jsx` | **NEW** — 14 tests covering: customer variant hides tiles across `preview`/`development`/`production`/fetch-fail/never-called-fetch, form/links still render, root testid + variant marker; staff variant regression guards (still shows tiles in preview, hides in production); source-grep locks the `/portal/login` route wiring. |

**No changes:**
- `frontend/src/components/auth/PreviewDemoLogins.jsx` — component intact.
- `backend/routers/config.py` — no backend touch. Same auth endpoint used by both routes.
- `mobile/**` — mobile login unchanged.
- Phase 41.1d stashed work (`stash@{0}: phase-41.1d-wip-post-hotfix-2`) untouched.

## 4. `to="/login"` / `navigate("/login")` Audit

`grep -rn 'to="/login"\|navigate("/login"' frontend/src` (excluding tests/coverage) surfaced **8 callsites**. Classification:

| # | File:Line | Context | Decision | Rationale |
|---|---|---|:---:|---|
| 1 | `ResetPassword.jsx:55` | Post-reset auto-redirect | → `/portal/login` | Ambiguous — customers and staff both reset. Safer default = tiles hidden. Staff can nav to `/login` manually. |
| 2 | `ResetPassword.jsx:188` | "Back to sign in" link | → `/portal/login` | Same as above. |
| 3 | `Signup.jsx:131` | "Already have an account?" link on signup | → `/portal/login` | Signup is customer-facing. |
| 4 | `tech/ToolsHub.jsx:132` | `<Navigate>` for unauthed tech tool | **kept `/login`** | Unambiguously staff (tech-role page). |
| 5 | `tech/BusinessCard.jsx:146` | `<Navigate>` for unauthed tech tool | **kept `/login`** | Unambiguously staff. |
| 6 | `ForgotPassword.jsx:117` | "Back to sign in" link | → `/portal/login` | Ambiguous, safer default. |
| 7 | `layouts/AppLayout.jsx:262` | Auth guard for admin/staff routes | **kept `/login`** | AppLayout wraps admin/staff-only routes. Not ambiguous. |
| 8 | `layouts/AppLayout.jsx:334` | Post-logout navigate from admin nav | **kept `/login`** | Same as above. |

**Result:** 4 changed to `/portal/login` (all customer-adjacent or ambiguous), 4 kept as `/login` (unambiguously staff-only surfaces). Zero remaining ambiguities.

## 5. DOM Assertions (Playwright, unmocked backend, `APP_ENV=preview`)

| Route | Root `data-testid` | `data-login-variant` | `preview-demo-logins` block | Tiles rendered | Form + "Forgot" + "Create account" |
|---|---|---|:---:|:---:|:---:|
| `/portal/login` | `portal-login-page` | `customer` | ❌ Absent | **0** | ✅ Present |
| `/login` (preview) | `login-page` | `staff` | ✅ Present | **4** | ✅ Present |

Screenshots captured: `/portal/login` shows Sign-in form + "Forgot password?" + "Create an account" only. `/login` shows the same form PLUS the "DEMO LOGINS (Preview Only)" section with Super Admin / Admin / Customer / Landscape Tech tiles.

## 6. Test Count Delta

- **Vitest:** 1258 → **1272** (+14 tests, one new file `portal-login-hides-demo-tiles.test.jsx`).
  - 11 tests for customer variant (hides tiles across all `app_env` values + fetch failure, form/links still render, no `/config/public` call, testid + variant marker).
  - 3 regression guards on staff variant (preview shows tiles, production hides, source-grep locks route wiring).
- **Mobile Jest:** 132 → **132** (unchanged, mobile login not touched).
- **Backend coverage gate:** unchanged (no backend touch this phase).

## 7. Invariants Held Green (Post-Hotfix)

| Gate | Result |
|---|---|
| Frontend Vitest | **1272 / 1272 passed** ✅ |
| Mobile Jest | **132 / 132 passed** ✅ |
| Frontend ESLint `--max-warnings=0` | exit **0** ✅ |
| Backend curated coverage gate | Unchanged from previous hotfix (149 tests, 2.45%, floor 2%) ✅ |
| `/portal/login` DOM | 0 tiles, variant marker `customer` ✅ |
| `/login` DOM | 4 tiles in preview, variant marker `staff` ✅ |

## 8. Phase 41.1d Stash Confirmation

- **Stash:** `stash@{0}: On main: phase-41.1d-wip-post-hotfix-2`
- Verified via `git stash list` — one entry, correct label, untouched during this hotfix.
- **Resume with:** `git stash pop stash@{0}` (or `git stash apply` to inspect first).
- Stashed files: `backend/tests/conftest.py`, six `test_phase34_task_*.py` files, `backend/tests/_phase34_asyncio.py` — see the Phase 41.1d hand-off for the WIP session-loop-pin approach.

## 9. Guardrail Confirmation

- ✅ `<PreviewDemoLogins>` component unchanged — still works on `/login`.
- ✅ Backend `/api/config/public` untouched.
- ✅ Mobile login unchanged.
- ✅ Phase 41.1d WIP still in stash — no accidental changes.
- ✅ Default landing route for authed users unchanged (still `landingFor(role)`).
- ✅ Same auth endpoint used by both routes (`useAuth().login()`).

**End of P0 Hotfix #2 (Option C) report.**
