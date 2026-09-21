/**
 * Phase N2 · Feb-2026 — Universal Input Restyle Refinement.
 *
 * Cosmetic refinement on top of Phase N1:
 *
 *   1. Sitewide input text color flipped from navy ``#000080`` to
 *      brand blue ``#0284C7``.  Placeholder RGB updated to match.
 *   2. New ``colors.searchIcon`` theme token (``#0284C7``) resolves
 *      the color of every ``<Search>`` / ``<SearchIcon>`` in the
 *      app so a future palette change is a one-line edit.
 *   3. K52.1 navy-strip search inputs (Customers list, Leads
 *      dashboard, Schedule calendar) previously bypassed the app-
 *      wide theme with a translucent-white overlay + white text.
 *      They now use the standard white-input theme (solid white
 *      bg + brand-blue text + brand-blue icon).
 *
 * Coverage:
 *  A. Theme
 *     A1. ``colors.searchIcon`` exists and equals ``#0284C7``.
 *
 *  B. CSS
 *     B1. Phase T1 base rule paints ``color: #0284C7`` (not
 *         ``#000080``).
 *     B2. Phase T1 placeholder rule paints
 *         ``rgba(2, 132, 199, 0.55)`` (not navy).
 *
 *  C. Shared components
 *     C1. Shadcn ``<Input>``, ``<Textarea>``, and legacy
 *         ``<TextInput>`` render with ``text-[#0284C7]`` and
 *         ``placeholder:text-[#0284C7]/55``.  No stale navy hex.
 *
 *  D. Search-icon coverage
 *     D1. Every ``<Search>`` / ``<SearchIcon>`` occurrence across
 *         ``frontend/src/`` (excluding the shadcn cmdk primitive
 *         which uses a Tailwind arbitrary class instead) resolves
 *         its color via ``colors.searchIcon`` OR a direct
 *         ``#0284C7`` hex — no stale ``colors.muted`` / ``.brand`` /
 *         ``.nav.fgMuted`` / ``text-zinc-400`` / ``text-gray-400``
 *         references remain on a ``<Search>`` element.
 *
 *  E. K52.1 pages
 *     E1. CustomersList, LeadsDashboardPage, and CalendarSchedule
 *         search inputs use ``bg-white`` + ``text-[#0284C7]`` (no
 *         translucent-white overlay + white text overrides).
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { colors } from "@/theme";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { TextInput } from "@/components/ui-kit";

const SRC = path.resolve(__dirname, "..");

const readIfExists = (rel) => {
  const p = path.resolve(SRC, rel);
  return fs.existsSync(p) ? fs.readFileSync(p, "utf8") : "";
};

const indexCss = readIfExists("index.css");

describe("Phase N2 · A · theme token", () => {
  it("A1 · colors.searchIcon === #0284C7", () => {
    expect(colors.searchIcon).toBe("#0284C7");
  });
});

describe("Phase N2 · B · Phase T1 base rule flipped to brand blue", () => {
  it("B1 · text color is #0284C7 (no stale #000080)", () => {
    const t1Header = "Phase T1 · Feb-2026 — Sitewide text-input theme";
    const section = indexCss.split(t1Header)[1] || "";
    expect(section).toMatch(/color:\s*#0284C7/i);
    expect(section).not.toMatch(/color:\s*#000080/i);
  });

  it("B2 · placeholder is rgba(2, 132, 199, 0.55)", () => {
    const t1Header = "Phase T1 · Feb-2026 — Sitewide text-input theme";
    const section = indexCss.split(t1Header)[1] || "";
    expect(section).toMatch(/rgba\(\s*2\s*,\s*132\s*,\s*199\s*,\s*0\.55\s*\)/);
    expect(section).not.toMatch(/rgba\(\s*0\s*,\s*0\s*,\s*128/);
  });
});

describe("Phase N2 · C · shared components paint brand blue", () => {
  it("C1 · Input renders text-[#0284C7] + placeholder:text-[#0284C7]/55", () => {
    const { container } = render(<Input placeholder="x" />);
    const el = container.querySelector("input");
    expect(el.className).toMatch(/text-\[#0284C7\]/);
    expect(el.className).toMatch(/placeholder:text-\[#0284C7\]\/55/);
    expect(el.className).not.toMatch(/text-\[#000080\]/);
  });

  it("C1 · Textarea renders text-[#0284C7] + placeholder:text-[#0284C7]/55", () => {
    const { container } = render(<Textarea placeholder="x" />);
    const el = container.querySelector("textarea");
    expect(el.className).toMatch(/text-\[#0284C7\]/);
    expect(el.className).toMatch(/placeholder:text-\[#0284C7\]\/55/);
    expect(el.className).not.toMatch(/text-\[#000080\]/);
  });

  it("C1 · legacy <TextInput> renders text-[#0284C7]", () => {
    const { container } = render(
      <TextInput testid="n2-tinput" placeholder="x" />,
    );
    const el = container.querySelector('[data-testid="n2-tinput"]');
    expect(el.className).toMatch(/text-\[#0284C7\]/);
    expect(el.className).toMatch(/placeholder:text-\[#0284C7\]\/55/);
  });
});

/*
 * Collect every ``<Search>`` / ``<SearchIcon>`` call-site under
 * ``frontend/src/`` (excluding ``test/`` fixtures, ``mobile/``,
 * and any string containing "SearchBar" which is a different
 * component family).  The check walks each element region up to
 * 8 lines ahead so multi-line JSX blocks are covered.
 */
