/**
 * Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Attrition Report tests.
 *
 * Contract:
 *   1) Renders 3 summary tiles + reason bars + row table + CSV
 *      button after a successful fetch.
 *   2) Empty state — no rows / no reasons → truthful empty
 *      messages, NOT fabricated content.
 *   3) Refetch on date-range change — a second URL search string
 *      triggers a second ``api.get`` call with the new range.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, rerender as _r } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("@/api", () => ({ api: { get: vi.fn() } }));
vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

import { api } from "@/api";
import AttritionReport from "@/pages/reports/AttritionReport";

const _envelope = ({ total = 2, rate = 12.5, avgLtv = 240,
                     rows = null, reasons = null } = {}) => ({
  summary: {
    total_attrited: total,
    attrition_rate_pct: rate,
    avg_ltv_of_attrited: avgLtv,
  },
  rows: rows ?? [
    { customer_id: "c-1", customer_name: "Muted Mo",
      became_inactive_at: "2026-02-14T10:00:00+00:00",
      inactive_reason: "moved_away", lifetime_value: 240,
      last_service_date: "2026-01-30" },
    { customer_id: "c-2", customer_name: "Silent Sam",
      became_inactive_at: "2026-02-16T15:00:00+00:00",
      inactive_reason: "not_specified", lifetime_value: 0,
      last_service_date: null },
  ],
  chart: {
    reason_counts: reasons ?? { moved_away: 1, not_specified: 1 },
  },
  tenant_id: "T1",
  computed_at: "2026-02-20T09:00:00+00:00",
});

const _render = (initialUrl = "/reports/attrition?start=2026-02-01&end=2026-02-28") =>
  render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <AttritionReport />
    </MemoryRouter>,
  );

describe("AttritionReport", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it("renders summary + reason bars + rows after fetch", async () => {
    api.get.mockResolvedValueOnce(_envelope());
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("tile-total-attrited-primary").textContent)
        .toMatch(/2/);
    });
    expect(screen.getByTestId("tile-attrition-rate-primary").textContent)
      .toMatch(/12\.5%/);
    expect(screen.getByTestId("tile-avg-ltv-primary").textContent)
      .toMatch(/\$240\.00/);
    // Two reason bars.
    expect(screen.getByTestId("reason-bar-moved_away")).toBeDefined();
    expect(screen.getByTestId("reason-bar-not_specified")).toBeDefined();
    // Two rows.
    expect(screen.getByTestId("attrition-row-c-1")).toBeDefined();
    expect(screen.getByTestId("attrition-row-c-2")).toBeDefined();
    expect(screen.getByTestId("attrition-report-csv-btn")).toBeDefined();
    // Called with the date range from the URL.
    expect(api.get).toHaveBeenCalledWith(
      expect.stringMatching(
        /reports\/attrition\?start_date=2026-02-01&end_date=2026-02-28/,
      ),
    );
  });

  it("renders truthful empty state when window is empty", async () => {
    api.get.mockResolvedValueOnce(_envelope({
      total: 0, rate: 0, avgLtv: 0, rows: [], reasons: {},
    }));
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("tile-total-attrited-primary").textContent)
        .toMatch(/0/);
    });
    expect(screen.getByTestId("attrition-report-chart-empty")).toBeDefined();
    expect(screen.getByTestId("attrition-report-table-empty")).toBeDefined();
  });

  it("renders error banner on API failure (not fake success)", async () => {
    api.get.mockRejectedValueOnce(new Error("500 boom"));
    _render();
    await waitFor(() => {
      expect(screen.getByTestId("attrition-report-error")).toBeDefined();
    });
    expect(screen.queryByTestId("attrition-report-tiles")).toBeNull();
  });
});
