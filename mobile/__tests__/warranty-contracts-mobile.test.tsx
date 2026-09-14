/**
 * Warranty Contracts — Mobile parity tests.
 *
 * 5 cases:
 *   1. Portal empty state renders
 *   2. Portal card renders contract_name, coverage window, linked_summary
 *   3. Admin section empty state renders
 *   4. Admin section card renders linked_summary chip
 *   5. WarrantyCard renders expired badge for past-end contracts
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

// ── Mocks ──────────────────────────────────────────────────────────
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(),
  },
}));
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: { role: "customer" }, loading: false }),
}));
jest.mock("@/src/components/widgets", () => ({
  Header: () => null,
  NotificationBell: () => null,
}));
jest.mock("@/src/components/ui", () => ({
  Loading: () => null,
  EmptyState: ({ testID }: any) => {
    const { Text } = require("react-native");
    return <Text testID={testID}>Empty</Text>;
  },
}));
jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { cb(); }, []);
  },
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: "cust-1" }),
  useSegments: () => ["portal", "warranties"],
  Redirect: () => null,
  Stack: () => null,
}));

import { api } from "@/src/api";
const mockGet = api.get as jest.Mock;

import WarrantyCard from "@/src/components/warranties/WarrantyCard";
import CustomerWarrantiesSection from "@/src/components/warranties/CustomerWarrantiesSection";

// ── Tests ──────────────────────────────────────────────────────────

describe("WarrantyCard", () => {
  it("renders contract name, coverage window, and linked summary", () => {
    const w = {
      id: "w1",
      contract_name: "Pentair 3-Year",
      provider: "Pentair Inc.",
      coverage_start: "2025-06-01",
      coverage_end: "2028-06-01",
      linked_summary: { type: "equipment" as const, label: "Filter Pump · Pentair IntelliFlo" },
    };
    const { getByTestId, getByText } = render(
      <WarrantyCard warranty={w} index={0} testIdPrefix="test-warranty" />,
    );
    expect(getByTestId("test-warranty-card-0")).toBeTruthy();
    expect(getByTestId("test-warranty-card-name-0")).toBeTruthy();
    expect(getByText("Pentair 3-Year")).toBeTruthy();
    expect(getByTestId("test-warranty-card-window-0")).toBeTruthy();
    expect(getByText(/2025-06-01/)).toBeTruthy();
    expect(getByText(/2028-06-01/)).toBeTruthy();
    expect(getByTestId("test-warranty-card-link-0")).toBeTruthy();
    expect(getByText(/Filter Pump/)).toBeTruthy();
  });

  it("renders EXPIRED badge for past-end contracts", () => {
    const w = {
      id: "w2",
      contract_name: "Old Warranty",
      coverage_start: "2020-01-01",
      coverage_end: "2021-01-01",
    };
    const { getByText } = render(
      <WarrantyCard warranty={w} index={0} />,
    );
    expect(getByText("EXPIRED")).toBeTruthy();
  });
});

describe("CustomerWarrantiesSection", () => {
  beforeEach(() => mockGet.mockReset());

  it("renders empty state when API returns no items", async () => {
    mockGet.mockResolvedValueOnce({ items: [] });
    const { getByTestId } = render(
      <CustomerWarrantiesSection customerId="cust-1" />,
    );
    await waitFor(() => {
      expect(getByTestId("warranty-empty")).toBeTruthy();
    });
    expect(mockGet).toHaveBeenCalledWith("/customers/cust-1/warranties");
  });

  it("renders warranty cards when API returns items", async () => {
    mockGet.mockResolvedValueOnce({
      items: [
        {
          id: "w1",
          contract_name: "Gold Plan",
          provider: "Acme",
          coverage_start: "2025-01-01",
          coverage_end: "2027-01-01",
          linked_summary: { type: "install", label: "Pool Install · 2025-01-10" },
        },
      ],
    });
    const { getByTestId, getByText } = render(
      <CustomerWarrantiesSection customerId="cust-1" />,
    );
    await waitFor(() => {
      expect(getByTestId("warranty-card-0")).toBeTruthy();
    });
    expect(getByText("Gold Plan")).toBeTruthy();
    expect(getByTestId("warranty-card-link-0")).toBeTruthy();
    expect(getByText(/Pool Install/)).toBeTruthy();
  });

  it("renders error state on API failure", async () => {
    mockGet.mockRejectedValueOnce(new Error("Network error"));
    const { getByTestId } = render(
      <CustomerWarrantiesSection customerId="cust-1" />,
    );
    await waitFor(() => {
      expect(getByTestId("warranty-error")).toBeTruthy();
    });
  });
});
