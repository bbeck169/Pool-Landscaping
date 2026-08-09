/**
 * Phase 53e · Feb-2026 — EBIT dashboard tile (web) vitest suite.
 *
 * Covers the standalone <EbitTile /> component AND the Dashboard.jsx
 * mount-side role gate:
 *
 *   1. Loading state renders on first mount.
 *   2. Positive delta renders in green with "vs last month" pill.
 *   3. Negative delta renders in red.
 *   4. No-prior-month state renders when the series has only one point.
 *   5. Error state → retry button re-fetches.
 *   6. Sparkline renders one <rect> per series point + zero baseline line.
 *   7. "View report" link resolves to /admin/reports/profit.
 *   8. Dashboard.jsx role gate — admin + super_admin see the tile
 *      slot; manager does NOT. Static-source assertion so we don't
 *      have to boot the full dashboard graph inside vitest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const getMock = vi.fn();
vi.mock("@/api", () => ({ api: { get: (...a) => getMock(...a) } }));

import EbitTile from "@/components/dashboard/EbitTile";

// Fixture builders.
function series(values) {
  return values.map((ebit, i) => ({
    month: `2026-${String(i + 1).padStart(2, "0")}`,
    revenue: ebit + 500,
    cogs: 100,
    opex: 300,
    depreciation: 100,
    ebit,
  }));
}

beforeEach(() => {
  getMock.mockReset();
});
afterEach(() => cleanup());

function renderTile() {
  return render(
    <MemoryRouter>
      <EbitTile />
    </MemoryRouter>,
  );
}

describe("Phase 53e — EbitTile", () => {
  it("renders the loading state before the fetch resolves", async () => {
    let resolve;
    getMock.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    renderTile();
    expect(await screen.findByTestId("dashboard-ebit-tile")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-ebit-tile-loading")).toBeInTheDocument();
    resolve({ months: 6, revenue_basis: "cash", series: series([100]) });
  });

  it("fetches /ebit/trend?months=6&revenue_basis=cash", async () => {
    getMock.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash", series: series([100, 200]),
    });
    renderTile();
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith(
        "/ebit/trend?months=6&revenue_basis=cash");
    });
  });

  it("renders the current-month value + positive delta chip", async () => {
    // Prev month 100 → current 200 → +100.0%
    getMock.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash", series: series([100, 200]),
    });
    renderTile();
    const value = await screen.findByTestId("dashboard-ebit-tile-value");
    expect(value.textContent).toContain("$200");
    const delta = await screen.findByTestId("dashboard-ebit-tile-delta");
    expect(delta.textContent).toContain("100.0%");
    expect(delta.textContent).toContain("vs last month");
    // Green delta chip color (#16A34A normalizes to rgb(22, 163, 74)
    // in jsdom).
    expect(delta.getAttribute("style") || "")
      .toMatch(/rgb\(22,\s*163,\s*74\)/i);
  });

  it("renders a red delta chip when EBIT falls month over month", async () => {
    // 400 → 100 → -75.0%
    getMock.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash", series: series([400, 100]),
    });
    renderTile();
    const delta = await screen.findByTestId("dashboard-ebit-tile-delta");
    expect(delta.textContent).toContain("75.0%");
    // Red delta chip color (#DC2626 normalizes to rgb(220, 38, 38)).
    expect(delta.getAttribute("style") || "")
      .toMatch(/rgb\(220,\s*38,\s*38\)/i);
  });

  it("renders the no-prior-month state when the series has one point", async () => {
    getMock.mockResolvedValueOnce({
      months: 1, revenue_basis: "cash", series: series([250]),
    });
    renderTile();
    expect(await screen.findByTestId("dashboard-ebit-tile-no-prior"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("dashboard-ebit-tile-delta")).toBeNull();
  });

  it("renders the error state and retry re-fetches the trend", async () => {
    getMock
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        months: 6, revenue_basis: "cash", series: series([50, 75]),
      });
    renderTile();
    expect(await screen.findByTestId("dashboard-ebit-tile-error"))
      .toBeInTheDocument();
    fireEvent.click(screen.getByTestId("dashboard-ebit-tile-retry"));
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByTestId("dashboard-ebit-tile-value"))
      .toBeInTheDocument();
  });

  it("sparkline renders one bar per series point + a zero baseline", async () => {
    getMock.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash",
      series: series([100, -50, 200, 300, -100, 400]),
    });
    renderTile();
    const spark = await screen.findByTestId("dashboard-ebit-tile-sparkline");
    // Phase 53f drill-down: each series point renders TWO <rect>s —
    // a full-height transparent hit-target (so zero-height bars stay
    // clickable) + the visible ebit bar. So 6 points × 2 = 12 rects.
    // Assert one visible-bar rect per point via the per-bar testid
    // instead, and keep the single <line> zero baseline.
    expect(spark.querySelectorAll("rect").length).toBe(12);
    expect(spark.querySelectorAll("[data-testid^='dashboard-ebit-tile-sparkline-bar-']").length)
      .toBe(6);
    expect(spark.querySelectorAll("line").length).toBe(1);
  });

  it("View report link points at /admin/reports/profit", async () => {
    getMock.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash", series: series([100]),
    });
    renderTile();
    const link = await screen.findByTestId("dashboard-ebit-tile-report-link");
    expect(link.getAttribute("href")).toBe("/admin/reports/profit");
  });

  it("Dashboard.jsx gates the EBIT tile slot to super_admin + admin", async () => {
    // Static-source assertion — the Dashboard component's transitive
    // dep graph is too heavy for vitest to mount reliably (see
    // vitest.config.js Phase 41.5 exclude notes), so we assert the
    // gate directly at the source level. This still catches an
    // accidental gate widening (e.g. someone dropping `admin` or
    // adding `manager`).
    const fs = await import("fs");
    const path = await import("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/admin/Dashboard.jsx"), "utf8");
    // Only super_admin + admin should be inside the gate expression
    // that wraps <EbitTile />.
    expect(src).toMatch(
      /super_admin.*admin.*<EbitTile\s*\/?>/s);
    // Manager must NOT appear inside the gate expression that wraps
    // the tile slot. Grab the slot block and assert `"manager"` is
    // not the third role in that same conditional.
    const slotIdx = src.indexOf("dashboard-ebit-tile-slot");
    expect(slotIdx).toBeGreaterThan(-1);
    // 400-char window before the slot testid captures the whole gate
    // expression on the previous few lines.
    const gateWindow = src.slice(Math.max(0, slotIdx - 400), slotIdx);
    expect(gateWindow).not.toMatch(/"manager"/);
  });
});
