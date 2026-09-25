/**
 * Feb-2026 · AdminTopBar dropdown styling lock.
 *
 * Locks the three cosmetic bumps the design brief asked for:
 *
 *   1. Section-title (``DropdownMenuLabel``) — text is wrapped in a
 *      subtle brand-tinted chip: ``bg-white/5``,
 *      ``text-sm font-bold uppercase tracking-wider``, colored via
 *      ``colors.brandTertiary``.
 *   2. Entry links inside ``EntryItem`` — indented by ``pl-6``.
 *   3. ``DropdownMenuSeparator`` bumped to ``h-[2px] bg-white/25``.
 *
 * Mobile parity — the ``MobileMenu`` block mirrors the label chip
 * styling and the ``pl-6`` link indent.
 *
 * Rationale for a source-scan style test (mirrors K75 · line 109):
 * Radix DropdownMenu portals only open in jsdom with a pointer-
 * event polyfill.  The whole surface here is CSS-class polish
 * with no behavior change; a source-level regex on
 * ``AdminTopBar.jsx`` is the least-brittle way to lock the
 * classes without inventing a Radix jsdom shim.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const _SRC = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);

// Slice the source into the desktop CategoryDropdown block and the
// MobileMenu block so we can assert parity independently.
function _sliceBetween(needle, endNeedle) {
  const i = _SRC.indexOf(needle);
  if (i < 0) throw new Error(`missing marker: ${needle}`);
  const j = _SRC.indexOf(endNeedle, i + 1);
  if (j < 0) throw new Error(`missing end marker: ${endNeedle}`);
  return _SRC.slice(i, j);
}
const _DESKTOP = _sliceBetween(
  "function CategoryDropdown(",
  "function EntryItem(",
);
const _ENTRY = _sliceBetween("function EntryItem(", "function MobileMenu(");
const _MOBILE = _sliceBetween(
  "function MobileMenu(",
  "// Phase A1 Hotfix",
);


describe("AdminTopBar · dropdown section-title styling", () => {
  it("desktop CategoryDropdown label chip carries uppercase + font-bold + brand-tinted background", () => {
    // Every ``DropdownMenuLabel`` in the desktop block wraps its
    // text in a span with the four canonical polish classes.
    const chipClass =
      /className="[^"]*\bbg-white\/5\b[^"]*\brounded\b[^"]*\btext-sm\b[^"]*\bfont-bold\b[^"]*\buppercase\b[^"]*\btracking-wider\b[^"]*"/;
    expect(_DESKTOP).toMatch(chipClass);
    // Color comes from the ``brandTertiary`` token, not an inline hex.
    expect(_DESKTOP).toMatch(
      /<DropdownMenuLabel[\s\S]*?style=\{\{\s*color:\s*colors\.brandTertiary\s*\}\}/,
    );
  });

  it("mobile MobileMenu mirrors the section-title chip class + brandTertiary color", () => {
    const chipClass =
      /className="[^"]*\bbg-white\/5\b[^"]*\brounded\b[^"]*\btext-sm\b[^"]*\bfont-bold\b[^"]*\buppercase\b[^"]*\btracking-wider\b[^"]*"/;
    expect(_MOBILE).toMatch(chipClass);
    expect(_MOBILE).toMatch(
      /<DropdownMenuLabel[\s\S]*?style=\{\{\s*color:\s*colors\.brandTertiary\s*\}\}/,
    );
  });
});


describe("AdminTopBar · entry link indent", () => {
  it("EntryItem link element carries the pl-6 indent", () => {
    // Only the link's className should carry ``pl-6``; the label
    // header stays flush with the dropdown's own padding.
    expect(_ENTRY).toMatch(
      /<Link\s+to=\{e\.to\}\s+className="[^"]*\bpl-6\b[^"]*"/,
    );
  });

  it("MobileMenu fixed-item links carry pl-6 for parity", () => {
    expect(_MOBILE).toMatch(
      /<Link\s+to=\{it\.to\}\s+className="[^"]*\bpl-6\b[^"]*"/,
    );
  });
});


describe("AdminTopBar · thicker dividers", () => {
  it("desktop DropdownMenuSeparator instances carry h-[2px] bg-white/25", () => {
    // Match both usages inside the desktop block — the
    // noSub↔bySub boundary and the between-bySub loop.
    const sepPattern =
      /<DropdownMenuSeparator\s+className="[^"]*\bh-\[2px\][^"]*\bbg-white\/25\b[^"]*"/g;
    const hits = _DESKTOP.match(sepPattern) || [];
    expect(hits.length).toBeGreaterThanOrEqual(2);
    // And the DropdownMenuContent's ``[role=separator]`` override
    // is bumped to bg-white/25 so the class on the child wins the
    // attribute-selector fight.
    expect(_DESKTOP).toMatch(/\[&_\[role=separator\]\]:bg-white\/25/);
  });
});
