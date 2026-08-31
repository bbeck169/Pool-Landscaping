/**
 * __tests__/subscriptions-mobile-list.test.tsx
 */
import React from "react";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

const mockListSubs = jest.fn();

jest.mock("@/src/api/subscriptions", () => ({
  listSubscriptions: (...a: any[]) => mockListSubs(...a),
  listPrices: jest.fn(async () => ({ rows: [] })),
  createSubscription: jest.fn(),
  updateSubscription: jest.fn(),
  cancelSubscription: jest.fn(),
}));

jest.mock("@/src/api/stripe", () => ({
  listPaymentMethods: jest.fn(async () => []),
}));

jest.mock("@/src/offline", () => ({ useOnline: () => true }));

import SubscriptionsSection from "@/src/components/subscriptions/SubscriptionsSection";

describe("Subscriptions Mobile List", () => {
  beforeEach(() => { jest.clearAllMocks(); });

  it("renders formatted_plan_label when present", async () => {
    mockListSubs.mockResolvedValue({
      rows: [{
        stripe_subscription_id: "sub_1",
        price_id: "price_abc",
        formatted_plan_label: "Pool Pro — $29.99/month",
        status: "active",
        quantity: 1,
        current_period_end: "2026-04-01T00:00:00Z",
      }],
      total: 1,
    });
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => {
      expect(tree.getByTestId("subscriptions-row-sub_1-plan")).toBeTruthy();
    });
    expect(tree.getByText("Pool Pro — $29.99/month")).toBeTruthy();
    console.log("✅ SL-T1: formatted_plan_label renders");
  });

  it("falls back to price_id if formatted_plan_label missing", async () => {
    mockListSubs.mockResolvedValue({
      rows: [{
        stripe_subscription_id: "sub_2",
        price_id: "price_xyz",
        status: "active",
        quantity: 1,
      }],
      total: 1,
    });
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => {
      expect(tree.getByTestId("subscriptions-row-sub_2-plan-fallback")).toBeTruthy();
    });
    console.log("✅ SL-T2: falls back to price_id");
  });

  it("empty state renders when API returns []", async () => {
    mockListSubs.mockResolvedValue({ rows: [], total: 0 });
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => {
      expect(tree.getByTestId("subscriptions-empty")).toBeTruthy();
    });
    console.log("✅ SL-T3: empty state renders");
  });

  it("refresh triggers re-fetch", async () => {
    mockListSubs.mockResolvedValue({ rows: [], total: 0 });
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-empty")).toBeTruthy());
    expect(mockListSubs).toHaveBeenCalledTimes(1);
    fireEvent.press(tree.getByTestId("subscriptions-refresh"));
    await waitFor(() => expect(mockListSubs).toHaveBeenCalledTimes(2));
    console.log("✅ SL-T4: refresh triggers re-fetch");
  });
});
