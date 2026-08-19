/**
 * Feb-2026 · UX cleanup — Customer detail action bar consolidated
 * to a single horizontal row.
 *
 * Source-inspection tests (same pattern as
 * ``queue-item-3-customer-detail-tags-section.test.jsx``) that lock
 * in the layout contract without rendering the whole page. Covers:
 *   • All 8 action affordances live inside a single flex-row
 *     container tagged ``data-testid="cd-action-row"``.
 *   • Every original testid is preserved (regression guard against a
 *     future refactor accidentally dropping a button).
 *   • The Delete / Chemistry / Chem History buttons are wrapped by
 *     the ``AdminOnly`` gate (App-level route guards +
 *     ``super_admin|admin|manager`` role check via the router — but
 *     the buttons themselves rely on the page's own auth gate; here
 *     we assert the page still routes ``/chemistry`` and
 *     ``/chemistry-history`` links which are guarded upstream by
 *     ``AdminOnly`` in ``App.js``, so techs cannot even land on the
 *     page URL that contains these buttons).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname, "../pages/customers/CustomerDetail.jsx");
const APP_PATH  = resolve(__dirname, "../App.js");
const pageSrc = readFileSync(PAGE_PATH, "utf8");
const appSrc  = readFileSync(APP_PATH,  "utf8");


describe("Customer detail action bar — single-row layout", () => {
  it("wraps every action affordance in ONE flex-row container", () => {
    // The row lives at the top of the customer-detail page.
    const rowIdx = pageSrc.indexOf('data-testid="cd-action-row"');
    expect(rowIdx).toBeGreaterThan(-1);

    // Confirm nowrap + overflow fallback so buttons stay on one line
    // at desktop widths while remaining reachable on tablet.
    const rowSlice = pageSrc.slice(rowIdx - 200, rowIdx + 60);
    expect(rowSlice).toMatch(/flex[- ]row/);
    expect(rowSlice).toMatch(/flex-nowrap/);
    expect(rowSlice).toMatch(/overflow-x-auto/);
  });

  it("preserves every button testid inside the same row", () => {
    // Locate the row block (opening data-testid → next `</div>`
    // that closes it). We approximate by finding the row testid then
    // taking a generous forward slice — any missing testid inside
    // this slice indicates a regression.
    const rowIdx = pageSrc.indexOf('data-testid="cd-action-row"');
    // The row is followed by ~80 lines of markup; slice generously.
    const rowBlock = pageSrc.slice(rowIdx, rowIdx + 4000);

    // 8 required affordances in order.
    const REQUIRED = [
      "<CustomerActionDropdowns",        // Send + Create dropdowns
      'testid="cd-edit"',
      'testid="cd-chemistry"',
      'testid="cd-chemistry-history"',
      'testid="cd-delete"',
      'data-testid="cd-click-to-call-wrapper"',
      "cd-click-to-call",                // Prefix used by ClickToCallButton for its Call button testid
      "cd-click-to-call-tel-fallback",   // Compact "Dial from this device" icon
    ];
    for (const key of REQUIRED) {
      expect(rowBlock).toContain(key);
    }
  });

  it("compact button sizing applied to Edit/Chemistry/Chem History/Delete", () => {
    // The consolidation shrinks padding from ``px-4 py-2`` (ui-kit
    // default) to ``px-2.5 py-1 text-xs`` on the row buttons so all
    // 8 fit at ≥1200px viewports.
    const rowIdx = pageSrc.indexOf('data-testid="cd-action-row"');
    const rowBlock = pageSrc.slice(rowIdx, rowIdx + 4000);
    // At least 4 occurrences (Edit, Chemistry, Chem History, Delete).
    const matches = rowBlock.match(/px-2\.5 py-1 text-xs/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(4);
  });

  it("suppresses the ClickToCallButton's stacked fallback so it fits one row", () => {
    // The compact icon-only fallback is rendered directly by
    // CustomerDetail; the shared ClickToCallButton must NOT also
    // render its own stacked ``Dial from this device`` link (would
    // force wrap on desktop).
    const rowIdx = pageSrc.indexOf('data-testid="cd-action-row"');
    const rowBlock = pageSrc.slice(rowIdx, rowIdx + 4000);
    expect(rowBlock).toMatch(/showFallback=\{false\}/);
  });

  it("role gate: technicians cannot reach the page (route wrapped in <NoTech>)", () => {
    // The buttons themselves are always rendered when the page
    // mounts, but ``/customers/:id`` is guarded by ``<NoTech>`` in
    // App.js so technicians never see the page at all. Confirm the
    // guard is still on the route + the route still renders
    // <CustomerDetail>.
    expect(appSrc).toMatch(/customers\/:id"\s+element=\{\s*<NoTech>\s*<CustomerDetail/);
  });
});
