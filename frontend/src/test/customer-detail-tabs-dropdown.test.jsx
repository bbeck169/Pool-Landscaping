/**
 * Phase I6 · Feb-2026 — Customer-detail tab bar collapses to a
 * dropdown selector (was horizontal-scroll strip). Source-body
 * contract on ``pages/customers/CustomerDetail.jsx`` +
 * ``components/ui/responsive-tabs.jsx``.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const CD_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/pages/customers/CustomerDetail.jsx"),
  "utf-8",
);
const RT_SRC = fs.readFileSync(
  path.resolve(process.cwd(),
    "src/components/ui/responsive-tabs.jsx"),
  "utf-8",
);


describe("CustomerDetail · I6 tabs-as-dropdown", () => {
  it("ResponsiveTabs is mounted with forceDropdown", () => {
    const idx = CD_SRC.indexOf("<ResponsiveTabs");
    expect(idx).toBeGreaterThan(-1);
    // Widen the slice: prop attributes span ~7 lines / ~250 chars,
    // and forceDropdown lives on the last one before the closing.
    const slice = CD_SRC.slice(idx, idx + 800);
    expect(slice).toMatch(/forceDropdown/);
    expect(slice).toMatch(/testidPrefix="cd-tab"/);
    expect(slice).toMatch(/tabs=\{TABS\}/);
  });

  it("dropdown lives in a compact ~280px width-bounded shell", () => {
    // The wrapper carries a maxWidth style + its own testid so a
    // future full-width regression is easy to catch.
    const idx = CD_SRC.indexOf('data-testid="cd-tabs-dropdown-shell"');
    expect(idx).toBeGreaterThan(-1);
    const slice = CD_SRC.slice(Math.max(0, idx - 200), idx + 300);
    expect(slice).toMatch(/maxWidth:\s*280/);
  });

  it("the dropdown shell sits ABOVE the tab-panel container", () => {
    const shellIdx = CD_SRC.indexOf(
      'data-testid="cd-tabs-dropdown-shell"');
    // Locate the tab-panel wrapper by its neighbouring inline
    // padding class (``p-5`` on the inner container).
    const panelIdx = CD_SRC.indexOf('className="p-5"', shellIdx);
    expect(shellIdx).toBeGreaterThan(-1);
    expect(panelIdx).toBeGreaterThan(shellIdx);
  });

  it("ResponsiveTabs supports the forceDropdown prop", () => {
    // Signature + branch class wiring.
    expect(RT_SRC).toMatch(/forceDropdown\s*=\s*false/);
    expect(RT_SRC).toMatch(
      /const\s+dropdownShellClass\s*=\s*forceDropdown\s*\?/,
    );
    expect(RT_SRC).toMatch(
      /const\s+stripClass\s*=\s*forceDropdown/,
    );
  });

  it("TABS array still lists every existing customer section", () => {
    // Regression guard: the dropdown should carry every entry
    // that used to sit on the horizontal strip.
    for (const k of ["overview", "properties", "jobs", "quotes",
                          "invoices", "equipment", "tasks", "notes",
                          "credits"]) {
      expect(CD_SRC).toMatch(new RegExp(`k:\\s*"${k}"`));
    }
  });

  it("tab state hook + setTab wire are retained", () => {
    // The tab state hook + change handler stay in place — no
    // refactor of the state path. (CustomerDetail uses local
    // ``useState`` rather than URL-sync — the same pattern as
    // pre-I6.  If a future revision adds URL persistence, this
    // test should be tightened accordingly.)
    expect(CD_SRC).toMatch(/const\s+\[tab,\s*setTab\]\s*=\s*useState\(/);
    expect(CD_SRC).toMatch(/onChange=\{setTab\}/);
  });

  it("no legacy horizontal-scroll classes at the CustomerDetail mount", () => {
    // Belt-and-suspenders: nothing in the ~600 char slice around
    // the ResponsiveTabs mount should still name an overflow-x
    // scroll strip.
    const idx = CD_SRC.indexOf("<ResponsiveTabs");
    const slice = CD_SRC.slice(Math.max(0, idx - 400),
                                        idx + 500);
    expect(slice).not.toMatch(/overflow-x-auto/);
    expect(slice).not.toMatch(/hidden md:flex/);
  });
});