function collectSearchElements() {
  const results = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "test" || entry.name === "__tests__" || entry.name === "node_modules") continue;
        walk(p);
      } else if (entry.name.endsWith(".jsx")) {
        const src = fs.readFileSync(p, "utf8");
        const lines = src.split("\n");
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];
          if (!/<Search(Icon)?\b/.test(line)) continue;
          if (/SearchBar\b/.test(line)) continue;
          // Walk forward until the specific <Search element's
          // closing ``/>`` — sibling elements on the same line
          // (e.g. ``<Loader2 ... /> : <SearchIcon ... />``) mean
          // we can't rely on the first ``/>``.  Instead, seek to
          // the first ``/>`` *after* the ``<Search`` opening.
          const openMatch = /<Search(Icon)?\b/.exec(line);
          const startCol = openMatch.index;
          const chunk = lines.slice(i, i + 8).join("\n");
          const localStart = chunk.indexOf("<Search", 0);
          const endRel = chunk.indexOf("/>", localStart);
          const region = endRel >= 0
            ? chunk.slice(localStart, endRel + 2)
            : chunk.slice(localStart);
          results.push({
            file: path.relative(SRC, p),
            lineNo: i + 1,
            region,
          });
        }
      }
    }
  };
  walk(SRC);
  return results;
}

describe("Phase N2 · D · search-icon token coverage", () => {
  const STALE_PATTERNS = [
    { name: "colors.muted", re: /colors\.muted\b/ },
    { name: "colors.brand (idle)", re: /colors\.brand(?![A-Za-z])/ },
    { name: "colors.nav.fgMuted", re: /colors\.nav\.fgMuted\b/ },
    { name: "colors.onSurfaceSecondary", re: /colors\.onSurfaceSecondary\b/ },
    { name: "text-zinc-400", re: /text-zinc-400\b/ },
    { name: "text-gray-400", re: /text-gray-400\b/ },
    { name: "text-muted-foreground", re: /text-muted-foreground\b/ },
    { name: "#000080", re: /#000080/i },
  ];

  it("D1 · every <Search> element uses colors.searchIcon (or #0284C7)", () => {
    const found = collectSearchElements();
    expect(found.length, "at least 40 search icon call-sites expected").toBeGreaterThanOrEqual(40);

    const stale = [];
    for (const site of found) {
      // Exempt: the shadcn cmdk primitive uses a Tailwind
      // arbitrary class ``text-[#0284C7]`` — that's still the
      // brand-blue token expressed differently, allow it.
      if (site.file === "components/ui/command.jsx") continue;

      const okToken =
        /colors\.searchIcon\b/.test(site.region) ||
        /text-\[#0284C7\]/.test(site.region) ||
        /style=\{\{[^}]*color:\s*colors\.searchIcon/.test(site.region);
      if (!okToken) {
        stale.push(`${site.file}:${site.lineNo} — missing colors.searchIcon`);
        continue;
      }
      for (const { name, re } of STALE_PATTERNS) {
        if (re.test(site.region)) {
          stale.push(`${site.file}:${site.lineNo} — stale pattern "${name}"`);
        }
      }
    }
    expect(stale, `stale patterns found on Search icons:\n${stale.join("\n")}`).toEqual([]);
  });
});

describe("Phase N2 · E · K52.1 navy strip pages match sitewide theme", () => {
  const K52_FILES = [
    ["pages/customers/CustomersList.jsx", "customers-search"],
    ["pages/leads/LeadsDashboardPage.jsx", "lead-search-input"],
    ["pages/schedule/CalendarSchedule.jsx", "calendar-search"],
  ];

  it.each(K52_FILES)("E1 · %s search input uses bg-white + brand-blue text (no white/navy override)", (rel, testId) => {
    const src = readIfExists(rel);
    expect(src.length, `expected ${rel} on disk`).toBeGreaterThan(0);
    // Locate the search input region by data-testid — the test
    // was previously scanning the WHOLE file, which false-positived
    // on unrelated ``colors.nav.fg`` references used by tab labels
    // / filter chips on the same page.
    const idx = src.indexOf(`data-testid="${testId}"`);
    expect(idx, `expected data-testid="${testId}" in ${rel}`).toBeGreaterThan(0);
    // Grab 40 lines of context around the testid.
    const lines = src.split("\n");
    let idIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].includes(`data-testid="${testId}"`)) { idIdx = i; break; }
    }
    const region = lines.slice(Math.max(0, idIdx - 20), idIdx + 5).join("\n");
    // Contains bg-white and text-[#0284C7] on the K52 filter row.
    expect(region).toMatch(/bg-white/);
    expect(region).toMatch(/text-\[#0284C7\]/);
    // No white-on-navy overrides on the search input row.
    expect(region).not.toMatch(/placeholder:text-white\/70/);
    expect(region).not.toMatch(/color:\s*colors\.nav\.fg\b/);
  });
});
