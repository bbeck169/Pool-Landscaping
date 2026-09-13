/**
 * routing-cost-telemetry-tile · Feb-2026 · UX Polish Batch B
 *
 * Locks the RoutingCostTile contract:
 *
 *  1. Renders and hits ``GET /reports/routing-cost-telemetry`` on mount
 *     with the default 30d window.
 *  2. Window selector round-trips (7 / 30 / 90) — each change fires a
 *     fresh GET.
 *  3. Empty state renders when ``total_calls === 0``.
 *  4. Populated state renders the aware / baseline / est-extra rows.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const getMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/theme", () => ({
  colors: { muted: "#666", brand: "#0B4A6F", onSurface: "#111", border: "#ddd" },
}));

import RoutingCostTile from "@/components/admin/RoutingCostTile";


beforeEach(() => {
  getMock.mockReset();
});


describe("RoutingCostTile · Batch B", () => {
  it("fires the default 30d request on mount", async () => {
    getMock.mockResolvedValue({
      window_days: 30, tenant_id: "t-1",
      total_calls: 0, traffic_aware_calls: 0, traffic_unaware_calls: 0,
      waypoints_billed: 0, est_traffic_aware_cost_usd: 0,
      est_baseline_cost_usd: 0,
    });
    render(<RoutingCostTile />);
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(getMock.mock.calls[0][0]).toContain("window_days=30");
  });

  it("empty state renders when total_calls is 0", async () => {
    getMock.mockResolvedValue({
      window_days: 30, tenant_id: "t-1",
      total_calls: 0, traffic_aware_calls: 0, traffic_unaware_calls: 0,
      waypoints_billed: 0, est_traffic_aware_cost_usd: 0,
      est_baseline_cost_usd: 0,
    });
    render(<RoutingCostTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("routing-cost-empty")).toBeTruthy(),
    );
  });

  it("populated rows render the aware / baseline / extra-cost values", async () => {
    getMock.mockResolvedValue({
      window_days: 30, tenant_id: "t-1",
      total_calls: 15, traffic_aware_calls: 9, traffic_unaware_calls: 6,
      waypoints_billed: 130, est_traffic_aware_cost_usd: 0.09,
      est_baseline_cost_usd: 0.03,
    });
    render(<RoutingCostTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("routing-cost-aware-row")).toBeTruthy(),
    );
    expect(screen.getByTestId("routing-cost-aware-row").textContent).toContain("9");
    expect(screen.getByTestId("routing-cost-baseline-row").textContent).toContain("6");
    expect(screen.getByTestId("routing-cost-extra-row").textContent).toContain("$0.09");
  });

  it("window selector round-trips (30 → 7 fires a fresh GET)", async () => {
    getMock.mockResolvedValue({
      window_days: 30, tenant_id: "t-1",
      total_calls: 0, traffic_aware_calls: 0, traffic_unaware_calls: 0,
      waypoints_billed: 0, est_traffic_aware_cost_usd: 0,
      est_baseline_cost_usd: 0,
    });
    render(<RoutingCostTile />);
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByTestId("routing-cost-window-select"), {
      target: { value: "7" },
    });
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    expect(getMock.mock.calls[1][0]).toContain("window_days=7");
  });
});
