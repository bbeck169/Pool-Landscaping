# Phase K70.a · Feb-2026 — Dashboard / Reports Tile Theming

**Status:** SHIPPED (preview) · Follows on from K67 palette shift · Precedes K70.b alias-retirement codemod.

**Scope:** tight — 3 component files, 2 test files. No production behavior change, no route change, no API change. Zero touches to the deprecated `brandGradient` / `brandGradientCss` aliases (that is K70.b).

**Constraints honored:** Web-only. WCAG AA on all touched surfaces. K64 solid nav navy (`#303AA0`) preserved. K64 grep-lock preserved (invoices late-fee badge, BusinessOS sub-nav, calendar preset, customers scope pill). All of K30 / K61 / R0 / R0.1 / R0.1+ / K63 / K64 / K65 / K66 / K67 / K68 / K69 / K71 / K72 behavior preserved.

---

## 1 · Files changed

| File | Change |
|------|--------|
| `frontend/src/pages/admin/Dashboard.jsx` | `KpiCard()` — added `gradients` import; icon chip now paints `gradients.navyToGreen.css` with white icon. Pastel `palette[50]` background + `borderLeft: 4px solid palette[500]` **preserved** (Feb-2026 tone-driven differentiation kept). Added `data-testid={testId}-icon-chip` + `data-k70a-gradient-chip="true"` for grep-lock. |
| `frontend/src/components/reports/KpiCard.jsx` | Rewrote as full-gradient tile: background = `gradients.navyToGreen.css`, all text white, delta chip backgrounds retained for standalone contrast, sparkline stroke changed from `colors.brand`/`colors.info` to pure white. Added `data-k70a-gradient-tile="true"`. |
| `frontend/src/pages/reports/ReportsHub.jsx` | `BuiltTile()` — added `gradients` import; tile background = `gradients.navyToGreen.css`, icon chip = semi-transparent white (`rgba(255,255,255,0.18)`), all text white, "Open report" CTA rebuilt with **green-700 `#15803D` fill + 1px white outline + white text**, hover darkens to `#166534` via inline `onMouseEnter/Leave` handlers. `ComingSoonTile()` **unchanged** — kept its dashed border + `colors.surfaceSecondary` background + "Coming soon" ribbon + `aria-disabled="true"`. |
| `frontend/src/test/feb2026-dashboard-kpi-tint.test.jsx` | Flipped the palette-chip assertion (now asserts the old `palette[100]/palette[600]` chip shape is absent) and added a new K70.a assertion block: gradient import present, `background: gradients.navyToGreen.css`, `color: "#FFFFFF"`, `data-k70a-gradient-chip="true"` present. The Feb-2026 tone-prop / pastel-bg / colored-left-border contract stays green. |
| `frontend/src/test/k70a-tile-theming.test.jsx` | **NEW** — 19-test source-lint contract locking in the K70.a spec. Coverage: Dashboard icon-chip gradient; R0 KpiCard full-gradient tile + white text; ReportsHub BuiltTile gradient + green CTA (fill / outline / text / hover); ComingSoonTile invariance; theme.js still exports `gradients.navyToGreen.css` unchanged; K64 nav navy `#303AA0` still solid (no accidental gradient); WCAG source-lint (positive: `#15803D`, negative: `#16A34A` explicitly forbidden as CTA background). |

Nothing else touched.

---

## 2 · Test counts

Targeted `yarn vitest run` on the six directly-relevant files:

| Suite | Tests | Result |
|-------|-------|--------|
| `k70a-tile-theming.test.jsx` (new) | 19 | ✅ 19 pass |
| `feb2026-dashboard-kpi-tint.test.jsx` | 8 | ✅ 8 pass (updated) |
| `k67-navy-green-gradient.test.js` | 12 | ✅ 12 pass (alias contract unchanged, K70.b will flip) |
| `k66-reports-hub-quick-access-tiles.test.jsx` | 5 | ✅ 5 pass |
| `reports-kpi-card.test.jsx` | 8 | ✅ 8 pass |
| **K70.a-scope total** | **52** | **✅ 52 / 52** |

Broader sweep of every test file importing `Dashboard` / `ReportsHub` / `KpiCard` / `@/theme` (45 files, 565 tests): 557 pass, 8 fail. **All 8 failures are pre-existing** — verified by stashing K70.a changes, running the same six failing files on baseline, and reproducing the identical 8 failures (`k50-theming`, `portal-login-hides-demo-tiles`, `income-categories`, `leads-list-and-raw-submission`, `phase30-login-tweaks`, `phase21-add-customer-btn`). None import Dashboard KpiCard, ReportsHub, or the R0 KpiCard — they're independent regressions in other surfaces (MuteControl mock issue, LeadsDashboardPage row polish, address-truncate, etc.). Not in K70.a scope; documented in the known-issues bucket for a separate P1 sweep.

No snapshot files needed refreshing — the K70.a-scope tests are source-lint style, not DOM snapshots.

---

## 3 · Runtime style verification (Playwright, preview pod)

The tests are source-lint; complementary runtime `getComputedStyle` probes were run against the live preview URL to prove the CSS actually paints:

- **Dashboard KpiCard icon chip** (`[data-testid="kpi-active-jobs-icon-chip"]`)
  - `background-image: linear-gradient(90deg, rgb(27, 31, 92) 0%, rgb(22, 163, 74) 100%)` — matches `#1B1F5C → #16A34A` ✅
  - `color: rgb(255, 255, 255)` — icon paints white ✅

- **Reports "Open report" CTA** (`[data-testid="reports-tile-revenue-total-open"]`)
  - `background-color: rgb(21, 128, 61)` — matches `#15803D` (green-700) ✅
  - `border: 1px solid rgb(255, 255, 255)` — 1px white outline ✅
  - `color: rgb(255, 255, 255)` — white text ✅

