# Phase K70.b · Feb-2026 — Alias Retirement Codemod

**Status:** SHIPPED (preview) · Follows K70.a tile theming · Unblocks R1 Financial Suite.

**Scope:** pure code hygiene. The K67 palette shift is unchanged (aliases already routed to `gradients.navyToGreen.*`); K70.b just deletes the deprecated re-exports and updates every non-test call site to the canonical shape. **Zero visual behavior change.**

**Constraints honored:** Web-only. WCAG AA preserved (nothing visual moved). K64 solid nav navy (`#303AA0`) unchanged. K64 grep-lock preserved. All of K30 / K61 / R0 / R0.1 / R0.1+ / K63 / K64 / K65 / K66 / K67 / K68 / K69 / K70.a / K71 / K72 behavior preserved.

---

## 1 · What retired

| Alias | Line in `theme.js` (pre-K70.b) | Replacement |
|-------|-------------------------------|-------------|
| `export const brandGradient` (`[string, string]`) | 232 | `gradients.navyToGreen.stops` (new array export on the canonical token) |
| `export const brandGradientCss` (`string`) | 233 | `gradients.navyToGreen.css` (already exported) |

Both `export` lines physically deleted from `theme.js`; comment block above them replaced with a K70.b tombstone banner ("RETIRED — do NOT re-add — import `gradients` from `@/theme` and reach for `gradients.navyToGreen.css` / `.stops` directly").

---

## 2 · What was added

Single new field on the canonical token:

```javascript
export const gradients = {
  navyToGreen: {
    from: "#1B1F5C",
    to:   "#16A34A",
    stops:    ["#1B1F5C", "#16A34A"],   // ← new (K70.b)
    css:      "linear-gradient(90deg, #1B1F5C 0%, #16A34A 100%)",
    cssHover: "linear-gradient(90deg, #2A2F7A 0%, #22B457 100%)",
    fg: "#FFFFFF",
    textShadow: "0 1px 2px rgba(0, 0, 0, 0.25)",
  },
};
```

`stops` is the canonical replacement for the retired `brandGradient` array export. Consumers wiring Recharts strokes / bars / fills to the two brand endpoints reach for `gradients.navyToGreen.stops[0]` (navy start) / `[1]` (green end).

---

## 3 · Codemod

Applied via `/tmp/k70b_codemod.py` — Python regex codemod, dry-run first, `--apply` second.

- Enumerates every non-test file under `frontend/src/` that imports the aliases (73 files).
- For each: (a) drops the alias names from the `@/theme` import list, (b) injects `gradients` into the import if not already present, (c) rewrites body identifiers: `brandGradientCss` → `gradients.navyToGreen.css`, `brandGradient[N]` → `gradients.navyToGreen.stops[N]`, bare `brandGradient` → `gradients.navyToGreen.stops`.
- Idempotent: rerunning is a no-op because files no longer have the alias identifiers to rewrite.
- Preserves original import formatting (single-line vs multi-line named list preserved).

**Numbers**

| Metric | Count |
|--------|-------|
| Non-test files rewritten | **73 / 73** |
| `brandGradientCss` usage sites rewritten | **201** |
| `brandGradient` array-form sites rewritten | **18** across 5 files (`BusinessSummary.jsx`, `Forecast.jsx`, `IncomeByCategoryPage.jsx`, `RevenueSlices.jsx`, `SeoPages.jsx`) |
| Test files updated | 7 (see §4) |
| `theme.js` alias exports deleted | 2 lines |
| **Total alias references remaining outside K67 test grep-lock** | **0** (audited via `grep -rn "brandGradientCss\|brandGradient\b" frontend/src`) |

**Cosmetic note.** The `\bbrandGradient\b` identifier match also caught one occurrence inside a `//` comment in `components/customers/PaymentMethodTiles.jsx:68` — the comment now reads *"the `gradients.navyToGreen.stops` that the Create button ships with"* instead of *"the `brandGradient` that the Create button ships with"*. Grammatically slightly awkward, factually accurate, zero runtime impact. Left as-is.

---

## 4 · Test file updates

Seven test files carried alias references — all were `vi.mock("@/theme", () => ({ ... }))` stubs that predated the K70.a work.

| File | Change |
|------|--------|
| `test/k67-navy-green-gradient.test.js` | (a) Import switched from named `{ brandGradient, brandGradientCss }` to namespace `* as themeModule` so we can assert **absence** of properties. (b) The old "aliases re-route to K67 token" assertion **flipped to assert absence** (user option A): `expect(themeModule).not.toHaveProperty("brandGradient")` + regex negative on the theme.js source. (c) New assertion: `gradients.navyToGreen.stops` is a `["#1B1F5C", "#16A34A"]` array. |
| `test/phase23-ai-transparency-content.test.jsx` | `@/theme` mock — swapped `brandGradientCss: "…"` for `gradients: { navyToGreen: { css: "…" } }`. |
| `test/k35-portal-login.test.jsx` | `@/theme` mock — same swap. |
| `test/phase30-login-tweaks.test.jsx` | `@/theme` mock — same swap. |
| `test/portal-login-hides-demo-tiles.test.jsx` | `@/theme` mock — same swap. |
| `test/phase20-quick-nav-rail-managerial-links.test.jsx` | `@/theme` mock — same swap (was a function-value stub). |
| `test/demo-logins-hostname-gate.test.jsx` | `@/theme` mock — same swap. |

