/**
 * Feb-2026 · Reports Gap Fill Phase 5a.1 — Business Snapshot page tests.
 *
 * Contract:
 *   1. Renders the three tiles + CSV export button + computed-at
 *      timestamp after a successful fetch.
 *   2. Error state renders (not a fake success) when the API
 *      returns a failure.
 *   3. Empty/null values render as em-dash — never fabricated.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({
  api: { get: vi.fn() },
}));
vi.mock("@/hooks/use-toast", () => ({
  toast: vi.fn(),
}));

import { api } from "@/api";
import BusinessSnapshot from "@/pages/reports/BusinessSnapshot";

describe("BusinessSnapshot", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders the three tiles + CSV button + computed-at after fetch", async () => {
    api.get.mockResolvedValueOnce({
      service_radius: { max_miles: 25, avg_last_30d_miles: 12.4 },
      employee_count: 7,
      bh_per_week_capacity: 280,
      tenant_id: "T1",
      computed_at: "2026-02-11T09:00:00+00:00",
    });
    render(
      <MemoryRouter>
        <BusinessSnapshot />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("tile-service-radius-primary").textContent)
        .toMatch(/25/);
    });
    expect(screen.getByTestId("tile-service-radius-secondary").textContent)
      .toMatch(/12\.4/);
    expect(screen.getByTestId("tile-employee-count-primary").textContent)
      .toMatch(/7/);
    expect(screen.getByTestId("tile-bh-per-week-primary").textContent)
      .toMatch(/280/);
    expect(screen.getByTestId("business-snapshot-csv-btn")).toBeDefined();
    expect(screen.getByTestId("business-snapshot-computed-at").textContent)
      .toMatch(/Computed at:/);
  });

  it("renders truthful em-dash for null service_radius", async () => {
    api.get.mockResolvedValueOnce({
      service_radius: { max_miles: null, avg_last_30d_miles: null },
      employee_count: 0,
      bh_per_week_capacity: 0,
      tenant_id: "T2",
      computed_at: "2026-02-11T09:00:00+00:00",
    });
    render(
      <MemoryRouter>
        <BusinessSnapshot />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("tile-service-radius-primary").textContent)
        .toMatch(/—/);
    });
    expect(screen.getByTestId("tile-service-radius-secondary").textContent)
      .toMatch(/—/);
  });

  it("renders error banner on API failure (not fake success)", async () => {
    api.get.mockRejectedValueOnce(new Error("500 provider blown"));
    render(
      <MemoryRouter>
        <BusinessSnapshot />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("business-snapshot-error")).toBeDefined();
    });
    expect(screen.getByTestId("business-snapshot-error").textContent)
      .toMatch(/500 provider blown/);
    // No tile grid rendered on error.
    expect(screen.queryByTestId("business-snapshot-tiles")).toBeNull();
  });
});
