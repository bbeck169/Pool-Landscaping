/**
 * TD-38 · Feb-2026 — Vitest coverage for ``AutomationsSuppressedChip``
 * on the admin invoice/quote detail surface.
 *
 * Rendering contract (per the component's doc comment):
 *   * doc.automations_suppressed === true  → chip renders with the
 *     "Automations suppressed" label + BellOff icon + warning tone.
 *   * doc.automations_suppressed === false → render null (silent).
 *   * flag absent / undefined / null       → render null (silent).
 *   * doc is null/undefined                → render null (defensive).
 *   * stray truthy values ("yes", 1, "true") → render null (strict
 *     ``=== true`` compare locks the chip to an EXPLICIT backend
 *     decision).
 *
 * The chip accepts a ``title`` tooltip explaining what suppression
 * means to operators.
 */
import React from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

import { AutomationsSuppressedChip } from "@/pages/quotes/QuoteInvoiceDetail";


beforeEach(() => {
  cleanup();
});


describe("AutomationsSuppressedChip · TD-38", () => {
  it("renders the chip when doc.automations_suppressed === true", () => {
    render(<AutomationsSuppressedChip doc={{ automations_suppressed: true }} />);
    const chip = screen.getByTestId("automations-suppressed-chip");
    expect(chip).toBeTruthy();
    // Label text + icon-adjacent span inside the chip.
    expect(chip.textContent).toContain("Automations suppressed");
  });

  it("renders a tooltip explaining the suppression state", () => {
    render(<AutomationsSuppressedChip doc={{ automations_suppressed: true }} />);
    const chip = screen.getByTestId("automations-suppressed-chip");
    // The tooltip lives on the inner <span> as a native ``title`` attr.
    const innerSpan = chip.querySelector("span[title]");
    expect(innerSpan).toBeTruthy();
    expect(innerSpan.getAttribute("title")).toMatch(
      /reminder emails/i,
    );
    expect(innerSpan.getAttribute("title")).toMatch(
      /automated workflows won['’]t fire/i,
    );
  });

  it("renders null when doc.automations_suppressed is false", () => {
    const { container } = render(
      <AutomationsSuppressedChip doc={{ automations_suppressed: false }} />,
    );
    expect(screen.queryByTestId("automations-suppressed-chip")).toBeNull();
    // Entire render output is empty.
    expect(container.firstChild).toBeNull();
  });

  it("renders null when the flag is absent from the doc", () => {
    render(<AutomationsSuppressedChip doc={{ id: "inv_abc", status: "sent" }} />);
    expect(screen.queryByTestId("automations-suppressed-chip")).toBeNull();
  });

  it("renders null when doc is null or undefined (defensive)", () => {
    const { container: c1 } = render(<AutomationsSuppressedChip doc={null} />);
    expect(c1.firstChild).toBeNull();
    cleanup();
    const { container: c2 } = render(<AutomationsSuppressedChip doc={undefined} />);
    expect(c2.firstChild).toBeNull();
  });

  it("renders null on stray truthy values (strict ``=== true`` lock)", () => {
    // The chip MUST NOT fire on a backend writing the field as a
    // truthy string / number / etc.  Only an explicit ``true`` boolean
    // flips the chip.
    for (const stray of ["true", "yes", 1, "1", {}, []]) {
      cleanup();
      render(
        <AutomationsSuppressedChip doc={{ automations_suppressed: stray }} />,
      );
      expect(
        screen.queryByTestId("automations-suppressed-chip"),
      ).toBeNull();
    }
  });

  it("applies the warning tone styling (soft yellow background)", () => {
    render(<AutomationsSuppressedChip doc={{ automations_suppressed: true }} />);
    const chip = screen.getByTestId("automations-suppressed-chip");
    // The Chip ui-kit maps tone="warning" to bg "#FEF9C3" + fg
    // "#A16207".  Browsers normalize inline hex to ``rgb(...)`` on
    // render, so we compare against both the normalized form (the
    // actual DOM representation) and the source hex (what the
    // ui-kit palette map writes).  Snapshotting the resolved color
    // lets a future refactor of the chip palette fail LOUDLY if the
    // suppression chip accidentally flips to a different visual
    // family (e.g. danger-red would read as a hard error instead of
    // a muted operator advisory).
    const style = chip.getAttribute("style") || "";
    // Warning bg: #FEF9C3 == rgb(254, 249, 195)
    expect(style).toContain("rgb(254, 249, 195)");
    // Warning fg: #A16207 == rgb(161, 98, 7)
    expect(style).toContain("rgb(161, 98, 7)");
  });
});
