/**
 * Phase R0 · Feb-2026 — Reporting formatters unit tests.
 */
import { describe, it, expect } from "vitest";
import {
  formatCurrency,
  formatNumber,
  formatPercent,
  formatDelta,
  formatValue,
} from "../components/reports/formatters";

describe("R0 · formatters", () => {
  it("formats currency with two decimals", () => {
    expect(formatCurrency(1234.5)).toBe("$1,234.50");
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("returns em-dash for null/undefined/NaN", () => {
    expect(formatCurrency(null)).toBe("—");
    expect(formatCurrency(undefined)).toBe("—");
    expect(formatCurrency(NaN)).toBe("—");
    expect(formatNumber(null)).toBe("—");
    expect(formatPercent(null)).toBe("—");
    expect(formatDelta(null)).toBe("—");
  });

  it("compact currency uses k/M/B suffix", () => {
    expect(formatCurrency(1500, { compact: true })).toBe("$1.5k");
    expect(formatCurrency(2_500_000, { compact: true })).toBe("$2.5M");
    expect(formatCurrency(1_000_000_000, { compact: true })).toBe("$1B");
  });

  it("formats integer numbers with thousand separators", () => {
    expect(formatNumber(1234)).toBe("1,234");
    expect(formatNumber(1234.5)).toBe("1,234.50");
  });

  it("formats percent with configurable decimals and sign", () => {
    expect(formatPercent(25)).toBe("25.0%");
    expect(formatPercent(0.25, { fractional: true })).toBe("25.0%");
    expect(formatPercent(25, { signed: true })).toBe("+25.0%");
    expect(formatPercent(-3.14, { decimals: 2 })).toBe("-3.14%");
  });

  it("formats delta with sign", () => {
    expect(formatDelta(12.4)).toBe("+12.4%");
    expect(formatDelta(-3)).toBe("-3.0%");
  });

  it("routes formatValue by format prop", () => {
    expect(formatValue(1500, "currency")).toBe("$1,500.00");
    expect(formatValue(25, "percent")).toBe("25.0%");
    expect(formatValue(42, "number")).toBe("42");
  });
});
