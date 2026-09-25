/**
 * Admin Sidebar subsection styling · Feb-2026 · small-polish task.
 *
 * Locks the "bolder submenu titles + indented submenu items" UI
 * polish applied to ``layouts/AdminSidebar.jsx``.  Follows the
 * source-inspection convention already established by
 * ``admin-sidebar-pinned-nav.test.jsx`` — the full sidebar pulls
 * in dozens of route modules so we assert against the JSX source
 * text rather than mounting a DOM.
 *
 *   1. Subsection heading uses ``text-sm``, ``font-bold`` and
 *      ``colors.onSurfaceSecondary`` (bumped up from the old
 *      ``text-[10px] font-semibold colors.muted`` chrome).
 *   2. Subsection-entries wrapper (the ``space-y-0.5`` immediately
 *      under the heading) has ``pl-3`` for the indent.
 *   3. Safety: no other ``space-y-0.5`` wrapper in the file gained
 *      ``pl-3`` — the outer subgroups container (``space-y-0.5
 *      pl-1``) MUST stay at pl-1 so non-subgroup top-level entries
 *      don't shift right.
 *   4. The old chrome tokens (``text-[10px] font-semibold`` on the
 *      subsection heading, ``colors.muted`` on the same node) are
 *      gone — regression guard so a future refactor doesn't
 *      accidentally revert.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


function readAdminSidebarSource() {
  return fs.readFileSync(
    path.resolve(__dirname, "../layouts/AdminSidebar.jsx"),
    "utf8",
  );
}


describe("AdminSidebar subsection heading styling", () => {
  it("subsection heading uses text-sm font-bold colors.onSurfaceSecondary", () => {
    const src = readAdminSidebarSource();
    // Match the single JSX block that renders the subsection name
    // (``{sub.name}``) plus the immediately-preceding <div> that
    // styles it.  The regex tolerates whitespace + newline drift.
    const m = src.match(
      /<div\s+className="([^"]+)"\s+style=\{\{\s*color:\s*colors\.([A-Za-z]+)\s*\}\}>[\s\S]{0,40}\{sub\.name\}/,
    );
    expect(m, "subsection heading <div> around {sub.name} not found").not.toBeNull();
    const cls = m[1];
    const colorToken = m[2];
    expect(cls).toMatch(/\btext-sm\b/);
    expect(cls).toMatch(/\bfont-bold\b/);
    expect(colorToken).toBe("onSurfaceSecondary");
  });

  it("subsection heading no longer uses text-[10px] / font-semibold / colors.muted chrome", () => {
    const src = readAdminSidebarSource();
    // Regression guard — the exact chrome that used to precede
    // ``{sub.name}`` must not reappear on that specific node.
    const preName = src.match(/(<div[^>]*>)[\s\S]{0,40}\{sub\.name\}/);
    expect(preName, "expected <div> immediately before {sub.name}").not.toBeNull();
    const headingOpenTag = preName[1];
    expect(headingOpenTag).not.toMatch(/text-\[10px\]/);
    expect(headingOpenTag).not.toMatch(/font-semibold/);
    expect(headingOpenTag).not.toMatch(/colors\.muted/);
  });
});


describe("AdminSidebar subsection entries indent", () => {
  it("subsection-entries wrapper has pl-3", () => {
    const src = readAdminSidebarSource();
    // The wrapper is the ``<div className="space-y-0.5 pl-3">``
    // that sits between the heading and ``sub.entries.map(...)``.
    // Match against ``sub.entries.map`` to disambiguate from
    // other ``space-y-0.5`` wrappers in the file (pinned list,
    // outer subgroups container).
    const m = src.match(
      /<div\s+className="([^"]+)">\s*\{sub\.entries\.map/,
    );
    expect(m, "subsection-entries wrapper <div> not found").not.toBeNull();
    const cls = m[1];
    expect(cls).toMatch(/\bspace-y-0\.5\b/);
    expect(cls).toMatch(/\bpl-3\b/);
  });

  it("outer subgroups wrapper (space-y-0.5 pl-1) is NOT bumped to pl-3", () => {
    // The outer container is ``<div className="space-y-0.5 pl-1">``
    // which wraps EITHER the subgroup list OR the plain
    // ``g.entries.map(...)`` list.  Bumping IT to pl-3 would push
    // every top-level non-nested link right — the safety check
    // from the brief.
    const src = readAdminSidebarSource();
    expect(src).toMatch(/<div\s+className="space-y-0\.5 pl-1">/);
    // And that specific opener MUST NOT contain pl-3.
    const outer = src.match(/<div\s+className="space-y-0\.5 pl-1">/);
    expect(outer, "outer subgroups wrapper missing").not.toBeNull();
    expect(outer[0]).not.toMatch(/pl-3/);
  });
});
