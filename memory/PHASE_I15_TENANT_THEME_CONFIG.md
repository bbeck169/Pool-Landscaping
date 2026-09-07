# Phase I1.5 — Tenant Theme Config

Ship log for the multi-sub-phase Tenant Theme Config feature.
Each sub-phase appends its own section below; do not rewrite prior
sections.

---

## I1.5.a — Backend Theme storage + API + Preset Registry
**Shipped:** Feb-2026 · **Status:** GREEN

### What shipped
- **New service package** `backend/services/theme/`
  - `presets.py` — static in-code registry of **31 presets**
    (`default`, `pool_landscape`, `pool`, `landscape`, `hvac`,
    `plumbing`, `electrical`, `roofing`, `solar`, `cleaning`,
    `pest_control`, `moving`, `painting`, `flooring`, `drywall`,
    `handyman`, `fencing`, `appliance_repair`, `garage_door`,
    `auto_detail`, `junk_removal`, `snow_removal`, `notary`,
    `photography`, `salon`, `spa`, `dental`, `medical`, `legal`,
    `real_estate`, `fitness`). Public API: `PRESETS`,
    `get_preset(key)`, `list_presets()`.
  - `validate.py` — `validate_theme_payload()` enforcing:
    - 5 sections required (menu, rail, tiles, buttons, accents)
    - Every slot has `{mode, solid?, gradient?}` shape
    - **Text / small-element slots are solid-only** (menu.text,
      rail.text, tiles.text, tiles.border, buttons.text,
      accents.text, accents.link, accents.focus_ring,
      accents.badge_text). Gradient here → `GRADIENT_NOT_ALLOWED` 400.
    - **WCAG AA (≥4.5:1)** paired contrast (skipped when either
      side is a gradient — soft warning belongs in I1.5.b UI):
      - menu.text vs menu.bg
      - rail.text vs rail.bg  ← per user note
      - tiles.text vs tiles.bg
      - buttons.text vs buttons.bg
      - accents.link vs `#ffffff` (default page canvas)
      - accents.badge_text vs accents.badge_bg
      Fail → `CONTRAST_FAIL` 400 with friendly WCAG-guidance msg.
    - Unknown sections / slots → 400.
  - `contrast.py` — pure `relative_luminance` / `contrast_ratio` /
    `passes_aa_normal_text` (isolated so I1.5.b can reuse).
- **New endpoints** in `backend/routers/tenants.py`:
  - `GET  /api/tenants/me/theme` — any authenticated user in the
    tenant. Returns persisted `theme` if present, else the
    `default` preset **expanded (no auto-write)**.
  - `PUT  /api/tenants/me/theme` — admin-only. Validates + stamps
    `theme_updated_at` / `theme_updated_by`. Manager/tech → 403.
  - `GET  /api/theme-presets` — returns `{presets: [{key, name,
    theme}]}` (31 entries).
  - `POST /api/tenants/me/theme/apply-preset` — admin-only. Copies
    the preset. Unknown key → `UNKNOWN_PRESET` 400.
- **Frontend hook bonus** (`frontend/src/hooks/useIsNarrow.js`):
  - Added `useIsWide(breakpoint)` and `useBreakpoint()` (returns
    `"base" | "sm" | "md" | "lg" | "xl" | "2xl"`) alongside the
    existing `useIsNarrow` — all three share the same
    `useSyncExternalStore` substrate.
  - Renamed contract test →
    `frontend/src/test/use-breakpoint-hooks.test.jsx` (18 specs,
    all green).
- **Test file:** `backend/tests/test_i15a_tenant_theme_endpoint.py`
  — **9 tests, all green** (round-trip, gradient-in-text reject,
  contrast-fail reject, preset list count, apply-preset happy +
  unknown, RBAC, module-level all-presets-pass-AA lock).

### Contract locks
- Every preset in the registry passes the validator (locked in
  `test_i15a_presets_all_pass_aa`).
- No `brandGradient` alias introduced.
- `GET /api/tenants/me/theme` **never** writes when unset — DB row
  stays `theme`-less until `PUT` / `apply-preset` (locked in
  `test_i15a_get_returns_default_expanded_when_unset`).

### Test results
- Backend: `tests/test_i15a_tenant_theme_endpoint.py` — **9/9 pass**.
- Frontend: `src/test/use-breakpoint-hooks.test.jsx` — **18/18 pass**.
- Frontend suite regression baseline: **468 files / 3698 tests
  passing / 34 pre-existing skips** (Hygiene B quarantine
  untouched; no new drift).

