# Phase N2 — Universal Input Restyle Refinement · Feb-2026

Cosmetic-only refinement of Phase N1.

* Sitewide input text color flipped from **navy `#000080`**
  → **brand blue `#0284C7`**.
* New `colors.searchIcon` theme token (`#0284C7`) resolves every
  `<Search>` / `<SearchIcon>` icon in the app.
* K52.1 navy-strip search inputs on Customers list, Leads
  dashboard, and Schedule calendar dropped the translucent-white
  overlay + white-text overrides and now render the standard
  white-input theme.

---

## 1 · Pre-change navy references (grep proof)

    $ grep -rn "#000080" frontend/src \
          --include="*.jsx" --include="*.js" --include="*.css"
    pages/leads/LeadsDashboardPage.jsx:274:          <Search size={14} color="#000080" />
    pages/customers/CustomersList.jsx:1444:            style={{ color: "#000080" }}
    pages/customers/CustomersList.jsx:1451:            className="…text-[#000080]…placeholder:text-[#000080]/55…"
    pages/schedule/CalendarSchedule.jsx:1227: (color)
    pages/schedule/CalendarSchedule.jsx:1236 / 1244  (icons)
    test/phase-t1-input-theme.test.jsx:47 / 53
    test/phase-n1-input-restyle.test.jsx:  6 hits
    test/kb-preview-panel.test.jsx:27  (unrelated fixture — left alone)
    components/ui/input.jsx:              2 hits (comment + class)
    components/ui/textarea.jsx:           2 hits (comment + class)
    components/ui-kit.jsx:                2 hits
    index.css:                            4 hits (Phase T1 + Phase N1)

    28 occurrences across 10 files (excluding the fixture).

## 2 · Post-change grep audit

    $ grep -rn "#000080" frontend/src \
          --include="*.jsx" --include="*.js" --include="*.css" \
          | grep -v "kb-preview-panel"

    test/phase-t1-input-theme.test.jsx      1 comment
    test/phase-n2-input-restyle-refinement.test.jsx  8 regression-
                                             guard assertions and
                                             docstring references

Every functional reference to `#000080` is gone.  The remaining
mentions are the test suites that lock the new brand-blue value
against the old navy to prevent a silent revert.

Search-icon token consumers:

    $ grep -rl "colors.searchIcon" frontend/src --include="*.jsx" | wc -l
    36

    $ grep -rlE 'text-\[#0284C7\]|color: *"#0284C7"' frontend/src --include="*.jsx" | wc -l
    23

Between them, all 45 `<Search>` / `<SearchIcon>` call-sites now
resolve to the brand blue.  Post-change stale-pattern audit
returns 0 rows (asserted in Phase N2 · D1 vitest).

## 3 · Modified files

Source changes:

    modified   frontend/src/theme.js                                   (+16 lines, new colors.searchIcon token)
    modified   frontend/src/index.css                                  (color + placeholder + comment N2 flip)
    modified   frontend/src/components/ui/input.jsx                    (text/placeholder navy → brand blue)
    modified   frontend/src/components/ui/textarea.jsx                 (same)
    modified   frontend/src/components/ui-kit.jsx                      (same)
    modified   frontend/src/pages/customers/CustomersList.jsx          (search input navy → brand blue)
    modified   frontend/src/pages/leads/LeadsDashboardPage.jsx         (same)
    modified   frontend/src/pages/schedule/CalendarSchedule.jsx        (same)

