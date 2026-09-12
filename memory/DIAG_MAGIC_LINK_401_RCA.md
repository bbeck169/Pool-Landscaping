# DIAG · Magic-link `/e/estimate` 401 RCA scaffolding

**Status:** Temporary diagnostic scaffolding. Preview-only.
**Owner:** main agent (auto-generated).
**Ship-date:** Feb-2026.

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