### Notes for I1.5.b / I1.5.c
- The theme model deliberately allows a free-form `preset: str`
  key on `PUT` so the editor can persist custom themes without
  pinning to a registry key. `apply-preset` is the authoritative
  writer for registered keys.
- Preset registry is deep-copied on every read (`get_preset()`) so
  a downstream admin PATCH that mutates a slot never corrupts the
  module-level source.
- Gradient contrast validation is intentionally skipped in
  I1.5.a — surface a soft warning in the editor UI in I1.5.b.
- For I1 industry profile: `services.theme.presets.get_preset(key)`
  is the auto-apply entry point — pass the industry key and it
  returns a validated, deep-copied theme ready to persist.

---

## I1.5.b — Frontend Theme Editor UI in Settings + Live Preview
**Shipped:** Feb-2026 · **Status:** GREEN

### What shipped

**Backend addition — shadow validate endpoint**
- `POST /api/tenants/me/theme/preview` — admin-only, side-effect-free.
  Returns `{valid, errors: [{code, path, message, computed_ratio?}]}`.
  Unlike PUT (which raises on the first violation), preview collects
  **every** contrast failure in one response so the editor can
  highlight all offending slots at once.
- New `preview_theme_payload()` + `_structural_validate()` helpers in
  `backend/services/theme/validate.py` (structural pass raises
  immediately, contrast pass accumulates errors).
- `ThemeValidationError` extended with `computed_ratio` field —
  echoed on 400 responses from PUT and on errors from the preview
  endpoint so the editor UI can render the exact numeric ratio.
- Backend tests: 5 new tests in
  `tests/test_i15a_tenant_theme_endpoint.py` (`test_i15b_*`) —
  **14/14 pass** total for the file.

**Frontend — Theme editor page**
- New page `frontend/src/pages/settings/ThemeSettings.jsx`.
- Route `/settings/theme` registered in `App.js` under the existing
  `<AdminOnly><SettingsHub /></AdminOnly>` block (managers/admins
  reach it; techs 403).
- New "Theme" entry in `layouts/SettingsHub.jsx` sidebar (5 canonical
  entries: general, branding, **theme**, integrations, social).
