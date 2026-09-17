/**
 * Feb-2026 · TeardropPin redesign · new visual + selected state.
 *
 * The base pin API stays backward-compatible (existing tests still
 * pass, see ``teardrop-pin.test.jsx`` +
 * ``phase-teardrop-pin-numbered-label.test.jsx``). This file locks
 * the NEW acceptance items:
 *   1. Default variant: glossy gradient body + soft drop shadow +
 *      ``data-color`` carries the flat hex.
 *   2. Selected variant: brighter ring, heavier shadow, scale
 *      transform on the body group.
 *   3. Labeled variant: white inner disc + dark-slate numeric text.
 *   4. Custom color variant: gradient stops derive from the input hex.
 *   5. ``aria-label`` includes the label when provided.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import TeardropPin, { mixWithWhite } from "@/components/maps/TeardropPin";


describe("TeardropPin · redesigned visual", () => {
  it("(1) default variant renders body + shadow + highlight", () => {
    render(<TeardropPin color="#3B82F6" testid="pin-default" />);
    const body = screen.getByTestId("pin-default-body");
    expect(body.getAttribute("data-color")).toBe("#3B82F6");
    expect(body.getAttribute("fill")).toMatch(/^url\(#td-grad-/);
    // Soft drop shadow ellipse under the tip.
    const shadow = screen.getByTestId("pin-default-shadow");
    expect(shadow.tagName.toLowerCase()).toBe("ellipse");
    // Glossy highlight circle sitting on the head.
    const highlight = screen.getByTestId("pin-default-highlight");
    expect(highlight.tagName.toLowerCase()).toBe("circle");
    // No selected transform on the default variant.
    const svg = screen.getByTestId("pin-default");
    expect(svg.getAttribute("data-selected")).toBe("false");
  });

  it("(2) selected variant applies a scale-up transform + brighter ring", () => {
    render(<TeardropPin color="#3B82F6" testid="pin-sel" selected />);
    const svg = screen.getByTestId("pin-sel");
    expect(svg.getAttribute("data-selected")).toBe("true");
    const group = screen.getByTestId("pin-sel-group");
    // Anchor-preserving scale-up.
    expect(group.getAttribute("transform"))
      .toContain("scale(1.10)");
    // Shadow ry grows on selected.
    const shadow = screen.getByTestId("pin-sel-shadow");
    expect(Number(shadow.getAttribute("ry"))).toBeGreaterThan(1.5);
    // Stroke thickens by 0.2 so the ring reads bolder.
    const body = screen.getByTestId("pin-sel-body");
    expect(body.getAttribute("stroke-width")).toBe("1.2");
  });

  it("(3) labeled variant renders the white inner disc + slate text", () => {
    render(<TeardropPin color="#0369A1" label={7} testid="pin-lbl" />);
    const disc = screen.getByTestId("pin-lbl-disc");
    expect(disc.tagName.toLowerCase()).toBe("circle");
    expect(disc.getAttribute("fill")).toBe("#FFFFFF");
    const text = screen.getByTestId("pin-lbl-label");
    expect(text.textContent).toBe("07");
    expect(text.getAttribute("fill")).toBe("#0F172A");
    // aria-label reflects the numeric label.
    const svg = screen.getByTestId("pin-lbl");
    expect(svg.getAttribute("aria-label")).toContain("07");
  });

  it("(4) custom color propagates into the gradient stops", () => {
    const custom = "#B45309";  // Amber-700, off-palette
    render(<TeardropPin color={custom} testid="pin-custom" />);
    const body = screen.getByTestId("pin-custom-body");
    expect(body.getAttribute("data-color")).toBe(custom);
    // The gradient's middle stop == the input hex verbatim.
    const svg = screen.getByTestId("pin-custom");
    const middle = svg.querySelector("stop[offset='0.55']");
    expect(middle).not.toBeNull();
    expect(middle.getAttribute("stop-color")).toBe(custom);
  });

  it("(5) mixWithWhite helper lightens + darkens by amount", () => {
    // +amt lightens.
    expect(mixWithWhite("#000000", 1.0)).toBe("#FFFFFF");
    expect(mixWithWhite("#3B82F6", 0.5)).not.toBe("#3B82F6");
    // -amt darkens.
    expect(mixWithWhite("#FFFFFF", -1.0)).toBe("#000000");
  });
});
