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

