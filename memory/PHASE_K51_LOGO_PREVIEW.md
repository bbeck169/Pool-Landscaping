# Phase K51 · Feb-2026 — Admin logo preview toggle in Branding settings

## Brief
Admins editing their tenant logo at `/settings/branding` had a single
white-checkered preview tile — great for spotting transparency
artefacts, but no way to see how the same asset renders against the
**navy chrome** (`#1B1F5C`, the K50 nav-bar background) *before*
saving.  The navy chrome runs the tenant logo through a
`filter: brightness(0) invert(1)` white-fill treatment; a logo with
a solid (non-transparent) background degrades to an opaque white
rectangle under that filter — visually indistinguishable from a blank
tile.

**Goal.** Ship a side-by-side chrome preview surface (Light + Navy)
so admins can eyeball the treatment before Save, and hint at
low-contrast outcomes via a rough client-side heuristic.

**Non-goals.** Anything that touches the actual logo-processing
pipeline (upload endpoint, storage, white-fill filter itself), mobile
drawer chrome, the primary nav-bar rendering, or the customer portal
logo behaviour.  All four remain unchanged.

---

## What shipped

### 1. Side-by-side chrome preview
Location: `/app/frontend/src/pages/settings/BrandLogoSettings.jsx`,
mounted below the existing "Current logo" checkered preview and above
the "Last changed" audit line — same card, no route/layout change.

Two 96 px tall tiles in a 2-col grid:

| Tile | Background | Filter applied to `<img>` | Testid |
| --- | --- | --- | --- |
| Light | `#FFFFFF` | *(none — raw asset)* | `logo-preview-light` |
| Navy | `#1B1F5C` (`rgb(27, 31, 92)`) | `brightness(0) invert(1)` (mirrors the live nav-bar treatment) | `logo-preview-navy` |

The previewed asset is `pending?.previewUrl` (the pre-save blob URL
during a replace) if present, else the currently-live absolute logo
URL, else `null` → each tile falls back to a "No logo uploaded"
placeholder (`logo-preview-empty` / `logo-preview-navy-empty`).

### 2. Contrast heuristic
On the navy tile's `<img onLoad>`, we sample the logo onto a 32×32
canvas and count fully-opaque pixels (α ≥ 240 out of 255).  If ≥95%
of the sample is opaque, we surface a warning affordance
(`logo-preview-contrast-warning`) that reads:

> "This logo looks like a solid block on navy chrome — the app-shell
> white-fill treatment will render it as an opaque white rectangle.
> Consider a transparent background or a lighter variant."

**Guardrails.**
* The heuristic is a *hint*, not a gate.  Upload/Save is never
  blocked by contrastWarn state.
* `getContext` unavailability, cross-origin taint, or any thrown
  error inside the sampling routine is swallowed silently — we never
  want the heuristic to break the preview itself.
* Sample re-runs whenever the previewed source changes (React
  `useEffect` resets `contrastWarn` on every `previewSrc` update),
  so a warning does not persist across re-uploads.

### 3. Testids added
Standardised on the `logo-preview-*` namespace so it's easy to
distinguish from the existing `brand-logo-*` testids on the
transparency-checker tile above:

* `logo-preview-chrome-group` — wrapper
* `logo-preview-light` — light chrome tile
* `logo-preview-light-img` — light chrome logo `<img>`
* `logo-preview-navy` — navy chrome tile
* `logo-preview-navy-img` — navy chrome logo `<img>` (carries the
  `brightness(0) invert(1)` filter)
* `logo-preview-empty` — placeholder on light tile
* `logo-preview-navy-empty` — placeholder on navy tile
* `logo-preview-contrast-warning` — warning affordance

---

## Tests
File: `/app/frontend/src/test/k51-logo-preview.test.jsx` — 4 tests,
all passing under `yarn test:unit`.