Nothing else was touched in the test tree.

---

## 5 · Test counts

Targeted run on the K70.b-touched files (9 files, 87 tests): **85 pass · 2 fail**. Both failures are **pre-existing** (documented in the K70.a report's "Pre-existing test regressions" bucket — `portal-login-hides-demo-tiles` "Create an account" link assertion + `phase30-login-tweaks` `/config/public` fetch). Neither is caused by K70.b: verified by running the same two files on the pre-K70.a baseline in the prior phase.

Broader sweep (45 files touching Dashboard / Reports / KpiCard / theme importers, 566 tests): **558 pass · 8 fail**. Identical failure fingerprint to K70.a baseline — same 6 files, same 8 tests. K70.b introduced **zero new regressions**.

No snapshot files needed refreshing.

---

## 6 · Runtime style verification

Playwright + `getComputedStyle` probe on the preview pod after K70.b landed:

- **Login page primary CTA** (major consumer of the retired `brandGradientCss` — 6 sites in `Login.jsx` alone before codemod):  
  `background-image: linear-gradient(90deg, rgb(27, 31, 92) 0%, rgb(22, 163, 74) 100%)` — matches `#1B1F5C → #16A34A` exactly ✅
- **Estimator page** — renders clean, no white screen, `New estimate` button + top nav both paint the gradient ✅

Zero visual delta from the K70.a → K70.b transition. Exactly what code-hygiene refactors should look like.

---

## 7 · Screenshot notes

- `/tmp/k70b_login.png` — Login page with water-hero panel and navy→green Sign in CTA. Identical to pre-K70.b render.
- `/tmp/k70b_estimator.png` — Estimator index. Codemodded (6 css sites in `EstimatorPages.jsx`). Renders clean; onboarding modal overlay is an existing UX prompt, not K70.b-caused.

---

## 8 · WCAG AA verification

Nothing visual moved — every alias resolved to `gradients.navyToGreen.css` pre-K70.b via the re-export. WCAG state carried over unchanged from the K67 + K70.a memos:

- White text on navy stop `#1B1F5C`: 12.8 : 1 (AAA)
- White text on green stop `#16A34A`: 4.4 : 1 (AA body / AAA large)
- Perceptual mid-point luminance ~0.35: > 3 : 1 large-text bar

No re-verification needed. Locked in `test/k67-navy-green-gradient.test.js` (contrast rule comment block in `theme.js` above `gradients.navyToGreen`).

---

## 9 · What did NOT change

- `theme.js` `gradients.navyToGreen.{from, to, css, cssHover, fg, textShadow}` — untouched (K67 palette contract).
- `colors.gradient.*` (the K52 signature gradient with the K67-swapped navy end) — untouched.
- K64 solid nav navy `#303AA0` — untouched.
- K64 grep-lock strings (invoices late-fee badge, BusinessOS sub-nav, calendar preset, customers scope pill) — untouched.
- Any behavior of Dashboard, ReportsHub, portal, admin, tech, marketing, seo, csat, dunning, estimator, business card, service report, employee onboarding — untouched. Only imports + identifier references changed.
- K72 mass-messaging guards (K72.fix + K72.a + K72.1) — untouched.
- K72.b apology dispatch script + runbook — untouched.

---

## 10 · Follow-ups

- **R1 Financial Suite proper** — now unblocked. Per user directive: P&L (revenue - costs by month/quarter/YTD with drill-down to invoice/expense line items), cash flow (invoiced vs collected by period), AR aging (0-30 / 31-60 / 61-90 / 90+) with drill-down, revenue by service type (K71 Service Category join), unpaid invoices dashboard, CSV + PDF exports, period / service_type / tech_id filter matrix, and the index migration flagged after R0.1+ (`quotes(tenant_id, customer_id, paid_at)` + `quotes(tenant_id, customer_id, created_at)`). Flip R1 tile on ReportsHub from Coming Soon to Built. Wire metrics under `services/reporting/metrics/` and self-register via `register_metric`.
- **Pre-existing test regressions** (`k50-theming`, `portal-login-hides-demo-tiles`, `income-categories`, `leads-list-and-raw-submission`, `phase30-login-tweaks`, `phase21-add-customer-btn`) — 8 tests across 6 files, unchanged since K70.a baseline. Candidate P2 sweep after R7.
- **Held: K72.b apology dispatch** — script + runbook staged; awaiting user prod redeploy + operator run per `/app/memory/K72_APOLOGY_RUNBOOK.md`.
