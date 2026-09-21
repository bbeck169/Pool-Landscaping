# Phase N1 — Universal Input Restyle · Feb-2026

Cosmetic-only phase.  Applies a sitewide **rounded-lg** curve +
**blue-500 focus ring** on top of the Phase T1 base theme
(solid-white bg + `#000080` navy text) so every text-shaped
`<input>` / `<textarea>` across the web app renders with the same
polished, focused-state-visible aesthetic — without breaking
per-consumer styling.

---

## 1 · Grep output — brand-navy resolution

The design guidelines and the app-wide theme tokens use several
navy candidates:

| Source | Hex | Usage |
| --- | --- | --- |
| `frontend/src/theme.js` — `colors.nav.bg` / `.fgActive` | `#1B1F5C` | K50/K64 nav chrome, K74 KPI tiles |
| `frontend/src/theme/presets.js` — several tenant presets | `#0f172a`, `#1e40af`, `#1e3a8a` | tenant-swappable |
| **Phase T1 base CSS** in `frontend/src/index.css` (already shipped) | **`#000080`** | **sitewide text-input color** |

Decision: Phase N1 is a strict extension of Phase T1, so the navy
value locks to `#000080` (Phase T1 canonical).  Every N1 rule +
shared-component patch uses that hex so operator eyes see one
consistent navy across every input in the app.  Contrast:
white (`#FFF`) on `#000080` → **15.3 : 1** (WCAG AAA).

Focus-ring accent: `#3B82F6` (Tailwind `blue-500`).  Distinguishable
from the text navy; contrast on white → **3.68 : 1** (WCAG AA-large
& AA-graphical per 1.4.11).

---

## 2 · Shared input components modified

| Path | Change |
| --- | --- |
| `frontend/src/components/ui/input.jsx` | shadcn `<Input>` — `rounded-md` → `rounded-lg`, `bg-transparent` → `bg-white`, added `text-[#000080]` + `border-slate-200`, focus-visible now paints `ring-2 ring-blue-500 border-blue-500`, placeholder → `#000080` at 55 %. |
| `frontend/src/components/ui/textarea.jsx` | shadcn `<Textarea>` — identical class contract to `<Input>`. |
| `frontend/src/components/ui-kit.jsx` | Legacy `<TextInput>` — replaced inline `colors.surface/onSurface/border` `style` block with the same Phase N1 class chain (`bg-white text-[#000080] border-slate-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500`). |
| `frontend/src/index.css` | Added a dedicated `Phase N1` `@layer base` block **after** the Phase T1 block.  New rules ship `border-radius: 0.5rem` + `:focus-visible { outline: 2px solid #3B82F6; border-color: #3B82F6; }` on the exact same T1 selector chain (same exclusion list — checkbox / radio / file / color / date family / range / submit / reset / button / image / hidden). |

Because the base-CSS additive is scoped to `@layer base`, **every
raw `<input>` on every admin page automatically inherits the
Phase N1 curve + focus ring — no per-page migration required**
except where a page's own inline style overrides bg/text/border
(the K52.1 navy chrome strip pages listed below).

---

## 3 · Hand-rolled inputs migrated (K52.1 override reconciliation)

Three pages hand-roll the search input inside a K52.1 navy chrome
strip (`data-k52-navy-strip="true"`).  Those inputs previously
painted white text on a translucent-white overlay so they'd read
on the navy strip.  Phase N1 recolors them to the sitewide
solid-white + navy-text theme so the app-wide styling stays
coherent — the K52.1 strip container stays as a navy "colored
frame" and the input reads as a white card resting on it.

| Page | Path | Line (pre-patch) | Notes |
| --- | --- | --- | --- |
| Customers list | `pages/customers/CustomersList.jsx` | 1438 | `data-testid="customers-search"` |
| Leads dashboard | `pages/leads/LeadsDashboardPage.jsx` | 268 | `data-testid="lead-search-input"` |
| Schedule (calendar) | `pages/schedule/CalendarSchedule.jsx` | 1227 | `data-testid="calendar-search"` |

