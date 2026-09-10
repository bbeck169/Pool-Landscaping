/**
 * Feb-2026 · CardOnFileWarningBanner — "Add card on file" button
 * layout regression guard.
 *
 * Locks in the CSS invariants that keep the button from clipping /
 * wrapping ugly at desktop widths AND stacking cleanly on narrow
 * viewports:
 *   1. Label text is exactly "Add card on file" (verbatim — no
 *      truncation, no rename).
 *   2. Button has ``whitespace-nowrap`` so the label stays on a
 *      single line inside the button.
 *   3. Button has ``shrink-0`` so the row's middle text column
 *      cannot squeeze the button below its content width.
 *   4. Outer banner uses ``flex-wrap`` so the button wraps to a new
 *      line at narrow widths instead of overflowing the container.
 *   5. Icon has ``shrink-0`` — the ``CreditCard`` glyph never
 *      collapses to 0px if the button gets pinched.
 *   6. Label is wrapped in a plain ``<span>`` so future upstream
 *      style changes (e.g. adding ``truncate``) can target the
 *      copy without breaking icon layout.
 *
 * Contract is asserted via source-body regex + a rendered DOM
 * check for the class list on the button, mirroring the pattern
 * used across the ``src/test`` layout-regression suites.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, vi } from "vitest";


vi.mock("@/api", () => ({
  api: { post: vi.fn(() => new Promise(() => {})) },
}));


import CardOnFileWarningBanner from "@/components/customers/CardOnFileWarningBanner";

const SRC = fs.readFileSync(
  path.resolve(
    process.cwd(),
    "src/components/customers/CardOnFileWarningBanner.jsx",
  ),
  "utf-8",
);


const _customer = {
  id: "c-css",
  effective_require_card_on_file: true,
  has_card_on_file: false,
};


describe("CardOnFileWarningBanner · button layout regression", () => {
  it("renders the label verbatim ('Add card on file')", () => {
    render(<CardOnFileWarningBanner customer={_customer} />);
    const btn = screen.getByTestId("card-on-file-send-link-btn");
    expect(btn.textContent).toBe("Add card on file");
    expect(btn.textContent).not.toMatch(/Send add-card link/);
    expect(btn.textContent).not.toMatch(/\.\.\./);
  });

  it("button has whitespace-nowrap + shrink-0 so it can't be squeezed", () => {
    render(<CardOnFileWarningBanner customer={_customer} />);
    const btn = screen.getByTestId("card-on-file-send-link-btn");
    const cls = btn.className;
    expect(cls).toMatch(/whitespace-nowrap/);
    expect(cls).toMatch(/shrink-0/);
  });

  it("banner container uses flex-wrap so narrow widths stack cleanly", () => {
    render(<CardOnFileWarningBanner customer={_customer} />);
    const banner = screen.getByTestId("card-on-file-warning-banner");
    expect(banner.className).toMatch(/flex-wrap/);
  });

  it("icon carries shrink-0 so it never collapses when the button pinches", () => {
    // Source-body check — matches the CreditCard render line.
    expect(SRC).toMatch(
      /<CreditCard\s+size=\{13\}\s+className="shrink-0"\s*\/>/,
    );
  });

  it("label is wrapped in a <span> so future truncation can target the copy without breaking icon layout", () => {
    expect(SRC).toMatch(
      /<span>\{busy \? "Sending…" : "Add card on file"\}<\/span>/,
    );
  });

  it("middle text column has a min-width floor so it can't push the button off-row at narrow widths", () => {
    // ``min-w-[12rem]`` (or similar) forces the flex-wrap threshold
    // instead of letting the text column crush the button.
    expect(SRC).toMatch(/min-w-\[12rem\]/);
  });

  it("preserves the canonical test-id (regression guard for the p44 row action test)", () => {
    render(<CardOnFileWarningBanner customer={_customer} />);
    expect(screen.getByTestId("card-on-file-send-link-btn")).toBeTruthy();
  });
});
