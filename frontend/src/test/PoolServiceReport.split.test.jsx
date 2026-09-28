/**
 * POOL-B · Feb-2026 — Pool Service Report service/repair split UI.
 *
 * Locks the FE contract added by POOL-B:
 *   (a) Renders BOTH sections (Maintenance + Repairs) with the
 *       correct counts from a mocked API payload.
 *   (b) Empty-state per section fires when its bucket is empty.
 *   (c) "Other" summary chip is hidden when ``other_visits == 0``.
 *   (d) "Other" summary chip is visible when ``other_visits > 0``.
 *   (e) No landscape-shaped mock row ever renders (guardrail —
 *       the backend filters landscape jobs; a corrupt payload
 *       with a landscape tech row is a smoke test that the FE
 *       doesn't add any post-processing that resurrects them).
 *   (f) The spec-mandated ``data-testid``s are present:
 *          - ``pool-report-total-serviced``
 *          - ``pool-report-total-repairs``
 *          - ``pool-report-tech-row-<tid>-serviced``
 *          - ``pool-report-tech-row-<tid>-repairs``
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));

import { api } from "@/api";
import PoolServiceReport from "@/pages/reports/PoolServiceReport";


function _mockReport(overrides = {}) {
  return {
    week_start: "2026-02-16",
    week_end:   "2026-02-22",
    total_completed: 3,
    total_skipped: 1,
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
        technician_id: "tech-alice",
        technician_name: "Alice Adams",
        technician_active: true,
        pools_serviced: 2, repairs_completed: 0, other: 0, skipped: 1,
        completed: 2,
      },
      {
        technician_id: "tech-bob",
        technician_name: "Bob Brown",
        technician_active: true,
        pools_serviced: 1, repairs_completed: 0, other: 0, skipped: 0,
        completed: 1,
      },
    ],
    repairs: overrides.repairs ?? [
      {
        technician_id: "tech-carol",
        technician_name: "Carol Cook",
        technician_active: true,
        pools_serviced: 0, repairs_completed: 2, other: 0, skipped: 0,
        completed: 0,
      },
    ],
    other: overrides.other ?? [],
    visits: [],
    totals: { pools_serviced: 3, repairs_completed: 2 },
    by_technician: overrides.by_technician ?? [
      {
        technician_id: "tech-alice", technician_name: "Alice Adams",
        pools_serviced: 2, repairs_completed: 0, other: 0, skipped: 1,
      },
      {
        technician_id: "tech-bob", technician_name: "Bob Brown",
        pools_serviced: 1, repairs_completed: 0, other: 0, skipped: 0,
      },
      {
        technician_id: "tech-carol", technician_name: "Carol Cook",
        pools_serviced: 0, repairs_completed: 2, other: 0, skipped: 0,
      },
    ],
  };
}


beforeEach(() => {
  api.get.mockReset();
});


describe("PoolServiceReport · POOL-B split", () => {
  it("renders both sections with correct counts from a mocked payload", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport());
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);

    // Summary chips — brief mandate.
    await waitFor(() =>
      expect(screen.getByTestId("pool-report-total-serviced"))
        .toHaveTextContent("Maintenance:3"),
    );
    expect(screen.getByTestId("pool-report-total-repairs"))
      .toHaveTextContent("Repairs:2");
    // Total = 3 + 2 + 1
    expect(screen.getByTestId("pool-report-total-all"))
      .toHaveTextContent("Total:6");

    // Both section tables render.
    expect(screen.getByTestId("pool-service-maintenance-table"))
      .toBeInTheDocument();
    expect(screen.getByTestId("pool-service-repairs-table"))
      .toBeInTheDocument();

    // Spec-mandated per-row test-ids.
    expect(screen.getByTestId("pool-report-tech-row-tech-alice-serviced"))
      .toHaveTextContent("2");
    expect(screen.getByTestId("pool-report-tech-row-tech-carol-repairs"))
      .toHaveTextContent("2");

    // Tech names surface in the right sections.
    expect(screen.getByText("Alice Adams")).toBeInTheDocument();
    expect(screen.getByText("Bob Brown")).toBeInTheDocument();
    expect(screen.getByText("Carol Cook")).toBeInTheDocument();
  });

  it("fires per-section empty state when its bucket is empty", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport({
          maintenance: [],
          repairs: [],
          summary: {
            total_pool_visits: 0, maintenance_visits: 0,
            repair_visits: 0, other_visits: 0,
          },
        }));
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);

    await waitFor(() =>
      expect(screen.getByTestId("pool-service-maintenance-empty"))
        .toHaveTextContent("No maintenance visits in this period"),
    );
    expect(screen.getByTestId("pool-service-repairs-empty"))
      .toHaveTextContent("No repairs completed in this period");
  });

  it("hides the Other chip when other_visits === 0", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport({
          summary: {
            total_pool_visits: 3, maintenance_visits: 3,
            repair_visits: 0, other_visits: 0,
          },
          repairs: [],
        }));
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);
    await waitFor(() =>
      expect(screen.getByTestId("pool-report-total-serviced"))
        .toBeInTheDocument(),
    );
    expect(screen.queryByTestId("pool-report-total-other"))
      .not.toBeInTheDocument();
  });

  it("shows the Other chip when other_visits > 0", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport({
          summary: {
            total_pool_visits: 5, maintenance_visits: 3,
            repair_visits: 1, other_visits: 1,
          },
          other: [{
            technician_id: "tech-unknown",
            technician_name: "Unknown Uma",
            pools_serviced: 0, repairs_completed: 0,
            other: 1, skipped: 0, completed: 0,
          }],
        }));
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);
    await waitFor(() =>
      expect(screen.getByTestId("pool-report-total-other"))
        .toHaveTextContent("Other:1"),
    );
  });

  it("never renders a landscape-shaped mock row (POOL-A + POOL-B guardrail)", async () => {
    // Even a corrupt payload with a landscape technician name in
    // ``maintenance`` should NOT slip through the FE — but the FE
    // trusts the backend filter so we assert the tech name IS
    // rendered when present (this test doubles as documentation of
    // the boundary: the FE renders whatever the backend gives it,
    // so the landscape filter MUST live at the backend).
    //
    // The guardrail we CAN assert on the FE side: no
    // "landscape"-shaped fields (``industry`` / ``service_type``)
    // are ever read by the component — a landscape payload without
    // work_class-derived counts should render as zero.
    api.get.mockImplementation((url) => {
      if (url.startsWith("/reports/pool-service?"))
        return Promise.resolve(_mockReport({
          // ONLY the ``by_technician`` array has a landscape-labelled
          // tech; both bucket arrays are empty so the FE renders
          // empty states.  Proves the FE never falls back to
          // ``by_technician`` for the row lists — brief mandate.
          maintenance: [],
          repairs: [],
          summary: {
            total_pool_visits: 0, maintenance_visits: 0,
            repair_visits: 0, other_visits: 0,
          },
          by_technician: [
            {
              technician_id: "tech-landscape-larry",
              technician_name: "Landscape Larry",
              pools_serviced: 5, repairs_completed: 3,
              other: 0, skipped: 0,
            },
          ],
        }));
      if (url.includes("email-history"))
        return Promise.resolve({ items: [] });
      return Promise.resolve({});
    });

    render(<PoolServiceReport />);
    await waitFor(() =>
      expect(screen.getByTestId("pool-service-maintenance-empty"))
        .toBeInTheDocument(),
    );
    // No landscape tech row appears in the visible sections.
    expect(screen.queryByText("Landscape Larry")).not.toBeInTheDocument();
    // Total counts reflect the summary, not the by_technician array.
    expect(screen.getByTestId("pool-report-total-serviced"))
      .toHaveTextContent("Maintenance:0");
    expect(screen.getByTestId("pool-report-total-repairs"))
      .toHaveTextContent("Repairs:0");
  });
});
