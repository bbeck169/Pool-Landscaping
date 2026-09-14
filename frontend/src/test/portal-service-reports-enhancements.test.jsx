/**
 * Feb-2026 · Portal Service Reports — enhancements ship.
 *
 * Coverage:
 *   1. List page fetches with pagination query params (``page`` +
 *      ``page_size``) and renders rows with ``sr-list-row-<i>``
 *      testids.
 *   2. Empty ``items`` → EmptyState (no rows, no pagination).
 *   3. Total > page_size → pagination bar with prev/next + page
 *      indicator ("Page 1 of N (T total)").
 *   4. Search input debounces + fires the fetch with ``?q=`` query
 *      param.
 *   5. Detail view renders "Job Photos" section when ``job_photos``
 *      is non-empty, hides it otherwise.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a), post: vi.fn(), patch: vi.fn(), del: vi.fn() },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ id: "sr-1" }),
}));

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0B4A6F", onBrand: "#FFFFFF", onSurface: "#111827",
    onSurfaceSecondary: "#6B7280", muted: "#6B7280", border: "#E5E7EB",
    divider: "#E5E7EB", surface: "#FFFFFF", surfaceSecondary: "#F8FAFC",
    success: "#059669",
  },
  money: (n) => `$${Number(n || 0).toFixed(2)}`,
}));

import {
  PortalServiceReports,
  PortalServiceReportDetail,
} from "@/pages/portal/PortalServiceReports";


function _row(id, overrides = {}) {
  return {
    id, job_id: `job-${id}`, job_title: `Visit ${id}`,
    service_type: "pool_service",
    submitted_at: "2026-02-01T10:00:00Z",
    scheduled_start: "2026-02-01T09:00:00Z",
    tech_name: "Mike",
    customer_notes: "",
    water_bodies_summary: [],
    water_body_count: 0,
    ...overrides,
  };
}


describe("PortalServiceReports · list enhancements", () => {
  beforeEach(() => {
    getSpy.mockReset();
    vi.useRealTimers();
  });

  it("fetches with pagination query params and renders sr-list-row-<i>", async () => {
    getSpy.mockResolvedValue({
      items: [_row("a"), _row("b")], page: 1, page_size: 20,
      total: 2, total_pages: 1,
    });
    render(<PortalServiceReports />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const path = getSpy.mock.calls[0][0];
    expect(path).toMatch(/^\/customers\/me\/service-reports\?/);
    expect(path).toMatch(/page=1/);
    expect(path).toMatch(/page_size=20/);
    // Rows expose the new stable testid.
    expect(await screen.findByTestId("sr-list-row-0")).toBeTruthy();
    expect(screen.getByTestId("sr-list-row-1")).toBeTruthy();
    // Single-page result → NO pagination bar.
    expect(screen.queryByTestId("sr-list-pagination")).toBeNull();
  });

  it("renders pagination bar when total > page_size with correct indicator", async () => {
    getSpy.mockResolvedValue({
      items: [_row("a")], page: 1, page_size: 20,
      total: 47, total_pages: 3,
    });
    render(<PortalServiceReports />);
    await screen.findByTestId("sr-list-pagination");
    expect(screen.getByTestId("sr-list-page-indicator").textContent)
      .toMatch(/Page 1 of 3.*47 total/);
    // Prev disabled on page 1.
    expect(screen.getByTestId("sr-list-pagination-prev").disabled).toBe(true);
    expect(screen.getByTestId("sr-list-pagination-next").disabled).toBe(false);
  });

  it("search input debounces + hits API with ?q= param", async () => {
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(<PortalServiceReports />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    getSpy.mockClear();
    const box = screen.getByTestId("sr-list-search");
    fireEvent.change(box, { target: { value: "chlorine" } });
    // Waits past the 300ms debounce for the follow-up fetch to fire.
    await waitFor(
      () => {
        expect(getSpy).toHaveBeenCalled();
        const path = getSpy.mock.calls[getSpy.mock.calls.length - 1][0];
        expect(path).toMatch(/q=chlorine/);
      },
      { timeout: 2000 },
    );
  });

  it("legacy bare-array response is still handled (backwards-compat guard)", async () => {
    getSpy.mockResolvedValue([_row("a")]);
    render(<PortalServiceReports />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(await screen.findByTestId("sr-list-row-0")).toBeTruthy();
  });
});


describe("PortalServiceReportDetail · Job Photos section", () => {
  beforeEach(() => {
    getSpy.mockReset();
    vi.useRealTimers();
  });

  it("renders 'Job Photos' section when job_photos is non-empty", async () => {
    getSpy.mockResolvedValue({
      id: "sr-1", job: { id: "job-1", title: "Weekly service" },
      status: "submitted", template: "generic",
      photos: [],
      job_photos: [
        { id: "p1", caption: "Before",
          thumb: "data:image/jpeg;base64,/9j/AAAA",
          url: "/api/customers/me/jobs/job-1/photos/p1" },
        { id: "p2", caption: "After",
          thumb: "data:image/jpeg;base64,/9j/AAAA",
          url: "/api/customers/me/jobs/job-1/photos/p2" },
      ],
    });
    render(<PortalServiceReportDetail />);
    expect(await screen.findByTestId("service-report-job-photos-section"))
      .toBeTruthy();
    expect(screen.getByTestId("service-report-job-photo-0")).toBeTruthy();
    expect(screen.getByTestId("service-report-job-photo-1")).toBeTruthy();
    // Distinct from ``portal-service-report-photos`` (tech-attached).
    expect(screen.queryByTestId("portal-service-report-photos")).toBeNull();
  });

  it("hides the section entirely when job_photos is empty or missing", async () => {
    getSpy.mockResolvedValue({
      id: "sr-2", job: { id: "job-2", title: "Weekly service" },
      status: "submitted", template: "generic",
      photos: [],
      job_photos: [],
    });
    render(<PortalServiceReportDetail />);
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.queryByTestId("service-report-job-photos-section")).toBeNull();
    expect(screen.queryByTestId("service-report-job-photo-0")).toBeNull();
  });
});
