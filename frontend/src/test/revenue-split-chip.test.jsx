/**
 * Feb 2026 · Batch 2 — RevenueSplitChip component tests.
 *
 * Covers the four cases briefed:
 *   a) 60/40 pool vs landscape
 *   b) 100% pool
 *   c) 100% landscape
 *   d) all zeros (empty state)
 * Plus a mixed-bucket rendering case (three segments) and a
 * ``<1%`` percentage-honesty guard.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import RevenueSplitChip from "../components/dashboard/RevenueSplitChip";

describe("Task Batch 2 · RevenueSplitChip", () => {
  it("(a) 60% pool + 40% landscape — renders both segments with correct labels", () => {
    render(<RevenueSplitChip pool={600} landscape={400} mixed={0} />);
    const chip = screen.getByTestId("revenue-split-chip");
    expect(chip).toBeTruthy();
    // Two segments — pool + landscape; no mixed segment.
    expect(screen.getByTestId("revenue-split-segment-pool")).toBeTruthy();
    expect(screen.getByTestId("revenue-split-segment-landscape")).toBeTruthy();
    expect(screen.queryByTestId("revenue-split-segment-mixed")).toBeNull();
    // Legend shows both labels with money + percent.
    const poolLegend = screen.getByTestId("revenue-split-legend-pool");
    expect(poolLegend.textContent).toMatch(/Pool/);
    expect(poolLegend.textContent).toMatch(/60%/);
    const landLegend = screen.getByTestId("revenue-split-legend-landscape");
    expect(landLegend.textContent).toMatch(/Landscape/);
    expect(landLegend.textContent).toMatch(/40%/);
  });

  it("(b) 100% pool — single pool segment; no landscape segment", () => {
    render(<RevenueSplitChip pool={1000} landscape={0} mixed={0} />);
    expect(screen.getByTestId("revenue-split-segment-pool")).toBeTruthy();
    expect(screen.queryByTestId("revenue-split-segment-landscape")).toBeNull();
    expect(screen.queryByTestId("revenue-split-segment-mixed")).toBeNull();
    expect(
      screen.getByTestId("revenue-split-segment-pool").textContent,
    ).toMatch(/100%/);
  });

  it("(c) 100% landscape — single landscape segment; no pool segment", () => {
    render(<RevenueSplitChip pool={0} landscape={1500} mixed={0} />);
    expect(
      screen.queryByTestId("revenue-split-segment-pool"),
    ).toBeNull();
    expect(screen.getByTestId("revenue-split-segment-landscape")).toBeTruthy();
    expect(
      screen.getByTestId("revenue-split-segment-landscape").textContent,
    ).toMatch(/100%/);
  });

  it("(d) all zeros — renders the empty state, not the chip", () => {
    render(<RevenueSplitChip pool={0} landscape={0} mixed={0} />);
    expect(screen.queryByTestId("revenue-split-chip")).toBeNull();
    const empty = screen.getByTestId("revenue-split-chip-empty");
    expect(empty.textContent).toMatch(/no revenue this period/i);
  });

  it("mixed segment renders when mixed > 0 (three-segment case)", () => {
    render(<RevenueSplitChip pool={300} landscape={400} mixed={300} />);
    expect(screen.getByTestId("revenue-split-segment-pool")).toBeTruthy();
    expect(screen.getByTestId("revenue-split-segment-landscape")).toBeTruthy();
    expect(screen.getByTestId("revenue-split-segment-mixed")).toBeTruthy();
    expect(screen.getByTestId("revenue-split-legend-mixed").textContent)
      .toMatch(/Mixed/);
  });

  it("shows ``<1%`` for a non-zero segment below 1% instead of ``0%``", () => {
    // Pool = 3, landscape = 997 → pool ~0.3% → Math.round → 0
    // → display must show as ``<1%`` (honest, not 0%).
    render(<RevenueSplitChip pool={3} landscape={997} mixed={0} />);
    const poolSeg = screen.getByTestId("revenue-split-segment-pool");
    expect(poolSeg.textContent).toMatch(/<1%/);
    expect(poolSeg.textContent).not.toMatch(/^0%/);
    // Small segment still renders visibly — width has a 4% floor.
    expect(poolSeg.getAttribute("style")).toMatch(/width:\s*4%/);
  });

  it("undefined props are treated as 0 (defensive)", () => {
    render(<RevenueSplitChip />);
    expect(screen.getByTestId("revenue-split-chip-empty")).toBeTruthy();
  });
});
