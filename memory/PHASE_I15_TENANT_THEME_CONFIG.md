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
