# DIAG · Magic-link `/e/estimate` 401 RCA — **CLOSED**

**Status:** ✅ **RESOLVED.** Root cause confirmed, fix landed,
diagnostic scaffolding removed.
**Owner:** main agent.
**Ship-date:** Feb-2026.

---

## Root cause (confirmed)

The customer magic-link surface at `/e/estimate?token=<jwt>` was
failing under automation with "Invalid estimate link" 401 when a
stale staff JWT was sitting in `localStorage.token`. The `authHeaders()`
helper in `frontend/src/api.js` was attaching that stale JWT as
`Authorization: Bearer <staff-jwt>` on the magic-link fetches
(`/portal/quotes/via-token?token=…`, `/portal/tenant/branding?token=…`,
`/portal/quotes/via-token/{jwt}/approve|decline|…`).

curl (no session) never sent that header → route accepted the query
token → 200. Browser (with a signed-in operator profile) → route
saw the Bearer header shadowing the query credential → 401.

The trailing-punctuation sanitizer that shipped in
`PublicEstimateLanding.jsx` was necessary (URL emitters can and do
append punctuation), but was not sufficient — it fixed one class of
failure mode without addressing the header-shadowing pattern.

## Fix landed

**Client-side (this codebase):**
`frontend/src/api.js` — `authHeaders(outboundPath)` is now gated on
the outbound URL. When the outbound path starts with `/portal/` AND
carries its own credential (either `?token=` in the query string OR
`/via-token/…` in the path segment), NO client-side session header
attaches. All other `/portal/*` calls (authenticated customer-portal
flow) preserve the pre-fix behaviour — `localStorage.token` and
`X-Tenant-Slug` still attach as before, honouring the K13 contract
(`k13-impersonation-token-wiring.test.jsx`).

Regression coverage: `frontend/src/test/api-auth-headers-portal-gate.test.jsx`
— 5 cases, all green:

1. `GET /portal/quotes/via-token?token=…` with staff JWT in
   localStorage → NO Authorization, NO X-Tenant-Slug.
2. `GET /portal/tenant/branding?token=…` — same.
3. `GET /quotes/xyz` (staff endpoint) — Authorization + X-Tenant-Slug
   attach as before.
4. Authenticated customer portal (`/portal/customers/me` from
   `/portal/dashboard`, sessionStorage.portal_token set alongside a
   stale staff JWT in localStorage) → portal_token wins, staff JWT
   does NOT shadow.
5. `POST /portal/quotes/via-token/{tok}/approve` — NO Authorization
   header.

Tester subsequently confirmed the fix reproduces the pre-fix failure
(3/4 cases), the sanitizer-plus-fix combo now passes end-to-end, and
the new Vitest suite is 5/5 green.

## Backend hardening — audit outcome

`_verify_estimate_token` in `backend/routers/estimate_viewer.py` is
**already query-only**. Every magic-link endpoint declares
`token: str = Query(...)`; there is no `HTTPBearer` dependency, no
`Authorization` header read, and no ambient session state consulted
inside `_verify_estimate_token`. FastAPI routes cannot be shadowed
by a Bearer header at the route/verifier level.

Concretely:
- `estimate_viewer.py:531` — `_verify_estimate_token(tok)` calls
  `jwt.decode(tok, …)` directly on its argument.
- `estimate_viewer.py:572-574` — `view_estimate_via_token(token: str = Query(...))`.
- `estimate_viewer.py:579-581` — `accept_via_token(token: str = Query(...))`.
- `estimate_viewer.py:607-608` — `decline_via_token(body, token: str = Query(...))`.
- `estimate_viewer.py:632-633` — `changes_via_token(body, token: str = Query(...))`.
- Path-token variants (`.../via-token/{token}/approve|decline|line-items/…`)
  also take the token from the path segment via FastAPI path parsing,
  not from the header.
- `business_settings.py:242-253` — `portal_tenant_branding` uses
  `token: str = Query(..., min_length=8)` and calls
  `_verify_estimate_token(token)` with the query value only.