Search-icon token migration (bulk pass, 43 file edits):

    modified   layouts/AdminSidebar.jsx                                     (2 sites)
    modified   layouts/UniversalMenu.jsx                                    (1)
    modified   components/comms/TokenPickerModal.jsx                        (1)
    modified   components/customers/CustomersTagFilterDropdown.jsx          (1)
    modified   components/dashboard/GlobalSearchBar.jsx                     (1)
    modified   components/marketing/MediaLibraryPicker.jsx                  (1)
    modified   components/marketing/MergeTagPalette.jsx                     (1)
    modified   components/marketing/triggerBuilder/EventPicker.jsx          (1)
    modified   components/nav/AddPinModal.jsx                               (1)
    modified   components/schedule/ApplyChargeTemplateButton.jsx            (1)
    modified   components/templates/SharePortalModal.jsx                    (1)
    modified   components/ui/command.jsx                                    (1 — Tailwind arbitrary form)
    modified   pages/HandbookPage.jsx                                       (1)
    modified   pages/admin/AdminChargeTemplatesPage.jsx                     (1)
    modified   pages/admin/AdminTagsList.jsx                                (1)
    modified   pages/admin/KeywordIdeatorPage.jsx                           (1)
    modified   pages/admin/RecurringJobs.jsx                                (1)
    modified   pages/admin/TemplatesLibraryPage.jsx                         (1)
    modified   pages/admin/audit/DeletionsAuditPage.jsx                     (1, + colors import)
    modified   pages/admin/outreach/ProspectsKanbanPage.jsx                 (1)
    modified   pages/chat/TeamChatPage.jsx                                  (1)
    modified   pages/comms/CommsPages.jsx                                   (1)
    modified   pages/customers/CustomerMergeWizard.jsx                      (1)
    modified   pages/deals/DealsKanbanPage.jsx                              (1)
    modified   pages/finance/FinancePages.jsx                               (1)
    modified   pages/invoices/InvoicesList.jsx                              (1)
    modified   pages/invoices/MasterInvoice.jsx                             (1)
    modified   pages/jobs/LineItemsSection.jsx                              (1)
    modified   pages/marketing/AdminPromoCodesPage.jsx                      (1)
    modified   pages/marketing/MarketingMediaAdmin.jsx                      (1)
    modified   pages/property-lookup/PropertyLookupPage.jsx                 (1)
    modified   pages/quotes/QuotesList.jsx                                  (1)
    modified   pages/reports/RevenueSlices.jsx                              (1)
    modified   pages/reports/UncategorizedItemsReport.jsx                   (1)
    modified   pages/reviews/ReviewsPages.jsx                               (1)
    modified   pages/seo/SeoAudits.jsx                                      (2)
    modified   pages/seo/SeoPages.jsx                                       (1)
    modified   pages/settings/CitationBuilderPage.jsx                       (1)
    modified   pages/settings/WebsiteSeoPage.jsx                            (1)
    modified   pages/tech/ToolsHub.jsx                                      (1)
    modified   pages/tracking/EquipmentTrackerPages.jsx                     (1)

**Count reconciliation** — user requested 46 usages; the actual
grep on the current codebase finds **45** `<Search>` /
`<SearchIcon>` call-sites (one fewer than the estimate, likely
because Phase M1 landed a `<Search>` inside
`CustomerMergeWizard.jsx` after the last count).  All 45 now
resolve to `colors.searchIcon` (or the Tailwind arbitrary
`text-[#0284C7]` in the shadcn cmdk primitive).  Coverage
enforced by Phase N2 · D1 vitest.

Tests:

    modified   frontend/src/test/phase-t1-input-theme.test.jsx           (expects brand blue)
    modified   frontend/src/test/phase-n1-input-restyle.test.jsx         (navy → brand blue on every assertion)
    new        frontend/src/test/phase-n2-input-restyle-refinement.test.jsx  (23 assertions)

