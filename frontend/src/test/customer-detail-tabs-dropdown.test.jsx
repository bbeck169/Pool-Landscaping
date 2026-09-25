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

  it("dropdown lives in a compact width-bounded shell inside the navy strip", () => {
    // Feb-2026 · Customer Header Navy Strip — the shell relocated
    // from a standalone ``maxWidth: 280`` container into the
    // unified ``cd-command-strip`` flex row. It now carries
    // ``minWidth: 220`` so it holds its column when the strip
    // scrolls horizontally.
    const idx = CD_SRC.indexOf('data-testid="cd-tabs-dropdown-shell"');
    expect(idx).toBeGreaterThan(-1);
    const slice = CD_SRC.slice(Math.max(0, idx - 200), idx + 300);
    expect(slice).toMatch(/minWidth:\s*220/);
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
    // refactor of the state path.  Phase J1 · Feb-2026 wraps the
    // raw ``useState`` setter behind a ``setTab`` helper that also
    // pushes the value into the URL query string, so the hook is
    // now declared as ``[tab, _setTab]`` with a wrapping helper.
    expect(CD_SRC).toMatch(
      /const\s+\[tab,\s*_setTab\]\s*=\s*useState\(/,
    );
    expect(CD_SRC).toMatch(/const\s+setTab\s*=\s*\(next\)\s*=>/);
    expect(CD_SRC).toMatch(/onChange=\{setTab\}/);
  });

  // ── Phase J1 · Feb-2026 — URL-param persistence on tabs ───────
  it("tab selection round-trips through the ?tab= query param", () => {
    // Initial mount seeds from the URL:
    //   const q = searchParams.get("tab");
    expect(CD_SRC).toMatch(/searchParams\.get\(\s*"tab"\s*\)/);
    // ``setTab`` writes back into the URL via ``setSearchParams``:
    //   params.set("tab", next);
    //   setSearchParams(params, { replace: true });
    expect(CD_SRC).toMatch(/params\.set\(\s*"tab"\s*,\s*next\s*\)/);
    expect(CD_SRC).toMatch(
      /setSearchParams\(\s*params\s*,\s*\{\s*replace:\s*true\s*\}\s*\)/,
    );
    // Default tab ("overview") is elided so the URL stays clean:
    //   else params.delete("tab");
    expect(CD_SRC).toMatch(/params\.delete\(\s*"tab"\s*\)/);
  });

  it("useSearchParams is imported + wired to the URL param hook", () => {
    // Import + hook call must both be present so a future refactor
    // that drops the hook will break loudly.
    expect(CD_SRC).toMatch(
      /import\s+\{[^}]*useSearchParams[^}]*\}\s+from\s+"react-router-dom"/,
    );
    expect(CD_SRC).toMatch(
      /const\s+\[searchParams,\s*setSearchParams\]\s*=\s*useSearchParams\(\)/,
    );
  });

  it("no legacy horizontal-scroll classes on the ResponsiveTabs mount itself", () => {
    // Belt-and-suspenders: the ResponsiveTabs component's own
    // mount site must NOT carry an overflow-x scroll strip. The
    // parent navy command strip DOES use ``overflow-x-auto``
    // (needed for narrow desktops with many buttons) but the
    // ResponsiveTabs itself renders as a compact
    // ``forceDropdown`` shell — so we bound the slice from the
    // ``<ResponsiveTabs`` open to the FIRST ``/>`` that closes it.
    const idx = CD_SRC.indexOf("<ResponsiveTabs");
    const closeIdx = CD_SRC.indexOf("/>", idx);
    const slice = CD_SRC.slice(idx, closeIdx + 2);
    expect(slice).not.toMatch(/overflow-x-auto/);
    expect(slice).not.toMatch(/hidden md:flex/);
  });
});