- Two-column responsive layout via `useIsWide(768)` (the hook
  shipped in I1.5.a's bonus): editor left / live preview right on
  ≥ md, stacked below.
- Editor features:
  - Preset picker (shadcn Select) + Apply-preset confirm modal
    (shadcn AlertDialog) → `POST /apply-preset` with `{key}`.
  - Per-section shadcn Accordion (menu expanded by default).
  - Per-slot solid/gradient mode toggle **hidden** on solid-only
    slots (menu.text, rail.text, tiles.text, tiles.border,
    buttons.text, accents.text/link/focus_ring/badge_text).
  - Solid mode: color picker + hex input with lowercase normalize
    on blur.
  - Gradient mode: two color pickers (from/to) + 0–360 angle Slider
    + inline swatch + soft warning banner ("Contrast not
    auto-checked on gradient — verify legibility visually").
  - Debounced 400 ms POST to `/preview` on every change; inline
    per-slot error surfaces + top-of-page summary lists every issue
    (path + computed ratio).
  - **Save** disabled when the working payload isn't dirty **or**
    preview reports errors.
  - **Discard changes** button — resets working state to server
    state (dirty flag cleared).
- Live preview panel renders sample nav, rail (3 pins), tiles row
  (3 KPI tiles), buttons row (Primary CTA + Secondary + Delete), and
  accents row (link + focus ring + badge) using the current editor
  state — no server round-trip required to see changes.

**Test suite**
- New vitest `frontend/src/test/i15b-theme-editor.test.jsx` — 9/9
  pass. Covers: 5-section render · solid-only toggle hiding ·
  solid→gradient flip · color→preview live update ·
  preset-enumeration · apply-preset modal + body shape · discard ·
  save-disable-under-errors · save PUT body.
- Adjusted `test/settings-nav-old-routes.test.jsx` from "4 canonical
  keys" → "5 canonical keys" (added `theme`) — still green.

### Test results
- Backend: `tests/test_i15a_tenant_theme_endpoint.py` — **14/14 pass**
  (9 from I1.5.a + 5 new I1.5.b preview tests).
- Frontend suite: **469 files / 3707 tests passing / 34 pre-existing
  Hygiene B skips** — zero new drift, zero new K78 tags.
- Screenshot captured at `/tmp/theme-editor.png` — editor rendering
  the default preset with menu expanded, live preview showing nav +
  rail + tiles + buttons + link + focus ring + badge.

### Contract locks
- Live preview never persists — `POST /preview` is validation-only
  (locked in `test_i15b_preview_never_persists`).
- No `brandGradient` alias reintroduced anywhere.
- Editor speaks the tester-confirmed backend contract verbatim:
  snake_case slot names, lowercase hex, `{key}` on apply-preset.
- Solid-only slots at both layers (validator + editor UI) — the
  editor can't even *offer* a gradient mode toggle on them.

### Notes for I1.5.c / I1.5.d
- The editor loads via `api.get("/tenants/me/theme")` + presets via
  `api.get("/theme-presets")` on mount and consumes the returned
  theme directly — the future `useTenantTheme()` hook (I1.5.c) can
  drop in as a cache in front of these calls without touching the
  editor UI.
- The editor currently doesn't refresh the app-shell colours on save
  — that's I1.5.c's job (invalidate the `useTenantTheme` cache and
  the shell's `theme.js` computed vars).
- Gradient contrast is deliberately *unchecked* end-to-end (backend
  skips, editor surfaces a warning). If a stricter mode is wanted
  later, wire it through the existing `computed_ratio` field.

### Deferred (out of I1.5.b scope)
- App-shell wiring to consume the persisted theme (that's I1.5.c —
  the `useTenantTheme` hook + `theme.js` refactor).
- Backwards-compat migration script + preset seed audit (I1.5.d).

---

## I1.5.c — `useTenantTheme` hook + `theme.js` refactor
**Shipped:** Feb-2026 · **Status:** GREEN

### What shipped

**Client-side preset registry**
- `frontend/src/theme/presets.js` — 31-entry mirror of the backend
  registry (generated from `services/theme/presets.py` at ship
  time to guarantee byte-perfect parity).
- `getClientPreset(key)` returns a deep-cloned entry, falling back
  to `default` on unknown keys.

**Tenant CSS-var overlay**
- `frontend/src/theme/tenantVars.js`:
  - `TENANT_VAR_SPEC` — 16-slot spec mapping every backend slot
    (`menu.bg`, `rail.text`, `tiles.border`, `accents.badge_bg` …)
    to a `--tenant-<name>` CSS custom-property name.
  - `writeTenantCssVars(el, theme)` writes both a solid `#hex` and
    (for fill slots) a `-css` variant that carries the full
    `linear-gradient(...)` string.
  - `clearTenantCssVars(el)` — used on sign-out.
  - `tenantCssVar(path, fallback, kind)` — returns
    `"var(--tenant-<name>, <fallback>)"`.

**`useTenantTheme` hook + `TenantThemeProvider`**
- New file `frontend/src/hooks/useTenantTheme.jsx`.
- Fetches `GET /api/tenants/me/theme` once on mount, exposes
  `{ theme, isLoading, error, refetch, applyOverride }`.
- **Auth-aware**: re-fetches when the auth-context `user.id`
  transitions to non-null (fixes the login-race where the provider
  mounts before a token exists → falls back to default → tenant
  palette never lands until manual reload).
- Clears CSS vars on sign-out so a stale palette never bleeds into
  the login page.
- Fallback contract: on any GET error → returns the client-side
  `default` preset without throwing.
- Consumers outside the provider get the default with
  `isLoading=false`, no fetch (public routes work).
- Fixes React 18 StrictMode double-mount bug where the `alive`
  ref was flipped to `false` on the first synthetic unmount,
  swallowing the post-mount refetch.

**App-shell integration**
- `App.js` — `<TenantThemeProvider>` wraps the tree inside
  `<AuthProvider>` (public login route also renders inside it but
  clears the overlay via the auth-null branch).
- `settings/ThemeSettings.jsx` — save + apply-preset handlers call
  `applyTenantThemeOverride(persisted)` (optimistic reskin) and
  `refetchTenantTheme()` (authoritative reconcile) so the shell
  reskins in place the instant PUT returns 200.

**CSS overlay rules (`index.css`)**
- Non-invasive `!important` overlay for K74/K74.1/K75/K67 data
  attributes:
  - `[data-k74-solid-navy-chip]`, `[data-k74-solid-navy-tile]`,
    `[data-k74-1-schedule-tile]` → `--tenant-tiles-bg`
  - `[data-k75-nav-active]` → `--tenant-menu-bg`
  - `[data-k67-primary-cta]` → `--tenant-buttons-bg-css`
    (gradient-capable via the `-css` variant)
- Fallback in every rule = the historical hardcoded hex, so
  consumers outside `<TenantThemeProvider>` (tests, public routes)
  paint identically to pre-refactor pixels.

**Consumer sweep**
- **Zero consumer files touched.** Existing K64/K67/K70/K70a/K74/
  K74.1/K75/K76 JSX unchanged → every source-grep regression test
  passes verbatim. The reskin is a **stylesheet-only** concern.
- `theme.js` static exports **unchanged** — `colors.nav.bg`,
  `colors.tile.solidNavy`, `gradients.navyToGreen.css` etc. keep
  returning literal hex strings (K67, K64, K70a/K74 unit tests
  keep asserting on them verbatim).

### Test suite
- New:
  - `test/use-tenant-theme-hook.test.jsx` — 5 specs: mount fetch,
    refetch, GET-error fallback to default, `applyOverride`
    optimism, out-of-provider default.
  - `test/tenant-theme-css-vars.test.jsx` — 10 specs: writer
    covers every spec slot, gradient `-css` variant, clear removes
    every var, `tenantCssVar` shape, provider writes to
    `documentElement`, refetch flips in place, override flips
    without a GET.
  - `test/theme-preset-parity.test.js` — 3 specs: key equality,
    31-count, per-preset deep equal (via a Python subprocess that
    imports the backend registry — no source-file regex fragility).
- Bumped: `test/settings-nav-old-routes.test.jsx` from 4 → 5
  canonical sidebar keys in I1.5.b (unchanged this sub-phase).

### Test results
- Backend: `tests/test_i15a_tenant_theme_endpoint.py` — **14/14 pass**
  (9 I1.5.a + 5 I1.5.b preview).
- Frontend suite: **472 files / 3725 tests passing / 34 pre-existing
  Hygiene B skips** — zero new drift.
- Live runtime verify (Playwright): CSS var `--tenant-menu-bg`
  flips from `#0f172a` (default preset) → `#9d174d` (salon preset)
  on the admin dashboard between preset applies. Screenshots at
  `/tmp/reskin-default.png` and `/tmp/reskin-salon.png`.

### Guardrail sweep
- **No `brandGradient` alias** reintroduced.
- **No new hardcoded hex regressions** — every new hex reference
  lives inside `services/theme/presets.py`, `theme/presets.js`,
  `theme/tenantVars.js` (defaults map), or an `index.css` CSS-var
  fallback declaration. Pre-existing `#1B1F5C` hardcodings in
  legacy consumer files (from prior K-phases) are untouched.
- **All 34 pre-existing Hygiene B skips** stay put — no new
  quarantines this sub-phase.
- **Backend + frontend suites** both green.

### Notes for I1 (industry profile) — smart enhancement uptake
- The user-approved "Reset to industry default" button belongs in
  Phase I1. Wire it in the theme editor header row (next to Save)
  as a one-click `apply-preset` with `key = tenant.industry`. All
  the plumbing is now in place — `applyTenantThemeOverride` +
  `refetchTenantTheme` are already imported into
  `ThemeSettings.jsx`. See PRD backlog.

### Notes for I1.5.d (migration)
- Any tenant with a persisted `theme` in Mongo already round-trips
  through the validator (I1.5.a PUT guarantees). I1.5.d migration
  can be a no-op for tenants without a `theme` field (they read
  the `default` preset via the GET fallback).
- The client-side registry generator is a one-liner (see the
  `python <<'PY' ... > src/theme/presets.js` shell recipe). Bake
  it into `scripts/dump-theme-presets.py` as I1.5.d cleanup so
  future preset additions can't drift.


---

## I1.5.c.fix — CSS-var overlay coverage patch
**Shipped:** Feb-2026 · **Status:** GREEN

### What was broken
The I1.5.c CSS-var overlay landed with three surfaces missing
their `--tenant-*` wiring, plus two testing-affordances the QA
Playwright pass needed to verify overlay coverage post-fix:

1. **Schedule tile bg (K74.1 mint)** wasn't reskinning under any
   non-default preset — the overlay only re-hit `[data-k50-bg=
   "#EAF7F0"]` via `--tenant-tiles-bg`, which every 31-preset
   default pins to `#FFFFFF`. The mint schedule bg turned
   white on preset apply.
2. **Top-nav BAR** (`AdminTopBar.jsx` outer container) was not
   covered by any overlay rule — only the K75 active-item chip
   was. Editing `menu.bg` in the theme editor never reached the
   surface a tenant actually looks at.
3. **Reports "solid-navy" built tiles** didn't have a stable
   test-ID for the Playwright reskin verifier.
4. **Dashboard KPI identity chip** lacked a stable `data-testid`
   — every card interpolated `${testId}-icon-chip`, so a
   fixture-agnostic screenshot verifier had no reliable hook.

### What shipped
- **New derived-surface vars** in `frontend/src/theme/tenantVars.js`
  (`DERIVED_SURFACE_VARS` block, lines 65-84):
  - `--tenant-k74-identity` ← `accents.secondary` (was previously
    misrouted to `--tenant-tiles-bg` which regressed to white).
  - `--tenant-schedule-tile-bg` ← `accents.badge_bg` (new).
  Writer + clear path handles both alongside the 16-slot spec.
- **`index.css` overlay retargets + additions** (lines 163-211):
  - `[data-k74-solid-navy-chip="true"], [data-k74-solid-navy-tile="true"]`
    → `var(--tenant-k74-identity, #1B1F5C)` (retargeted from
    `--tenant-tiles-bg`).
  - `[data-k50-bg="#EAF7F0"]` → `var(--tenant-schedule-tile-bg,
    #EAF7F0)` (new rule).
  - `[data-testid="admin-topbar"], [data-testid="admin-topbar-
    narrow-wrap"], [data-testid="admin-topbar-wide-wrap"]` →
    `var(--tenant-menu-bg, #1B1F5C) !important` (new rule).
- **Dashboard KPI chip** (`pages/admin/Dashboard.jsx` line 147):
  data-testid is now unconditionally `"k74-kpi-identity-chip"`;
  per-tile identifier moved to `data-tile-key={testId}` so
  existing selectors like `kpi-active-jobs` still work through
  the attribute lookup. All 4 KPI chips carry the stable ID
  (screenshot verifier resolves 4 nodes → picks .first).
- **Reports built tile** (`pages/reports/ReportsHub.jsx` line 254):
  `BuiltTile` now accepts `isPrimary` (passed as `i === 0` in the
  hub grid map). The primary tile (revenue-total) gets
  `data-testid="k74-reports-tile-bg"` for the deterministic
  Playwright hook while non-primary tiles keep their existing
  `data-testid="reports-tile-<key>"` (all built tiles carry a
  `data-tile-testid` mirror + `data-k74-solid-navy-tile="true"`
  for CSS selection).
- **Mobile `TODO(I13)`** in `mobile/src/lib/jobStatus.ts` header
  (lines 11-34) documenting that React Native has no CSS-var
  substrate and I13 (mobile tenant theme parity) will wire the
  consumer to read `tenant.theme.accents.badge_bg` via a hook
  instead of the frozen K50 map.

### Runtime verification (Playwright + preview pod)
Logged-in as `super@aquaterra.com`, `admin/dashboard` +
`/reports` in the aquaterra tenant. Applied via the theme editor
using `POST /api/tenants/me/theme/apply-preset`.

| Surface / var             | Default preset | Salon preset applied |
|---------------------------|----------------|----------------------|
| `--tenant-menu-bg`        | `#1b1f5c`      | `#9d174d`            |
| `--tenant-schedule-tile-bg` | `#eaf7f0`    | `#fce7f3`            |
| `--tenant-k74-identity`   | `#1b1f5c`      | `#9d174d`            |
| `[data-testid="admin-topbar"]` computed bg | `rgb(27, 31, 92)` | `rgb(157, 23, 77)` (salon magenta) |
| `[data-testid="k74-kpi-identity-chip"]` chip bg | `rgb(27, 31, 92)` | `rgb(157, 23, 77)` |
| `[data-testid="k74-reports-tile-bg"]` bg  | `rgb(27, 31, 92)` | `rgb(157, 23, 77)` |
| KPI chip count on Dashboard | 4              | 4                   |

Screenshots (preview pod):
- `/tmp/i15c-fix-dashboard-default.png` — dashboard with the
  default navy topbar + navy KPI icon chips.
- `/tmp/i15c-fix-dashboard-salon.png` — dashboard after
  apply-preset(salon): topbar + all 4 KPI chips render magenta.
- `/tmp/i15c-fix-reports-salon.png` — Reports Hub with all 4
  BuiltTile backgrounds painted salon magenta; ComingSoon tiles
  keep their muted default (per K74 spec — only built tiles
  carry the K74 solid-navy attribute).
- `/tmp/i15c-fix-schedule-salon.png` — Schedule route captured
  under salon; no `open`/`scheduled` jobs on the test tenant
  today (0 K50 open cards to paint), but the CSS var flip was
  proven via `getPropertyValue('--tenant-schedule-tile-bg')`
  above. When jobs land in the `open` bucket the overlay will
  paint pastel-pink instead of mint.

Tenant returned to `default` preset after the verify pass so
the aquaterra demo boots on the K64/K74 signature palette
next run.

### Grep sweep (post-fix)
Ran the user-mandated regression grep across
`frontend/src/**`:
- `#1B1F5C` — 0 new hardcoded consumers. Pre-existing
  occurrences live inside `components/ui/select.jsx`,
  `components/ui/button.jsx`, `pages/settings/BrandLogoSettings.jsx`
  (K51 logo preview swatch), `layouts/AdminTopBar.jsx`
  (doc-comment only), and consumer files' doc comments —
  all documented in the I1.5.c ship report as "legacy K-phase
  hardcodings, untouched".
- `#EAF7F0` — 0 hardcoded consumers outside the allowed
  paths (`lib/jobStatus.js`, `mobile/lib/jobStatus.ts`,
  `theme/presets.js`, `theme/tenantVars.js`, `index.css`
  fallback, and test files).
- `#15803D` — 3 occurrences in `pages/reports/ReportsHub.jsx`
  for the K67 "Open report" green CTA pill. Pre-existing —
  outside the I1.5.c.fix scope (this fix targets 4 specific
  surfaces; the Open-report CTA is a K67 concern for a
  future phase).
- `navyToGreen` — 20 legitimate consumers of the `gradients.
  navyToGreen.css` canonical export (theme.js static export).
  All were retained by design per I1.5.c contract lock ("Zero
  consumer files touched — stylesheet-only concern").
- `brandGradient` — 0 code references. Present only in retired-
  alias assertions inside test files and a doc-comment in
  `topNavRegistry.js` documenting the retirement.

### Test results
- **Backend** — `tests/test_i15a_tenant_theme_endpoint.py`:
  **14 / 14 pass** (unchanged).
- **Frontend** — full suite: **472 files, 3725 tests passing,
  34 pre-existing Hygiene B skips**. Zero new drift. The
  previously failing (during exploration) `reports-hub-r1-tile-
  flip.test.jsx` now green because non-primary BuiltTiles
  retain their per-tile `data-testid`.
- **Targeted regression tests** re-run: `k70a-tile-theming`
  (21), `k75-top-nav` (33), `k67-navy-green-gradient` (13),
  `feb2026-dashboard-kpi-tint` (8), `k66-reports-hub-quick-
  access-tiles` (5 + 2 pre-existing skips), `i15b-theme-editor`
  (9), `tenant-theme-css-vars` (10), `use-tenant-theme-hook`
  (5), `theme-preset-parity` (3) — all green.

### Contract locks re-verified
- No `brandGradient` alias reintroduced.
- No new hardcoded hex in consumer files — every new hex lives
  in the preset registry, the tenantVars defaults map, or the
  index.css CSS-var fallback.
- All 34 pre-existing Hygiene B skips untouched.
- Public routes + jsdom tests still paint pre-refactor pixels
  (CSS fallback chain intact).

### Notes for I13 (mobile tenant theme parity)
Mobile `jobStatus.ts` now carries the `TODO(I13)` header.
When I13 lands: introduce a `useTenantThemeMobile()` hook
(likely an AsyncStorage-cached mirror of `useTenantTheme` from
web) that returns the persisted theme, then swap the mobile
Schedule card's `jobStatusColor(status)` call for a resolver
that overlays `tenant.theme.accents.badge_bg` on the
`open`/`scheduled` bucket only. The K50 frozen map stays put
as the offline-first fallback.