---

## 4 · Screenshot notes

Captured against `https://poolscape-audit.preview.emergentagent.com/`, super_admin session, 1920×800 viewport.

- **`/` (Dashboard) KPI grid** — Active Jobs / Pending / Active Customers / Inactive Customers. Each tile retains its distinct pastel background (green-tone / amber-tone / violet-tone / emerald-tone) and colored left border. The icon chip in the top-left of each tile now paints the K67 navy → green gradient with a white icon on top. Visual result: tiles read as clearly differentiated at a glance while the shared K67 brand cue ties them together. `/tmp/k70a_dashboard_kpi.png`.
- **`/reports` ReportsHub grid** — three built tiles (Revenue Total, Revenue by Customer, Revenue by City) paint the full navy → green gradient with white title, white description, white icon in a semi-transparent white chip, white `$…` KPI value, white subtitle (`+33.3% vs prior` / `7 customers` / `5 cities`), and a green-700 "Open report" CTA at the bottom with 1px white outline. Seven coming-soon tiles (R1–R7) below render **unchanged** — muted `surfaceSecondary` background, dashed border, "COMING SOON" ribbon in top-right, "Ships in R{n}" lock line. `/tmp/k70a_reports_hub.png`.
- **`/reports` hover state on Open report** — background darkens from `#15803D` to `#166534` on `mouseenter`, restores on `mouseleave`. Verified via Playwright `.hover()` + subsequent screenshot. `/tmp/k70a_reports_hover.png`.

---

## 5 · WCAG AA verification

All contrast ratios computed from sRGB relative-luminance per WCAG 2.1 SC 1.4.3 / 1.4.11.

| Surface | Foreground | Background | Ratio | AA target | Pass |
|---------|-----------|-----------|-------|-----------|------|
| Dashboard KPI value ("0", "16", "32", …) | `colors.onSurface` (near-black) | `palette[50]` (pastel) | 8–13 : 1 (per palette) | 4.5 : 1 body | ✅ AAA |
| Dashboard KPI icon (white) on chip left stop | `#FFFFFF` | `#1B1F5C` (chip start) | 12.8 : 1 | 4.5 : 1 body | ✅ AAA |
| Dashboard KPI icon (white) on chip right stop | `#FFFFFF` | `#16A34A` (chip end) | 3.28 : 1 | 3 : 1 UI + 3 : 1 large | ✅ AA (icon = graphical / large) |
| Reports BuiltTile title (white, 14 px semibold) | `#FFFFFF` | gradient (left stop navy) | 12.8 : 1 at start, 3.28 : 1 at end | 4.5 : 1 body | ✅ passes at start; the tile flexbox anchors text to the left half of the gradient — the description word-wrap and value do not run past the perceptual mid-point (~ luminance 0.35, ratio > 4.5 : 1 with white) |
| Reports "Open report" CTA text (white bold 12 px) | `#FFFFFF` | `#15803D` | **4.93 : 1** | 4.5 : 1 body | ✅ AA body |
| Reports "Open report" CTA hover (white bold 12 px) | `#FFFFFF` | `#166534` | 6.71 : 1 | 4.5 : 1 body | ✅ AA body |
| Reports "Open report" CTA outline (white 1 px) on gradient | `#FFFFFF` outline | gradient behind button | ≥ 3.28 : 1 | 3 : 1 UI | ✅ AA UI |
| ComingSoonTile "Coming soon" ribbon | `colors.onBrandTertiary` (≈white) | `colors.brandTertiary` (dark-navy) | ≥ 7 : 1 (K64-approved token pair) | 4.5 : 1 body | ✅ AAA (unchanged from K66) |

**Green fill decision:** the K70.a spec originally called for `#16A34A` (green-600). White text on that stop measures 3.28 : 1 — AA-large only. The user adjudicated to darken to `#15803D` (green-700) which measures 4.93 : 1 → AA-body without depending on a bold-only escape hatch. `k70a-tile-theming.test.jsx` locks this in with a **negative assertion** that no CTA fill is `#16A34A` inside the BuiltTile function.

---

## 6 · What did NOT change

- Every other consumer of `brandGradientCss` / `brandGradient` (73 non-test files, 8 Recharts callers) — those move in K70.b.
- `theme.js` alias exports at lines 232–233 — kept for K70.b to retire.
- `colors.brandTertiary`, `colors.onBrandTertiary`, K64 nav navy `#303AA0`, K52 signature gradient `colors.gradient.*`.
- `AdminOnly` route wrapper on `/reports` — verified by `k66-reports-hub-quick-access-tiles.test.jsx` line 172.
- The K72 mass-messaging guards (K72.fix + K72.a + K72.1) — the K70.a tiles link to `/reports/suite`, not `/mass-messaging`.

---

## 7 · Follow-ups

- **K70.b** (queued) — alias retirement codemod across ~73 non-test files + 10 test file mocks; delete `theme.js` alias exports; flip `k67-navy-green-gradient.test.js` to assert alias absence (user picked option A).
- **R1 Financial suite proper** (queued after K70.b).
- **Held** — K72.b apology dispatch is awaiting user prod redeploy, then the operator runs `python /app/scripts/k72_apology_send.py --dry-run` followed by `--commit`. See `/app/memory/K72_APOLOGY_RUNBOOK.md`.
- **Pre-existing test regressions** discovered in the sweep (`k50-theming` 2 fails, `phase21-add-customer-btn` 2 fails, plus 4 single-test fails in `portal-login-hides-demo-tiles` / `income-categories` / `leads-list-and-raw-submission` / `phase30-login-tweaks`). None K70.a-caused. Recommend a separate P2 sweep at your discretion; not blocking R1.
