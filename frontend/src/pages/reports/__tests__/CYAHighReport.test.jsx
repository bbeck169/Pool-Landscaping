/**
 * Feb-2026 · CYA Over-Threshold Report vitests.
 *
 * Covers the 8 FE cases locked in the operator dispatch:
 *   1. Renders tile in ReportsHub source
 *   2. Loads data and renders table rows
 *   3. Empty state when count = 0
 *   4. Error state on API failure
 *   5. Customer name link navigates to /customers/{id}
 *   6. CSV button triggers download
 *   7. Threshold change refetches with query param
 *   8. Date range change refetches
 */
import fs from "node:fs";
import path from "node:path";

import React from "react";
import {
  describe, it, expect, vi, beforeEach,
} from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, fireEvent, waitFor, within,
} from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));
vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    post: vi.fn(),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));

vi.mock("@/hooks/use-toast", () => ({
  toast: vi.fn(),
}));

// PageHeader minimal shim — the real one pulls in theme + layout
// context that the test env doesn't need to exercise here.
vi.mock("@/components/layout/PageHeader", () => ({
  default: ({ title, subtitle }) => (
    <header>
      <h1>{title}</h1>
      {subtitle ? <div>{subtitle}</div> : null}
    </header>
  ),
}));

import CYAHighReport from "../CYAHighReport";


function _mkItems(n = 2) {
  return Array.from({ length: n }).map((_, i) => ({
    customer_id: `cust-${i + 1}`,
    customer_name: `Customer ${i + 1}`,
    last_value: 110 + i,
    last_date: "2026-02-15T10:00:00Z",
    max_value: 150 + i,
    max_date: "2026-02-14T10:00:00Z",
    reading_count_over_threshold: 2 + i,
  }));
}


function _mkResponse(threshold = 100, items = _mkItems()) {
  return { threshold, count: items.length, items };
}


describe("CYAHighReport", () => {
  beforeEach(() => {
    getSpy.mockReset();
  });

  // 1. ReportsHub tile source registration (lightweight static check
  //    — avoids re-rendering the full ReportsHub + mocking every KPI
  //    endpoint it fans out to).
  it("1. registers a tile in ReportsHub source", () => {
    const hubPath = path.resolve(
      __dirname, "..", "ReportsHub.jsx",
    );
    const src = fs.readFileSync(hubPath, "utf8");
    expect(src).toContain('key: "cya-high"');
    expect(src).toContain("CYA Over Threshold");
    expect(src).toContain("/reports/cya-high");
  });

  // 2. Loads data and renders table rows.
  it("2. loads items and renders a row per customer", async () => {
    getSpy.mockResolvedValueOnce(_mkResponse(100, _mkItems(2)));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-high-table")).toBeTruthy();
    });
    expect(screen.getByTestId("cya-row-cust-1")).toBeTruthy();
    expect(screen.getByTestId("cya-row-cust-2")).toBeTruthy();
    expect(screen.getByText("Customer 1")).toBeTruthy();
  });

  // 3. Empty state.
  it("3. shows empty state when count = 0", async () => {
    getSpy.mockResolvedValueOnce(_mkResponse(100, []));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-high-empty")).toBeTruthy();
    });
    expect(screen.queryByTestId("cya-high-table")).toBeNull();
  });

  // 4. Error state on API failure.
  it("4. shows error state when the API throws", async () => {
    getSpy.mockRejectedValueOnce(new Error("boom"));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-high-error")).toBeTruthy();
    });
    expect(screen.getByTestId("cya-high-error").textContent).toContain(
      "boom",
    );
  });

  // 5. Customer name link navigates to /customers/{id}.
  it("5. customer-name cell links to /customers/{id}", async () => {
    getSpy.mockResolvedValueOnce(_mkResponse(100, _mkItems(1)));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-row-cust-1")).toBeTruthy();
    });
    const row = screen.getByTestId("cya-row-cust-1");
    const anchor = within(row).getByRole("link");
    expect(anchor.getAttribute("href")).toBe("/customers/cust-1");
  });

  // 6. CSV button triggers a download (URL.createObjectURL +
  //    anchor.click are the observable side-effects).
  it("6. CSV button triggers a download via Blob + anchor click", async () => {
    const createObjSpy = vi.fn(() => "blob:fake");
    const revokeSpy = vi.fn();
    const origCreate = URL.createObjectURL;
    const origRevoke = URL.revokeObjectURL;
    URL.createObjectURL = createObjSpy;
    URL.revokeObjectURL = revokeSpy;

    getSpy.mockResolvedValueOnce(_mkResponse(100, _mkItems(1)));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-export-csv-btn")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("cya-export-csv-btn"));
    expect(createObjSpy).toHaveBeenCalledTimes(1);
    expect(revokeSpy).toHaveBeenCalledTimes(1);

    URL.createObjectURL = origCreate;
    URL.revokeObjectURL = origRevoke;
  });

  // 7. Threshold change refetches with the new query param.
  it("7. threshold change refetches with ?threshold= in the URL", async () => {
    getSpy
      .mockResolvedValueOnce(_mkResponse(100, _mkItems(1)))
      .mockResolvedValueOnce(_mkResponse(50, _mkItems(2)));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(1));
    expect(getSpy.mock.calls[0][0]).toContain("threshold=100");

    fireEvent.change(screen.getByTestId("cya-threshold-input"), {
      target: { value: "50" },
    });
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
    expect(getSpy.mock.calls[1][0]).toContain("threshold=50");
  });

  // 8. Date range change refetches with ?from=/?to= in the URL.
  it("8. date-range change refetches with ?from= and ?to=", async () => {
    getSpy
      .mockResolvedValueOnce(_mkResponse(100, _mkItems(1)))
      .mockResolvedValueOnce(_mkResponse(100, _mkItems(1)))
      .mockResolvedValueOnce(_mkResponse(100, _mkItems(1)));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByTestId("cya-from-input"), {
      target: { value: "2026-01-01" },
    });
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
    expect(getSpy.mock.calls[1][0]).toContain("from=2026-01-01");

    fireEvent.change(screen.getByTestId("cya-to-input"), {
      target: { value: "2026-02-28" },
    });
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(3));
    expect(getSpy.mock.calls[2][0]).toContain("to=2026-02-28");
  });
});
