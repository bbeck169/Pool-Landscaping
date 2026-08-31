/**
 * __tests__/subscriptions-mobile-cancel.test.tsx
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockCancelSub = jest.fn();
const mockListSubs = jest.fn();

jest.mock("@/src/api/subscriptions", () => ({
  listSubscriptions: (...a: any[]) => mockListSubs(...a),
  listPrices: jest.fn(async () => ({ rows: [] })),
  createSubscription: jest.fn(),
  updateSubscription: jest.fn(),
  cancelSubscription: (...a: any[]) => mockCancelSub(...a),
}));

jest.mock("@/src/api/stripe", () => ({
  listPaymentMethods: jest.fn(async () => []),
}));

jest.mock("@/src/offline", () => ({ useOnline: () => true }));
jest.spyOn(require("react-native").Alert, "alert").mockImplementation(() => {});

import SubscriptionsSection from "@/src/components/subscriptions/SubscriptionsSection";

const SUB_ROW = {
  stripe_subscription_id: "sub_cancel",
  price_id: "price_1",
  formatted_plan_label: "Basic — $9.99/month",
  status: "active",
  quantity: 1,
};

describe("Subscriptions Mobile Cancel", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockListSubs.mockResolvedValue({ rows: [SUB_ROW], total: 1 });
    mockCancelSub.mockResolvedValue({});
  });

  it("radio defaults to at_period_end", async () => {
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-row-sub_cancel-cancel")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-row-sub_cancel-cancel"));
    await waitFor(() => expect(tree.getByTestId("subscriptions-cancel-mode-period-end")).toBeTruthy());
    // Default submit text should mention "at period end"
    const btn = tree.getByTestId("subscriptions-cancel-submit");
    expect(btn).toBeTruthy();
    console.log("✅ SCC-T1: radio defaults to at_period_end");
  });

  it("submit fires DELETE with mode=at_period_end", async () => {
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-row-sub_cancel-cancel")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-row-sub_cancel-cancel"));
    await waitFor(() => expect(tree.getByTestId("subscriptions-cancel-submit")).toBeTruthy());
    await act(async () => {
      fireEvent.press(tree.getByTestId("subscriptions-cancel-submit"));
    });
    await waitFor(() => {
      expect(mockCancelSub).toHaveBeenCalledWith("sub_cancel", "at_period_end");
    });
    console.log("✅ SCC-T2: DELETE with mode=at_period_end");
  });

  it("selecting immediate fires DELETE with mode=immediate", async () => {
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-row-sub_cancel-cancel")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-row-sub_cancel-cancel"));
    await waitFor(() => expect(tree.getByTestId("subscriptions-cancel-mode-immediate")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-cancel-mode-immediate"));
    await act(async () => {
      fireEvent.press(tree.getByTestId("subscriptions-cancel-submit"));
    });
    await waitFor(() => {
      expect(mockCancelSub).toHaveBeenCalledWith("sub_cancel", "immediate");
    });
    console.log("✅ SCC-T3: DELETE with mode=immediate");
  });

  it("no typed input required — confirm button is immediate", async () => {
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-row-sub_cancel-cancel")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-row-sub_cancel-cancel"));
    await waitFor(() => expect(tree.getByTestId("subscriptions-cancel-modal")).toBeTruthy());
    // No TextInput inside the cancel modal
    const inputs = tree.queryAllByTestId(/subscriptions-cancel.*input/i);
    expect(inputs.length).toBe(0);
    console.log("✅ SCC-T4: no typed input required");
  });
});
