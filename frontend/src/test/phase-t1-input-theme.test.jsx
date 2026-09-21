/**
 * Phase T1 · Feb-2026 · Sitewide text-input theme (WEB).
 *
 * The rule ships as a ``@layer base`` block in
 * ``frontend/src/index.css`` and targets EVERY text-shaped
 * ``<input>`` type + every ``<textarea>``.  Because the rule is
 * cascade-scoped (not a wrapper) we can't cheaply exercise the
 * *computed* style under jsdom — Vitest's jsdom environment doesn't
 * resolve Tailwind's ``@layer base`` sugar or ``::placeholder``
 * pseudo-elements.  Instead we lock the shipped CSS text against a
 * grep-shaped contract so a regression is loud and instant.
 *
 * Phase N2 · Feb-2026 refinement — text color flipped from navy
 * ``#000080`` to brand blue ``#0284C7``; placeholder RGB flipped
 * accordingly.  Selector chain and exclusion list are unchanged.
 *
 * Coverage:
 *  1. Solid-white background rule is present on the text-shaped
 *     ``<input>`` / ``<textarea>`` selector.
 *  2. Brand-blue (``#0284C7``) text color is present on the same rule.
 *  3. Placeholder rule targets the same excluded set and paints
 *     ``rgba(2, 132, 199, 0.55)``.
 *  4. Excluded types (checkbox, radio, file, color, date family,
 *     range, submit/reset/button/image/hidden) are ALL listed in
 *     the selector — regression guard against a stray commit
 *     bringing checkboxes / date pickers under the theme.
 *  5. The rule sits inside ``@layer base`` so utility overrides on
 *     per-consumer ``className`` still win the cascade.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const indexCss = fs.readFileSync(
  path.resolve(__dirname, "../index.css"),
  "utf8",
);

const T1_HEADER = "Phase T1 · Feb-2026 — Sitewide text-input theme";

describe("Phase T1 · sitewide text-input theme (index.css)", () => {
  it("declares a Phase-T1 header block", () => {
    expect(indexCss).toContain(T1_HEADER);
  });

  it("paints solid-white bg + brand-blue text on the text-shaped selector", () => {
    // Extract the Phase-T1 section so failures in unrelated rules
    // don't false-positive here.
    const section = indexCss.split(T1_HEADER)[1] || "";
    expect(section).toMatch(/background-color:\s*#FFFFFF/i);
    expect(section).toMatch(/color:\s*#0284C7/i);
  });

  it("declares a placeholder rule at 55%-opacity brand blue", () => {
    const section = indexCss.split(T1_HEADER)[1] || "";
    expect(section).toMatch(/::placeholder/);
    expect(section).toMatch(/rgba\(\s*2\s*,\s*132\s*,\s*199\s*,\s*0\.55\s*\)/);
    // Firefox regression guard — ensure ``opacity: 1`` is set,
    // otherwise Firefox will over-fade the placeholder to ~54%
    // of our own 55% and it becomes illegible.
    expect(section).toMatch(/opacity:\s*1/);
  });

  it("excludes every non-text-shaped input type from the theme", () => {
    const section = indexCss.split(T1_HEADER)[1] || "";
    const expectedExclusions = [
      "checkbox", "radio", "file", "color",
      "date", "datetime-local", "time",
      "month", "week", "range",
      "submit", "reset", "button", "image", "hidden",
    ];
    for (const type of expectedExclusions) {
      // Both the value + textarea selector and the placeholder
      // selector must exclude this type.
      const matches = section.match(new RegExp(
        `not\\(\\[type="${type.replace(/[-]/g, "\\-")}"\\]\\)`,
        "g",
      )) || [];
      expect(
        matches.length,
        `expected type="${type}" to be excluded on BOTH the value rule and the ::placeholder rule`,
      ).toBeGreaterThanOrEqual(2);
    }
  });

  it("wraps the rule in @layer base so utility overrides still win", () => {
    const section = indexCss.split(T1_HEADER)[1] || "";
    // A brittle-but-valuable substring check: the ``@layer base``
    // opener must appear inside the Phase-T1 section.
    expect(section).toMatch(/@layer\s+base\s*\{/);
  });
});
