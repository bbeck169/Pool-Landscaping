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
import { render, waitFor, fireEvent } from "@testing-library/react-native";

// ── Mocks ──────────────────────────────────────────────────────────
jest.mock("@/src/api", () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    patch: jest.fn(),
    del: jest.fn(),
  },
}));
jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: jest.fn() }),
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
const mockPost = api.post as jest.Mock;
const mockPatch = api.patch as jest.Mock;
const mockDel = api.del as jest.Mock;

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
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
    mockDel.mockReset();
  });

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

  it("shows Add Warranty button and opens form modal", async () => {
    mockGet.mockResolvedValueOnce({ items: [] });
    const { getByTestId } = render(
      <CustomerWarrantiesSection customerId="cust-1" />,
    );
    await waitFor(() => {
      expect(getByTestId("warranty-add-btn")).toBeTruthy();
    });
    fireEvent.press(getByTestId("warranty-add-btn"));
    await waitFor(() => {
      expect(getByTestId("warranty-modal")).toBeTruthy();
      expect(getByTestId("warranty-contract-name-input")).toBeTruthy();
      expect(getByTestId("warranty-provider-input")).toBeTruthy();
      expect(getByTestId("warranty-coverage-start-input")).toBeTruthy();
      expect(getByTestId("warranty-coverage-end-input")).toBeTruthy();
      expect(getByTestId("warranty-linked-type-select")).toBeTruthy();
    });
  });

  it("submits correct payload to POST /api/warranties/contracts", async () => {
    mockGet.mockResolvedValueOnce({ items: [] });
    mockPost.mockResolvedValueOnce({ id: "new-w" });
    // After save, reload
    mockGet.mockResolvedValueOnce({ items: [{ id: "new-w", contract_name: "Test Plan" }] });

    const { getByTestId } = render(
      <CustomerWarrantiesSection customerId="cust-1" />,
    );
    await waitFor(() => {
      expect(getByTestId("warranty-add-btn")).toBeTruthy();
    });

    fireEvent.press(getByTestId("warranty-add-btn"));
    await waitFor(() => {
      expect(getByTestId("warranty-contract-name-input")).toBeTruthy();
    });

    fireEvent.changeText(getByTestId("warranty-contract-name-input"), "Test Plan");
    fireEvent.changeText(getByTestId("warranty-provider-input"), "Acme Corp");
    fireEvent.changeText(getByTestId("warranty-coverage-start-input"), "2025-01-01");
    fireEvent.changeText(getByTestId("warranty-coverage-end-input"), "2028-01-01");

    fireEvent.press(getByTestId("warranty-modal-save-btn"));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        "/warranties/contracts",
        expect.objectContaining({
          customer_id: "cust-1",
          contract_name: "Test Plan",
          provider: "Acme Corp",
          coverage_start: "2025-01-01",
          coverage_end: "2028-01-01",
          linked_type: "none",
          linked_id: null,
        }),
      );
    });
  });

  it("shows edit and delete buttons per card", async () => {
    mockGet.mockResolvedValueOnce({
      items: [{ id: "w1", contract_name: "Existing Plan", provider: "Vendor" }],
    });
    const { getByTestId } = render(
      <CustomerWarrantiesSection customerId="cust-1" />,
    );
    await waitFor(() => {
      expect(getByTestId("warranty-edit-btn-0")).toBeTruthy();
      expect(getByTestId("warranty-delete-btn-0")).toBeTruthy();
    });
  });

  it("opens delete confirmation and calls DELETE on confirm", async () => {
    mockGet.mockResolvedValueOnce({
      items: [{ id: "w1", contract_name: "Delete Me" }],
    });
    mockDel.mockResolvedValueOnce({});
    mockGet.mockResolvedValueOnce({ items: [] });

    const { getByTestId, getByText } = render(
      <CustomerWarrantiesSection customerId="cust-1" />,
    );
    await waitFor(() => {
      expect(getByTestId("warranty-delete-btn-0")).toBeTruthy();
    });

    fireEvent.press(getByTestId("warranty-delete-btn-0"));
    await waitFor(() => {
      expect(getByText("Delete warranty?")).toBeTruthy();
      expect(getByTestId("warranty-delete-confirm-btn")).toBeTruthy();
    });

    fireEvent.press(getByTestId("warranty-delete-confirm-btn"));
    await waitFor(() => {
      expect(mockDel).toHaveBeenCalledWith("/warranties/contracts/w1");
    });
  });
});
