/**
 * Phase R0.1+ · Feb-2026 — DeltaCell tone selection.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { DeltaCell } from "../components/reports/DeltaCell";


describe("R0.1+ · DeltaCell", () => {
  it("renders the 'New' pill when prior is 0 and current > 0", () => {
    render(
      <DeltaCell deltaAbs={500} deltaPct={null} priorRevenue={0}
                    testid="dc" />,
    );
    expect(screen.getByTestId("dc").getAttribute("data-tone")).toBe("new");
    expect(screen.getByTestId("dc").textContent).toBe("New");
  });

  it("renders neutral em-dash when deltaAbs is 0", () => {
    render(
      <DeltaCell deltaAbs={0} deltaPct={0} priorRevenue={100}
                    testid="dc" />,
    );
    expect(screen.getByTestId("dc").getAttribute("data-tone")).toBe("neutral");
    expect(screen.getByTestId("dc").textContent).toBe("—");
  });

  it("renders neutral em-dash when deltaAbs is null", () => {
    render(
      <DeltaCell deltaAbs={null} deltaPct={null} priorRevenue={100}
                    testid="dc" />,
    );
    expect(screen.getByTestId("dc").getAttribute("data-tone")).toBe("neutral");
    expect(screen.getByTestId("dc").textContent).toBe("—");
  });

  it("uses 'up' tone when delta is positive", () => {
    render(
      <DeltaCell deltaAbs={150} deltaPct={30} priorRevenue={500}
                    testid="dc" />,
    );
    expect(screen.getByTestId("dc").getAttribute("data-tone")).toBe("up");
    expect(screen.getByTestId("dc").textContent).toContain("+");
    expect(screen.getByTestId("dc-pct").textContent).toBe("+30.0%");
  });

  it("uses 'down' tone when delta is negative", () => {
    render(
      <DeltaCell deltaAbs={-75} deltaPct={-15} priorRevenue={500}
                    testid="dc" />,
    );
    expect(screen.getByTestId("dc").getAttribute("data-tone")).toBe("down");
    expect(screen.getByTestId("dc-pct").textContent).toBe("-15.0%");
  });

  it("skips the pct row when delta_pct is null (baseline was 0)", () => {
    render(
      <DeltaCell deltaAbs={200} deltaPct={null} priorRevenue={0}
                    testid="dc" />,
    );
    // ``New`` branch fires first when priorRevenue == 0.
    expect(screen.getByTestId("dc").getAttribute("data-tone")).toBe("new");
  });
});
