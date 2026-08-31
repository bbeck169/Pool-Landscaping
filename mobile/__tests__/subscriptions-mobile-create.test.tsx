/**
 * __tests__/subscriptions-mobile-create.test.tsx
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

const mockListPrices = jest.fn();
const mockCreateSub = jest.fn();

jest.mock("@/src/api/subscriptions", () => ({
  listSubscriptions: jest.fn(async () => ({ rows: [], total: 0 })),
  listPrices: (...a: any[]) => mockListPrices(...a),
  createSubscription: (...a: any[]) => mockCreateSub(...a),
  updateSubscription: jest.fn(),
  cancelSubscription: jest.fn(),
}));

jest.mock("@/src/api/stripe", () => ({
  listPaymentMethods: jest.fn(async () => []),
}));

jest.mock("@/src/offline", () => ({ useOnline: () => true }));

jest.spyOn(require("react-native").Alert, "alert").mockImplementation(() => {});

import SubscriptionsSection from "@/src/components/subscriptions/SubscriptionsSection";

describe("Subscriptions Mobile Create", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockCreateSub.mockResolvedValue({});
  });

  it("price picker populated from /api/subscriptions/prices", async () => {
    mockListPrices.mockResolvedValue({
      rows: [
        { id: "price_1", nickname: "Basic", unit_amount: 999, currency: "usd", recurring: { interval: "month" } },
        { id: "price_2", nickname: "Pro", unit_amount: 2999, currency: "usd", recurring: { interval: "month" } },
      ],
    });
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-create-btn")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-create-btn"));
    await waitFor(() => {
      expect(tree.getByTestId("subscriptions-create-price-price_1")).toBeTruthy();
      expect(tree.getByTestId("subscriptions-create-price-price_2")).toBeTruthy();
    });
    console.log("✅ SC-T1: price picker populated");
  });

  it("empty state renders when prices list is []", async () => {
    mockListPrices.mockResolvedValue({ rows: [] });
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-create-btn")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-create-btn"));
    await waitFor(() => {
      expect(tree.getByTestId("subscriptions-create-empty-plans")).toBeTruthy();
    });
    console.log("✅ SC-T2: empty plans renders");
  });

  it("submit fires POST with correct body shape", async () => {
    mockListPrices.mockResolvedValue({
      rows: [
        { id: "price_A", nickname: "Starter", unit_amount: 499, currency: "usd", recurring: { interval: "month" } },
      ],
    });
    const tree = render(<SubscriptionsSection customerId="cust-1" />);
    await waitFor(() => expect(tree.getByTestId("subscriptions-create-btn")).toBeTruthy());
    fireEvent.press(tree.getByTestId("subscriptions-create-btn"));
    // Wait for prices to actually load before pressing submit
    await waitFor(() => expect(tree.getByTestId("subscriptions-create-price-price_A")).toBeTruthy());
    await act(async () => {
      fireEvent.press(tree.getByTestId("subscriptions-create-submit"));
    });
    await waitFor(() => {
      expect(mockCreateSub).toHaveBeenCalledWith(
        expect.objectContaining({
          customer_id: "cust-1",
          price_id: "price_A",
          quantity: 1,
        }),
      );
    });
    console.log("✅ SC-T3: submit fires POST with correct body");
  });
});
