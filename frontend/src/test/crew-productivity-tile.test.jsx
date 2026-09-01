/**
 * Phase H5 · Feb-2026 — CrewProductivityTile tests.
 *
 * Full-render pattern (mirrors soshie-publishing-tile.test.jsx) —
 * mocks the api layer and drives the range dropdown to prove the
 * refetch + totals + click-through wiring.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockGet = vi.fn();
vi.mock("../api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(),
    put: vi.fn(),
    del: vi.fn(),
  },
}));

import CrewProductivityTile from "@/components/admin/CrewProductivityTile";

const renderTile = () =>
  render(<MemoryRouter><CrewProductivityTile /></MemoryRouter>);

const SAMPLE = {
  tenant_id: "aquaterra",
  range: "this_week",
  range_start: "2026-02-02T00:00:00+00:00",
  range_end: "2026-02-09T00:00:00+00:00",
  crews: [
    {
      crew_id: "crew-b",
      crew_name: "Blue Crew",
      color: "#0EA5E9",
      member_count: 3,
      jobs_completed: 5,
      revenue_subtotal: 4820.0,
      revenue_currency: "USD",
      avg_job_value: 964.0,
    },
    {
      crew_id: "crew-a",
      crew_name: "Alpha Crew",
      color: "#F97316",
      member_count: 2,
      jobs_completed: 3,
      revenue_subtotal: 1200.0,
      revenue_currency: "USD",
      avg_job_value: 400.0,
    },
  ],
  totals: { jobs_completed: 8, revenue_subtotal: 6020.0 },
};

beforeEach(() => {
  mockGet.mockReset();
});


describe("CrewProductivityTile", () => {
  it("renders the tile with server-sorted crews + totals footer",
     async () => {
    mockGet.mockResolvedValue(SAMPLE);
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("crew-productivity-tile")).toBeTruthy(),
    );
    // Server-sorted: Blue (top) then Alpha.
    const tbody = await screen.findByTestId("crew-productivity-tile-tbody");
    const rows = tbody.querySelectorAll("tr");
    expect(rows.length).toBe(2);
    // First row corresponds to Blue Crew.
    expect(rows[0].getAttribute("data-testid"))
      .toBe("crew-productivity-row-crew-b");
    expect(rows[1].getAttribute("data-testid"))
      .toBe("crew-productivity-row-crew-a");
    // Revenue formatting = USD 2-digit.
    expect(
      screen.getByTestId("crew-productivity-row-crew-b-revenue").textContent,
    ).toMatch(/\$4,820\.00/);
    expect(
      screen.getByTestId("crew-productivity-row-crew-a-revenue").textContent,
    ).toMatch(/\$1,200\.00/);
    // Footer totals match sum of rows (server-provided).
    expect(
      screen.getByTestId("crew-productivity-tile-totals-jobs").textContent,
    ).toMatch(/8/);
    expect(
      screen.getByTestId("crew-productivity-tile-totals-revenue").textContent,
    ).toMatch(/\$6,020\.00/);
  });

  it("range dropdown triggers a refetch with the new range param",
     async () => {
    // First fetch: this_week (default on mount)
    mockGet.mockResolvedValueOnce(SAMPLE);
    // Second fetch: last_week
    mockGet.mockResolvedValueOnce({
      ...SAMPLE,
      range: "last_week",
      crews: [],
      totals: { jobs_completed: 0, revenue_subtotal: 0 },
    });
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("crew-productivity-tile-title").textContent)
        .toMatch(/This Week/),
    );
    // Mount call inspection: /admin/crew-productivity?range=this_week
    expect(mockGet).toHaveBeenNthCalledWith(
      1,
      "/admin/crew-productivity?range=this_week",
    );
    // Flip to last_week.
    fireEvent.change(screen.getByTestId("crew-productivity-tile-range"),
                     { target: { value: "last_week" } });
    await waitFor(() =>
      expect(screen.getByTestId("crew-productivity-tile-title").textContent)
        .toMatch(/Last Week/),
    );
    expect(mockGet).toHaveBeenNthCalledWith(
      2,
      "/admin/crew-productivity?range=last_week",
    );
    // With zero crews the empty-state shows and the table hides.
    expect(screen.getByTestId("crew-productivity-tile-empty")).toBeTruthy();
    expect(screen.queryByTestId("crew-productivity-tile-table")).toBeNull();
  });

  it("empty-state text follows the current range label", async () => {
    mockGet.mockResolvedValue({
      tenant_id: "t",
      range: "this_month",
      range_start: "2026-02-01T00:00:00Z",
      range_end: "2026-03-01T00:00:00Z",
      crews: [],
      totals: { jobs_completed: 0, revenue_subtotal: 0 },
    });
    renderTile();
    // Change range so we render with month label context.
    await waitFor(() =>
      expect(screen.getByTestId("crew-productivity-tile-range")).toBeTruthy(),
    );
    fireEvent.change(screen.getByTestId("crew-productivity-tile-range"),
                     { target: { value: "this_month" } });
    await waitFor(() =>
      expect(screen.getByTestId("crew-productivity-tile-empty").textContent)
        .toMatch(/this month/i),
    );
  });

  it("row click-through builds a /schedule?crew=<id> URL (F6a round-trip)",
     async () => {
    mockGet.mockResolvedValue(SAMPLE);
    renderTile();
    const link = await screen.findByTestId(
      "crew-productivity-row-crew-b-schedule",
    );
    expect(link.getAttribute("href")).toBe("/schedule?crew=crew-b");
    const link2 = screen.getByTestId(
      "crew-productivity-row-crew-a-schedule",
    );
    expect(link2.getAttribute("href")).toBe("/schedule?crew=crew-a");
  });

  it("hides zero-revenue-zero-job crews so operators focus on movers",
     async () => {
    mockGet.mockResolvedValue({
      ...SAMPLE,
      crews: [
        ...SAMPLE.crews,
        {
          crew_id: "crew-z",
          crew_name: "Zombie Crew",
          color: "#666",
          member_count: 1,
          jobs_completed: 0,
          revenue_subtotal: 0,
          revenue_currency: "USD",
          avg_job_value: 0,
        },
      ],
    });
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("crew-productivity-tile-tbody")).toBeTruthy(),
    );
    expect(
      screen.queryByTestId("crew-productivity-row-crew-z"),
    ).toBeNull();
    // But server totals still flow through untouched (the tile
    // doesn't recompute totals client-side — the server is the
    // authoritative source per H5 spec).
    expect(
      screen.getByTestId("crew-productivity-tile-totals-jobs").textContent,
    ).toMatch(/8/);
  });

  it("renders a loading skeleton on initial fetch", async () => {
    // A never-resolving promise keeps the tile in the loading state
    // long enough for us to assert the skeleton.
    let resolve;
    mockGet.mockReturnValue(new Promise((r) => { resolve = r; }));
    renderTile();
    expect(
      screen.getByTestId("crew-productivity-tile-skeleton"),
    ).toBeTruthy();
    // Cleanup — resolve so the effect unwinds.
    resolve(SAMPLE);
  });

  it("shows an error banner when the endpoint fails", async () => {
    mockGet.mockRejectedValueOnce(new Error("boom"));
    renderTile();
    await waitFor(() =>
      expect(screen.getByTestId("crew-productivity-tile-error")).toBeTruthy(),
    );
    expect(
      screen.getByTestId("crew-productivity-tile-error").textContent,
    ).toMatch(/boom/);
  });
});
