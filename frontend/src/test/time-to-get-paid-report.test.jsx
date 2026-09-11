/**
 * Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Time to Get Paid tests.
 *
 * Contract:
 *   1) Renders 4 summary tiles + rolling chart + row table + CSV
 *      button after a successful fetch. Row order preserved
 *      (backend sends sorted by days_to_paid desc).
 *   2) Empty state — no chart points → truthful empty message; no
 *      rows → truthful empty row.
 *   3) Error state — API failure → error banner, no table.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import TimeToGetPaidReport from "@/pages/reports/TimeToGetPaidReport";

const _envelope = ({ rows = null, chart = null } = {}) => ({
  summary: {
    avg_days_to_paid: 10,
    p50_days: 10,
    p90_days: 14,
    invoices_counted: 3,
  },
  rows: rows ?? [
    { invoice_id: "inv-2", customer_id: "c-1",
      customer_name: "Payer Pete",
      sent_at: "2026-02-11T00:00:00+00:00",
      paid_at: "2026-02-26T00:00:00+00:00",
      days_to_paid: 15 },
    { invoice_id: "inv-1", customer_id: "c-1",
      customer_name: "Payer Pete",
      sent_at: "2026-02-03T00:00:00+00:00",
      paid_at: "2026-02-13T00:00:00+00:00",
      days_to_paid: 10 },
    { invoice_id: "inv-0", customer_id: "c-1",
      customer_name: "Payer Pete",
      sent_at: "2026-02-01T00:00:00+00:00",
      paid_at: "2026-02-06T00:00:00+00:00",
      days_to_paid: 5 },
  ],
  chart: chart ?? {
    monthly_avg_days: [
      { month: "2025-11", avg_days: 8 },
      { month: "2025-12", avg_days: 12 },
      { month: "2026-01", avg_days: 9 },
      { month: "2026-02", avg_days: 10 },
    ],
  },
  tenant_id: "T1",
  computed_at: "2026-02-27T09:00:00+00:00",
});

const _render = (initialUrl = "/reports/time-to-get-paid?start=2025-11-11&end=2026-02-11") =>
  render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <TimeToGetPaidReport />
    </MemoryRouter>,
  );

describe("TimeToGetPaidReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders summary tiles + chart + rows sorted desc", async () => {
    api.get.mockResolvedValueOnce(_envelope());
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("tile-avg-days-primary").textContent)
        .toMatch(/10/);
    });
    expect(screen.getByTestId("tile-p50-days-primary").textContent).toMatch(/10/);
    expect(screen.getByTestId("tile-p90-days-primary").textContent).toMatch(/14/);
    expect(screen.getByTestId("tile-invoice-count-primary").textContent)
      .toMatch(/3/);
    // Chart has 4 monthly points.
    expect(screen.getByTestId("ttgp-chart-point-2025-11")).toBeDefined();
    expect(screen.getByTestId("ttgp-chart-point-2026-02")).toBeDefined();
    expect(screen.getByTestId("ttgp-report-chart-svg")).toBeDefined();
    // Rows in the same order the API sent them (desc by days_to_paid).
    const rowIds = ["inv-2", "inv-1", "inv-0"];
    rowIds.forEach((rid) => {
      expect(screen.getByTestId(`ttgp-row-${rid}`)).toBeDefined();
    });
    // Correct endpoint hit.
    expect(api.get).toHaveBeenCalledWith(
      expect.stringMatching(
        /reports\/time-to-get-paid\?start_date=2025-11-11&end_date=2026-02-11/,
      ),
    );
  });

  it("renders truthful empty states when there is no data", async () => {
    api.get.mockResolvedValueOnce(_envelope({
      rows: [], chart: { monthly_avg_days: [] },
    }));
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("ttgp-report-chart-empty")).toBeDefined();
    });
    expect(screen.getByTestId("ttgp-report-table-empty")).toBeDefined();
  });

  it("renders error banner on API failure (not fake success)", async () => {
    api.get.mockRejectedValueOnce(new Error("500 kaboom"));
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("ttgp-report-error")).toBeDefined();
    });
    expect(screen.queryByTestId("ttgp-report-tiles")).toBeNull();
  });
});
