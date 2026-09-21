/**
 * Phase N1 · Feb-2026 — Universal input restyle.
 *
 * Additive on top of Phase T1 (which paints solid-white bg + navy
 * text via a ``@layer base`` block in ``frontend/src/index.css``).
 * Phase N1 extends the same selector chain with:
 *
 *   1. ``border-radius: 0.5rem`` (Tailwind ``rounded-lg`` parity)
 *   2. ``:focus-visible`` outline — 2px solid blue-500 (#3B82F6)
 *      + matching border color
 *
 * Plus explicit shared-component patches (shadcn ``<Input>`` /
 * ``<Textarea>`` / legacy ``<TextInput>``) so they carry the
 * Tailwind ring utilities regardless of how they're consumed.
 *
 * Coverage:
 *  A. CSS
 *     A1. Phase N1 header comment is present in index.css
 *     A2. ``border-radius: 0.5rem`` rule on the T1 selector chain
 *     A3. ``:focus-visible`` rule sets outline #3B82F6
 *     A4. Excluded types (checkbox, radio, file, color, date
 *         family, range, submit/reset/button/image/hidden) stay
 *         listed on BOTH the border-radius rule and the
 *         focus-visible rule.
 *     A5. Rules wrap in ``@layer base`` so utility overrides win.
 *
 *  B. Shadcn <Input>
 *     B1. Renders with ``rounded-lg``, ``bg-white``, navy text,
 *         placeholder navy, focus-visible ring + border blue-500.
 *
 *  C. Shadcn <Textarea>
 *     C1. Same class contract as <Input>.
 *
 *  D. Legacy <TextInput> (components/ui-kit.jsx)
 *     D1. Renders with ``rounded-lg``, ``bg-white``, navy text,
 *         placeholder navy, focus ring blue-500.
 */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { TextInput } from "@/components/ui-kit";

const indexCss = fs.readFileSync(
  path.resolve(__dirname, "../index.css"),
  "utf8",
);

const N1_HEADER = "Phase N1 · Feb-2026 — Universal input restyle";

describe("Phase N1 · A · index.css contract", () => {
  it("A1 · declares a Phase-N1 header block", () => {
    expect(indexCss).toContain(N1_HEADER);
  });

  it("A2 · applies border-radius: 0.5rem on the T1 selector chain", () => {
    const section = indexCss.split(N1_HEADER)[1] || "";
    expect(section).toMatch(/border-radius:\s*0\.5rem/);
  });

  it("A3 · focus-visible rule sets 2px solid blue-500 outline", () => {
    const section = indexCss.split(N1_HEADER)[1] || "";
    expect(section).toMatch(/:focus-visible/);
    expect(section).toMatch(/outline:\s*2px\s+solid\s+#3B82F6/i);
    // border-color must also flip so a persistent border on the
    // consumer doesn't fight the outline visually.
    expect(section).toMatch(/border-color:\s*#3B82F6/i);
  });

  it("A4 · excluded input types stay excluded on N1 rules", () => {
    const section = indexCss.split(N1_HEADER)[1] || "";
    const expectedExclusions = [
      "checkbox", "radio", "file", "color",
      "date", "datetime-local", "time",
      "month", "week", "range",
      "submit", "reset", "button", "image", "hidden",
    ];
    for (const type of expectedExclusions) {
      // Both rules (border-radius + focus-visible) must exclude
      // this type — that's 2 occurrences minimum.
      const matches = section.match(new RegExp(
        `not\\(\\[type="${type.replace(/[-]/g, "\\-")}"\\]\\)`,
        "g",
      )) || [];
      expect(
        matches.length,
        `expected type="${type}" to be excluded on BOTH the border-radius rule and the focus-visible rule`,
      ).toBeGreaterThanOrEqual(2);
    }
  });

  it("A5 · wraps N1 rules in @layer base", () => {
    const section = indexCss.split(N1_HEADER)[1] || "";
    expect(section).toMatch(/@layer\s+base\s*\{/);
  });
});

describe("Phase N1 · B · shadcn <Input> class contract", () => {
  it("B1 · renders with N1 theme classes (idle + focus)", () => {
    const { container } = render(<Input placeholder="type here" />);
    const el = container.querySelector("input");
    expect(el).toBeTruthy();
    const cls = el.className;
    // Solid-white + navy + border + rounded-lg on idle.
    expect(cls).toMatch(/bg-white/);
    expect(cls).toMatch(/text-\[#000080\]/);
    expect(cls).toMatch(/border-slate-200/);
    expect(cls).toMatch(/rounded-lg/);
    // Placeholder navy at 55% opacity.
    expect(cls).toMatch(/placeholder:text-\[#000080\]\/55/);
    // Focus ring 2px + blue-500 + border blue-500.
    expect(cls).toMatch(/focus-visible:ring-2/);
    expect(cls).toMatch(/focus-visible:ring-blue-500/);
    expect(cls).toMatch(/focus-visible:border-blue-500/);
    // Disabled semantics preserved.
    expect(cls).toMatch(/disabled:cursor-not-allowed/);
    expect(cls).toMatch(/disabled:opacity-50/);
  });
});

describe("Phase N1 · C · shadcn <Textarea> class contract", () => {
  it("C1 · renders with N1 theme classes (idle + focus)", () => {
    const { container } = render(<Textarea placeholder="type here" />);
    const el = container.querySelector("textarea");
    expect(el).toBeTruthy();
    const cls = el.className;
    expect(cls).toMatch(/bg-white/);
    expect(cls).toMatch(/text-\[#000080\]/);
    expect(cls).toMatch(/border-slate-200/);
    expect(cls).toMatch(/rounded-lg/);
    expect(cls).toMatch(/placeholder:text-\[#000080\]\/55/);
    expect(cls).toMatch(/focus-visible:ring-2/);
    expect(cls).toMatch(/focus-visible:ring-blue-500/);
    expect(cls).toMatch(/focus-visible:border-blue-500/);
    expect(cls).toMatch(/disabled:cursor-not-allowed/);
    expect(cls).toMatch(/disabled:opacity-50/);
  });
});

describe("Phase N1 · D · legacy <TextInput> (ui-kit) class contract", () => {
  it("D1 · renders with N1 theme classes (idle + focus)", () => {
    const { container } = render(
      <TextInput testid="n1-textinput" placeholder="type here" />,
    );
    const el = container.querySelector(
      '[data-testid="n1-textinput"]',
    );
    expect(el).toBeTruthy();
    const cls = el.className;
    expect(cls).toMatch(/bg-white/);
    expect(cls).toMatch(/text-\[#000080\]/);
    expect(cls).toMatch(/border-slate-200/);
    expect(cls).toMatch(/rounded-lg/);
    expect(cls).toMatch(/placeholder:text-\[#000080\]\/55/);
    expect(cls).toMatch(/focus:ring-2/);
    expect(cls).toMatch(/focus:ring-blue-500/);
    expect(cls).toMatch(/focus:border-blue-500/);
  });
});
