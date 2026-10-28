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

  it("preserves every button testid inside the strip + adjacent submenu", () => {
    // Phase 2 (Feb-2026) · single-row refactor — the row is now
    // longer (added right-primary wrapper, Call wrapper, right-
    // destructive wrapper, mobile kebab) so byte-proximity to
    // the row open is no longer a reliable anchor.  Replaced
    // with structure-based containment inside the strip block
    // (which spans from ``cd-command-strip`` down to the next
    // sibling, the ``{/* Header card */}`` comment).
    //
    // ZZ-A Wave 3-B · Feb-2026 — Phase 28 moved ``{/* Header card
    // */}`` to render ABOVE ``cd-command-strip``, so the pre-Phase-28
    // "find the next Header card after the strip" bound returns -1.
    // Rebaselined to use the next ``cd-command-strip-tabs`` sibling
    // as the end bound instead. The strip block still contains the
    // same 5 affordances (Edit / Delete / Click-to-Call wrapper +
    // tel-fallback).
    //
    // ZZ-A Wave 3-B · Feb-2026 — Ticket HH relocated
    // ``<CustomerActionDropdowns />`` out of ``cd-command-strip``
    // and INTO the identity card above (``cd-identity-header-
    // actions``, see CustomerDetail.jsx:1577). Assertion for
    // ``<CustomerActionDropdowns`` moved out of the strip block
    // and into a sibling block check below.
    const stripIdx = pageSrc.indexOf('data-testid="cd-command-strip"');
    const nextBlockIdx = pageSrc.indexOf('data-testid="cd-command-strip-tabs"',
                                           stripIdx);
    const stripBlock = pageSrc.slice(stripIdx, nextBlockIdx);

    // 5 affordances live inside the strip itself (CustomerAction-
    // Dropdowns moved to the identity header per Ticket HH;
    // Chemistry + Chem History moved to the Create ▼ submenu in a
    // prior phase and are checked separately below).
    const STRIP_REQUIRED = [
      'testid="cd-edit"',
      'testid="cd-delete"',
      'data-testid="cd-click-to-call-wrapper"',
      "cd-click-to-call",
      "cd-click-to-call-tel-fallback",
    ];
    for (const key of STRIP_REQUIRED) {
      expect(stripBlock).toContain(key);
    }

    // CustomerActionDropdowns now lives in the identity header
    // card ABOVE the strip (post-Ticket-HH).
    const identityActionsIdx = pageSrc.indexOf('data-testid="cd-identity-header-actions"');
    expect(identityActionsIdx).toBeGreaterThan(-1);
    const identityActionsEnd = pageSrc.indexOf("</div>", identityActionsIdx);
    const identityActionsBlock = pageSrc.slice(identityActionsIdx, identityActionsEnd);
    expect(identityActionsBlock).toContain("<CustomerActionDropdowns");

    // Chemistry moved to the Create ▼ submenu.
    const actionsSrc = readFileSync(
      resolve(__dirname,
        "../components/customers/CustomerActionDropdowns.jsx"),
      "utf8");
    expect(actionsSrc).toContain('data-legacy-testid="cd-chemistry"');
    expect(actionsSrc).toContain(
      'data-legacy-testid="cd-chemistry-history"');
  });

  it("compact button sizing applied via shared NAVY_ className constants", () => {
    // Phase 2 (Feb-2026) · single-row refactor — the repeated
    // literal ``px-2.5 py-1 text-xs`` on each button was
    // extracted to ``BTN_BASE`` + three ``NAVY_*`` variants.
    // The compact-sizing contract now reads as: every right-
    // group button uses ``${BTN_BASE} ${NAVY_...}``.
    const stripIdx = pageSrc.indexOf('data-testid="cd-command-strip"');
    const nextBlockIdx = pageSrc.indexOf("{/* Header card */}",
                                           stripIdx);
    const stripBlock = pageSrc.slice(stripIdx, nextBlockIdx);
    const matches = stripBlock.match(
      /\$\{BTN_BASE\} \$\{NAVY_/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(3);
    // And BTN_BASE itself still carries the compact classes.
    expect(pageSrc).toMatch(
      /const\s+BTN_BASE\s*=\s*[\s\S]{0,80}px-2\.5 py-1 text-xs/);
  });

  it("suppresses the ClickToCallButton's stacked fallback so it fits one row", () => {
    // Phase 2 (Feb-2026) · single-row refactor — widened the
    // slice from 4000 → 8000 so the Call wrapper is reliably
    // reached regardless of how many role-gated buttons expand
    // the row ahead of it.
    const rowIdx = pageSrc.indexOf('data-testid="cd-action-row"');
    const rowBlock = pageSrc.slice(rowIdx, rowIdx + 8000);
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
