/**
 * Phase R0 · Feb-2026 — KpiCard component tests.
 *
 * Covers:
 *   1. Loading state renders a placeholder.
 *   2. Error state renders the error message.
 *   3. Data state renders formatted value + prior + signed delta.
 *   4. Delta chip tone flips based on ``direction`` prop.
 *   5. Sparkline renders when >= 2 points are supplied.
 *   6. Missing sparkline renders no chart.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { KpiCard } from "../components/reports/KpiCard";

describe("R0 · KpiCard", () => {
  it("renders loading placeholder", () => {
    render(<KpiCard label="Total Revenue" loading />);
    expect(screen.getByTestId("kpi-card-value").textContent).toContain("…");
  });

  it("renders error state when error prop is set", () => {
    render(
      <KpiCard label="Total Revenue" error="Network down" />,
    );
    expect(screen.getByTestId("kpi-card-value").textContent).toBe("Network down");
  });

  it("renders formatted currency value and prior", () => {
    render(
      <KpiCard
        label="Total Revenue"
        value={12345.67}
        priorValue={9876.54}
        deltaPct={25.0}
        format="currency"
      />,
    );
    expect(screen.getByTestId("kpi-card-label").textContent).toBe("Total Revenue");
    expect(screen.getByTestId("kpi-card-value").textContent).toBe("$12,345.67");
    expect(screen.getByTestId("kpi-card-prior").textContent).toContain("$9,876.54");
    expect(screen.getByTestId("kpi-card-delta").textContent).toBe("+25.0%");
  });

  it("delta chip is green when direction=up_is_good and delta > 0", () => {
    render(
      <KpiCard label="X" value={10} priorValue={5} deltaPct={100} direction="up_is_good" />,
    );
    const chip = screen.getByTestId("kpi-card-delta");
    // Success palette bg from theme.js is #DCFCE7.
    expect(chip.getAttribute("style")).toContain("rgb(220, 252, 231)");
  });

  it("delta chip is green when direction=down_is_good and delta < 0", () => {
    render(
      <KpiCard label="A/R aging" value={5} priorValue={10} deltaPct={-50} direction="down_is_good" />,
    );
    const chip = screen.getByTestId("kpi-card-delta");
    expect(chip.getAttribute("style")).toContain("rgb(220, 252, 231)");
  });

  it("delta chip is em-dash when deltaPct is null", () => {
    render(
      <KpiCard label="X" value={1} priorValue={0} deltaPct={null} />,
    );
    expect(screen.getByTestId("kpi-card-delta").textContent).toBe("—");
  });

  it("renders inline sparkline SVG for >= 2 points", () => {
    render(
      <KpiCard
        label="X"
        value={10}
        priorValue={5}
        deltaPct={100}
        format="number"
        sparkline={[{ t: "2026-02-01", v: 5 }, { t: "2026-02-02", v: 10 }]}
      />,
    );
    expect(screen.getByTestId("kpi-card-sparkline")).toBeTruthy();
  });

  it("does NOT render sparkline when 1 point is supplied (fallback message)", () => {
    render(
      <KpiCard
        label="X"
        value={10}
        priorValue={5}
        deltaPct={100}
        sparkline={[{ t: "2026-02-01", v: 5 }]}
      />,
    );
    expect(screen.getByTestId("kpi-card-sparkline-empty")).toBeTruthy();
  });
});
