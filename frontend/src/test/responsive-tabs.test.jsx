/**
 * Feb-2026 · Group A tab-strip migration — smoke test for the shared
 * ``<ResponsiveTabs>`` component.
 *
 * Locks the two DOM branches so the responsive contract can't be
 * silently regressed:
 *   1. A ``md:hidden`` dropdown-trigger button exists (< md branch).
 *   2. A ``hidden md:flex`` horizontal <nav> exists (≥ md branch).
 *   3. Both branches emit the same testid-prefixed items so
 *      existing testid conventions (``cd-tab-*`` / ``pd-tab-*``)
 *      still resolve regardless of which surface a test targets.
 *
 * Not a full render test — pulls the component source and asserts
 * the structural shape, matching the codebase convention for
 * lightweight structural tests (see
 * ``customer-portal-invite-relocation.test.jsx``).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = readFileSync(
  resolve(__dirname, "../components/ui/responsive-tabs.jsx"),
  "utf8",
);

describe("ResponsiveTabs — responsive contract", () => {
  it("dropdown branch is md:hidden", () => {
    // Dropdown trigger only renders on narrow viewports.
    expect(SRC).toMatch(/className="md:hidden"/);
    expect(SRC).toMatch(/testid=\{`\$\{testidPrefix\}-dropdown-trigger`\}/);
  });

  it("horizontal strip branch is hidden md:flex", () => {
    // Familiar strip only renders on ≥ md.
    expect(SRC).toMatch(/className="hidden md:flex overflow-x-auto"/);
  });

  it("both branches render the same item testids via _safeTestid", () => {
    // Item-level testids follow ``${prefix}-${slugified-key}``.
    // Both branches share the same helper so downstream test-ids
    // resolve identically.
    const helperMatches = SRC.match(/_safeTestid\(testidPrefix, t\.k\)/g)
      || [];
    expect(helperMatches.length).toBe(2);
  });

  it("accepts both string tabs and rich {k, label, icon} tabs", () => {
    // Normalizer branch — string tabs are wrapped into
    // ``{ k: str, label: str, icon: null }`` so both callers can
    // hand off their existing arrays verbatim.
    expect(SRC).toMatch(/typeof t === "string"/);
    expect(SRC).toMatch(/label: t\.label \?\? t\.k/);
  });

  it("uses shadcn DropdownMenu (not native <select>)", () => {
    // Matches the codebase convention — every other dropdown-shape
    // menu in the app uses ``@/components/ui/dropdown-menu``.
    expect(SRC).toMatch(
      /import\s*\{[^}]*DropdownMenu[^}]*\}\s*from\s*"@\/components\/ui\/dropdown-menu"/,
    );
    // Native <select> would be a UX regression here — reject it.
    expect(SRC).not.toMatch(/<select\b/);
  });

  it("preserves parent-owned active/onChange wiring", () => {
    // The signature must expose ``active`` + ``onChange`` so parents
    // keep owning URL/state sync — no internal state fork.
    expect(SRC).toMatch(/active,\s*\n\s*onChange/);
    expect(SRC).not.toMatch(/React\.useState\(/);
  });
});

describe("Group A migrations — call sites use ResponsiveTabs", () => {
  const CD = readFileSync(
    resolve(__dirname, "../pages/customers/CustomerDetail.jsx"),
    "utf8",
  );
  const PD = readFileSync(
    resolve(__dirname, "../pages/customers/PropertyDrawer.jsx"),
    "utf8",
  );

  it("CustomerDetail mounts ResponsiveTabs with cd-tab prefix", () => {
    expect(CD).toMatch(/from\s*"@\/components\/ui\/responsive-tabs"/);
    expect(CD).toMatch(/<ResponsiveTabs\b/);
    expect(CD).toMatch(/testidPrefix="cd-tab"/);
  });

  it("PropertyDrawer mounts ResponsiveTabs with pd-tab prefix", () => {
    expect(PD).toMatch(/from\s*"@\/components\/ui\/responsive-tabs"/);
    expect(PD).toMatch(/<ResponsiveTabs\b/);
    expect(PD).toMatch(/testidPrefix="pd-tab"/);
  });

  it("Old inline tab-strip button loops are gone from both", () => {
    // Both files used ``{TABS.map((t) => <button ...`` inline.
    // After migration, nothing in the file should still be
    // rendering that inline shape.
    expect(CD).not.toMatch(/TABS\.map\(\(t\) => \(\s*\n\s*<button/);
    expect(PD).not.toMatch(/TABS\.map\(\(t\) => \(\s*\n\s*<button/);
  });
});
