/**
 * Feb-2026 · Bulk Portal Invite from customers top-menu.
 *
 * Source-body contract check (mirrors the H1 pattern at
 * ``customers-bulk-portal-invite.test.jsx``). Locks the four
 * critical invariants of the top-menu button ship:
 *
 *   1. Top-menu button exists with the spec test-id
 *      ``customers-toolbar-portal-invite-btn`` — sits in the
 *      PageHeader ``right`` prop, not inside the selection-only
 *      bulk-actions bar.
 *   2. Admin-only gate (admin + super_admin only via ``isAdmin``).
 *      Manager / technician / customer roles do NOT see it.
 *   3. Disabled when ``selected.size === 0`` with the exact
 *      tooltip copy the spec requires; enabled otherwise.
 *      Click routes to ``setH1ConfirmOpen(true)`` — reuses the
 *      pre-existing H1 modal without extracting a shell.
 *   4. Portal Onboarding Health tile refetches on modal close —
 *      the tile receives ``externalRefetchToken={h1Result}`` so
 *      changing ``h1Result`` bumps its useEffect.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


const CUSTOMERS_SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomersList.jsx"),
  "utf-8",
);
const TILE_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/components/customers/PortalOnboardingHealthTile.jsx"),
  "utf-8",
);


describe("CustomersList · Feb-2026 top-menu Portal Invite button", () => {
  it("emits the spec test-id ``customers-toolbar-portal-invite-btn`` on the top toolbar", () => {
    expect(CUSTOMERS_SRC).toMatch(
      /testid="customers-toolbar-portal-invite-btn"/,
    );
  });

  it("is admin-gated (isAdmin ? ... : null) — tighter than the read gate on the list", () => {
    // The block that renders the top-menu button MUST be inside an
    // ``isAdmin ? (...) : null`` conditional so manager / tech /
    // customer roles never see it. Grab the preamble immediately
    // before the button test-id and assert the isAdmin gate is
    // present within 500 characters.
    const idx = CUSTOMERS_SRC.indexOf(
      'testid="customers-toolbar-portal-invite-btn"',
    );
    expect(idx).toBeGreaterThan(0);
    const preamble = CUSTOMERS_SRC.slice(Math.max(0, idx - 500), idx);
    expect(preamble).toMatch(/isAdmin\s*\?\s*\(/);
  });

  it("click routes to the pre-existing H1 modal (no shell extraction / no parallel bulk endpoint)", () => {
    // The onClick handler on the top-menu button MUST call
    // setH1ConfirmOpen(true) — proves it reuses the mature H1
    // modal rather than mounting a new confirm shell.
    const idx = CUSTOMERS_SRC.indexOf(
      'testid="customers-toolbar-portal-invite-btn"',
    );
    expect(idx).toBeGreaterThan(0);
    // Grab a 400-char window around the button so we can match the
    // onClick prop on the same JSX element.
    const window_ = CUSTOMERS_SRC.slice(Math.max(0, idx - 400),
                                              idx + 400);
    expect(window_).toMatch(/onClick=\{\(\)\s*=>\s*setH1ConfirmOpen\(true\)\}/);
  });

  it("is disabled when selected.size === 0 and shows the spec tooltip; enabled otherwise", () => {
    const idx = CUSTOMERS_SRC.indexOf(
      'testid="customers-toolbar-portal-invite-btn"',
    );
    const window_ = CUSTOMERS_SRC.slice(Math.max(0, idx - 400),
                                              idx + 800);
    // The ``disabled`` prop must be bound to ``selected.size === 0``.
    expect(window_).toMatch(/disabled=\{selected\.size\s*===\s*0\}/);
    // Spec tooltip verbatim.
    expect(window_).toMatch(/Select one or more customers to invite/);
    // Enabled-state tooltip surfaces the selection count.
    expect(window_).toMatch(/Send portal invite to \$\{selected\.size\}/);
  });

  it("Portal Onboarding Health tile receives ``externalRefetchToken={h1Result}`` for post-bulk refetch", () => {
    // CustomersList wires h1Result through the tile prop.
    expect(CUSTOMERS_SRC).toMatch(
      /PortalOnboardingHealthTile[\s\S]{0,120}externalRefetchToken=\{h1Result\}/,
    );
    // And the tile useEffect includes ``externalRefetchToken`` in
    // its dep array so any change re-fires the fetch.
    expect(TILE_SRC).toMatch(
      /useEffect\([\s\S]*?\}, \[refetchTick, externalRefetchToken\]\)/,
    );
    // Tile accepts the prop.
    expect(TILE_SRC).toMatch(
      /function PortalOnboardingHealthTile\(\{\s*externalRefetchToken\s*\}\)/,
    );
  });
});
