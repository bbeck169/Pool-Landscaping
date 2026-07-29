/**
 * Revenue tiles + shared date-range filter · Feb-2026 · Vitest.
 *
 * Covers:
 *   1. RevenueByCategoryTile fetches on range and renders legend items.
 *   2. RevenueForecastTile renders the combined total prominently.
 *   3. Filter preset change triggers a re-fetch with new range.
 *   4. Custom range picker triggers a re-fetch with the selected dates.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a), post: vi.fn(), patch: vi.fn() },
}));

// Recharts uses ResizeObserver — jsdom lacks it, we polyfill.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}

beforeEach(() => {
  getSpy.mockReset();
  try { localStorage.clear(); } catch { /* ignore */ }
});
afterEach(() => cleanup());

import RevenueByCategoryTile from "@/components/dashboard/RevenueByCategoryTile";
import RevenueForecastTile from "@/components/dashboard/RevenueForecastTile";
import RevenueDateRangeFilter from "@/components/dashboard/RevenueDateRangeFilter";

describe("RevenueByCategoryTile", () => {
  it("fetches on range change and renders legend rows", async () => {
    getSpy.mockResolvedValue({
      items: [
        { category: "Pool",      amount: 300, count: 3, color: "#aaa" },
        { category: "Chem",      amount: 150, count: 1, color: "#bbb" },
      ],
      total: 450, currency: "USD",
    });
    render(<RevenueByCategoryTile
              range={{ start: "2026-02-01", end: "2026-02-28" }} />);
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(1));
    expect(getSpy.mock.calls[0][0]).toContain(
      "/admin/dashboard/revenue-by-category?start=2026-02-01&end=2026-02-28");
    await waitFor(() => screen.getByTestId("revenue-cat-legend"));
    expect(screen.getByTestId("revenue-cat-legend-Pool")).toBeTruthy();
    expect(screen.getByTestId("revenue-cat-legend-Chem")).toBeTruthy();
    expect(screen.getByTestId("revenue-cat-item-count").textContent)
      .toContain("2 categories");
  });
});

describe("RevenueForecastTile", () => {
  it("renders combined total prominently and the caption", async () => {
    getSpy.mockResolvedValue({
      booked: { amount: 500, job_count: 3 },
      recurring: { amount: 200, subscription_count: 2, cycle_count: 4 },
      combined_total: 700, currency: "USD",
    });
    render(<RevenueForecastTile
              range={{ start: "2026-02-01", end: "2026-02-28" }} />);
    await waitFor(() => screen.getByTestId("revenue-forecast-combined"));
    expect(screen.getByTestId("revenue-forecast-combined").textContent)
      .toMatch(/700/);
    const cap = screen.getByTestId("revenue-forecast-caption").textContent;
    expect(cap).toContain("3 booked jobs");
    expect(cap).toContain("2 active subscriptions");
    expect(cap).toContain("4 billing cycles");
  });
});

describe("RevenueDateRangeFilter", () => {
  it("emits a range on mount and on preset change", async () => {
    const onChange = vi.fn();
    render(<RevenueDateRangeFilter onChange={onChange} />);
    // Emits once on mount (this_month default).
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange.mock.calls[0][0].preset).toBe("this_month");
    // Open popover, pick "Today".
    fireEvent.click(screen.getByTestId("revenue-range-toggle"));
    fireEvent.click(screen.getByTestId("revenue-range-preset-today"));
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
    expect(onChange.mock.calls[1][0].preset).toBe("today");
    expect(onChange.mock.calls[1][0].start).toBe(onChange.mock.calls[1][0].end);
  });

  it("Custom Range picker triggers re-fetch with selected dates", async () => {
    const onChange = vi.fn();
    render(<RevenueDateRangeFilter onChange={onChange} />);
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("revenue-range-toggle"));
    fireEvent.click(screen.getByTestId("revenue-range-preset-custom"));
    // Set start + end.
    fireEvent.change(screen.getByTestId("revenue-range-custom-start"), {
      target: { value: "2026-05-01" },
    });
    fireEvent.change(screen.getByTestId("revenue-range-custom-end"), {
      target: { value: "2026-05-31" },
    });
    fireEvent.click(screen.getByTestId("revenue-range-custom-apply"));
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(last.preset).toBe("custom");
    expect(last.start).toBe("2026-05-01");
    expect(last.end).toBe("2026-05-31");
  });
});
