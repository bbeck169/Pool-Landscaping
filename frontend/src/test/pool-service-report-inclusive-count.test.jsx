/**
 * Feb-2026 · Pool Service Report — inclusive-count FE contract.
 *
 * Locks the frontend wiring for the backend's new inclusive-count
 * additions (user-approved option (a)+(ii)):
 *
 *   (a) Primary "Completed Jobs" count renders ``total_completed_all``
 *       from the API response (service + repair + other combined).
 *   (b) Legacy breakdown chips (Maintenance / Repairs / Other / Total)
 *       continue to render — unchanged semantics so existing
 *       split-coverage keeps passing.
 *   (c) Admin-only ``dropped_count`` info line renders when the
 *       response reports non-terminal pool jobs (``scheduled``,
 *       ``in_progress``, etc.) AND the viewer is admin/super_admin.
 *   (d) Non-admin viewers never see the dropped-count info line.
 *   (e) ``dropped_count === 0`` suppresses the info line even for
 *       admins (brief §"Empty states").
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// Role is mutated per-test by swapping ``currentRole`` before render.
let currentRole = "admin";

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: currentRole, email: `${currentRole}@x.y` },
    loading: false,
  }),
  AuthProvider: ({ children }) => children,
}));

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));

import { api } from "@/api";
import PoolServiceReport from "@/pages/reports/PoolServiceReport";


function _mockReport(overrides = {}) {
  return {
    week_start: "2026-02-16",
    week_end:   "2026-02-22",
    // Legacy service-only count — stays untouched.
    total_completed: 3,
    total_skipped: 1,
    // NEW inclusive fields.
    total_completed_all: 6,
    dropped_count: 2,
    period: { start: "2026-02-16", end: "2026-02-22" },
    summary: {
      total_pool_visits:   6,
      maintenance_visits:  3,
      repair_visits:       2,
      other_visits:        1,
      ...(overrides.summary || {}),
    },
    maintenance: overrides.maintenance ?? [
      {
        technician_id: "tech-alice", technician_name: "Alice Adams",
        technician_active: true,
        pools_serviced: 2, repairs_completed: 0, other: 0, skipped: 1,
        completed: 2, completed_all: 2,
      },
      {
        technician_id: "tech-bob", technician_name: "Bob Brown",
        technician_active: true,
        pools_serviced: 1, repairs_completed: 0, other: 0, skipped: 0,
        completed: 1, completed_all: 1,
      },
    ],
    repairs: overrides.repairs ?? [
      {
        technician_id: "tech-carol", technician_name: "Carol Cook",
        technician_active: true,
        pools_serviced: 0, repairs_completed: 2, other: 0, skipped: 0,
        completed: 0, completed_all: 2,
      },
    ],
    other: overrides.other ?? [],
    visits: [],
    totals: { pools_serviced: 3, repairs_completed: 2 },
    by_technician: overrides.by_technician ?? [],
    ...overrides.topLevel,
  };
}


beforeEach(() => {
  api.get.mockReset();
  currentRole = "admin";
});


describe("PoolServiceReport · inclusive-count fix", () => {
  it("renders total_completed_all as the primary Completed Jobs count", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport());
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);

    await waitFor(() =>
      expect(screen.getByTestId("pool-report-completed-all"))
        .toHaveTextContent("6"),
    );
    // Breakdown chips (unchanged — regression guard).
    expect(screen.getByTestId("pool-report-total-serviced"))
      .toHaveTextContent("Maintenance:3");
    expect(screen.getByTestId("pool-report-total-repairs"))
      .toHaveTextContent("Repairs:2");
    expect(screen.getByTestId("pool-report-total-other"))
      .toHaveTextContent("Other:1");
  });

  it("falls back to summed chips when backend omits total_completed_all", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?")) {
        // Simulate an older backend that pre-dates the inclusive
        // field — the FE must still render a sensible primary count.
        const payload = _mockReport();
        delete payload.total_completed_all;
        return Promise.resolve(payload);
      }
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);
    await waitFor(() =>
      expect(screen.getByTestId("pool-report-completed-all"))
        .toHaveTextContent("6"),
    );
  });

  it("shows admin-only dropped-count info line when dropped_count > 0", async () => {
    currentRole = "admin";
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport());
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);
    await waitFor(() =>
      expect(screen.getByTestId("pool-report-dropped-count"))
        .toHaveTextContent(/2 jobs dropped/i),
    );
  });

  it("hides dropped-count info line when dropped_count === 0", async () => {
    currentRole = "admin";
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport({
          topLevel: { dropped_count: 0 },
        }));
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);
    // Wait for the primary count to render so we know the component
    // has settled before asserting absence.
    await waitFor(() =>
      expect(screen.getByTestId("pool-report-completed-all"))
        .toBeInTheDocument(),
    );
    expect(screen.queryByTestId("pool-report-dropped-count"))
      .not.toBeInTheDocument();
  });

  it("hides dropped-count info line for non-admin viewers", async () => {
    currentRole = "technician";
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport());
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);
    await waitFor(() =>
      expect(screen.getByTestId("pool-report-completed-all"))
        .toBeInTheDocument(),
    );
    expect(screen.queryByTestId("pool-report-dropped-count"))
      .not.toBeInTheDocument();
  });
});
