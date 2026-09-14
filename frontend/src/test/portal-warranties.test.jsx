/**
 * Phase Feb-2026 — Customer portal · Warranties (read-only) smoke.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: { get: (...a) => getSpy(...a) },
}));

import PortalWarranties from "@/pages/portal/PortalWarranties";

describe("PortalWarranties — read-only", () => {
  beforeEach(() => { getSpy.mockReset(); });

  it("shows the empty state when no warranties on file", async () => {
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 50, total: 0, total_pages: 1,
    });
    render(<PortalWarranties />);
    await waitFor(() =>
      expect(screen.getByTestId("portal-warranty-empty")).toBeInTheDocument()
    );
  });

  it("renders warranty cards with linked_summary when API returns rows", async () => {
    getSpy.mockResolvedValue({
      items: [{
        id: "w-1", plan_name_snapshot: "Extended Pool Warranty",
        start_date: "2026-02-01", end_date: "2028-02-01",
        status: "active",
        linked_type: "equipment", linked_id: "e-1",
        linked_summary: {
          type: "equipment",
          label: "Filter Pump — Pentair IntelliFlo",
          details: {},
        },
      }],
      page: 1, page_size: 50, total: 1, total_pages: 1,
    });
    render(<PortalWarranties />);
    await waitFor(() =>
      expect(screen.getByTestId("portal-warranty-card-0")).toBeInTheDocument()
    );
    expect(screen.getByTestId("portal-warranty-card-name-0").textContent)
      .toBe("Extended Pool Warranty");
    expect(screen.getByTestId("portal-warranty-card-window-0").textContent)
      .toContain("2026-02-01");
    expect(screen.getByTestId("portal-warranty-card-link-0").textContent)
      .toContain("Filter Pump");
  });

  it("uses /customers/me/warranties (portal endpoint)", async () => {
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 50, total: 0, total_pages: 1,
    });
    render(<PortalWarranties />);
    await waitFor(() =>
      expect(getSpy).toHaveBeenCalledWith("/customers/me/warranties")
    );
  });
});
