/**
 * Phase R0 · Feb-2026 — VarianceTile component tests.
 *
 * Covers the Datarails-signature tone-mapping:
 *   1. Positive delta + up_is_good → green stripe + ▲.
 *   2. Positive delta + down_is_good → red stripe + ▲ (bad).
 *   3. Negative delta + down_is_good → green stripe + ▼ (good).
 *   4. Null delta → neutral flat stripe + ▬ + em-dash label.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { VarianceTile } from "../components/reports/VarianceTile";

describe("R0 · VarianceTile", () => {
  it("green stripe when up_is_good and delta > 0", () => {
    render(
      <VarianceTile
        label="Revenue"
        current={100}
        prior={80}
        deltaPct={25}
        format="currency"
        direction="up_is_good"
      />,
    );
    expect(screen.getByTestId("variance-tile-stripe-up")).toBeTruthy();
    expect(screen.getByTestId("variance-tile-delta").textContent).toContain("+25.0%");
  });

  it("red stripe when up_is_good and delta < 0", () => {
    render(
      <VarianceTile
        label="Revenue"
        current={80}
        prior={100}
        deltaPct={-20}
      />,
    );
    expect(screen.getByTestId("variance-tile-stripe-down")).toBeTruthy();
    expect(screen.getByTestId("variance-tile-delta").textContent).toContain("-20.0%");
  });

  it("green stripe when down_is_good and delta < 0", () => {
    render(
      <VarianceTile
        label="Overdue invoices"
        current={5}
        prior={10}
        deltaPct={-50}
        direction="down_is_good"
      />,
    );
    expect(screen.getByTestId("variance-tile-stripe-up")).toBeTruthy();
  });

  it("neutral stripe + em-dash when delta is null", () => {
    render(
      <VarianceTile
        label="X"
        current={1}
        prior={0}
        deltaPct={null}
      />,
    );
    expect(screen.getByTestId("variance-tile-stripe-flat")).toBeTruthy();
    expect(screen.getByTestId("variance-tile-delta").textContent).toContain("—");
  });

  it("renders formatted current + prior values", () => {
    render(
      <VarianceTile
        label="Revenue"
        current={12345.67}
        prior={9876.54}
        deltaPct={25}
        format="currency"
      />,
    );
    expect(screen.getByTestId("variance-tile-current").textContent).toBe("$12,345.67");
    expect(screen.getByTestId("variance-tile-prior").textContent).toContain("$9,876.54");
  });
});
