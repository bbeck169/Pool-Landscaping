/**
 * Phase 54g · Feb-2026 — supplier sync analytics dashboard tests.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
vi.mock("@/api", () => ({ api: { get: (...a) => getMock(...a) } }));

let mockUser = { role: "admin" };
vi.mock("@/auth", () => ({ useAuth: () => ({ user: mockUser, loading: false }) }));

import SupplierSyncAnalytics from "@/pages/reports/SupplierSyncAnalytics";

const FIXTURE = {
  range_days: 30,
  generated_at: "2026-02-15T00:00:00Z",
  suppliers: [
    {
      slug: "ewing", display_name: "Ewing Irrigation",
      total_runs: 6, success_count: 3, error_count: 3, success_rate: 0.5,
      avg_items_added: 0, avg_items_updated: 0, avg_items_removed: 0,
      consecutive_errors: 3, days_since_last_success: 4,
      last_success_at: "2026-02-11T00:00:00Z",
      last_error_at:   "2026-02-14T00:00:00Z",
      last_error_message: "Layout changed — zero cards on first page",
      trend_daily: [
        { date: "2026-02-13", runs: 2, success: 0, error: 2, items_added: 0, items_updated: 0 },
        { date: "2026-02-14", runs: 1, success: 0, error: 1, items_added: 0, items_updated: 0 },
      ],
      health_signal: "critical",
      health_rationale: "3 consecutive errors",
    },
    {
      slug: "siteone", display_name: "SiteOne",
      total_runs: 10, success_count: 7, error_count: 3, success_rate: 0.7,
      avg_items_added: 20, avg_items_updated: 1, avg_items_removed: 0,
      consecutive_errors: 0, days_since_last_success: 1,
      last_success_at: "2026-02-14T00:00:00Z",
      last_error_at: "2026-02-10T00:00:00Z",
      last_error_message: null,
      trend_daily: [
        { date: "2026-02-14", runs: 1, success: 1, error: 0, items_added: 20, items_updated: 1 },
      ],
      health_signal: "warning",
      health_rationale: "success rate 70% (60-90%)",
    },
    {
      slug: "poolcorp", display_name: "Pool360 (PoolCorp)",
      total_runs: 5, success_count: 5, error_count: 0, success_rate: 1.0,
      avg_items_added: 42, avg_items_updated: 3, avg_items_removed: 0,
      consecutive_errors: 0, days_since_last_success: 0,
      last_success_at: "2026-02-15T00:00:00Z",
      last_error_at: null, last_error_message: null,
      trend_daily: [
        { date: "2026-02-15", runs: 1, success: 1, error: 0, items_added: 42, items_updated: 3 },
      ],
      health_signal: "healthy",
      health_rationale: "success rate 100%",
    },
  ],
};

beforeEach(() => {
  getMock.mockReset();
  getMock.mockResolvedValue(FIXTURE);
  mockUser = { role: "admin" };
});
afterEach(() => cleanup());

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/reports/supplier-syncs"]}>
      <SupplierSyncAnalytics />
    </MemoryRouter>,
  );
}


describe("Phase 54g — supplier analytics dashboard", () => {
  it("renders one card per supplier with the health signal + rationale", async () => {
    renderPage();
    await screen.findByTestId("supplier-sync-analytics-page");
    for (const slug of ["ewing", "siteone", "poolcorp"]) {
      expect(await screen.findByTestId(`analytics-card-${slug}`)).toBeInTheDocument();
      expect(await screen.findByTestId(`analytics-signal-${slug}`)).toBeInTheDocument();
      expect(await screen.findByTestId(`analytics-rationale-${slug}`)).toBeInTheDocument();
    }
    // Health-signal badges carry the correct label text.
    const critical = await screen.findByTestId("analytics-signal-ewing");
    expect(critical.textContent).toContain("Critical");
    const warning = await screen.findByTestId("analytics-signal-siteone");
    expect(warning.textContent).toContain("Warning");
    const healthy = await screen.findByTestId("analytics-signal-poolcorp");
    expect(healthy.textContent).toContain("Healthy");
  });

  it("sparklines render one per supplier", async () => {
    renderPage();
    for (const slug of ["ewing", "siteone", "poolcorp"]) {
      expect(await screen.findByTestId(`analytics-sparkline-${slug}`)).toBeInTheDocument();
    }
  });

  it("range picker refetches when changed", async () => {
    renderPage();
    await screen.findByTestId("supplier-sync-analytics-page");
    expect(getMock).toHaveBeenCalledWith("/suppliers/analytics?days=30");
    const picker = await screen.findByTestId("analytics-range-picker");
    fireEvent.change(picker, { target: { value: "90" } });
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith("/suppliers/analytics?days=90");
    });
  });

  it("expand-error toggle reveals the error body only when clicked", async () => {
    renderPage();
    const toggle = await screen.findByTestId("analytics-expand-error-ewing");
    // Body hidden by default.
    expect(screen.queryByTestId("analytics-error-body-ewing")).toBeNull();
    fireEvent.click(toggle);
    const body = await screen.findByTestId("analytics-error-body-ewing");
    expect(body.textContent).toContain("Layout changed");
    // Click again — hidden.
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(screen.queryByTestId("analytics-error-body-ewing")).toBeNull());
  });

  it("manager role disables the range picker (read-only)", async () => {
    mockUser = { role: "manager" };
    renderPage();
    const picker = await screen.findByTestId("analytics-range-picker");
    expect(picker).toBeDisabled();
  });

  it("route wrapper wires /reports/supplier-syncs through AdminOrManagerForSuppliers", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../App.js"), "utf8");
    expect(src).toMatch(
      /reports\/supplier-syncs.*AdminOrManagerForSuppliers.*SupplierSyncAnalytics/s);
  });
});
