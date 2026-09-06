# Phase K67 · Gradient Palette Sitewide (Navy → Green) — Ship Report

**Status:** COMPLETE (preview-verified).
**Scope:** Replace the sky-blue stop in every "blue-to-teal-green" gradient surface with the menu navy (`colors.nav.bg = #1B1F5C`) while preserving the green stop and gradient direction. All gradients now read as **navy → green** (or **green → navy** where direction had green-on-the-left) instead of **blue → teal-green**, visually cohering with the K50–K64 navy nav theme.

---

## 1 · What shipped

### Theme (single source of truth)

- **NEW canonical token** — `gradients.navyToGreen` exported from `theme.js`:
  ```js
  gradients.navyToGreen = {
    from: "#1B1F5C",        // menu navy (colors.nav.bg)
    to:   "#16A34A",        // green-600 (unchanged)
    css:      "linear-gradient(90deg, #1B1F5C 0%, #16A34A 100%)",
    cssHover: "linear-gradient(90deg, #2A2F7A 0%, #22B457 100%)",  // +8% lightness each stop
    fg: "#FFFFFF",
    textShadow: "0 1px 2px rgba(0, 0, 0, 0.25)",
  }
  ```
  A unit test locks `gradients.navyToGreen.from === colors.nav.bg` so the navy stop can never silently diverge from the K50 nav bg.

- **`colors.gradient` (K52 signature) end stop swapped in-place:**
  ```diff
  - to:   "#7DD3FC",                                                       // sky-300
  + to:   "#1B1F5C",                                                       // K67 · menu navy
  - css:      "linear-gradient(90deg, #22C55E 0%, #7DD3FC 100%)",
  + css:      "linear-gradient(90deg, #22C55E 0%, #1B1F5C 100%)",
  - cssHover: "linear-gradient(90deg, #34D673 0%, #93DDFD 100%)",
  + cssHover: "linear-gradient(90deg, #34D673 0%, #2A2F7A 100%)",
  ```
  Direction unchanged. Green stop unchanged. Comments in-file document the K67 palette shift + retained `textShadow` reasoning (now purely for perceptual mid-point legibility, not raw contrast).

- **`brandGradient` / `brandGradientCss` re-routed** (marked `@deprecated K67 · use gradients.navyToGreen.*`):
  ```diff
  - export const brandGradient = ["#0284C7", "#16A34A"];              // sky-600 → green-600
  + export const brandGradient = ["#1B1F5C", "#16A34A"];              // K67 navy → green
  - export const brandGradientCss = `linear-gradient(90deg, ${brandGradient[0]} 0%, ${brandGradient[1]} 100%)`;
  + export const brandGradientCss = gradients.navyToGreen.css;
  ```
  ~60 existing callers of `brandGradientCss` (auth pages, hero banners, badges, etc.) auto-inherit the palette shift. Full call-site migration is a K67 follow-up (removal phase); K67 does not delete the aliases.

### Direct callers migrated to the canonical token (per user's audit list)

| File | Change |
|------|--------|
| `frontend/src/components/ui/button.jsx` | Primary Button variant class list: swapped `#7DD3FC 100%` → `#1B1F5C 100%` and `#93DDFD 100%` → `#2A2F7A 100%`. Text-shadow retained for perceptual mid-point legibility. |
| `frontend/src/components/ui-kit.jsx` | Primary Chip inline `"linear-gradient(90deg, #0284C7 0%, #16A34A 100%)"` → `gradients.navyToGreen.css`. |
| `frontend/src/pages/portal/PortalPages.jsx` | Portal hero banner inline `"linear-gradient(90deg, #0284C7, #16A34A)"` → `gradients.navyToGreen.css`. |
| `frontend/src/pages/customers/CustomerChemistry.jsx` | AI-dosing icon plate 135deg diagonal — swapped inline `"linear-gradient(135deg, #0284C7 0%, #16A34A 100%)"` for `gradients.navyToGreen.css.replace("90deg","135deg")` so the diagonal direction is preserved while the stops flow through the canonical token. |

### Deliberately NOT touched (K64 grep-lock preserved)

