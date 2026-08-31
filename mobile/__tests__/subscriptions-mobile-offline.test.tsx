/**
 * __tests__/subscriptions-mobile-offline.test.tsx
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

let mockOnline = false;

jest.mock("@/src/api/subscriptions", () => ({
  listSubscriptions: jest.fn(async () => ({
    rows: [{
      stripe_subscription_id: "sub_off",
      price_id: "price_1",
      formatted_plan_label: "Plan A",
      status: "active",
      quantity: 1,
    }],
    total: 1,
  })),
  listPrices: jest.fn(async () => ({ rows: [] })),
  createSubscription: jest.fn(),
  updateSubscription: jest.fn(),
  cancelSubscription: jest.fn(),
}));

jest.mock("@/src/api/stripe", () => ({
  listPaymentMethods: jest.fn(async () => []),
}));

jest.mock("@/src/offline", () => ({
  useOnline: () => mockOnline,
}));

import SubscriptionsSection from "@/src/components/subscriptions/SubscriptionsSection";

describe("Subscriptions Mobile Offline", () => {
  beforeEach(() => {
    mockOnline = false;
    jest.clearAllMocks();
  });

  it("shows offline banner + disabled create button when offline", async () => {
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => {
      expect(tree.getByTestId("subscriptions-offline-banner")).toBeTruthy();
    });
    const createBtn = tree.getByTestId("subscriptions-create-btn");
    expect(createBtn.props.accessibilityState?.disabled).toBe(true);
    console.log("✅ SOF-T1: offline banner + disabled create button");
  });

  it("edit/cancel buttons disabled when offline", async () => {
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => {
      expect(tree.getByTestId("subscriptions-row-sub_off-edit")).toBeTruthy();
    });
    const editBtn = tree.getByTestId("subscriptions-row-sub_off-edit");
    const cancelBtn = tree.getByTestId("subscriptions-row-sub_off-cancel");
    expect(editBtn.props.accessibilityState?.disabled).toBe(true);
    expect(cancelBtn.props.accessibilityState?.disabled).toBe(true);
    console.log("✅ SOF-T2: edit/cancel buttons disabled when offline");
  });
});
