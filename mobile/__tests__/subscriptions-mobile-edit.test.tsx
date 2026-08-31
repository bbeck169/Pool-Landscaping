/**
 * __tests__/subscriptions-mobile-edit.test.tsx
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockUpdateSub = jest.fn();
const mockListSubs = jest.fn();

jest.mock("@/src/api/subscriptions", () => ({
  listSubscriptions: (...a: any[]) => mockListSubs(...a),
  listPrices: jest.fn(async () => ({ rows: [] })),
  createSubscription: jest.fn(),
  updateSubscription: (...a: any[]) => mockUpdateSub(...a),
  cancelSubscription: jest.fn(),
}));

jest.mock("@/src/api/stripe", () => ({
  listPaymentMethods: jest.fn(async () => []),
}));

jest.mock("@/src/offline", () => ({ useOnline: () => true }));
jest.spyOn(require("react-native").Alert, "alert").mockImplementation(() => {});

import SubscriptionsSection from "@/src/components/subscriptions/SubscriptionsSection";

const SUB_ROW = {
  stripe_subscription_id: "sub_edit",
  price_id: "price_1",
  formatted_plan_label: "Pool Pro — $29.99/month",
  status: "active",
  quantity: 3,
  cancel_at_period_end: false,
};

describe("Subscriptions Mobile Edit", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockListSubs.mockResolvedValue({ rows: [SUB_ROW], total: 1 });
    mockUpdateSub.mockResolvedValue({});
  });

  it("existing values pre-fill inputs", async () => {
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-row-sub_edit-edit")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-row-sub_edit-edit"));
    await waitFor(() => expect(tree.getByTestId("subscriptions-edit-quantity")).toBeTruthy());
    const input = tree.getByTestId("subscriptions-edit-quantity");
    expect(input.props.value).toBe("3");
    console.log("✅ SE-T1: existing values pre-fill");
  });

  it("submit fires PATCH with changed fields", async () => {
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-row-sub_edit-edit")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-row-sub_edit-edit"));
    await waitFor(() => expect(tree.getByTestId("subscriptions-edit-quantity")).toBeTruthy());
    fireEvent.changeText(tree.getByTestId("subscriptions-edit-quantity"), "5");
    await act(async () => {
      fireEvent.press(tree.getByTestId("subscriptions-edit-submit"));
    });
    await waitFor(() => {
      expect(mockUpdateSub).toHaveBeenCalledWith(
        "sub_edit",
        expect.objectContaining({ quantity: 5 }),
      );
    });
    console.log("✅ SE-T2: submit fires PATCH with changed fields");
  });
});
