/**
 * Feb-2026 · Monthly recurrence pattern label rename.
 *
 * Locks the "Nth weekday" → **Custom Weekdays** label rename on
 * the shared ``MonthlyNthWeekdaySelector`` (used by both
 * ``/admin/recurring-jobs`` and ``/jobs/new``). The wire enum
 * (``monthly_pattern === "nth_weekday"``) is unchanged — only
 * the human-facing button text moved. Testid also unchanged so
 * downstream automation stays green.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F", onBrand: "#FFFFFF", onSurface: "#111827",
    muted: "#6B7280", border: "#E5E7EB", surface: "#FFFFFF",
  },
}));

import { MonthlyNthWeekdaySelector } from
  "@/components/recurring/MonthlyNthWeekdaySelector";

describe("MonthlyNthWeekdaySelector · Custom Weekdays label", () => {
  it("renders 'Custom Weekdays' (not 'Nth weekday') on the pattern pill", () => {
    render(
      <MonthlyNthWeekdaySelector
        value={{ monthly_pattern: "day_of_month" }}
        onChange={() => {}}
      />,
    );
    const btn = screen.getByTestId("monthly-nth-pattern-nth_weekday");
    expect(btn.textContent.trim()).toBe("Custom Weekdays");
    // Guardrail — old label should be gone entirely from the pill.
    expect(btn.textContent).not.toMatch(/Nth weekday/);
  });

  it("Same day each month sibling pill is unchanged", () => {
    render(
      <MonthlyNthWeekdaySelector
        value={{ monthly_pattern: "day_of_month" }}
        onChange={() => {}}
      />,
    );
    const btn = screen.getByTestId("monthly-nth-pattern-day_of_month");
    expect(btn.textContent.trim()).toBe("Same day each month");
  });
});
