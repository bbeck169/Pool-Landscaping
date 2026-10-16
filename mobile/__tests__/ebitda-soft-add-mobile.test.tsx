/**
 * EBITDA-SOFT-ADD · mobile mirror of web 73f5fbc9a + 892e4c38e.
 * Headline EBITDA + tap-to-reveal tooltip (web copy verbatim), EBIT kept as a
 * secondary chip, legacy rows (null ebitda) → EBIT figure + "EBIT only (legacy)".
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

jest.setTimeout(15000);

const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a), post: jest.fn() },
  api_base: () => "https://example.test/api",
  getAuthToken: async () => "tok",
}));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { id: "u1", role: "super_admin" } }) }));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock("expo-file-system/legacy", () => ({ cacheDirectory: "file:///c/", writeAsStringAsync: jest.fn(), EncodingType: { UTF8: "utf8" } }));
jest.mock("expo-sharing", () => ({ shareAsync: jest.fn(), isAvailableAsync: jest.fn(async () => true) }));
jest.mock("expo-print", () => ({ printToFileAsync: jest.fn(), printAsync: jest.fn() }));

import EbitTile from "@/src/components/dashboard/EbitTile";
import EbitPanel from "@/src/components/admin/EbitPanel";
import { EBITDA_TOOLTIP, resolveEbitda } from "@/src/utils/ebitda";

function textOf(el: any): string {
  if (el == null) return "";
  if (typeof el === "string" || typeof el === "number") return String(el);
  if (Array.isArray(el)) return el.map(textOf).join("");
  const kids = el?.props?.children;
  return kids !== undefined ? textOf(kids) : "";
}
const bucket = (month: string, ebit: number, ebitda?: number | null) =>
  ({ month, revenue: 0, cogs: 0, opex: 0, depreciation: 100, ebit, ...(ebitda === undefined ? {} : { ebitda }) });

// User-mandated exact wording (decoupled from web source; web patch ships in parallel).
const TOOLTIP_EXACT =
  "EBITDA: Earnings Before Interest, Taxes, Depreciation, and Amortization. " +
  "A financial metric used to measure a company's overall operational profitability and core earning power.";

beforeEach(() => mockApiGet.mockReset());

describe("EBITDA soft-add · tile", () => {
  it("headline EBITDA + tap-to-reveal tooltip matching web copy verbatim", async () => {
    mockApiGet.mockResolvedValueOnce({ months: 6, revenue_basis: "cash", series: [bucket("2026-01", 100, 200), bucket("2026-02", 300, 400)] });
    const q = render(<EbitTile />);
    await waitFor(() => q.getByTestId("dashboard-ebitda-tile-value"));
    expect(textOf(q.getByTestId("dashboard-ebit-tile-label"))).toBe("EBITDA · This month");
    expect(textOf(q.getByTestId("dashboard-ebitda-tile-value"))).toBe("$400");
    expect(textOf(q.getByTestId("dashboard-ebit-tile-delta"))).toContain("100.0%"); // 400 vs 200 → EBITDA delta
    expect(q.queryByTestId("dashboard-ebitda-info-text")).toBeNull();
    fireEvent.press(q.getByTestId("dashboard-ebitda-info-btn"));
    expect(textOf(q.getByTestId("dashboard-ebitda-info-text"))).toBe(EBITDA_TOOLTIP);
    expect(EBITDA_TOOLTIP).toBe(TOOLTIP_EXACT);
    expect(q.getByTestId("dashboard-ebitda-info-btn").props.accessibilityHint).toBe(EBITDA_TOOLTIP);
    fireEvent.press(q.getByTestId("dashboard-ebitda-info-btn"));
    expect(q.queryByTestId("dashboard-ebitda-info-text")).toBeNull();
  });

  it("EBIT stays visible as the secondary chip", async () => {
    mockApiGet.mockResolvedValueOnce({ months: 6, revenue_basis: "cash", series: [bucket("2026-02", -50, 50)] });
    const q = render(<EbitTile />);
    await waitFor(() => q.getByTestId("dashboard-ebit-tile-value"));
    expect(textOf(q.getByTestId("dashboard-ebit-tile-value"))).toBe("EBIT -$50");
    expect(textOf(q.getByTestId("dashboard-ebitda-tile-value"))).toBe("$50");
    expect(q.queryByTestId("dashboard-ebitda-tile-legacy-chip")).toBeNull();
  });

  it("legacy bucket (null ebitda) → EBIT figure + 'EBIT only (legacy)' chip, no EBITDA headline", async () => {
    mockApiGet.mockResolvedValueOnce({ months: 6, revenue_basis: "cash", series: [bucket("2026-01", 100, 999), bucket("2026-02", 150, null)] });
    const q = render(<EbitTile />);
    await waitFor(() => q.getByTestId("dashboard-ebitda-tile-legacy-chip"));
    expect(textOf(q.getByTestId("dashboard-ebitda-tile-legacy-chip"))).toBe("EBIT only (legacy)");
    expect(textOf(q.getByTestId("dashboard-ebit-tile-value"))).toBe("$150");
    expect(q.queryByTestId("dashboard-ebitda-tile-value")).toBeNull();
    expect(textOf(q.getByTestId("dashboard-ebit-tile-delta"))).toContain("50.0%"); // EBIT-vs-EBIT, not 150 vs 999
  });

  it("resolveEbitda: primary ebitda, fallback ebit + legacy flag", () => {
    expect(resolveEbitda({ ebit: 1, ebitda: 3 })).toEqual({ value: 3, legacy: false });
    expect(resolveEbitda({ ebit: 1, ebitda: 0 })).toEqual({ value: 0, legacy: false });
    expect(resolveEbitda({ ebit: 1, ebitda: null })).toEqual({ value: 1, legacy: true });
    expect(resolveEbitda({ ebit: 1 })).toEqual({ value: 1, legacy: true });
    expect(resolveEbitda(undefined)).toEqual({ value: 0, legacy: false });
  });
});

describe("EBITDA soft-add · panel", () => {
  const LIVE = { range_from: "2026-02-01", range_to: "2026-02-28", revenue_basis: "cash",
    revenue: 1500, cogs: 300, opex: 900, depreciation: 200, ebit: 100, ebitda: 300 };

  it("title EBITDA + tooltip; EBITDA (effective) headline with EBIT sub-line", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE);
    const q = render(<EbitPanel />);
    await waitFor(() => q.getByTestId("ebitda-total-value"));
    expect(textOf(q.getByTestId("ebit-panel-title"))).toBe("EBITDA");
    expect(textOf(q.getByTestId("ebitda-total-value"))).toContain("300.00");
    expect(textOf(q.getByTestId("ebit-total-value"))).toMatch(/^EBIT .*100\.00/);
    expect(q.getByText("EBITDA (effective)")).toBeTruthy();
    fireEvent.press(q.getByTestId("ebit-panel-title-info-btn"));
    expect(textOf(q.getByTestId("ebit-panel-title-info-text"))).toBe(EBITDA_TOOLTIP);
  });

  it("snapshot history: legacy row (no ebitda) gets the legacy chip; modern row shows EBITDA + EBIT", async () => {
    mockApiGet.mockResolvedValueOnce(LIVE).mockResolvedValueOnce({ snapshots: [
      { id: "new", version: 2, ebit: 150, ebitda: 350, revenue_basis: "cash", saved_at: "2026-02-10T00:00:00Z" },
      { id: "old", version: 1, ebit: 100, revenue_basis: "cash", saved_at: "2026-02-05T00:00:00Z" },
    ] });
    const q = render(<EbitPanel />);
    await waitFor(() => q.getByTestId("ebit-total-value"));
    await act(async () => { fireEvent.press(q.getByTestId("ebit-open-versions")); });
    await waitFor(() => q.getByTestId("ebit-versions-modal"));
    expect(textOf(q.getByTestId("ebit-versions-row-old-legacy"))).toBe("EBIT only (legacy)");
    expect(q.queryByTestId("ebit-versions-row-new-legacy")).toBeNull();
    expect(textOf(q.getByTestId("ebit-versions-row-new"))).toMatch(/EBITDA .*350\.00 · EBIT .*150\.00/);
  });
});
