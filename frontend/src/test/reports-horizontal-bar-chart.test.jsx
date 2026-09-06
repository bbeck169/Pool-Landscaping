/**
 * Phase R0.1 · Feb-2026 — HorizontalBarChart tests.
 *
 * Covers:
 *   1. Empty data renders the "No data" placeholder.
 *   2. Populated data mounts the react-apexcharts <Chart> stub.
 *   3. Custom testid propagates to the root and empty state.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

vi.mock("react-apexcharts", () => ({
  __esModule: true,
  default: (props) =>
    React.createElement("div", {
      "data-testid": "apex-stub",
      "data-series-len": String(props?.series?.[0]?.data?.length ?? 0),
    }),
}));

import { HorizontalBarChart } from "../components/reports/HorizontalBarChart";

describe("R0.1 · HorizontalBarChart", () => {
  it("renders an empty placeholder when data is []", () => {
    render(<HorizontalBarChart data={[]} testid="chart" />);
    expect(screen.getByTestId("chart")).toBeTruthy();
    expect(screen.getByTestId("chart-empty").textContent).toContain("No data");
  });

  it("mounts the apex chart when data is provided", () => {
    render(
      <HorizontalBarChart
        data={[{ label: "A", value: 10 }, { label: "B", value: 20 }]}
        testid="chart"
      />
    );
    const stub = screen.getByTestId("apex-stub");
    expect(stub).toBeTruthy();
    expect(stub.getAttribute("data-series-len")).toBe("2");
  });

  it("uses the default testid when none is provided", () => {
    render(<HorizontalBarChart data={[]} />);
    expect(screen.getByTestId("horizontal-bar-chart")).toBeTruthy();
  });
});
