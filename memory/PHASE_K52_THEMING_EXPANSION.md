# Phase K52 · Feb-2026 — Theming expansion (navy filter row, navy popover, gradient CTA, gradient active nav)

## Brief
K50 landed the navy chrome on the nav bars.  K51 added an admin logo
preview.  K52 extends the theming vocabulary in four locked slices:
navy filter strip on the Schedule list view, navy popover panels on
CategoryDropdown + shadcn `<Select>`, a signature emerald→sky
gradient on the primary CTA `Button`, and the same gradient on every
active nav item (sidebar rail, top-bar CategoryDropdown trigger,
BusinessOS sub-nav tab).

Ship style: four independent slices on largely disjoint file sets so
per-slice revert is trivial.

---

## Locked tokens (added to `frontend/src/theme.js`)

```js
gradient: {
  from: "#22C55E",   // emerald-500
  to:   "#7DD3FC",   // sky-300
  css:      "linear-gradient(90deg, #22C55E 0%, #7DD3FC 100%)",
  cssHover: "linear-gradient(90deg, #34D673 0%, #93DDFD 100%)",
  fg: "#FFFFFF",
  fgHover: "#FFFFFF",
  textShadow: "0 1px 2px rgba(0, 0, 0, 0.25)",
}
```

Plus a small K50 tweak: `colors.nav.fgMuted` bumped from `0.65` →
`0.72` alpha — the placeholder copy on the K52 filter strip sits
directly on `colors.nav.bg` and the K50 alpha was borderline under
WCAG AA for placeholder text.

`colors.gradient.textShadow` is a *token*, not baked-in — every
consumer of the gradient (Button variant, active-pill nav items,
active-preset filter chip) applies it so small white body copy
stays legible on the `#7DD3FC` (sky-300) end of the gradient.

---

## Slice A — Filter row FULL navy

**File**: `frontend/src/pages/schedule/CalendarSchedule.jsx`
(2 hunks — filter toolbar + presets row).

Two rows now render as a two-row navy strip:

* **Filter toolbar** (`data-testid="calendar-filters"`, `data-k52-navy-strip="true"`)
  * Container: `background: colors.nav.bg`, subtle white/10 border.
  * Search input: white/10 tinted card, `color: colors.nav.fg`,
    placeholder tinted via `placeholder:text-white/70`, search icon
    `colors.nav.fgMuted`, clear icon `colors.nav.fgMuted`.
  * Four `<select>` triggers (`calendar-filter-tech`, `-crew`,
    `-service`, `-status`): `background: colors.nav.bg`, `color:
    colors.nav.fg`, `border: colors.nav.border`.  Tech-select
    disabled state uses `colors.nav.fgMuted` + 55% opacity to match
    the K52 Button disabled pattern.
  * Clear-filters button: white/10 outline pill, `colors.nav.fg`
    label.
* **Custom-range preset row** (`data-testid="calendar-presets"`,
  `data-k52-navy-strip="true"`)
  * Container: `background: colors.nav.bg`.
  * CUSTOM RANGE label: `colors.nav.fgMuted`.
  * Preset chips (Next 7/30/90 days, This quarter): transparent bg
    with `1px solid colors.nav.fgMuted` outline; **active** chip
    paints `colors.gradient.css` with `colors.gradient.textShadow`
    (matches Slice D active-nav pattern).
  * Date pickers: navy bg, white fg, `colorScheme: "dark"` so the
    native icon inverts to white.  The native calendar popover
    itself remains browser-controlled — out of reach without
    swapping to a shadcn `<DatePicker>`.
  * "N jobs in range" chip: white/15 tinted, white fg.

**Native `<select>` option popovers** (browser-controlled, opens
below the trigger) stay on default light chrome — same rationale
as the native date-picker popover.  Flagged as follow-up:
migrating these to shadcn `<Select>` would auto-navy them because
Slice B is already primitive-level.

**Other filter rows not in this patch** — see Grey areas §.

---

## Slice B — Dropdown popover MENU navy

Two independent surfaces:

