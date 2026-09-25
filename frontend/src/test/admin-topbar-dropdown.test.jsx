/**
 * Feb-2026 · AdminTopBar dropdown styling lock (revised spec).
 *
 * Locks the three cosmetic bumps the design brief asked for:
 *
 *   1. Section-title (``DropdownMenuLabel``) — renders as a
 *      distinct header block: background ``colors.nav.bgActiveNavy``
 *      (#303AA0), label indented ``pl-3`` (matching the sidebar's
 *      subsection row-indent at ``AdminSidebar.jsx:377``), inner
 *      text wrapped in a ``<span>`` with
 *      ``px-3 py-1.5 text-base font-bold uppercase``.
 *   2. Entry links inside ``EntryItem`` — indented by ``pl-6`` so
 *      they sit further left-shifted than the ``pl-3`` title.
 *   3. ``DropdownMenuSeparator`` bumped to ``h-[2px] bg-white/25``.
 *
 * Mobile parity — ``MobileMenu`` mirrors the label header block
 * treatment and the ``pl-6`` link indent.
 *
 * Rationale for a source-scan style test (mirrors K75 · line 109):
 * Radix DropdownMenu portals only open in jsdom with a pointer-
 * event polyfill. The whole surface here is CSS-class polish
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


describe("AdminTopBar · dropdown section-title header block", () => {
  it("desktop CategoryDropdown label carries bgActiveNavy token + pl-3 (sidebar row-anchor)", () => {
    // Label wrapper: pl-3 className + bgActiveNavy background via
    // the imported token (NOT a hardcoded hex).
    expect(_DESKTOP).toMatch(
      /<DropdownMenuLabel[\s\S]*?className="pl-3"[\s\S]*?style=\{\{[\s\S]*?backgroundColor:\s*colors\.nav\.bgActiveNavy[\s\S]*?\}\}/,
    );
    // Inner span carries the revised chip classes.
    expect(_DESKTOP).toMatch(
      /className="[^"]*\binline-block\b[^"]*\bpx-3\b[^"]*\bpy-1\.5\b[^"]*\btext-base\b[^"]*\bfont-bold\b[^"]*\buppercase\b[^"]*"/,
    );
  });

  it("mobile MobileMenu mirrors the header-block treatment", () => {
    expect(_MOBILE).toMatch(
      /<DropdownMenuLabel[\s\S]*?className="pl-3"[\s\S]*?style=\{\{[\s\S]*?backgroundColor:\s*colors\.nav\.bgActiveNavy[\s\S]*?\}\}/,
    );
    expect(_MOBILE).toMatch(
      /className="[^"]*\binline-block\b[^"]*\bpx-3\b[^"]*\bpy-1\.5\b[^"]*\btext-base\b[^"]*\bfont-bold\b[^"]*\buppercase\b[^"]*"/,
    );
  });
});


describe("AdminTopBar · entry link indent", () => {
  it("EntryItem link element carries the pl-6 indent (title pl-3 + additional pl-3 shift)", () => {
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
    const sepPattern =
      /<DropdownMenuSeparator\s+className="[^"]*\bh-\[2px\][^"]*\bbg-white\/25\b[^"]*"/g;
    const hits = _DESKTOP.match(sepPattern) || [];
    expect(hits.length).toBeGreaterThanOrEqual(2);
    // Parent's ``[role=separator]`` selector override is bumped to
    // bg-white/25 so the child className wins the attribute-selector
    // fight — otherwise the parent's higher specificity swallows it.
    expect(_DESKTOP).toMatch(/\[&_\[role=separator\]\]:bg-white\/25/);
  });
});
