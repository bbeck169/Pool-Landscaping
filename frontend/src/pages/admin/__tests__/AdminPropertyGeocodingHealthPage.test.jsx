/**
 * Phase A.5 · Feb-2026 — Property Geocoding Health admin page vitest.
 *
 * Verifies:
 *   1. Renders count tiles with values from GET /admin/diagnostics/property-geocoding.
 *   2. Renders duplicate-cluster list when the server returns clusters.
 *   3. "Run backfill (dry run)" button posts dry_run=true and shows candidate count.
 *   4. "Confirm backfill" is disabled until a dry-run returns candidates > 0.
 *   5. "Confirm backfill" posts dry_run=false after a successful dry run.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
const postMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: (...args) => postMock(...args),
  },
}));

vi.mock("@/components/layout/SafeScrollContainer", () => ({
  default: ({ children, ...rest }) => <div {...rest}>{children}</div>,
}));

import AdminPropertyGeocodingHealthPage
  from "@/pages/admin/AdminPropertyGeocodingHealthPage";

const DIAG_PAYLOAD = {
  total_properties: 7036,
  with_valid_coords: 280,
  null_coords: 6756,
  zero_coords: 0,
  sample_null: [],
  sample_zero: [],
  duplicate_coord_clusters: [
    { lat: 33.5806, lng: -112.2374, property_count: 235,
      property_ids: ["p1", "p2"],
      property_labels: ["Main", "P0", "P1"] },
    { lat: 33.4483, lng: -112.0725, property_count: 12,
      property_ids: ["p3", "p4"],
      property_labels: ["Main", "Main", "Main"] },
  ],
};

describe("AdminPropertyGeocodingHealthPage", () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    getMock.mockResolvedValue(DIAG_PAYLOAD);
  });
  afterEach(() => cleanup());

  it("renders count tiles with values from the diagnostic endpoint", async () => {
    render(
      <MemoryRouter>
        <AdminPropertyGeocodingHealthPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith(
        "/admin/diagnostics/property-geocoding");
    });
    await waitFor(() => {
      expect(screen.getByTestId("pg-count-total").textContent)
        .toMatch(/7,036/);
    });
    expect(screen.getByTestId("pg-count-valid").textContent)
      .toMatch(/280/);
    expect(screen.getByTestId("pg-count-null").textContent)
      .toMatch(/6,756/);
    expect(screen.getByTestId("pg-count-zero").textContent)
      .toMatch(/^.*Zero coords.*0$/s);
  });

  it("renders duplicate-cluster rows when the server returns clusters", async () => {
    render(
      <MemoryRouter>
        <AdminPropertyGeocodingHealthPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("pg-cluster-0")).toBeTruthy();
    });
    const c0 = screen.getByTestId("pg-cluster-0");
    expect(c0.textContent).toMatch(/33\.5806/);
    expect(c0.textContent).toMatch(/-112\.2374/);
    expect(c0.textContent).toMatch(/235 properties/);
  });

  it("dry-run button POSTs with dry_run=true and renders the candidate count", async () => {
    postMock.mockResolvedValue({
      dry_run: true, candidates: 150, processed: 0, updated: 0,
      failed: 0,
      sample_updates: [
        { property_id: "p-a", label: "Main", address: "1 Fake St" },
      ],
      errors: [],
    });
    render(
      <MemoryRouter>
        <AdminPropertyGeocodingHealthPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("pg-dry-run-btn"));
    await waitFor(() => {
      expect(postMock).toHaveBeenCalledWith(
        "/admin/properties/geocode-backfill",
        { dry_run: true, max_rows: 500 },
      );
    });
    await waitFor(() => {
      const r = screen.getByTestId("pg-dry-run-result");
      expect(r.textContent).toMatch(/150/);
      expect(r.textContent).toMatch(/Main.*1 Fake St/);
    });
  });

  it("confirm-backfill button is disabled before a successful dry run", async () => {
    render(
      <MemoryRouter>
        <AdminPropertyGeocodingHealthPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    const btn = screen.getByTestId("pg-confirm-backfill-btn");
    expect(btn.hasAttribute("disabled")).toBe(true);
  });

  it("confirm-backfill posts dry_run=false after a dry-run returns candidates", async () => {
    postMock.mockResolvedValueOnce({
      dry_run: true, candidates: 20, processed: 0, updated: 0,
      failed: 0, sample_updates: [], errors: [],
    });
    postMock.mockResolvedValueOnce({
      dry_run: false, candidates: 20, processed: 20, updated: 18,
      failed: 2, sample_updates: [], errors: [],
    });
    render(
      <MemoryRouter>
        <AdminPropertyGeocodingHealthPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("pg-dry-run-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("pg-dry-run-result")).toBeTruthy();
    });
    const confirm = screen.getByTestId("pg-confirm-backfill-btn");
    expect(confirm.hasAttribute("disabled")).toBe(false);
    fireEvent.click(confirm);
    await waitFor(() => {
      expect(postMock).toHaveBeenLastCalledWith(
        "/admin/properties/geocode-backfill",
        { dry_run: false, max_rows: 500 },
      );
    });
    await waitFor(() => {
      const r = screen.getByTestId("pg-live-result");
      expect(r.textContent).toMatch(/Backfill complete/);
      expect(r.textContent).toMatch(/Processed/);
    });
  });
});
