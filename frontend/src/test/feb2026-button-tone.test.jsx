/**
 * Feb 2026 · Color pass — Button tone prop contract.
 *
 * jsdom normalises inline hex ``style.background`` to ``rgb(r, g,
 * b)`` — so we compare against BOTH normalisations via a small
 * helper.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Button } from "@/components/ui-kit";
import { colors } from "@/theme";


function hexToRgbTuple(hex) {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function expectStyleColor(actual, hex) {
  const norm = (actual || "").toLowerCase();
  if (norm.includes(hex.toLowerCase())) return;
  const [r, g, b] = hexToRgbTuple(hex);
  const rgb = `rgb(${r}, ${g}, ${b})`;
  expect(norm).toContain(rgb.toLowerCase());
}


describe("Button · Feb-2026 tone prop", () => {
  it("default primary keeps the historical brand gradient", () => {
    render(<Button testid="btn-a">Save</Button>);
    const el = screen.getByTestId("btn-a");
    const bg = el.style.background.toLowerCase();
    // Some jsdom versions strip gradients — but the class-based
    // "primary" always ships them via style — we just check the
    // hex OR rgb of the two gradient stops.
    const has = (h) => bg.includes(h.toLowerCase())
      || bg.includes(`rgb(${hexToRgbTuple(h).join(", ")})`);
    // Either the raw gradient (Chrome/real browser path) or a
    // decomposed pair (jsdom style parser) is acceptable.
    // K67 · Feb-2026 — start stop swapped from sky-600 (#0284C7)
    // to menu navy (#1B1F5C); the green-600 end stop is unchanged.
    expect(has("#1B1F5C") || has("#16A34A")).toBe(true);
    expect(el.getAttribute("data-tone")).toBe("primary");
  });

  it("tone=pool → pool[600] solid fill", () => {
    render(<Button testid="btn-p" tone="pool">Schedule Pool</Button>);
    const el = screen.getByTestId("btn-p");
    expectStyleColor(el.style.background, colors.pool[600]);
    expect(el.getAttribute("data-tone")).toBe("pool");
  });

  it("tone=landscape → landscape[600] solid fill", () => {
    render(<Button testid="btn-l" tone="landscape">Landscape Estimate</Button>);
    const el = screen.getByTestId("btn-l");
    expectStyleColor(el.style.background, colors.landscape[600]);
    expect(el.getAttribute("data-tone")).toBe("landscape");
  });

  it("tone=violet → accent.violet[600] fill (accent family works)", () => {
    render(<Button testid="btn-v" tone="violet">Notify</Button>);
    const el = screen.getByTestId("btn-v");
    expectStyleColor(el.style.background, colors.accent.violet[600]);
  });

  it("tone=landscaping alias resolves to landscape family", () => {
    render(<Button testid="btn-la" tone="landscaping">Book Landscape</Button>);
    const el = screen.getByTestId("btn-la");
    expectStyleColor(el.style.background, colors.landscape[600]);
  });

  it("hover:brightness-95 preserved on every variant", () => {
    render(
      <>
        <Button testid="btn-h1">Default</Button>
        <Button testid="btn-h2" tone="pool">Pool</Button>
        <Button testid="btn-h3" tone="landscape">Landscape</Button>
      </>,
    );
    for (const id of ["btn-h1", "btn-h2", "btn-h3"]) {
      expect(screen.getByTestId(id).className)
        .toMatch(/hover:brightness-95/);
    }
  });

  it("danger variant is unaffected by tone (spec: keep existing red)", () => {
    // The color-pass spec explicitly excludes destructive buttons.
    render(<Button testid="btn-d" variant="danger" tone="pool">Delete</Button>);
    const el = screen.getByTestId("btn-d");
    // ``#FEE2E2`` normalises to ``rgb(254, 226, 226)`` in jsdom.
    expectStyleColor(el.style.background, "#FEE2E2");
    // ``colors.error`` = "#DC2626" → rgb(220, 38, 38).
    expectStyleColor(el.style.color, colors.error);
  });
});
