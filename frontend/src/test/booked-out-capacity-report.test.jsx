/**
 * Feb-2026 · Phase 5b.2 — Booked Out / Capacity · FE tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import BookedOutCapacityReport from "@/pages/reports/BookedOutCapacityReport";

const _env = ({ weeks = 8, firstAvail = "2026-W12" } = {}) => ({
  summary: {
    weekly_capacity_hours: 80,
    total_booked_hours: 200,
    avg_weekly_utilization_pct: 30,
    first_available_week: firstAvail,
  },
  rows: Array.from({ length: weeks }, (_, i) => ({
    week_start: `2026-03-${(i * 7 + 1).toString().padStart(2, "0")}`,
    week_end: `2026-03-${(i * 7 + 7).toString().padStart(2, "0")}`,
    booked_hours: i === 0 ? 100 : 20,
    capacity_hours: 80,
    utilization_pct: i === 0 ? 125 : 25,
    jobs_count: i === 0 ? 1 : 1,
  })),
  chart: { weekly_bookings: Array.from({ length: weeks }, (_, i) => ({
    week_label: i === 0 ? "This week" : `+${i} weeks`,
    week_start: `2026-03-${(i * 7 + 1).toString().padStart(2, "0")}`,
    booked_hours: i === 0 ? 100 : 20,
    capacity_hours: 80,
  })) },
});

const _render = () => render(<MemoryRouter>
  <BookedOutCapacityReport />
</MemoryRouter>);

describe("BookedOutCapacityReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders 4 tiles + bar chart + capacity line + rows", async () => {
    api.get.mockResolvedValueOnce(_env());
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-capacity-primary").textContent)
        .toMatch(/80h/));
    expect(screen.getByTestId("tile-booked-primary").textContent).toMatch(/200h/);
    expect(screen.getByTestId("tile-util-primary").textContent).toMatch(/30%/);
    expect(screen.getByTestId("tile-first-available-primary").textContent)
      .toMatch(/2026-W12/);
    // Capacity line is drawn.
    expect(screen.getByTestId("boc-capacity-line")).toBeDefined();
    // First bar is "This week".
    expect(screen.getByTestId("boc-bar-This-week")).toBeDefined();
    // Weeks-picker default 8 fired the initial request.
    expect(api.get).toHaveBeenCalledWith(
      "/reports/booked-out-capacity?weeks_ahead=8");
  });

  it("re-fetches when the weeks-ahead quick-pick changes", async () => {
    api.get.mockResolvedValueOnce(_env());
    api.get.mockResolvedValueOnce(_env({ weeks: 4 }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("boc-report-tiles")).toBeDefined());
    // Change to 4-week view.
    fireEvent.click(screen.getByTestId("boc-weeks-4"));
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(
        "/reports/booked-out-capacity?weeks_ahead=4"));
  });

  it("renders 'None' first-available when schedule is fully booked", async () => {
    api.get.mockResolvedValueOnce(_env({ firstAvail: null }));
    _render();
    await waitFor(() =>
      expect(screen.getByTestId("tile-first-available-primary").textContent)
        .toMatch(/None/));
  });
});