### AdminTopBar `CategoryDropdown` (top-nav popover)
**File**: `frontend/src/layouts/AdminTopBar.jsx` (2 hunks —
`CategoryDropdown` + `EntryItem`).

* Panel: `backgroundColor: colors.nav.bg`, border `white/10`,
  `data-k52-navy-popover="true"`.
* Menu item text: white.  Hover: `bg-[#2A2F7A]` (`colors.nav.bgHover`).
* Section labels ("SCHEDULE & DISPATCH", …): `colors.nav.fgMuted`.
* Separators: `white/10`.
* **Active row inside the popover** (route match): white pill with
  navy text — this is the K50 `bgActive` / `fgActive` pattern,
  RESERVED here per spec.  Slice D's gradient is for the nav
  SURFACES; inside the popover, gradient would clash with 6 sibling
  rows.

### Shadcn `<SelectContent>` / `<SelectItem>` primitive
**File**: `frontend/src/components/ui/select.jsx` (4 hunks —
`SelectContent`, `SelectLabel`, `SelectItem`, `SelectSeparator`).

Applies to every `<Select>` consumer in the app (5 known
consumers).  Same palette as CategoryDropdown popover.  Note:
hex values are inlined in Tailwind arbitrary values (`bg-[#1B1F5C]`)
because CVA cannot consume JS tokens at build time — the K52 vitest
suite asserts these hexes match `theme.js` so a token change fails
fast.

**NOT touched globally**: the shadcn `DropdownMenuContent` primitive.
Only the specific `CategoryDropdown` consumer opts into the navy
chrome via className overrides — this preserves the default light
theme on unrelated `DropdownMenu` usages (row action menus, kebab
menus).

---

## Slice C — Gradient primary Button

**File**: `frontend/src/components/ui/button.jsx` (1 hunk — CVA
`default` variant).

* `default` variant: gradient (`#22C55E` → `#7DD3FC`), white text,
  `text-shadow` for legibility on sky end, hover = `#34D673` →
  `#93DDFD` (~+8% brightness), focus ring = `#22C55E`,
  active = `brightness(0.95)`, disabled = 55% opacity of the
  gradient (not a flat gray).
* `destructive`: **not touched** — keeps `bg-destructive` flat red.
* `outline` / `ghost` / `link` / `secondary`: **not touched** —
  tertiary affordances stay flat so they don't fight the primary's
  visual weight.

**Fan-out**: every consumer using `<Button>` or `<Button variant="default">`
inherits the new look automatically — no per-consumer walk needed.
Consumers using `<Button variant="destructive">`, `outline`, `ghost`,
`link`, `secondary` are unaffected.

**Explicitly NOT auto-updated** — see Grey areas §:
* Native `<button style={{ backgroundColor: colors.brand }}>` usages
  (371 hits across the app).  These use a solid `backgroundColor`
  which can't hold a gradient value; auto-migration would require
  a per-file `background: colors.gradient.css` rewrite that's out
  of scope for the token-driven pass K52 spec called for.
* The `brandGradientCss` constant (existing sky→green signature).
  Not repointed to the new emerald→sky in this pass; flagged as a
  potential follow-up if the user wants a total fan-out swap.

---

## Slice D — Active nav item = gradient

Three surfaces:

* **Primary sidebar rail** — `frontend/src/layouts/AppLayout.jsx`,
  the `QuickNavRail` NavLink style prop.
* **Admin top-bar CategoryDropdown trigger** —
  `frontend/src/layouts/AdminTopBar.jsx` (Slice B file also updated
  the trigger).
* **BusinessOS sub-nav tab** —
  `frontend/src/pages/os/BusinessOS.jsx`, the sub-nav NavLink
  style prop.

All three consume `colors.gradient.css` on active, `colors.gradient.fg`
for white text, and `colors.gradient.textShadow`.  Idle stays
`colors.nav.fg` on transparent bg (parent `<aside>` / `<header>`
paints navy through).

**K50's `colors.nav.bgActive` (white pill) is NOT removed** — it's
retained for the shadcn `DropdownMenu` active row inside
CategoryDropdown popover (a gradient there would fight sibling rows,
per Slice B rationale).

