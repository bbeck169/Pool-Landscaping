/**
 * Phase 53e · Feb-2026 — Mobile EBIT dashboard tile jest suite.
 *
 * Mounts <EbitTile /> in isolation with every native dep mocked.
 * Covers:
 *   1. Loading state on first mount.
 *   2. Fetch call shape — /ebit/trend?months=6&revenue_basis=cash.
 *   3. Positive-delta chip renders green.
 *   4. Negative-delta chip renders red.
 *   5. No-prior-month state when series length == 1.
 *   6. Error state + retry re-fetches.
 *   7. Sparkline renders one bar per series point.
 *   8. View-report link routes to /profit-report.
 *   9. Dashboard.tsx mount-side role gate — the tile slot is
 *      wrapped in a super_admin + admin conditional (source-level
 *      assertion; manager is excluded).
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

jest.setTimeout(15000);

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a) },
}));

const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: (...a: any[]) => mockPush(...a) }),
}));

import EbitTile from "@/src/components/dashboard/EbitTile";

function textOf(el: any): string {
  if (el == null) return "";
  if (typeof el === "string" || typeof el === "number") return String(el);
  if (Array.isArray(el)) return el.map(textOf).join("");
  const kids = el?.props?.children;
  return kids !== undefined ? textOf(kids) : "";
}

function series(values: number[]) {
  return values.map((ebit, i) => ({
    month: `2026-${String(i + 1).padStart(2, "0")}`,
    revenue: ebit + 500,
    cogs: 100,
    opex: 300,
    depreciation: 100,
    ebit,
    // EBITDA-SOFT-ADD — post-TD-59 wire shape carries ebitda too (web
    // 892e4c38e uses ebitda = ebit so delta % stays locked).
    ebitda: ebit,
  }));
}

beforeEach(() => {
  mockApiGet.mockReset();
  mockPush.mockReset();
});

describe("Phase 53e · Mobile · EbitTile", () => {
  it("renders the loading state before the fetch resolves", async () => {
    let resolve: any;
    mockApiGet.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    const { getByTestId } = render(<EbitTile />);
    expect(getByTestId("dashboard-ebit-tile-loading")).toBeTruthy();
    await act(async () => {
      resolve({ months: 6, revenue_basis: "cash", series: series([100]) });
    });
  });

  it("fetches /ebit/trend?months=6&revenue_basis=cash on mount", async () => {
    mockApiGet.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash", series: series([100, 200]),
    });
    render(<EbitTile />);
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
    expect(mockApiGet.mock.calls[0][0])
      .toBe("/ebit/trend?months=6&revenue_basis=cash");
  });

  it("renders the current-month value + positive delta chip (green)", async () => {
    mockApiGet.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash", series: series([100, 200]),
    });
    const { getByTestId } = render(<EbitTile />);
    await waitFor(() => getByTestId("dashboard-ebit-tile-value"));
    expect(textOf(getByTestId("dashboard-ebit-tile-value"))).toContain("$200");
    // EBITDA-SOFT-ADD — headline is EBITDA; EBIT moved to the secondary chip.
    expect(textOf(getByTestId("dashboard-ebitda-tile-value"))).toBe("$200");
    expect(textOf(getByTestId("dashboard-ebit-tile-value"))).toBe("EBIT $200");
    const chip = getByTestId("dashboard-ebit-tile-delta");
    expect(textOf(chip)).toContain("100.0%");
    // The chip background is green (#DCFCE7) on positive delta.
    const flat = Array.isArray(chip.props.style)
      ? chip.props.style.reduce((a: any, b: any) => ({ ...a, ...(b || {}) }), {})
      : chip.props.style;
    expect(String(flat?.backgroundColor || "")).toMatch(/DCFCE7/i);
  });

  it("renders a red delta chip when EBIT falls month over month", async () => {
    mockApiGet.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash", series: series([400, 100]),
    });
    const { getByTestId } = render(<EbitTile />);
    await waitFor(() => getByTestId("dashboard-ebit-tile-delta"));
    const chip = getByTestId("dashboard-ebit-tile-delta");
    expect(textOf(chip)).toContain("75.0%");
    const flat = Array.isArray(chip.props.style)
      ? chip.props.style.reduce((a: any, b: any) => ({ ...a, ...(b || {}) }), {})
      : chip.props.style;
    expect(String(flat?.backgroundColor || "")).toMatch(/FEE2E2/i);
  });

  it("renders the no-prior-month state when the series has one point", async () => {
    mockApiGet.mockResolvedValueOnce({
      months: 1, revenue_basis: "cash", series: series([250]),
    });
    const { getByTestId, queryByTestId } = render(<EbitTile />);
    await waitFor(() => getByTestId("dashboard-ebit-tile-no-prior"));
    expect(queryByTestId("dashboard-ebit-tile-delta")).toBeNull();
  });

  it("renders the error state and retry re-fetches the trend", async () => {
    mockApiGet
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        months: 6, revenue_basis: "cash", series: series([50, 75]),
      });
    const { getByTestId } = render(<EbitTile />);
    await waitFor(() => getByTestId("dashboard-ebit-tile-error"));
    await act(async () => {
      fireEvent.press(getByTestId("dashboard-ebit-tile-retry"));
    });
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
    await waitFor(() => getByTestId("dashboard-ebit-tile-value"));
  });

  it("sparkline renders one bar per series point", async () => {
    mockApiGet.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash",
      series: series([100, -50, 200, 300, -100, 400]),
    });
    const { getByTestId, getAllByTestId } = render(<EbitTile />);
    await waitFor(() => getByTestId("dashboard-ebit-tile-sparkline"));
    const bars = getAllByTestId(/dashboard-ebit-tile-sparkline-bar-\d+/);
    expect(bars.length).toBe(6);
  });

  it("View report link routes to /profit-report", async () => {
    mockApiGet.mockResolvedValueOnce({
      months: 6, revenue_basis: "cash", series: series([100]),
    });
    const { getByTestId } = render(<EbitTile />);
    await waitFor(() => getByTestId("dashboard-ebit-tile-report-link"));
    await act(async () => {
      fireEvent.press(getByTestId("dashboard-ebit-tile-report-link"));
    });
    expect(mockPush).toHaveBeenCalledWith("/profit-report");
  });

  it("Mobile dashboard gates the EBIT tile slot to super_admin + admin", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../app/(app)/index.tsx"), "utf8");
    // The slot testid must be present.
    const slotIdx = src.indexOf("dashboard-ebit-tile-slot");
    expect(slotIdx).toBeGreaterThan(-1);
    // The wrapping gate references BOTH super_admin AND admin roles.
    const gateWindow = src.slice(Math.max(0, slotIdx - 400), slotIdx);
    expect(gateWindow).toMatch(/"super_admin"/);
    expect(gateWindow).toMatch(/"admin"/);
    // And manager MUST NOT appear inside the tile-slot gate window.
    expect(gateWindow).not.toMatch(/"manager"/);
  });
});
