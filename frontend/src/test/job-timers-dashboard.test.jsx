/**
 * Feb-2026 · Job Timers dashboard phase — page smoke test.
 *
 * Cases:
 *   1. Page mounts with SummaryCard showing all 5 metrics
 *      (avg / count / min / max / median) fed by
 *      ``/job-timers/summary``. Filter testids also render.
 *   2. Pagination footer is ALWAYS mounted (prev/next buttons
 *      visible even with a single-page result).
 *   3. ``?t=avgtime`` deep-link adds ``aria-current="true"`` to
 *      the avg summary tile.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

let _summaryResp = {
  avg_seconds: 1800, count: 5,
  min_seconds: 600, max_seconds: 3000,
  median_seconds: 1200,
};
let _listResp = {
  items: [
    { id: "t-1", started_at: "2026-02-14T15:00:00Z",
      ended_at: "2026-02-14T15:30:00Z",
      duration_seconds: 1800,
      technician_id: "tech-1", technician_name: "Ana Smith",
      tech_id: "tech-1", tech_name: "Ana Smith",
      job_id: "job-1", job_title: "Weekly Pool", customer_name: "Alice",
      start_source: "gps_arrival", end_source: "job_completed",
      source: "gps_arrival", entity_type: "tech",
    },
  ],
  count: 1, page: 1, page_size: 25, total: 1, total_pages: 1,
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/job-timers/summary")) return _summaryResp;
      if (path.startsWith("/job-timers/aggregates"))
        return { buckets: [], totals: null };
      if (path.startsWith("/job-timers"))       return _listResp;
      if (path === "/auth/me") return { role: "super_admin" };
      return {};
    }),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// scrollIntoView isn't in jsdom.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn();
}

import JobTimersPage from "@/pages/timers/JobTimersPage";

describe("JobTimersPage · dashboard phase", () => {
  beforeEach(() => {
    _summaryResp = {
      avg_seconds: 1800, count: 5,
      min_seconds: 600, max_seconds: 3000,
      median_seconds: 1200,
    };
    _listResp = {
      items: [
        { id: "t-1", started_at: "2026-02-14T15:00:00Z",
          ended_at: "2026-02-14T15:30:00Z",
          duration_seconds: 1800,
          technician_id: "tech-1", technician_name: "Ana Smith",
          tech_id: "tech-1", tech_name: "Ana Smith",
          job_id: "job-1", job_title: "Weekly Pool", customer_name: "Alice",
          start_source: "gps_arrival", end_source: "job_completed",
          source: "gps_arrival", entity_type: "tech" },
      ],
      count: 1, page: 1, page_size: 25, total: 1, total_pages: 1,
    };
    vi.clearAllMocks();
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("mounts summary card with all five metrics + filter testids", async () => {
    render(<MemoryRouter initialEntries={["/job-timers"]}>
      <JobTimersPage />
    </MemoryRouter>);

    // All five summary tiles render with the values from
    // /job-timers/summary.
    await screen.findByTestId("job-timers-summary-card");
    await waitFor(() => {
      expect(screen.getByTestId("job-timers-summary-avg").textContent)
        .toMatch(/30m/); // 1800s → "30m 00s"
      expect(screen.getByTestId("job-timers-summary-count").textContent)
        .toMatch(/5/);
      expect(screen.getByTestId("job-timers-summary-min").textContent)
        .toMatch(/10m/); // 600s
      expect(screen.getByTestId("job-timers-summary-max").textContent)
        .toMatch(/50m/); // 3000s
      expect(screen.getByTestId("job-timers-summary-median").textContent)
        .toMatch(/20m/); // 1200s
    });

    // Filter testids (spec — dashboard phase).
    expect(screen.getByTestId("job-timers-filter-from")).toBeTruthy();
    expect(screen.getByTestId("job-timers-filter-to")).toBeTruthy();
    expect(screen.getByTestId("job-timers-filter-technician")).toBeTruthy();
  });

  it("always mounts pagination controls (prev disabled + next disabled on single page)", async () => {
    render(<MemoryRouter initialEntries={["/job-timers"]}>
      <JobTimersPage />
    </MemoryRouter>);

    const prev = await screen.findByTestId("job-timers-pagination-prev");
    const next = await screen.findByTestId("job-timers-pagination-next");
    // Always mounted per spec — regardless of row count.
    expect(prev).toBeTruthy();
    expect(next).toBeTruthy();
    // Single page → both disabled.
    await waitFor(() => {
      expect(prev.disabled).toBe(true);
      expect(next.disabled).toBe(true);
    });
    // Row testid uses the index-based shape from spec.
    await waitFor(() => {
      expect(screen.getByTestId("job-timers-row-0")).toBeTruthy();
    });
  });

  it("?t=avgtime deep-link marks the avg tile aria-current", async () => {
    render(<MemoryRouter initialEntries={["/job-timers?t=avgtime"]}>
      <JobTimersPage />
    </MemoryRouter>);

    // The summary card renders on every tab — but only when the
    // ``t=avgtime`` query is present does the avg tile carry
    // aria-current="true" (per spec's focus behaviour).
    const avg = await screen.findByTestId("job-timers-summary-avg");
    await waitFor(() => {
      expect(avg.getAttribute("aria-current")).toBe("true");
    });
  });

  it("?t=avgtime view exposes BOTH filter testid schemes + always-mounted pagination", async () => {
    // Feb-2026 · Dashboard-phase fixup — the AvgTime sub-panel had
    // testid drift (``avg-filter-*``) that broke the shared
    // dashboard contract testers depend on. The dual-testid
    // convention keeps the old handle for Phase-1 tests AND adds
    // the spec's ``job-timers-filter-*`` name for the new suite.
    // Pagination footer is always-mounted-but-disabled (aggregated
    // view has nothing to page through).
    render(<MemoryRouter initialEntries={["/job-timers?t=avgtime"]}>
      <JobTimersPage />
    </MemoryRouter>);

    // AvgTime sub-panel is mounted (marker present).
    await screen.findByTestId("avgtime-tab");

    // Legacy testids still work.
    expect(screen.getByTestId("avg-filter-from")).toBeTruthy();
    expect(screen.getByTestId("avg-filter-to")).toBeTruthy();
    expect(screen.getByTestId("avg-filter-tech")).toBeTruthy();

    // Spec testids resolve on the same view.
    expect(screen.getByTestId("job-timers-filter-from")).toBeTruthy();
    expect(screen.getByTestId("job-timers-filter-to")).toBeTruthy();
    expect(screen.getByTestId("job-timers-filter-technician")).toBeTruthy();

    // Pagination testids are always mounted, both disabled here.
    const prev = screen.getByTestId("job-timers-pagination-prev");
    const next = screen.getByTestId("job-timers-pagination-next");
    expect(prev.disabled).toBe(true);
    expect(next.disabled).toBe(true);
    expect(screen.getByTestId("job-timers-page-indicator")).toBeTruthy();
  });
});
