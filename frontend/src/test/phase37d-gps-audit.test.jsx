/**
 * Feb-2026 · P37d — GpsAutoStartAudit page.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ role: "admin", isAdmin: true, isAdminOrManager: true }),
}));

const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin", tenant_id: "t1" } }),
}));


import GpsAutoStartAudit from "@/pages/reports/GpsAutoStartAudit";


const _mockPayload = {
  ok: true,
  window: { from: "2026-06-01T00:00:00Z", to: "2026-07-01T00:00:00Z" },
  summary: {
    total_arrivals: 20, started: 8, throttled: 4, out_of_radius: 3,
    consent_required: 3, feature_disabled: 2,
    median_distance_m: 40.0, p90_distance_m: 200.0,
    percent_excellent: 33.3, percent_acceptable: 46.7,
    percent_over_radius: 20.0,
    distance_sample_size: 15, current_radius_m: 75,
  },
  recent_events: [
    { arrived_at: "2026-06-30T15:00:00Z", tech_name: "T1",
      customer_name: "Cust A", job_id: "j1", outcome: "started",
      distance_m: 12, radius_m: 75, consent_state: "active" },
    { arrived_at: "2026-06-30T14:00:00Z", tech_name: "T2",
      customer_name: "Cust B", job_id: "j2", outcome: "out_of_radius",
      distance_m: 250, radius_m: 75, consent_state: "active" },
  ],
};


beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockResolvedValue(_mockPayload);
});


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/reports/gps-auto-start-audit"]}>
      <GpsAutoStartAudit />
    </MemoryRouter>,
  );
}


describe("GpsAutoStartAudit · P37d", () => {
  it("renders 5 outcome pills with counts", async () => {
    _mount();
    await waitFor(() =>
      expect(screen.getByTestId("gps-audit-outcome-started")).toBeTruthy());
    expect(screen.getByTestId("gps-audit-outcome-started").textContent).toMatch(/8/);
    expect(screen.getByTestId("gps-audit-outcome-throttled").textContent).toMatch(/4/);
    expect(screen.getByTestId("gps-audit-outcome-out_of_radius").textContent).toMatch(/3/);
    expect(screen.getByTestId("gps-audit-outcome-consent_required").textContent).toMatch(/3/);
    expect(screen.getByTestId("gps-audit-outcome-feature_disabled").textContent).toMatch(/2/);
  });

  it("renders median + p90 distance", async () => {
    _mount();
    await waitFor(() => {
      expect(screen.getByTestId("gps-audit-median-distance").textContent).toMatch(/40/);
      expect(screen.getByTestId("gps-audit-p90-distance").textContent).toMatch(/200/);
    });
  });

  it("renders 3 percent stats", async () => {
    _mount();
    await waitFor(() => {
      expect(screen.getByTestId("gps-audit-percent-excellent").textContent).toMatch(/33/);
      expect(screen.getByTestId("gps-audit-percent-acceptable").textContent).toMatch(/46/);
      expect(screen.getByTestId("gps-audit-percent-over-radius").textContent).toMatch(/20/);
    });
  });

  it("renders recent events rows in order (newest first)", async () => {
    _mount();
    await waitFor(() =>
      expect(screen.getByTestId("gps-audit-recent-row-0")).toBeTruthy());
    const row0 = screen.getByTestId("gps-audit-recent-row-0");
    const row1 = screen.getByTestId("gps-audit-recent-row-1");
    expect(row0.textContent).toContain("T1");
    expect(row0.textContent).toContain("Cust A");
    expect(row1.textContent).toContain("T2");
    expect(row1.textContent).toContain("Cust B");
  });

  it("empty window renders the empty-state message", async () => {
    mockGet.mockResolvedValue({
      ..._mockPayload,
      summary: { ..._mockPayload.summary, total_arrivals: 0 },
      recent_events: [],
    });
    _mount();
    await waitFor(() =>
      expect(screen.getByTestId("gps-audit-recent-empty")).toBeTruthy());
  });
});