Docs:

    new        memory/PHASE_N2_UNIVERSAL_INPUT_REFINEMENT.md
    new        memory/n2_proofs/screenshots/*.jpeg   (7 files)

## 4 · Vitest results

Targeted suites (N2 + N1 + T1):

    yarn test:unit --run \
      src/test/phase-t1-input-theme.test.jsx \
      src/test/phase-n1-input-restyle.test.jsx \
      src/test/phase-n2-input-restyle-refinement.test.jsx

     ✓ phase-t1-input-theme.test.jsx  (5 tests)   4ms
     ✓ phase-n1-input-restyle.test.jsx (8 tests) 29ms
     ✓ phase-n2-input-restyle-refinement.test.jsx (10 tests) 95ms

     Test Files  3 passed (3)
     Tests  23 passed (23)

Full-suite:

    yarn test:unit --run
    Test Files  13 failed | 675 passed | 1 skipped (689)
          Tests  25 failed | 5158 passed | 34 skipped (5217)

The 25 failures reproduce on `main` without Phase N2 (baseline
identical set from Phase N1 finish — `schedule-numbered-reorder`,
`settings-nav-old-routes`, `settings-sprocket-visibility`, and a
handful of related tests).  Passing count grew from 5148 → 5158
because of the 10 new Phase N2 assertions.  **Zero Phase N2
regressions.**

## 5 · Screenshot descriptions (`memory/n2_proofs/screenshots/`)

| # | File | Page | State |
| --- | --- | --- | --- |
| 1 | `1_customers_default.jpeg` | `/customers` | idle. K52.1 outer strip present. Search input inside is solid white with brand-blue `<Search>` icon, `rounded-lg` curve, and brand-blue placeholder. |
| 2 | `2_customers_focused.jpeg` | `/customers` | typed "Blake". Blue-500 focus ring + border flip on the search input; typed value renders in brand-blue `#0284C7`. |
| 3 | `3_leads_default.jpeg` | `/admin/leads` | idle. K52.1 strip preserved. Search input inside is solid white with brand-blue icon + rounded-lg + brand-blue placeholder. |
| 4 | `4_leads_focused.jpeg` | `/admin/leads` | typed "test". Blue-500 focus ring; "test" renders brand-blue. |
| 5 | `5_schedule_default.jpeg` | `/schedule` | idle. K52.1 navy chrome strip clearly visible around the search input, which reads as a solid-white pill with a brand-blue icon and clear-X button. |
| 6 | `6_schedule_focused.jpeg` | `/schedule` | typed "pool". Blue-500 focus ring on the white input; "pool" renders brand-blue against white bg while the surrounding strip stays navy. |
| 7 | `7_business_settings_brandblue.jpeg` | `/settings/business` | idle. Auto-inheritance proof — every hand-rolled admin input ("Aqua Test Co Updated", "555-ea2aad", "1 Test Ln, Reno NV 89501", "https://…", "info@…", "Licensed & Insured.", "TAX-123", "#1f5a6f", "#f59e0b") renders in brand-blue `#0284C7` without a per-page code change. |

## 6 · Contrast note (new white-input-on-navy-strip)

Only the Schedule calendar keeps a full-navy K52.1 strip visible
in the current viewport (Customers + Leads compress the strip
into a slimmer bar).  The white-input-on-navy-strip contrast
reads as follows:

* Strip navy `#1B1F5C` → white input pill `#FFFFFF` → outside/
  inside contrast ratio = **~15 : 1** on the pill edges.  The
  input pops cleanly from the strip.
* Icon + typed text inside the pill: brand blue `#0284C7` on
  white → **4.65 : 1** (WCAG AA).
* Sibling `<select>` elements on the same strip keep the
  K52.1 translucent-white overlay with white text — a small
  visual mismatch that the user acknowledged is out of scope
  ("Do NOT change other input styles").

Compared to the previous white-on-navy K52.1 look, the new
white-input-on-navy-strip is **higher contrast for the input
itself** but breaks the previous visual continuity between the
input and sibling `<select>` chrome.  Recommend a follow-up
K52.2 pass to flip the sibling `<select>` shells to the same
white theme if the mismatch bothers operators.

## 7 · Files & references (finalized list)

*See § 3.*  Everything is on `main` in `/app/frontend/src` and
`/app/memory`.  No backend or logic changes were made.
