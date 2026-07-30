// Phase G5b · Feb-2026 — TimeOnSitePage vitest suite.
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _summary = {
  as_of: "2026-02-14T09:00:00Z",
  range: "week",
  counts: {
    pending: 3, auto_linked: 7, manual_linked: 2,
    no_match: 5, unlinked: 1,
  },
  top_jobs_by_time_on_site: [
    { job_id: "job-1", job_name: "Depot cleaning",
      customer_id: "c1", customer_name: "Ana's Pool",
      scheduled_date: "2026-02-14",
      stop_count: 3, total_stop_duration_s: 3600 },
    { job_id: "job-2", job_name: "Chemistry check",
      customer_id: "c2", customer_name: "Ben's Yard",
      scheduled_date: "2026-02-14",
      stop_count: 1, total_stop_duration_s: 1200 },
  ],
};

const _jobDetail = {
  job_id: "job-1",
  job_name: "Depot cleaning",
  customer_id: "c1", customer_name: "Ana's Pool",
  scheduled_date: "2026-02-14",
  attributed_stops: [
    { id: "stop-1", user_id: "u1", user_name: "Ana",
      started_at: "2026-02-14T09:00:00Z",
      ended_at: "2026-02-14T09:20:00Z",
      duration_s: 1200,
      attribution_distance_m: 32,
      attribution_status: "auto_linked" },
    { id: "stop-2", user_id: "u1", user_name: "Ana",
      started_at: "2026-02-14T10:00:00Z",
      ended_at: "2026-02-14T10:15:00Z",
      duration_s: 900,
      attribution_distance_m: null,
      attribution_status: "manual_linked" },
  ],
  total_stop_duration_s: 2100,
  unique_techs: 1,
};

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/admin/gps/attribution/summary")) return _summary;
      if (path.startsWith("/admin/gps/attribution/job/")) return _jobDetail;
      return {};
    }),
    post: vi.fn(async () => ({ processed: 3, auto_linked: 2, no_match: 1 })),
    patch: vi.fn(), del: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import TimeOnSitePage from "@/pages/admin/TimeOnSitePage";
import { api } from "@/api";

describe("TimeOnSitePage · G5b", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders counts strip and top-jobs table", async () => {
    render(<MemoryRouter><TimeOnSitePage /></MemoryRouter>);
    expect(await screen.findByTestId("tos-title")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("tos-count-auto_linked"))
        .toHaveTextContent("7");
      expect(screen.getByTestId("tos-count-no_match"))
        .toHaveTextContent("5");
      expect(screen.getByTestId("tos-top-job-row-job-1")).toBeInTheDocument();
      expect(screen.getByTestId("tos-top-job-row-job-2")).toBeInTheDocument();
    });
  });

  it("opens the job drawer with attributed stops", async () => {
    render(<MemoryRouter><TimeOnSitePage /></MemoryRouter>);
    await screen.findByTestId("tos-top-job-row-job-1");
    fireEvent.click(screen.getByTestId("tos-details-job-1"));
    await waitFor(() => {
      expect(screen.getByTestId("tos-job-drawer")).toBeInTheDocument();
      expect(screen.getByTestId("tos-job-stop-stop-1")).toBeInTheDocument();
      expect(screen.getByTestId("tos-job-stop-stop-2")).toBeInTheDocument();
      expect(screen.getByTestId("tos-job-unique-techs")).toHaveTextContent(/1/);
    });
  });

  it("range change refetches summary", async () => {
    render(<MemoryRouter><TimeOnSitePage /></MemoryRouter>);
    await screen.findByTestId("tos-title");
    const range = screen.getByTestId("tos-range-select");
    fireEvent.change(range, { target: { value: "day" } });
    await waitFor(() => {
      const calls = api.get.mock.calls.map((c) => c[0]);
      expect(calls.some((p) => p.includes("range=day"))).toBe(true);
    });
  });

  it("run-batch button POSTs and refreshes", async () => {
    render(<MemoryRouter><TimeOnSitePage /></MemoryRouter>);
    await screen.findByTestId("tos-title");
    fireEvent.click(screen.getByTestId("tos-run-batch"));
    await waitFor(() => {
      const posts = api.post.mock.calls.filter(
        (c) => c[0] === "/admin/gps/attribution/run-batch");
      expect(posts.length).toBe(1);
    });
  });
});