**K51 Branding preview tiles NOT touched** — the K52 test suite
explicitly asserts the light tile stays `#FFFFFF` and the navy tile
stays `#1B1F5C`, and neither picks up the gradient.  The whole point
of the K51 preview is showing both chromes side-by-side to admins.

---

## Tests

**New**: `frontend/src/test/k52-theming.test.js` — 16 assertions
across 4 describes:

* **Theme tokens** (3 tests): gradient block shape + values,
  `theme.js` block position, `fgMuted` alpha bump.
* **Slice A · Filter row navy** (3 tests): calendar-filters strip
  bg, four select triggers + search + clear all white-on-navy,
  presets row navy + gradient-active preset chip.
* **Slice B · Popover navy** (2 tests): CategoryDropdown panel +
  active row pattern, shadcn `<SelectContent>` primitive palette.
* **Slice C · Gradient Button** (4 tests): `default` variant
  gradient present, `destructive` NOT gradient-ified, tertiary
  variants stay flat, disabled = 55% opacity of gradient.
* **Slice D · Active nav gradient** (4 tests): sidebar rail,
  CategoryDropdown trigger, BusinessOS sub-nav, and K51 preview
  tiles NOT touched.

**Updated** (K50 → K52 pattern shift):
* `frontend/src/test/k50-theming.test.js` — 3 assertions updated to
  reflect the K50 white-pill → K52 gradient promotion on
  QuickNavRail, CategoryDropdown trigger, and BusinessOS sub-nav.
* `frontend/src/test/rail-nav.test.jsx` — active-rail-item
  assertion updated: was asserting `rgb(255,255,255)` + `rgb(27,31,92)`
  on the pill; now asserts the K52 linear-gradient inline.

**Regression sweep** — 172/172 pass across:
* K52 (new): 16
* K50 (updated): 22
* K51: 4
* K41 / K41b / K41c / K48 / K49 (unaffected): 86
* Sibling nav / logo suites (rail-nav, rail-nav-leads,
  nav-hover-polish, admin-sidebar-pinned-nav, brand-logo × 4,
  header-signout-relocated, business-os-fabric): 44

