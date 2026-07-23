/**
 * Feb-2026 · Enhancement 2 — Revenue Forecast filter chips (vitest).
 *
 * Verifies preset chips render + toggle, custom-range date picker
 * appears, and each change refetches the forecast endpoint with
 * the correct query params. Also verifies ``localStorage`` persistence.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// Mock recharts — its ResponsiveContainer needs measured DOM.
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  AreaChart: ({ children }) => <div data-testid="area-chart">{children}</div>,
  Area: () => null, XAxis: () => null, YAxis: () => null,
  CartesianGrid: () => null, Tooltip: () => null,
}));

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));
vi.mock("@/api", () => ({ api: { get: apiGetMock } }));

import Forecast from "@/pages/reports/Forecast";

beforeEach(() => {
  try { localStorage.clear(); } catch { /* jsdom */ }
  apiGetMock.mockReset();
  apiGetMock.mockImplementation((path) => {
    if (path.startsWith("/reports/forecast-cards")) {
      return Promise.resolve({
        pipeline_value: 100, weighted_forecast: 60,
        monthly_recurring: 4200, forecast_total_90d: 12000,
      });
    }
    if (path.startsWith("/reports/forecast")) {
      return Promise.resolve({
        series: [{ week: "2026-02-19", date: "2026-02-19", amount: 500 }],
        total: 500, range: "today",
        date_from: "2026-02-19", date_to: "2026-02-19",
      });
    }
    return Promise.resolve({});
  });
});

describe("Forecast filter chips", () => {
  it("renders every preset chip + default days chip", async () => {
    render(<MemoryRouter><Forecast /></MemoryRouter>);
    await screen.findByTestId("forecast-page");
    for (const key of ["today", "tomorrow", "week", "month", "custom"]) {
      expect(screen.getByTestId(`forecast-range-${key}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("forecast-range-default")).toBeInTheDocument();
  });

  it("clicking a preset calls the forecast endpoint with range param + persists to localStorage", async () => {
    render(<MemoryRouter><Forecast /></MemoryRouter>);
    await screen.findByTestId("forecast-page");
    fireEvent.click(screen.getByTestId("forecast-range-week"));
    await waitFor(() => expect(apiGetMock).toHaveBeenCalledWith(
      "/reports/forecast?range=week",
    ));
    expect(localStorage.getItem("revenueForecast.range")).toBe("week");
    fireEvent.click(screen.getByTestId("forecast-range-month"));
    await waitFor(() => expect(apiGetMock).toHaveBeenCalledWith(
      "/reports/forecast?range=month",
    ));
    expect(localStorage.getItem("revenueForecast.range")).toBe("month");
  });

  it("custom range surfaces the date pickers + only fires with both dates", async () => {
    render(<MemoryRouter><Forecast /></MemoryRouter>);
    await screen.findByTestId("forecast-page");
    apiGetMock.mockClear();
    fireEvent.click(screen.getByTestId("forecast-range-custom"));
    expect(await screen.findByTestId("forecast-custom-range")).toBeInTheDocument();
    // Filling only one date does NOT trigger a fetch yet.
    fireEvent.change(screen.getByTestId("forecast-custom-from"),
                      { target: { value: "2026-02-01" } });
    // Only forecast-cards may have been called at mount — no new /forecast?range=custom.
    const rangeCustomCalls = apiGetMock.mock.calls.filter(
      (c) => String(c[0]).includes("range=custom"));
    expect(rangeCustomCalls.length).toBe(0);
    // Fill the second date → fetch fires.
    fireEvent.change(screen.getByTestId("forecast-custom-to"),
                      { target: { value: "2026-02-07" } });
    await waitFor(() => expect(apiGetMock).toHaveBeenCalledWith(
      "/reports/forecast?range=custom&date_from=2026-02-01&date_to=2026-02-07",
    ));
  });
});