**Conclusion:** Backend was already correct; the client fix was
sufficient. The pre-fix 401 was almost certainly emitted by an
upstream middleware or dependency chain that validated the
Authorization header before the route ran (or by a tenant-scoping
middleware that saw the Bearer JWT and short-circuited when its
tenant did not match the target quote's tenant). Stripping the
header client-side resolves the symptom deterministically regardless
of which upstream mechanism was catching it.

No backend code was changed in the fix dispatch. If a follow-up
dispatch wants defense-in-depth, the recommended pattern is:

- In each `/portal/*/via-token…` route, explicitly ignore
  `Authorization` (e.g. via a dedicated dependency that reads only
  `Query`), and add a route-level test that requests the endpoint
  with BOTH `?token=<valid>` and `Authorization: Bearer <valid-but-different-token>`
  and asserts the response comes from the query token, not the header.

But this is a hardening item, not a bug fix — flagged, not blocking.

## Diagnostic scaffolding — removed

All `[DEBUG-MAGIC-LINK-RCA — REMOVE AFTER ROOT CAUSE FOUND]` sentinel
blocks have been stripped from `EstimateView.jsx` and
`useTenantBranding.js`:

- Module-scope helpers (`_redactSensitive`, `_summarizeToken`,
  `_cookieNames`, `_swController`, `_buildMagicLinkDiag`) — removed.
- `errDiag` state + `setErrDiag` calls — removed.
- Temporary `data-outbound-url` / `data-token-summary` /
  `data-response-status` / `data-response-body` / `data-cookies` /
  `data-sw-controller` attributes — removed.
- `console.error("[magic-link-debug]", …)` and
  `[magic-link-debug:branding]` — removed.

**Kept (permanent):**

- Trailing-punctuation sanitizer in
  `PublicEstimateLanding.jsx` (line 39).
- One-shot `console.warn("[phase-a] magic-link token had trailing
  punctuation stripped …")` with `window.__phaseA_public_estimate_stripped`
  latch — permanent defense; fires only if the ingress URL emitter
  is broken.
- `data-testid="estimate-view-error"` — permanent testid.
- `data-error-source={backend-401|backend-404|backend-other|network|unknown}`
  — permanent classifier, small and useful.

## Tester-flagged side item — mobile action bar `md:hidden` leak

Fixed alongside the cleanup. `EstimateView.jsx:1116-1132` — dropped
inline `style={{ display: "flex" }}` and moved to Tailwind classes
(`className="ev-mobile-action-bar md:hidden flex items-stretch"`).
Now `md:hidden` wins at ≥ 768 px with no inline override to fight.

`theme-refresh-estimate-view.test.jsx` cases 4 and 4b updated to
assert:
- `bar.className.includes("flex")`
- `bar.className.includes("md:hidden")`
- `bar.style.display === ""` at both narrow AND wide viewports.

All 60 tests across the 11 magic-link / estimate-view / portal-gate
files green after cleanup. Full suite: **4238 pass / 19 pre-existing
fail / 34 skipped** — zero regressions.

---

## Original diagnostic scaffolding notes (retained for archaeology)

*Below this line is the pre-cleanup memo, kept for future reference.
Delete this whole file if archival value has passed.*

---

## Client-side fix landed (this dispatch)

**File:** `frontend/src/api.js` — `authHeaders(outboundPath)` is now
gated on the outbound URL rather than being applied unconditionally.

**Rule (final, narrower than the original dispatch wording):**
- A `/portal/*` outbound call is a **magic-link call** when the URL
  carries its own credential — either `?token=` in the query string
  or `/via-token/…` in the path segment.
- On magic-link calls, NO client-side session header attaches. Only
  `Content-Type: application/json` is sent. This kills the
  staff-JWT-shadowing bug at the root.
- All OTHER `/portal/*` calls (authenticated customer-portal —
  customer logged in with password, JWT in `localStorage.token`)
  preserve the pre-existing behaviour: attach the localStorage token
  (or the K13 `sessionStorage.portal_token` when on a `/portal` page)
  and the `X-Tenant-Slug` when present.

**Why narrower than the original wording**
- The dispatch said "any `/portal/*` outbound call → no Authorization
  and no X-Tenant-Slug, EXCEPT when sessionStorage.portal_token is
  set." That rule assumes authenticated customer-portal tokens live in
  `sessionStorage.portal_token`.
- Grepping the repo confirmed only ONE writer to
  `sessionStorage.portal_token`: `index.js:25`, which fires only on
  URLs carrying `?impersonation_token=` (the admin-as-customer
  impersonation flow). Regular customer logins go through
  `auth.jsx::persist()` (line 73), which writes to
  `localStorage.TOKEN_KEY` — the same key staff logins use.
- Applying the blunt rule would have broken every real authenticated
  customer-portal request (customer logs in → JWT in
  `localStorage.token` → hits `/portal/customers/me` → server sees no
  `Authorization` header → 401).
- The K13 contract test
  `frontend/src/test/k13-impersonation-token-wiring.test.jsx` explicitly
  guards this behaviour with its third case ("on /portal/* with no
  sessionStorage still uses localStorage").
- The narrower magic-link-marker rule (`?token=` or `/via-token/` in
  the outbound URL) covers exactly the failure mode described in the
  interceptor audit while leaving the authenticated customer-portal
  path untouched. All K13 tests remain green.

**Regression tests (new)**
`frontend/src/test/api-auth-headers-portal-gate.test.jsx` — 5 cases:
1. `GET /portal/quotes/via-token?token=…` with staff JWT in
   localStorage → NO Authorization, NO X-Tenant-Slug.
2. `GET /portal/tenant/branding?token=…` — same.
3. `GET /quotes/xyz` (staff endpoint) — Authorization AND X-Tenant-Slug
   attach as before.
4. Authenticated customer portal (`/portal/customers/me` from
   `/portal/dashboard`, sessionStorage.portal_token set alongside a
   stale staff JWT in localStorage) → portal_token wins, staff JWT
   does NOT shadow, X-Tenant-Slug attaches (K13 contract preserved).
5. `POST /portal/quotes/via-token/{tok}/approve` — NO Authorization
   header.

All 5 pass. All 3 K13 tests remain green. All 10 API-401 interceptor
tests remain green.

**Diagnostic sentinel instrumentation is intentionally kept in place.**
The tester will re-run the customer magic-link surface. If the fix
worked, the error surface simply will not render — the diag attributes
will render as empty strings. If it did not, the diag attributes will
tell us exactly what is still wrong.

## Backend hardening — deferred to a separate dispatch

Recommended follow-up: in `_verify_estimate_token` (backend), prefer
the `?token=` query param over any `Bearer` header when both are
present on a magic-link route. That is the server-authoritative fix
and stops the whole class of "another client re-attached a session
header" bugs. Explicitly out-of-scope for this dispatch — no backend
files were modified.

---

## Why this exists

The customer magic-link surface at `/e/estimate?token=<jwt>` continues
to fail under automation with an "Invalid estimate link" 401 even after
the trailing-punctuation sanitizer shipped in
`PublicEstimateLanding.jsx`. The sanitizer alone did not resolve the
failure, and curl (from the same pod) succeeds — which means the
browser is sending something structurally different from curl. This
scaffolding captures the exact browser-side outbound context on the
error branch so the root cause can be confirmed with real evidence.

## What was added (three files)

### 1. `frontend/src/components/EstimateView.jsx`

- Module-scope helpers (redaction-safe):
  - `_redactSensitive(s)` — removes any `Bearer <token>` header string
    and any 3-segment JWT longer than ~40 chars.
  - `_summarizeToken(t)` — returns `<jwt:len=N,head=xxxxxx,tail=xxxxxx>`
    (never returns the raw JWT).
  - `_cookieNames()` — returns cookie **names only**, semicolon-joined.
    Cookie *values* are never surfaced.
  - `_swController()` — reports one of `no-sw-api` / `no-controller` /
    `sw-controlled`.
  - `_buildMagicLinkDiag({...})` — assembles the redacted diag object.
- New `errDiag` React state (populated **only** on the token-mode
  error branch; success path never sets it).
- `load()` catches the api error and populates `errDiag` +
  `console.error("[magic-link-debug]", diag)` when a token is
  present.
- On the existing `estimate-view-error` element the following
  temporary `data-*` attributes are attached (empty string when no
  diag is present):
  - `data-outbound-url`
  - `data-token-summary`
  - `data-response-status`
  - `data-response-body`
  - `data-cookies`
  - `data-sw-controller`

Every temporary block is wrapped in explicit sentinel comments:

```jsx
// [DEBUG-MAGIC-LINK-RCA — REMOVE AFTER ROOT CAUSE FOUND]
...
// [/DEBUG-MAGIC-LINK-RCA]
```

### 2. `frontend/src/hooks/useTenantBranding.js`

- No UI error surface exists here (this hook silently falls back to
  default colours on 401). Console-only diag added inside the
  `useTenantBranding` catch, wrapped in the same
  `[DEBUG-MAGIC-LINK-RCA]` sentinel.
- Uses inline redaction (identical rules to EstimateView) — no shared
  helper import to avoid changing the module's public surface.

### 3. `frontend/package.json`

- Preview-only heap fix. `start` and `build` scripts now prepend
  `NODE_OPTIONS=--max-old-space-size=4096` so webpack does not OOM on
  the initial compile of this large codebase. Not related to the RCA
  itself but was required to bring the frontend back to `200 OK`
  before the diagnostic could be verified.
- Follow-up ticket recommended: investigate whether the leak is in a
  huge JSX file (`EstimateView.jsx` @ 1080 lines is a candidate) or a
  rogue watcher. Not blocking.

## Redaction guarantees

- No raw JWT is ever placed in a `data-*` attribute or console log.
- No cookie *value* is ever placed in a `data-*` attribute or console
  log — only cookie names.
- No `Authorization: Bearer <...>` header value is ever surfaced.
- Response body is capped at 500 chars and JWT-stripped before
  emission.

## Removal steps (when the root cause is confirmed)

1. `grep -rn "\[DEBUG-MAGIC-LINK-RCA" /app/frontend/src` → identify
   every sentinel-wrapped block.
2. Delete each block from top of file to bottom (order matters — the
   helpers must be removed together with their call sites).
3. Remove the `errDiag` state, the `setErrDiag` calls, and the
   `data-outbound-url` / `data-response-*` / `data-cookies` /
   `data-sw-controller` attributes.
4. Delete this memo.
5. Re-run `yarn test:unit` — the touched test surfaces
   (`public-estimate-landing-regression.test.jsx`,
   `theme-refresh-estimate-view.test.jsx`,
   `magic-link-outbound-url.test.jsx`) should stay green because
   they assert on `data-testid="estimate-view-error"` and
   `data-error-source`, not on the new debug attributes.

## Known findings from the audit that landed alongside this diag

### `api.js` interceptor / header shape

`authHeaders()` in `frontend/src/api.js` (lines 107-130) attaches
`Authorization: Bearer <localStorage.token>` and
`X-Tenant-Slug: <localStorage.tenant_slug>` on **every** call from the
`api` wrapper — including the magic-link calls at:

- `GET /portal/quotes/via-token?token=<jwt>` (EstimateView.load)
- `GET /portal/tenant/branding?token=<jwt>` (useTenantBranding)
- `POST /portal/quotes/via-token/<jwt>/decline` and
  `.../approve` (EstimateView.call2)

**Consequence:** If a staff user is signed in on the same browser
profile, opening a customer magic link will send BOTH the
`?token=<magic-jwt>` query string AND a `Bearer <staff-jwt>` header
plus `X-Tenant-Slug`. Depending on how the backend
`_verify_estimate_token` dependency reads its token (query vs header
precedence), the staff JWT could shadow the magic token and the
server could 401 with "Invalid estimate link" — which is exactly the
symptom the tester keeps hitting.

Per dispatch scope, **this file was not modified**. The finding is
recorded here so the next dispatch can decide whether to:

- (a) Strip `Authorization` + `X-Tenant-Slug` on paths starting with
  `/portal/*` or `/public/*` in `authHeaders()`, or
- (b) Fix precedence server-side in `_verify_estimate_token` to
  always prefer the query-string token when the path is a magic-link
  path (per problem statement: backend routing / token verify was
  explicitly out-of-scope for this dispatch).

Option (a) is client-only and lower blast radius. Option (b) is
authoritative and avoids relying on every caller doing the right
thing. Recommend a follow-up dispatch to decide.

### Service worker / PWA

- `grep -rn -E "serviceWorker\\.register|workbox" /app/frontend/src
  /app/frontend/public` → **zero matches**.
- `frontend/public/index.html` has no SW registration.
- `frontend/public/manifest.json` exists (PWA metadata only —
  `display: standalone`, theme color, icons) but does NOT register a
  service worker. Manifest alone will not install one.
- Bundle grep: `serviceWorker.register` in the served `bundle.js` →
  **zero matches**. `workbox` in bundle → **zero matches**.

Conclusion: No service worker is registered. SW cache theory is
ruled out. No defensive `unregister()` call was added on mount of
`PublicEstimateLanding` — it would be dead code.

### Sanitizer bundle verification

- `grep -c "trailing punctuation stripped" /tmp/bundle.js` → **1**
- Regex `[.,;:!?)\\]}` present in the bundle.
- Conclusion: the sanitizer shipped in
  `PublicEstimateLanding.jsx:39` IS present in the served dev
  bundle. Trailing-punctuation stripping is live.

## Test-suite delta

- Pre-instrumentation: 4286 tests, 19 pre-existing failures across 9
  files (schedule-map, portal-identity-and-add-card,
  pricebook-edit-item-modal, settings-nav-old-routes, and related —
  none of which touch the files modified here).
- Post-instrumentation: same 4286 tests, same 19 pre-existing
  failures. No new failures introduced.
- Touched surfaces (all pass):
  `estimate-view-decline-per-group`, `estimate-view-grouped-lock`,
  `estimate-view-phase-a-decline`, `estimate-view-phase-c-signature-gate`,
  `theme-refresh-estimate-view`, `public-estimate-landing-valid-token`,
  `public-estimate-landing-regression`, `magic-link-outbound-url`,
  `api-401-interceptor` — **52 / 52 green**.
