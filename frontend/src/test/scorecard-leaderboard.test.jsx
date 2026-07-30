// Phase G5d · Feb-2026 — Driver Scorecard page vitest.
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _board = {
  range: { from: "2026-02-09T00:00:00Z", to: "2026-02-14T23:59:59Z",
            label: "This Week" },
  rows: [
    { user_id: "u-1", user_name: "Ana Rodriguez",
      role: "technician", department: "north",
      score: 88, rank: 1,
      metrics: { stops_count: 34, avg_stop_duration_s: 1800,
                 total_stopped_time_s: 61200, total_driving_time_s: 21600,
                 total_pings_count: 250, unique_jobs_attributed: 12,
                 unique_customers_attributed: 10,
                 on_time_arrival_rate: 0.94, estimated_miles: 145.3,
                 days_active: 5, attribution_coverage: 0.94,
                 idle_penalty: 0 } },
    { user_id: "u-2", user_name: "Ben Miller",
      role: "technician", department: "south",
      score: 62, rank: 2,
      metrics: { stops_count: 18, avg_stop_duration_s: 2100,
                 total_stopped_time_s: 37800, total_driving_time_s: 14400,
                 total_pings_count: 180, unique_jobs_attributed: 5,
                 unique_customers_attributed: 4,
                 on_time_arrival_rate: 0.6, estimated_miles: 88.1,
                 days_active: 4, attribution_coverage: 0.72,
                 idle_penalty: 0 } },
  ],
};

const _detail = {
  range: _board.range,
  row: { ..._board.rows[0] },
  trend: Array.from({ length: 8 }).map((_, i) => ({
    week_start: `2026-01-${String(5 + i * 7).padStart(2, "0")}`,
    score: 70 + i * 2,
  })),
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (p) => {
      if (p.startsWith("/admin/gps/scorecard/leaderboard")) return _board;
      if (p.startsWith("/admin/gps/scorecard/user/"))        return _detail;
      return {};
    }),
    post: vi.fn(), patch: vi.fn(), del: vi.fn(),
  },
  TOKEN_KEY: "auth_token",
  api_base: () => "http://mock",
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

// Guard recharts from choking on 0x0 layouts in jsdom.
vi.mock("recharts", async () => {
  const actual = await vi.importActual("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }) =>
      <div style={{ width: 300, height: 140 }}
           data-testid="mock-responsive">{children}</div>,
  };
});

import DriverScorecardPage from "@/pages/admin/DriverScorecardPage";
import { api } from "@/api";

describe("DriverScorecardPage · G5d", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders leaderboard rows in rank order with score badges", async () => {
    render(<MemoryRouter><DriverScorecardPage /></MemoryRouter>);
    expect(await screen.findByTestId("scorecard-title")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("scorecard-row-u-1")).toBeInTheDocument();
      expect(screen.getByTestId("scorecard-row-u-2")).toBeInTheDocument();
      expect(screen.getByTestId("scorecard-score-u-1")).toHaveTextContent("88");
      expect(screen.getByTestId("scorecard-score-u-2")).toHaveTextContent("62");
    });
  });

  it("range dropdown refetches with the new range", async () => {
    render(<MemoryRouter><DriverScorecardPage /></MemoryRouter>);
    await screen.findByTestId("scorecard-title");
    fireEvent.change(screen.getByTestId("scorecard-range"),
                      { target: { value: "last_week" } });
    await waitFor(() => {
      const calls = api.get.mock.calls
        .filter((c) => c[0].startsWith("/admin/gps/scorecard/leaderboard")
                        && c[0].includes("range=last_week"));
      expect(calls.length).toBeGreaterThan(0);
    });
  });

  it("row click opens detail drawer with trend chart + metrics", async () => {
    render(<MemoryRouter><DriverScorecardPage /></MemoryRouter>);
    fireEvent.click(await screen.findByTestId("scorecard-row-u-1"));
    expect(await screen.findByTestId("scorecard-detail-drawer"))
      .toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("scorecard-detail-name"))
        .toHaveTextContent(/Ana Rodriguez/);
      expect(screen.getByTestId("scorecard-gauge")).toBeInTheDocument();
      expect(screen.getByTestId("scorecard-trend-chart")).toBeInTheDocument();
      expect(screen.getByTestId("scorecard-detail-metrics"))
        .toBeInTheDocument();
    });
  });

  it("department filter refetches with the department param", async () => {
    render(<MemoryRouter><DriverScorecardPage /></MemoryRouter>);
    await screen.findByTestId("scorecard-title");
    fireEvent.change(screen.getByTestId("scorecard-department"),
                      { target: { value: "north" } });
    await waitFor(() => {
      const calls = api.get.mock.calls
        .filter((c) => c[0].startsWith("/admin/gps/scorecard/leaderboard")
                        && c[0].includes("department=north"));
      expect(calls.length).toBeGreaterThan(0);
    });
  });

  it("empty rows show the empty state", async () => {
    api.get.mockImplementationOnce(async () => ({
      range: _board.range, rows: [],
    }));
    render(<MemoryRouter><DriverScorecardPage /></MemoryRouter>);
    expect(await screen.findByTestId("scorecard-empty")).toBeInTheDocument();
  });

  it("Custom range reveals date inputs and fires the endpoint with from/to", async () => {
    render(<MemoryRouter><DriverScorecardPage /></MemoryRouter>);
    await screen.findByTestId("scorecard-title");
    fireEvent.change(screen.getByTestId("scorecard-range"),
                      { target: { value: "custom" } });
    // Custom date-inputs revealed.
    const fromEl = await screen.findByTestId("scorecard-custom-from");
    const toEl   = await screen.findByTestId("scorecard-custom-to");
    expect(fromEl).toBeInTheDocument();
    expect(toEl).toBeInTheDocument();
    // Set both dates.
    fireEvent.change(fromEl, { target: { value: "2026-02-01" } });
    fireEvent.change(toEl,   { target: { value: "2026-02-14" } });
    await waitFor(() => {
      const calls = api.get.mock.calls
        .filter((c) => c[0].startsWith("/admin/gps/scorecard/leaderboard")
                        && c[0].includes("range=custom")
                        && c[0].includes("from=2026-02-01T00%3A00%3A00Z")
                        && c[0].includes("to=2026-02-14T23%3A59%3A59Z"));
      expect(calls.length).toBeGreaterThan(0);
    });
    // Invalid range (from > to) shows inline error and does NOT refetch.
    api.get.mockClear();
    fireEvent.change(fromEl, { target: { value: "2026-03-01" } });
    expect(await screen.findByTestId("scorecard-custom-error"))
      .toBeInTheDocument();
    expect(api.get.mock.calls.filter(
      (c) => c[0].startsWith("/admin/gps/scorecard/leaderboard")).length)
      .toBe(0);
  });
});
