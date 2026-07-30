// Phase G5b · Feb-2026 — Attribution modal on the Driver Activity page.
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const _jobs = [
  { id: "job-1", title: "Pool cleaning",
    customer_name: "Ana's Yard", address: "42 Palm Ave",
    lat: 33.5, lon: -112.0 },
  { id: "job-2", title: "Chemistry",
    customer_name: "Ben's Yard", address: "9 Oak Rd",
    lat: 33.6, lon: -112.1 },
];

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/jobs")) return _jobs;
      return {};
    }),
    post: vi.fn(async () => ({ id: "stop-x",
      attribution_status: "manual_linked",
      attributed_job_id: "job-1" })),
    patch: vi.fn(), del: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

import StopAttributionModal from "@/pages/admin/StopAttributionModal";
import { api } from "@/api";

const STOP = {
  id: "stop-x",
  started_at: "2026-02-14T09:00:00Z",
  ended_at: "2026-02-14T09:15:00Z",
  center_lat: 33.5001,
  center_lon: -112.0001,
};

describe("StopAttributionModal · G5b", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("loads same-day scheduled jobs sorted by distance", async () => {
    render(<MemoryRouter>
      <StopAttributionModal stop={STOP} onClose={() => {}} onSaved={() => {}} />
    </MemoryRouter>);
    expect(await screen.findByTestId("stop-attribution-title"))
      .toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("stop-attribution-candidates"))
        .toBeInTheDocument();
      // job-1 (closer) should render before job-2 in the list.
      const list = screen.getByTestId("stop-attribution-candidates");
      const items = list.querySelectorAll("[data-testid^='stop-attribution-candidate-']");
      expect(items.length).toBe(2);
      expect(items[0].getAttribute("data-testid"))
        .toBe("stop-attribution-candidate-job-1");
    });
  });

  it("Link button POSTs to /admin/gps/stops/{id}/attribute", async () => {
    const onSaved = vi.fn();
    const onClose = vi.fn();
    render(<MemoryRouter>
      <StopAttributionModal stop={STOP} onClose={onClose} onSaved={onSaved} />
    </MemoryRouter>);
    fireEvent.click(await screen.findByTestId("stop-attribution-link-job-1"));
    await waitFor(() => {
      const posts = api.post.mock.calls.filter(
        (c) => c[0] === `/admin/gps/stops/${STOP.id}/attribute`);
      expect(posts.length).toBe(1);
      expect(posts[0][1]).toEqual({ job_id: "job-1" });
      expect(onSaved).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("Unlink button POSTs {unlink:true}", async () => {
    render(<MemoryRouter>
      <StopAttributionModal stop={STOP} onClose={() => {}} onSaved={() => {}} />
    </MemoryRouter>);
    fireEvent.click(await screen.findByTestId("stop-attribution-unlink-btn"));
    await waitFor(() => {
      const posts = api.post.mock.calls.filter(
        (c) => c[0] === `/admin/gps/stops/${STOP.id}/attribute`);
      expect(posts.length).toBe(1);
      expect(posts[0][1]).toEqual({ unlink: true });
    });
  });
});
