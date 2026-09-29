/**
 * Feb-2026 · QuotesList search input styling.
 *
 * Source-grep guard for the QuotesList (admin) search input — after
 * the patch it binds ``backgroundColor``/``border``/``color`` to
 * theme tokens (``colors.surface`` / ``colors.border`` /
 * ``colors.onSurface``) and drops the ``placeholder:text-white/70``
 * class in favour of ``placeholder:text-zinc-400`` so the placeholder
 * is legible on the theme's light surface.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/quotes/QuotesList.jsx"),
  "utf-8",
);

describe("QuotesList · search input style contract", () => {
  it("uses colors.surface for backgroundColor", () => {
    expect(SRC).toContain("backgroundColor: colors.surface");
  });

  it("uses colors.border for the border color with an explicit 1px solid shorthand", () => {
    expect(SRC).toContain("border: '1px solid ' + colors.border");
  });

  it("uses colors.onSurface for color", () => {
    expect(SRC).toContain("color: colors.onSurface");
  });

  it("does NOT use the legacy placeholder:text-white/70 class", () => {
    expect(SRC).not.toContain("placeholder:text-white/70");
  });

  it("uses placeholder:text-zinc-400 for the input placeholder", () => {
    expect(SRC).toContain("placeholder:text-zinc-400");
  });
});