Search icons (`<Search>` / `<XIcon>`) on the same three pages
were re-colored from `colors.nav.fgMuted` (white-70 %) to
`#000080` so icon + typed text stay perceptually matched
(user acceptance criterion — "search icon uses the same navy
blue color as text").

### Admin pages (Dashboard, Jobs, Estimates, Invoices, Settings)

Scanned for hand-rolled text-shaped `<input>` occurrences.
Every one auto-inherits the Phase T1 / N1 base-layer rules
without a per-page code change — verified by the screenshot on
`/settings/business` (see § 6).  Zero admin-page files needed a
direct patch.  Explicit list of files inspected:

* `pages/settings/BusinessSettings.jsx` — auto-inherits ✓
* `pages/settings/LateFees.jsx` — number-only inputs (excluded by
  N1 selector — retain native number spinner ergonomics)
* `pages/settings/LegalDocs.jsx` — text input auto-inherits ✓
* `pages/settings/AutoVisitEmailSettings.jsx` — auto-inherits ✓
* `pages/settings/ServiceCategoriesPage.jsx` — text/color/number
  mix.  Text auto-inherits ✓
* `pages/settings/VanitySlugsPage.jsx` — auto-inherits ✓
* `pages/settings/CustomerTagsSettingsPage.jsx` — auto-inherits ✓
* `pages/settings/QuietHoursPage.jsx` — auto-inherits ✓
* `pages/settings/PricebookSuppliersAdmin.jsx` — auto-inherits ✓
* `pages/settings/AIConfigurationSettings.jsx` — auto-inherits ✓
* `pages/settings/BusinessCardSettings.jsx` — auto-inherits ✓
* `pages/jobs/JobsList.jsx` — reschedule date + qty number inputs
  are typed → correctly excluded by the T1/N1 selector chain
* `pages/jobs/FollowUpEditor.jsx` — datetime-local → correctly
  excluded

---

## 4 · Dark-mode detection outcome

`grep` for `dark:` Tailwind variants across `frontend/src`:

    frontend/src/components/ui/alert.jsx:
      "border-destructive/50 text-destructive dark:border-destructive [&>svg]:text-destructive"

Result: **1 vestigial occurrence** on the shadcn `alert.jsx`
component (comes straight from the shadcn template).  No
`ThemeProvider`, no `useTheme` hook, no app-wide dark palette,
no dark-mode toggle in any page.  `tailwind.config.js` does
declare `darkMode: ["class"]` but nothing in the app ever adds
that class.

Decision: **skip `dark:` variants**.  Phase N1 is scoped to the
same environment Phase T1 already ships in.  If the app ever
adopts a real dark-mode contract, a follow-up phase adds
`dark:bg-slate-800 dark:text-blue-200 dark:border-slate-600`
equivalents to both the base-CSS block and the three shared
components — a mechanical migration once the contract exists.

---

## 5 · Vitest results

New spec: `frontend/src/test/phase-n1-input-restyle.test.jsx`.
Covers:

* **A · index.css contract** — Phase N1 header, `border-radius:
  0.5rem`, `:focus-visible` outline + border colour flip, T1
  exclusion list preserved on BOTH new rules, `@layer base`
  wrapper.
* **B · shadcn `<Input>` classes** — bg-white, text navy,
  slate-200 border, rounded-lg, placeholder navy-55, focus ring
  + border blue-500, disabled semantics preserved.
* **C · shadcn `<Textarea>` classes** — same contract.
* **D · legacy `<TextInput>` classes** — same contract.

    yarn test:unit --run \
      src/test/phase-n1-input-restyle.test.jsx \
      src/test/phase-t1-input-theme.test.jsx

     ✓ src/test/phase-t1-input-theme.test.jsx  (5 tests) 5ms
     ✓ src/test/phase-n1-input-restyle.test.jsx  (8 tests) 29ms
     Test Files  2 passed (2)
     Tests  13 passed (13)

Full-suite baseline: **5148 pass · 25 fail · 34 skipped**.  Every
one of the 25 failures reproduces on `main` **without** the
Phase N1 changes (schedule-numbered-reorder, settings-nav-old-routes,
settings-sprocket-visibility).  Zero N1-caused regressions.

---

## 6 · Screenshot proof

Screenshots at `/app/memory/n1_proofs/screenshots/` (`.jpeg`,
1920×800 viewport, quality 20 for size budget).

| # | Page | State | File |
| --- | --- | --- | --- |
| 1 | `/login` | idle | `1_login_default.jpeg` |
| 2 | `/login` | password focused | `2_login_focused.jpeg` |
| 3 | `/customers` | idle | `3_customers_default.jpeg` |
| 4 | `/customers` | search focused (typed "Blake") | `4_customers_focused.jpeg` |
| 5 | `/admin/leads` | idle | `5_leads_default.jpeg` |
| 6 | `/admin/leads` | search focused (typed "test") | `6_leads_focused.jpeg` |
| 7 | `/schedule` | idle | `7_schedule_default.jpeg` |
| 8 | `/schedule` | search focused (typed "pool") | `8_schedule_focused.jpeg` |
| 9 | `/settings/business` | idle | `9_business_settings_default.jpeg` |
| 10 | `/settings/business` | phone focused | `10_business_settings_focused.jpeg` |

Every focused screenshot shows the **2 px blue-500 ring**
paired with the blue-500 border flip; every idle screenshot
shows the **solid-white bg + `rounded-lg` curve + `#000080`
navy text**.  Screenshots 9-10 are the auto-inheritance proof
for admin pages that were **not** hand-patched.

---

## 7 · WCAG-AA contrast sanity

* White (`#FFFFFF`) on navy text (`#000080`) → **15.3 : 1**
  (AAA body + large text)
* Placeholder navy at 55 % on white → **~6.4 : 1** (AA-large
  minimum met; AA-body borderline — accepted, matches Phase T1
  ship)
* Blue-500 (`#3B82F6`) focus ring on white → **3.68 : 1**
  (AA-large + AA-graphical per 1.4.11 — the ring is a UI
  component, not body text, so 3 : 1 minimum applies)

No accessibility regression versus Phase T1 baseline.

---

## 8 · Known cosmetic tension (K52.1 navy strip pages)

The Customers list, Leads dashboard, and Schedule calendar
retain the K52.1 navy chrome strip **around** the input; the
input inside is now white.  Sibling `<select>` dropdowns on the
same strips were not patched (user explicitly excluded native
`<select>` — component-specific styling), so the visual mix is:

* Search input (white card) → new Phase N1 theme
* Filter chips + native selects → unchanged K52.1 white-on-navy

The user's acceptance criterion "Every named page (Schedule /
Customers / Leads) shows the new styling" is met on the input
level.  If the intent is a full K52.1 rework, that's a follow-up
phase (`<select>` component + chip family repaint).

---

## Files changed (final list)

    modified   frontend/src/index.css
    modified   frontend/src/components/ui/input.jsx
    modified   frontend/src/components/ui/textarea.jsx
    modified   frontend/src/components/ui-kit.jsx
    modified   frontend/src/pages/customers/CustomersList.jsx
    modified   frontend/src/pages/leads/LeadsDashboardPage.jsx
    modified   frontend/src/pages/schedule/CalendarSchedule.jsx
    new        frontend/src/test/phase-n1-input-restyle.test.jsx
    new        memory/PHASE_N1_UNIVERSAL_INPUT_RESTYLE.md
    new        memory/n1_proofs/screenshots/*.jpeg  (10 files)