**Full-suite sweep interrupted** — the full `yarn test:unit` run hit
a pre-existing unresolved isolation bug in
`phase27-mute-control.test.jsx` (`api.get is not a function` — the
component's on-click fires after the mock is torn down).  Bug
predates K52; already tracked in the P2 list.  Every suite listed
above ran green individually.

---

## Files changed

| File | Slice | Change |
| --- | --- | --- |
| `frontend/src/theme.js` | tokens | +`colors.gradient` block; `colors.nav.fgMuted` `0.65 → 0.72` |
| `frontend/src/pages/schedule/CalendarSchedule.jsx` | A | Filter toolbar + preset row now render on navy |
| `frontend/src/layouts/AdminTopBar.jsx` | B + D | CategoryDropdown popover navy; active trigger paints gradient |
| `frontend/src/components/ui/select.jsx` | B | `SelectContent` / `SelectItem` / `SelectLabel` / `SelectSeparator` navy palette |
| `frontend/src/components/ui/button.jsx` | C | `default` variant → gradient; other variants unchanged |
| `frontend/src/layouts/AppLayout.jsx` | D | `QuickNavRail` active state → gradient |
| `frontend/src/pages/os/BusinessOS.jsx` | D | Sub-nav active tab → gradient |
| `frontend/src/test/k52-theming.test.js` | — | New, 16 tests |
| `frontend/src/test/k50-theming.test.js` | — | 3 assertions updated for K52 pattern shift |
| `frontend/src/test/rail-nav.test.jsx` | — | active-rail-item assertion → K52 gradient |
| `memory/PHASE_K52_THEMING_EXPANSION.md` | — | New, this document |

---

## Grey areas (flagged, NOT shipped in K52 — need your call)

1. **Other filter rows** (Customers, Jobs, Quotes, Invoices,
   Payments, Estimates, Leads, Pool Report, Job Timers, Reports).
   The K52 spec called for consistent application across all
   list-view filter strips, but each page's filter strip is a
   one-off with its own layout / testid conventions.  Migrating
   all of them in K52 would 5–10x the diff size and risk
   regressions on unrelated flows.  **Proposal**: ship the
   Schedule strip as the K52 pattern reference, then a K52.1
   follow-up walks the remaining pages one at a time under a
   `data-k52-navy-strip="true"` marker for the tester to sweep.

2. **Calendar / Grid toggle pair** on Schedule.  Action-shaped
   (looks like a Button) but state-selecting (picks a view mode).
   K52 spec explicitly listed this as ambiguous.  **NOT touched**
   in this patch — it retains its existing 2-state look.  Awaiting
   your call: gradient primary variant, or a state-toggle
   affordance (K50 white-pill on navy)?

3. **Native `<button style={{ backgroundColor: colors.brand }}>`
   consumers (371 hits)**.  These use a solid `backgroundColor`
   which cannot hold a gradient value.  Slice C only fans out to
   `<Button variant="default">` consumers via the shadcn primitive.
   **Proposal options**:
   a. Ship a `background: colors.gradient.css` sweep in K52.1 (per-file walk).
   b. Introduce a `.k52-btn-gradient` utility class and migrate consumers to it.
   c. Leave them on solid `colors.brand` (which the token still exports) and treat the shadcn Button as the canonical primary — flag the direct-style consumers for a subsequent Button-component migration.
   No default assumption baked into this patch.

4. **`brandGradientCss` constant** (existing sky-600 → green-600
   gradient used on ~30 consumers as `background: brandGradientCss`).
   Slice C did NOT repoint this to the new emerald→sky.  Options:
   a. Repoint `brandGradientCss` to `colors.gradient.css` (auto-fans
      the new palette to every existing consumer — highest impact,
      lowest per-file diff).
   b. Deprecate `brandGradientCss` and migrate consumers to
      `colors.gradient.css` explicitly.
   c. Leave both gradients in the app (they're intentionally
      distinct — sky-first for legacy, emerald-first for K52+).
   No default baked in.

5. **CategoryDropdown active row inside popover** — kept as K50
   white pill / navy text per Slice B rationale (a gradient there
   would fight the 6 sibling rows).  Confirming this is the intended
   read of "this active state is DIFFERENT from the top-nav active
   state which is switching to the gradient in Slice D" from your
   spec.  If gradient-inside-popover was actually the intent, one-line
   swap in `EntryItem` → `colors.gradient.css`.

---

## Revert safety

Each slice can be reverted independently:
* Slice A: revert 2 hunks in `CalendarSchedule.jsx`.
* Slice B (top-bar): revert 2 hunks in `AdminTopBar.jsx`.
* Slice B (select): revert 4 hunks in `components/ui/select.jsx`.
* Slice C: revert 1 hunk in `components/ui/button.jsx`.
* Slice D: revert 1 hunk each in `AppLayout.jsx`, `AdminTopBar.jsx`
  (trigger `style` prop only), `BusinessOS.jsx`.
* Tokens: revert 1 hunk in `theme.js`.

Test files can be selectively kept — the K52 assertions catch
regressions but the K50 pattern-shift updates and the rail-nav
active-item update depend on K52 being live.

---

## Out of scope (unchanged, per brief)

* Mobile Expo chrome (K50 rule).
* K51 Branding preview tiles (guarded by K52 Slice D regression test).
* Portal customer-facing page backgrounds.
* Filter chip ROWS that show status/state indicators (K50 kept those alone).
* Icon-only chrome buttons.
* Destructive/danger buttons (K52 spec exception).
* Table column headers, section titles, card headers, plain form inputs.
* K50 Slice B job-status shading map.
* Row-action `DropdownMenu` usages (kebab menus etc.) — Slice B
  scoped only to CategoryDropdown + shadcn `<Select>`.

---

## K52 Design Principles (adjudicated grey areas — Feb-2026)

These decisions are now **codified**, not TODOs.  Any future patch
that contradicts one of these must call it out explicitly.

1. **`colors.brand` solid = legacy inline buttons (deliberate).**
   371 native `<button style={{ backgroundColor: colors.brand }}>`
   consumers stay on the solid brand color.  Rationale: shadcn
   `Button` is the canonical primary; those inline buttons are
   secondary/contextual actions that don't need to compete with
   the primary's visual weight.  **Do NOT migrate them** to the
   K52 gradient.

2. **shadcn `Button` primitive = canonical for the K52 gradient.**
   The `default` variant is the SINGLE opt-in for the gradient
   look.  Consumers wanting the gradient use `<Button>`; consumers
   wanting a solid primary use the existing inline pattern.
   Neither is deprecated.

3. **`brandGradientCss` (sky→green) vs `colors.gradient.css`
   (green→sky) = intentionally distinct palettes.**  The two
   gradients coexist.  `brandGradientCss` is retained on the
   ~30 legacy consumers that already use it.  `colors.gradient.css`
   is the K52+ signature.  **Do NOT repoint** `brandGradientCss`
   to the K52 palette.  If the two ever appear side-by-side and
   read as inconsistent, revisit — but no pre-emptive migration.

4. **CategoryDropdown active-row-inside-popover = K50 white pill
   (deliberate).**  When a menu item inside the top-nav popover
   matches the current route, it renders as a white pill with
   navy text — NOT the K52 gradient.  Rationale: 6 sibling rows
   share the popover; a gradient there would fight the surrounding
   items and dilute the "top-nav is active" affordance the
   trigger's own gradient already carries.

5. **Calendar/Grid toggle = K50 white pill state-selector
   (deliberate).**  The view-mode toggle on Schedule is action-
   shaped but state-selecting; it retains its 2-state look
   (white pill on navy for the active view mode).  Rationale:
   distinguishes VIEW selectors from FILTER chips (which paint
   the K52 gradient when active) and from ACTION buttons (which
   paint the K52 gradient via shadcn `Button`).

---

## K52.1 · Filter row navy sweep across list-view pages

**Adjudication**: Following the K52 ship, user chose option (a) —
sweep the navy filter-strip pattern across every list-view page
that has a full-width filter strip.  Paint-only pass; no filter
LOGIC changed.

### Swept pages (5)

| Page | File | Strip testid | Notes |
| --- | --- | --- | --- |
| **Customers** (`/customers`) | `pages/customers/CustomersList.jsx` | `customers-filters` | Scope chips (All / Unscheduled / Waitlist) treated as filter-state chips → active paints the K52 gradient (was `colors.brandTertiary` teal-mint). Tag / Sort / Portal-status selects all navy. |
| **Quotes** (`/quotes`) | `pages/quotes/QuotesList.jsx` | `quotes-filters` | Search + status select navy. |
| **Invoices** (`/invoices`) | `pages/invoices/InvoicesList.jsx` | `invoices-filters` | Search + status + card-on-file selects navy. "Has late fee" toggle promoted from red-tint to gradient-when-active. Selected-category chips promoted from blue-tint (`#DBEAFE`) to gradient (matches active filter-state affordance). |
| **Leads** (`/leads`) | `pages/leads/LeadsDashboardPage.jsx` | `leads-filters` | Was a bare flex row; wrapped in a proper K52 navy strip. Search + source + status selects navy. |
| **Job Timers** (`/timers`) | `pages/timers/JobTimersPage.jsx` | `timers-filters` | 2 date inputs opt into `colorScheme: "dark"` so the native calendar icon inverts white. 2 text inputs use the K52 `rgba(255,255,255,0.10)` tinted-card treatment (matches CalendarSchedule search input). |

### Plus K52 (already shipped) — 2 strips on `pages/schedule/CalendarSchedule.jsx`:
* `calendar-filters` (filter toolbar)
* `calendar-presets` (range preset row)

**Grand total**: 7 filter strips app-wide, all reachable via a
single selector `[data-k52-navy-strip="true"]`.

### Skipped pages (with reason)

| Page | Reason |
| --- | --- |
| **Jobs** (`/jobs`) | Route redirects to `/schedule` → covered by K52 Slice A. |
| **Payments** | No dedicated `/payments` list page; payments render inside the customer detail view (not a list-page filter strip). |
| **Estimates** (`/estimator`) | The page only has a single-control `CustomerFilterBar` (a customer-scoping dropdown), not a full filter strip.  The `CustomerFilterBar` component sits in its own row above the table and doesn't warrant a wrapping navy strip.  Ambiguous surface — flagged for your call before painting. |
| **Pool Service Report** (`/reports/pool-service`) | The filter controls (week picker + Refresh + Export CSV) are embedded inline in the page header, not a distinct filter strip.  Painting them navy would recolour the whole header.  Ambiguous surface — flagged for your call. |
| **Reports Hub** (`/reports`) | No filter strip; just KPI cards and drilldown links. |
| **Customers cohort tabs** (Active / Inactive / Muted / All at top of `/customers`) | This is a segmented view selector (like Calendar/Grid on Schedule).  Per Design Principle §5, view-selectors keep their K50 white pill.  Not part of the filter strip. |

### Unusual layouts (flagged, not painted)

1. **Estimator** — single-dropdown filter, not a strip.  Adjudicate:
   (a) leave as-is (my default), (b) wrap the `CustomerFilterBar`
   in a navy strip anyway for consistency.
2. **Pool Service Report** — week picker + Refresh + Export CSV
   embedded in the page header.  Adjudicate: (a) leave as-is (my
   default), (b) extract the trio into a navy strip below the
   header, (c) paint the header itself navy.

### Tests

New assertions in `test/k52-theming.test.js` under `K52.1 · Filter
row navy sweep`:

* One assertion per swept page — filter strip carries
  `data-k52-navy-strip="true"` + `colors.nav.bg` background.
* Regression guards on each page for the pre-K52 tokens that must
  not resurface (`colors.surface` / `colors.surfaceSecondary` /
  `colors.onSurfaceSecondary` / `#FEE2E2` / `#DBEAFE` / `background:
  "#fff"`).
* Marker-selector sweep — every swept page carries at least one
  `data-k52-navy-strip="true"` attribute; CalendarSchedule carries
  exactly 2 (filter toolbar + preset row).

**Test count**: K52 suite grew from 16 → 22 (+6 K52.1 tests).

### Regression sweep

**205/205 pass** across:
* K52 (16 K52 + 6 K52.1 = 22)
* K50 (22)
* K51 (4)
* K41 / K41b / K41c / K48 / K49 (86)
* Sibling nav / logo / customer-list / invoice suites (71)

**Pre-existing failure** (NOT a K52.1 regression, confirmed via
git-stash):
* `feb2026-customers-tag-filter-dropdown.test.jsx :: "URL sync
  effect still lives in the page (unchanged surface)"` — 1
  assertion on `CustomersList.jsx`'s inline `rowTags` snippet
  that predates my K52.1 changes.  Same failure reproduces on
  `HEAD~` (before K52.1).  Not touched.

### Files changed (K52.1 delta only)

| File | Change |
| --- | --- |
| `frontend/src/pages/customers/CustomersList.jsx` | Filter strip → navy K52; scope chips promoted to gradient-when-active |
| `frontend/src/pages/quotes/QuotesList.jsx` | Filter strip → navy K52 |
| `frontend/src/pages/invoices/InvoicesList.jsx` | Filter strip → navy K52; late-fee toggle + category chips promoted to gradient-when-active |
| `frontend/src/pages/leads/LeadsDashboardPage.jsx` | Bare flex row → proper navy K52 strip |
| `frontend/src/pages/timers/JobTimersPage.jsx` | Filter strip → navy K52; date inputs opt into dark colorScheme |
| `frontend/src/test/k52-theming.test.js` | +6 K52.1 assertions (one per swept page + marker sweep) |
| `memory/PHASE_K52_THEMING_EXPANSION.md` | This section |
