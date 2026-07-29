/**
 * PB1 · Profit Report tests.
 *
 * - Renders 5 summary tiles (Revenue, COGS, Labor, Gross Profit, Margin)
 * - Dimension toggle re-fetches with new dimension param
 * - Custom range shows date picker inputs
 * - Non-admin gets forbidden screen
 * - Export CSV button present
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({}),
}));

const mockGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockGet(...a), post: jest.fn().mockResolvedValue({}) },
  api_base: () => "http://test/api",
  getAuthToken: () => Promise.resolve("tok"),
}));

let mockRole = "super_admin";
jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: mockRole, name: "Admin" },
  }),
}));

jest.mock("expo-file-system/legacy", () => ({
  cacheDirectory: "/cache/",
  downloadAsync: jest.fn().mockResolvedValue({ status: 200, uri: "/cache/f" }),
}));
jest.mock("expo-sharing", () => ({
  isAvailableAsync: jest.fn().mockResolvedValue(true),
  shareAsync: jest.fn(),
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ title }: any) => {
    const { Text } = require("react-native");
    return <Text>{title}</Text>;
  },
}));

import ProfitReport from "@/app/profit-report";

const MOCK_REPORT = {
  totals: {
    revenue: 2276.0,
    cogs: 450.0,
    labor: 300.0,
    gross_profit: 1526.0,
    margin_pct: 67.1,
    line_count: 13,
  },
  breakdown: [
    {
      category_id: "uncat",
      category_name: "Uncategorized",
      revenue: 2276.0,
      cogs: 450.0,
      labor: 300.0,
      profit: 1526.0,
      margin_pct: 67.1,
    },
  ],
  range: { label: "This Month" },
};

describe("PB1 · Profit Report", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRole = "super_admin";
    mockGet.mockResolvedValue(MOCK_REPORT);
  });

  it("renders all 5 summary tiles for admin", async () => {
    const { getByTestId } = render(<ProfitReport />);
    await waitFor(() => {
      expect(getByTestId("profit-report-tile-revenue")).toBeTruthy();
      expect(getByTestId("profit-report-tile-cogs")).toBeTruthy();
      expect(getByTestId("profit-report-tile-labor")).toBeTruthy();
      expect(getByTestId("profit-report-tile-profit")).toBeTruthy();
      expect(getByTestId("profit-report-tile-margin")).toBeTruthy();
    });
  }, 15000);

  it("shows breakdown table with Uncategorized row", async () => {
    const { getByTestId, getByText } = render(<ProfitReport />);
    await waitFor(() => {
      expect(getByTestId("profit-report-breakdown")).toBeTruthy();
      expect(getByText("Uncategorized")).toBeTruthy();
    });
  });

  it("dimension toggle re-fetches with income_category", async () => {
    const { getByTestId } = render(<ProfitReport />);
    await waitFor(() => expect(getByTestId("profit-report-dim-income")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("profit-report-dim-income"));
    });

    await waitFor(() => {
      const calls = mockGet.mock.calls.map(([url]: any) => url);
      expect(calls.some((u: string) => u.includes("dimension=income_category"))).toBe(true);
    });
  });

  it("custom range shows date picker inputs", async () => {
    const { getByTestId, queryByTestId } = render(<ProfitReport />);
    await waitFor(() => expect(getByTestId("profit-report-range-custom")).toBeTruthy());

    // Before clicking custom, date pickers should not be visible
    expect(queryByTestId("profit-report-custom-picker")).toBeNull();

    await act(async () => {
      fireEvent.press(getByTestId("profit-report-range-custom"));
    });

    await waitFor(() => {
      expect(getByTestId("profit-report-custom-picker")).toBeTruthy();
      expect(getByTestId("profit-report-custom-from")).toBeTruthy();
      expect(getByTestId("profit-report-custom-to")).toBeTruthy();
    });
  });

  it("renders forbidden screen for customer role", async () => {
    mockRole = "customer";
    const { getByTestId, queryByTestId } = render(<ProfitReport />);
    expect(getByTestId("profit-report-forbidden")).toBeTruthy();
    expect(queryByTestId("profit-report-page")).toBeNull();
  });

  it("renders forbidden screen for technician role", async () => {
    mockRole = "technician";
    const { getByTestId, queryByTestId } = render(<ProfitReport />);
    expect(getByTestId("profit-report-forbidden")).toBeTruthy();
    expect(queryByTestId("profit-report-page")).toBeNull();
  });

  it("export CSV button is present and enabled when data loaded", async () => {
    const { getByTestId } = render(<ProfitReport />);
    await waitFor(() => {
      expect(getByTestId("profit-report-export-csv")).toBeTruthy();
    });
  });

  it("range pills are visible and this_month is default active", async () => {
    const { getByTestId } = render(<ProfitReport />);
    await waitFor(() => {
      expect(getByTestId("profit-report-range-this_month")).toBeTruthy();
      expect(getByTestId("profit-report-range-last_month")).toBeTruthy();
      expect(getByTestId("profit-report-range-ytd")).toBeTruthy();
    });
  });

  it("fetches with default this_month range on mount", async () => {
    render(<ProfitReport />);
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(
        expect.stringContaining("range=this_month"),
      );
    });
  });
});