1. **Standard render** — asserts both tiles present, navy tile has
   `element.style.backgroundColor === "rgb(27, 31, 92)"` (proves the
   K50 nav-bar navy is in lockstep with the preview chrome), light
   tile has `rgb(255, 255, 255)`, both `<img>`s resolve to the
   expected absolute URL, navy `<img>.style.filter ===
   "brightness(0) invert(1)"` while the light `<img>` has no filter,
   and no warning is surfaced under default jsdom (canvas returns
   `null` → heuristic short-circuits).

2. **No-logo edge case** — `tenant.logo_url === null` and
   `tenant.branding.logo_url === null`.  Both tiles still render,
   navy chrome preserved, both placeholder testids surface with
   "No logo" copy, no logo `<img>` tags exist, no warning affordance.

3. **Contrast heuristic — trigger** — installs a canvas polyfill via
   `HTMLCanvasElement.prototype.getContext` that returns a controlled
   `ImageData` payload with 100% opaque pixels.  Manually fires
   `load` on the navy `<img>` (jsdom doesn't load real images), then
   asserts `logo-preview-contrast-warning` appears with the expected
   actionable copy.

4. **Contrast heuristic — safe path** — same canvas polyfill but
   with only 10% opaque pixels; asserts the warning affordance does
   NOT surface.  (Guards against a false-positive regression where
   any successful `getImageData` call would flip the warning on.)

### Pre-existing regressions
Ran the four sibling suites that also mount `BrandLogoSettings` /
`BrandLogo`:

* `brand-logo.test.jsx` — 6/6 pass
* `brand-logo-uploader.test.jsx` — 8/8 pass
* `brand-logo-last-changed.test.jsx` — 3/3 pass
* `brand-logo-single-instance.test.jsx` — 3/3 pass

No regressions.

---

## Files touched

| File | Change |
| --- | --- |
| `frontend/src/pages/settings/BrandLogoSettings.jsx` | Added `contrastWarn` state, `onNavyPreviewLoad` heuristic, `previewSrc` selector, side-by-side chrome preview section, `AlertTriangle` icon import. |
| `frontend/src/test/k51-logo-preview.test.jsx` | New — 4 tests covering standard render, no-logo edge case, heuristic trigger, heuristic safe path. |
| `memory/PHASE_K50_THEMING.md` | Cross-linked K51 as the shipped follow-up to the "white-fill logo asset" future-work item. |
| `memory/PHASE_K51_LOGO_PREVIEW.md` | New — this document. |

## Files intentionally NOT touched
* `frontend/src/components/branding/BrandLogo.jsx` — live nav-bar
  rendering path.  Untouched per non-goal.
* `frontend/src/layouts/AdminTopBar.jsx`, `AppLayout.jsx`,
  `UniversalMenu.jsx` — nav chrome.  Untouched per non-goal.
* `mobile/**` — no mobile parity in scope for K51.
* `backend/**` — no backend touches; the heuristic is entirely
  client-side.

---

## Revert safety
Isolated to two files (`BrandLogoSettings.jsx` — one hunk in the
render, one hunk of hooks/state — and `k51-logo-preview.test.jsx`).
Revert = drop the new preview `<div>`, remove `contrastWarn` state
and `onNavyPreviewLoad`, delete the new test file.  Nothing else in
the app reads any of the new testids or exported types.

---

## Follow-ups (not shipped)
* **Actual white-fill logo asset pipeline.**  K51 makes the
  interim `brightness(0) invert(1)` treatment *visible* to admins,
  but the "proper" fix (a stored light-variant logo asset baked into
  the tenant-brand pipeline) is still owed.  Tracked in
  `PHASE_K50_THEMING.md` → Follow-ups.
* **Threshold-tunable heuristic.**  The 95%-opaque cutoff is a
  reasonable default — could be widened to 90% or paired with a
  luminance check (mean R+G+B) so admins uploading a *dark solid*
  logo also get warned (dark solids → `brightness(0) invert(1)`
  produces white, same visual outcome).  Defer until we see field
  reports.
* **Preview-hover comparison** — nice-to-have hover state that
  overlays both tiles' logos on a 50/50 split for direct comparison.
  Not requested; parking for future polish.