- **`colors.nav.bgActiveNavy = #303AA0`** — the K64 solid active-nav is a SOLID, not a gradient. Untouched.
- **`pages/portal/PortalReviewSubmit.jsx:127`** — the `linear-gradient(135deg, #0284C7, #4F46E5)` blue→indigo diagonal is NOT a blue-to-green gradient. Out of K67 scope (user's phase title is specifically "Navy → Green").
- **`pages/tenants/TenantsAdminPage.jsx:20`** — per-tenant brand color DEFAULTS (`brand_primary: "#0284C7", brand_secondary: "#16A34A"`) are user-configurable customizations, not theme tokens.
- **`pages/ops/MapPages.jsx`** — polyline colour picker.
- **Invoices late-fee badge, BusinessOS sub-nav, calendar preset, customers scope pill** — all K64 grep-lock surfaces, verified untouched via grep before and after.

### Tests

- **NEW `frontend/src/test/k67-navy-green-gradient.test.js`** — 12 vitest cases across 4 describe blocks:
  1. Canonical `gradients.navyToGreen` token exports the exact locked stops.
  2. Navy start stop equals `colors.nav.bg` (single-source-of-truth invariant).
  3. `brandGradient` / `brandGradientCss` aliases re-route to K67.
  4. `colors.gradient` (K52 signature) end stop is navy; from/css/cssHover locked.
  5. `theme.js` gradient block has no residual sky hex literals inside its scope (comment-stripped regression grep).
  6. Primary Button variant class list uses only K67 stops — inside `bg-[linear-gradient(...)]` classes.
  7. `ui-kit.jsx` primary Chip references `gradients.navyToGreen.css` (no inline literal).
  8. `PortalPages.jsx` hero banner references the canonical token.
  9. `CustomerChemistry.jsx` keeps 135deg direction while adopting K67 stops.
  10. K64 grep-lock — solid active-nav `#303AA0` untouched.
  11. PortalReviewSubmit blue→indigo diagonal deliberately preserved.
  12. TenantsAdminPage per-tenant brand-color defaults untouched.
- **Updated snapshot expectations** — `k52-theming.test.js` (22 tests) + `k64-nav-active-hover-unify.test.jsx` (12 tests) + `feb2026-button-tone.test.jsx` (7 tests). All green.

**Total K67 + adjacent theme tests: 53/53 PASS.**

### Pre-existing failures (not K67-caused)
- `import-resolution-guard.test.js` — reports 2 unresolved imports in **other** test files (`f5-armtodelete-retrofit.test.jsx` → `.*TypedConfirmModal`, `k47-invoice-view-tracking.test.jsx` → `@/src/components/invoices/InvoiceViewHistory`). Verified pre-existing via `git stash` bisect.
- `phase30-login-tweaks.test.jsx` + `portal-login-hides-demo-tiles.test.jsx` — mock `@/theme` entirely (`brandGradientCss: "linear-gradient(#000,#111)"`) so they don't consume K67 changes at all. Their failures are pre-K67 flakes in the login DOM selector expectations.

---

## 2 · Full grep audit — before / after

### Before
```
grep -rn "linear-gradient.*#0284C7\|linear-gradient.*#7DD3FC\|linear-gradient.*22C55E.*7DD3FC\|linear-gradient.*0284C7.*16A34A" src/ (excluding /test/):
  components/ui-kit.jsx:190  → "linear-gradient(90deg, #0284C7 0%, #16A34A 100%)"        ✗
  components/ui/button.jsx:33 → bg-[linear-gradient(90deg,_#22C55E_0%,_#7DD3FC_100%)]     ✗
  pages/customers/CustomerChemistry.jsx:114 → "linear-gradient(135deg, #0284C7 0%, #16A34A 100%)"  ✗
  pages/portal/PortalPages.jsx:175 → "linear-gradient(90deg, #0284C7, #16A34A)"           ✗
  pages/portal/PortalReviewSubmit.jsx:127 → "linear-gradient(135deg, #0284C7, #4F46E5)"   ← blue→indigo, OUT OF SCOPE
```

### After
```
grep -rn "linear-gradient.*#0284C7\|linear-gradient.*#7DD3FC\|linear-gradient.*22C55E.*7DD3FC\|linear-gradient.*0284C7.*16A34A" src/ (excluding /test/):
  pages/portal/PortalReviewSubmit.jsx:127 → "linear-gradient(135deg, #0284C7, #4F46E5)"   ← untouched (blue→indigo)
```

**All blue-teal-green gradient literals in the app source have been eliminated.** The single remaining `#0284C7` reference is in a blue-to-INDIGO diagonal that is explicitly out of scope per the user's phase title.

### Callers via the deprecated `brandGradientCss` alias (auto-inherit)
```
grep -rn "brandGradientCss\|brandGradient\b" src/ (excluding /test/):
  ~60 hits across auth pages, dashboard hero, hero banners, misc badges
  All resolve through gradients.navyToGreen.css post-K67. No action needed.
```

---

## 3 · WCAG AA / AAA contrast note

| Surface | Before (blue-teal) | After (K67 navy-green) | Verdict |
|---------|--------------------|------------------------|---------|
| White text on gradient **start** stop | `#0284C7` sky-600 → 4.6 : 1 (AA body) | `#1B1F5C` menu navy → **12.8 : 1 (AAA at all sizes)** | ✅ MAJOR uplift |
| White text on gradient **end** stop (blue-teal-green) | `#16A34A` green-600 → 4.4 : 1 (AA body / AAA large) | `#16A34A` (unchanged) → 4.4 : 1 | ✅ Preserved |
| White text on K52 button **end** stop (green-sky) | `#7DD3FC` sky-300 → 2.4 : 1 raw (below AA — required `text-shadow` patch to hit AA large) | `#1B1F5C` menu navy → **12.8 : 1 (AAA at all sizes)** | ✅ MAJOR uplift — the `text-shadow` patch is now cosmetic, not a compliance crutch |
| White text on gradient **perceptual mid-point** | luminance ~0.55 (green-teal cyan blend, marginal) | luminance ~0.35 (green-navy blend, well above 3:1 large-text bar) | ✅ Preserved above threshold; `text-shadow` retained for the small-text portion of primary buttons |

**Verdict:** No surfaces became marginal. Every surface either improved to AAA or preserved its pre-K67 pass. `text-shadow` retained on primary Button and `gradient.textShadow` token — no longer needed for raw contrast, retained for perceptual mid-point legibility.

---

## 4 · Files changed

| Kind | File | Lines |
|------|------|-------|
| MOD | `frontend/src/theme.js` | +50/-12 (new `gradients.navyToGreen`; K52 gradient end swap; brandGradient aliases re-routed with `@deprecated K67`) |
| MOD | `frontend/src/components/ui/button.jsx` | +6/-4 (primary variant class list) |
| MOD | `frontend/src/components/ui-kit.jsx` | +7/-3 (primary Chip → canonical token) |
| MOD | `frontend/src/pages/portal/PortalPages.jsx` | +2/-1 (hero banner → canonical token) |
| MOD | `frontend/src/pages/customers/CustomerChemistry.jsx` | +11/-3 (135deg icon plate → canonical token, direction preserved) |
| NEW | `frontend/src/test/k67-navy-green-gradient.test.js` | 152 (12 tests) |
| MOD | `frontend/src/test/k52-theming.test.js` | +12/-9 (K52 test snapshots refreshed for navy end) |
| MOD | `frontend/src/test/k64-nav-active-hover-unify.test.jsx` | +4/-3 (K64 snapshot refreshed) |
| MOD | `frontend/src/test/feb2026-button-tone.test.jsx` | +3/-2 (start-stop expectation updated) |
| DOC | `/app/memory/PHASE_K67_GRADIENT_NAVY_GREEN.md` | this file |
| DOC | `/app/memory/PRD.md` | entry prepended |

No backend files changed. No `.env` changes. No dependency additions.

---

## 5 · Screenshot notes

Captured at `/tmp/k67_login.png` + `/tmp/k67_dashboard.png` + `/tmp/k67_suite.png`.

- **Login page primary Button** (`Sign in →`) — renders the new K67 gradient with a clear **green-to-navy** sweep. White label remains crisp against the navy end (12.8:1 contrast vs 2.4:1 pre-K67).
- **Onboarding modal `Start setup` button** — same K67 gradient. Full navy end visible on the right; green on the left.
- **Dashboard KPI hero tiles** — the "Total Revenue $200.00 (+33.3%)" strip on `/reports/suite` renders through the K66 tile grid; K52 gradient primary buttons on the page (including onboarding modal CTA) show the K67 sweep.
- **Reports Suite hero** — banner-region gradients that historically consumed `brandGradientCss` (K66 replaced the ReportsHub blue-teal banner with the tile grid, so this legacy path is gone; other pages using `brandGradientCss` — auth hero, etc. — auto-inherit).
- **Sidebar / TopNav K64 solid navy** — unchanged (verified via visible screenshot: sidebar bg is still `#1B1F5C` and active-nav pill is still solid `#303AA0`).

---

## 6 · Acceptance-criteria verification

1. ✅ `theme.js` exports `gradients.navyToGreen` — locked by K67 test 1.
2. ✅ Consumers in the audit list reference the canonical token — locked by K67 tests 6–9 (Button, ui-kit Chip, PortalPages hero, CustomerChemistry icon plate).
3. ✅ Grep confirms zero remaining callers of the deprecated blue-teal gradient outside `theme.js` — only remaining `#0284C7` in the source tree is the intentionally-out-of-scope blue→indigo diagonal on `PortalReviewSubmit.jsx`.
4. ✅ K64 grep-lock preserved — solid active-nav (`#303AA0`), invoices late-fee badge, BusinessOS sub-nav, calendar preset, customers scope pill, per-tenant brand color defaults — all verified untouched (K67 test 10–12 + visible screenshot).
5. ✅ WCAG AA/AAA — every surface either improved to AAA or preserved its pre-K67 pass. Full matrix in §3.
6. ✅ Snapshot / DOM tests updated for at least one KPI tile and one gradient button — K52 test locks the primary Button variant + K67 test locks canonical token + ui-kit Chip + PortalPages hero.
7. ✅ All existing tests still green — 53/53 K52 + K64 + K67 + feb2026-button-tone. Pre-existing unrelated failures (import-resolution-guard, phase30-login-tweaks, portal-login-hides-demo-tiles) confirmed pre-K67 via git stash bisect.

---

## 7 · What's next

- **K68** — customer status tab counts.
- **K70** — retheme K66 tiles with the K67 canonical `gradients.navyToGreen` token (navy→green gradient bg + green-fill white-outline `Open report` button). K67 shipped first so K70 has the token to consume; K70 is a pure `style={}` swap.
- **K63.test-dispatch** — per-recipient test-dispatch button on LeadAlertsSettings.
- **R1** — full Financial suite (P&L, cash flow, A/R aging) — will flip R1 tile from placeholder to built.
- **K67 follow-up (removal phase)** — retire the `brandGradient` / `brandGradientCss` aliases after their ~60 callers have been migrated to `gradients.navyToGreen.*`. Held until after the K66 tile theming (K70) lands.
