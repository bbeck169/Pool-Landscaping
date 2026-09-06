/**
 * Phase R0 · Feb-2026 — PeriodPicker component tests.
 *
 * Covers:
 *   1. Default state highlights the MTD preset.
 *   2. Clicking a preset emits ``{period: <key>}`` only.
 *   3. Clicking "Custom" reveals start/end inputs.
 *   4. Typing into the custom inputs emits ``{period, start, end}``.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { PeriodPicker } from "../components/reports/PeriodPicker";

describe("R0 · PeriodPicker", () => {
  it("marks the active preset via aria-pressed", () => {
    render(<PeriodPicker value={{ period: "mtd" }} onChange={() => {}} />);
    expect(screen.getByTestId("period-picker-preset-mtd").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("period-picker-preset-ytd").getAttribute("aria-pressed")).toBe("false");
  });

  it("emits {period} when a preset is clicked", () => {
    const onChange = vi.fn();
    render(<PeriodPicker value={{ period: "mtd" }} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("period-picker-preset-ytd"));
    expect(onChange).toHaveBeenCalledWith({ period: "ytd" });
  });

  it("hides custom inputs when active preset != custom", () => {
    render(<PeriodPicker value={{ period: "mtd" }} onChange={() => {}} />);
    expect(screen.queryByTestId("period-picker-start")).toBeNull();
    expect(screen.queryByTestId("period-picker-end")).toBeNull();
  });

  it("reveals custom inputs when the custom preset is clicked", () => {
    const onChange = vi.fn();
    const { rerender } = render(<PeriodPicker value={{ period: "mtd" }} onChange={onChange} />);
    fireEvent.click(screen.getByTestId("period-picker-preset-custom"));
    expect(onChange).toHaveBeenCalledWith({ period: "custom", start: "", end: "" });
    rerender(<PeriodPicker value={{ period: "custom" }} onChange={onChange} />);
    expect(screen.getByTestId("period-picker-start")).toBeTruthy();
    expect(screen.getByTestId("period-picker-end")).toBeTruthy();
  });

  it("emits {period, start, end} when custom start changes", () => {
    const onChange = vi.fn();
    render(<PeriodPicker value={{ period: "custom", start: "", end: "" }} onChange={onChange} />);
    fireEvent.change(screen.getByTestId("period-picker-start"), {
      target: { value: "2026-01-01" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      period: "custom", start: "2026-01-01", end: "",
    });
  });
});
